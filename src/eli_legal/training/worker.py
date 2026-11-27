#!/usr/bin/env python3
"""ELI Legal's trainer. It runs in the training environment (its own Python, with PyTorch), not
inside ELI Legal, and imports nothing of ELI Legal: ELI Legal writes a job file, starts this
with the environment's Python, and reads what it prints, one JSON object per line, from the log
file the output goes to. It needs nothing of ELI Legal once started: whatever happens it writes
outcome.json (done, failed or cancelled) and deletes the examples it trained on, so a run started
by a scheduler that has since finished still ends properly.

    python worker.py JOB.json

The job names the base model folder (Hugging Face format: config.json, the weights in
safetensors, the tokenizer), the training examples (JSONL, each a conversation: system, user,
assistant), the output folder, the recipe, and llama.cpp's converter. The run:

    1  loads the base model on the best device there is (CUDA, ROCm, Metal, XPU, or the
       processor), in 4 bits when asked and bitsandbytes is there
    2  trains a LoRA adapter on the answers only (the system message and the prompt are context,
       never learnt), with the learning rate warming up and then falling
    3  saves the adapter, merges it into the base, and writes one GGUF file with llama.cpp's
       converter, then the GGUF's SHA-256 and a result.json saying what was done

A file named "cancel" appearing in the output folder stops it between steps. Nothing is
uploaded anywhere; nothing is downloaded unless the base model named is not a folder.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PRINT_LOCK = None


def emit(kind: str, **fields: Any) -> None:
    try:
        print(json.dumps({"type": kind, **fields}, ensure_ascii=False), flush=True)
    except (OSError, ValueError):  # nobody is reading: the outcome file still says how it ended
        pass


def finish(job: dict[str, Any], status: str, **fields: Any) -> None:
    """How the run ended, written whatever happened, and the examples deleted: they are case
    material, and do not outlive the run."""
    out = Path(job["out"])
    try:
        tmp = out / "outcome.json.tmp"
        tmp.write_text(json.dumps({"status": status, **fields}, indent=2), encoding="utf-8")
        os.replace(tmp, out / "outcome.json")
    finally:
        try:
            Path(job["train"]).unlink()
        except OSError:
            pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_examples(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            messages = row.get("messages") or []
            if len(messages) >= 2 and messages[-1].get("role") == "assistant":
                rows.append(row)
    return rows


def pick_device(requested: str) -> str:
    import torch

    if requested and requested != "auto":
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch, "xpu", None) is not None and torch.xpu.is_available():
        return "xpu"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def render(tokenizer: Any, messages: list[dict[str, str]], *, add_generation_prompt: bool) -> str:
    """The conversation as the model reads it: its own chat template, or a plain one."""
    if getattr(tokenizer, "chat_template", None):
        return tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=add_generation_prompt
        )
    text = "".join(f"<|{m['role']}|>\n{m['content']}\n" for m in messages)
    return text + ("<|assistant|>\n" if add_generation_prompt else "")


def encode(tokenizer: Any, row: dict[str, Any], seq_len: int) -> tuple[list[int], list[int]] | None:
    """Token ids and labels: the answer's tokens are learnt, everything before it is not."""
    messages = row["messages"]
    context = render(tokenizer, messages[:-1], add_generation_prompt=True)
    full = render(tokenizer, messages, add_generation_prompt=False)
    if not full.startswith(context):  # a template that renders the turns differently in full
        full = context + messages[-1]["content"] + (tokenizer.eos_token or "")
    context_ids = tokenizer(context, add_special_tokens=False)["input_ids"]
    full_ids = tokenizer(full, add_special_tokens=False)["input_ids"]
    if tokenizer.eos_token_id is not None and (
        not full_ids or full_ids[-1] != tokenizer.eos_token_id
    ):
        full_ids = full_ids + [tokenizer.eos_token_id]
    answer = len(full_ids) - len(context_ids)
    if answer <= 0:
        return None
    if len(full_ids) > seq_len:
        keep_context = seq_len - answer
        if keep_context < 16:  # the answer alone does not fit: nothing sensible to learn
            return None
        context_ids = context_ids[-keep_context:]
        full_ids = context_ids + full_ids[len(full_ids) - answer :]
    labels = [-100] * len(context_ids) + full_ids[len(context_ids) :]
    return full_ids, labels


# The projection layers LoRA tunes, by the names the common families give them (ELI v3's list):
# attention and feed-forward, never a mixture-of-experts router or the output head.
PROJECTIONS = {
    "qkv_proj", "q_proj", "k_proj", "v_proj", "o_proj", "out_proj",
    "gate_proj", "up_proj", "down_proj", "wqkv", "w1", "w2", "w3",
    "c_attn", "c_proj", "c_fc", "query_key_value", "dense_h_to_4h",
    "dense_4h_to_h", "fc_in", "fc_out", "Wqkv", "fc1", "fc2",
}  # fmt: skip


def lora_targets(model: Any, explicit: Any = None) -> Any:
    """The layers to tune, read from the loaded model (a Qwen and a Phi-3 name them differently),
    unless the recipe names them; PEFT's own "all-linear" where none is recognised."""
    if explicit:
        return list(explicit)
    import torch.nn as nn

    found = {
        name.rsplit(".", 1)[-1]
        for name, module in model.named_modules()
        if isinstance(module, nn.Linear) and name.rsplit(".", 1)[-1] in PROJECTIONS
    }
    return sorted(found) if found else "all-linear"


def accelerator_name(device: str) -> str:
    """The device named as it is: a ROCm build answers to "cuda" on a Radeon card."""
    import torch

    if device == "cuda":
        name = torch.cuda.get_device_name(0)
        return f"{name} ({'ROCm' if getattr(torch.version, 'hip', None) else 'CUDA'})"
    return {"mps": "Apple graphics (Metal)", "xpu": "Intel graphics (XPU)", "cpu": "processor"}.get(
        device, device
    )


def load_config(base: str) -> Any:
    """The model's configuration, with Phi-3's RoPE settings as transformers now reads them
    (ELI v3's shim, in memory only: the downloaded files are never changed)."""
    from transformers import AutoConfig

    config = AutoConfig.from_pretrained(base)
    rope = getattr(config, "rope_scaling", None)
    if isinstance(rope, dict):
        fixed = dict(rope)
        if "short_factor" in fixed or "long_factor" in fixed:
            fixed["type"] = fixed["rope_type"] = "longrope"
        elif "type" not in fixed and "rope_type" in fixed:
            fixed["type"] = fixed["rope_type"]
        config.rope_scaling = fixed
    return config


def train(job: dict[str, Any]) -> dict[str, Any]:
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    recipe = job.get("recipe") or {}
    out = Path(job["out"])
    out.mkdir(parents=True, exist_ok=True)
    cancel = out / "cancel"
    seed = int(recipe.get("seed", 1234))
    random.seed(seed)
    torch.manual_seed(seed)
    device = pick_device(str(recipe.get("device", "auto")))
    # 4-bit needs bitsandbytes, which is built for NVIDIA cards: not ROCm, Metal or XPU.
    four_bit = bool(recipe.get("four_bit")) and device == "cuda"
    if four_bit and getattr(torch.version, "hip", None):
        four_bit = False
        emit("stage", message="4-bit training needs an NVIDIA card; training in 16 bits")
    emit("stage", message=f"training on {accelerator_name(device)}")
    if device == "cuda":
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    else:
        dtype = torch.float32
    emit(
        "stage",
        message=f"loading the base model on {device} "
        f"({'4-bit' if four_bit else str(dtype).replace('torch.', '')})",
    )
    base = job["base"]
    tokenizer = AutoTokenizer.from_pretrained(base)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model_config = load_config(base)
    load: dict[str, Any] = {"torch_dtype": dtype, "config": model_config}
    if four_bit:
        from transformers import BitsAndBytesConfig

        # ELI v2's proven set-up for small cards: 4-bit weights, filling the card up to a cap
        # and the rest in main memory (an 8 GB card trained an 8-billion-weight model this way).
        card_gb = torch.cuda.get_device_properties(0).total_memory / 2**30
        gpu_gb = float(recipe.get("gpu_memory_gb") or max(1.0, round(card_gb * 0.7, 1)))
        cpu_gb = float(recipe.get("cpu_memory_gb") or 20)
        load = {
            "config": model_config,
            "quantization_config": BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=dtype,
                llm_int8_enable_fp32_cpu_offload=True,
            ),
            "device_map": "sequential",
            "max_memory": {0: f"{gpu_gb}GiB", "cpu": f"{cpu_gb}GiB"},
        }
    model = AutoModelForCausalLM.from_pretrained(base, **load)
    if not four_bit:
        model.to(device)
    if four_bit:
        from peft import prepare_model_for_kbit_training

        model = prepare_model_for_kbit_training(model)
    if recipe.get("gradient_checkpointing", device != "cpu"):
        model.gradient_checkpointing_enable()
        model.config.use_cache = False
        if hasattr(model, "enable_input_require_grads"):
            model.enable_input_require_grads()
    targets = lora_targets(model, recipe.get("target_modules"))
    config = LoraConfig(
        r=int(recipe.get("rank", 16)),
        lora_alpha=int(recipe.get("alpha", 32)),
        lora_dropout=float(recipe.get("dropout", 0.05)),
        target_modules=targets,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, config)
    if dtype == torch.float16 and not four_bit:
        for p in model.parameters():  # trainable weights in full precision under fp16 autocast
            if p.requires_grad:
                p.data = p.data.float()
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    named = targets if isinstance(targets, str) else ", ".join(targets)
    emit("stage", message=f"LoRA on {named}: {trainable:,} of {total:,} weights train")

    rows = load_examples(Path(job["train"]))
    seq_len = int(recipe.get("seq_len", 1024))
    encoded = [e for e in (encode(tokenizer, r, seq_len) for r in rows) if e is not None]
    if not encoded:
        raise SystemExit("no example fits the sequence length")
    emit("stage", message=f"{len(encoded)} of {len(rows)} examples fit {seq_len} tokens")

    batch = max(1, int(recipe.get("batch_size", 1)))
    accum = max(1, int(recipe.get("grad_accum", 8)))
    epochs = float(recipe.get("epochs", 2))
    per_epoch = math.ceil(len(encoded) / batch / accum)
    max_steps = int(recipe.get("max_steps") or max(1, round(per_epoch * epochs)))
    warmup = max(1, int(max_steps * 0.05))
    lr = float(recipe.get("learning_rate", 1e-4))
    params = [p for p in model.parameters() if p.requires_grad]
    optim = torch.optim.AdamW(params, lr=lr, weight_decay=0.0)
    scaler = torch.amp.GradScaler("cuda") if dtype == torch.float16 and not four_bit else None
    autocast = (
        torch.autocast(device_type="cuda", dtype=dtype)
        if device == "cuda"
        else torch.autocast(device_type="cpu", enabled=False)
    )

    def batches():
        while True:
            order = list(range(len(encoded)))
            random.shuffle(order)
            for i in range(0, len(order), batch):
                yield [encoded[j] for j in order[i : i + batch]]

    on = model.device  # where the batches go (the model itself is let go after training)

    def collate(items):
        width = max(len(ids) for ids, _ in items)
        pad = tokenizer.pad_token_id
        ids = [x + [pad] * (width - len(x)) for x, _ in items]
        labels = [y + [-100] * (width - len(y)) for _, y in items]
        mask = [[1] * len(x) + [0] * (width - len(x)) for x, _ in items]
        return (
            torch.tensor(ids, device=on),
            torch.tensor(labels, device=on),
            torch.tensor(mask, device=on),
        )

    model.train()
    source = batches()
    losses: list[float] = []
    started = time.time()
    for step in range(1, max_steps + 1):
        if cancel.exists():
            emit("cancelled", message=f"stopped at step {step - 1} of {max_steps}")
            return {"cancelled": True, "steps": step - 1}
        scale = (
            step / warmup
            if step <= warmup
            else max(
                0.0, 0.5 * (1 + math.cos(math.pi * (step - warmup) / max(1, max_steps - warmup)))
            )
        )
        for group in optim.param_groups:
            group["lr"] = lr * scale
        total_loss = 0.0
        for _ in range(accum):
            ids, labels, mask = collate(next(source))
            with autocast:
                loss = model(input_ids=ids, attention_mask=mask, labels=labels).loss / accum
            (scaler.scale(loss) if scaler else loss).backward()
            total_loss += float(loss.detach())
        if scaler:
            scaler.unscale_(optim)
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        if scaler:
            scaler.step(optim)
            scaler.update()
        else:
            optim.step()
        optim.zero_grad(set_to_none=True)
        losses.append(total_loss)
        emit(
            "step",
            step=step,
            max_steps=max_steps,
            loss=round(total_loss, 5),
            lr=round(lr * scale, 8),
            seconds=round(time.time() - started, 1),
        )

    adapter = out / "adapter"
    model.save_pretrained(adapter)
    tokenizer.save_pretrained(adapter)
    emit("stage", message=f"adapter saved in {adapter}")
    del model, optim
    if device == "cuda":
        torch.cuda.empty_cache()

    emit("stage", message="merging the adapter into the base model")
    merge_dtype = torch.float16 if dtype == torch.float32 and device == "cpu" else dtype
    merge_dtype = torch.float32 if recipe.get("merge_float32") else merge_dtype
    base_model = AutoModelForCausalLM.from_pretrained(
        base, torch_dtype=merge_dtype, config=load_config(base)
    )
    merged = PeftModel.from_pretrained(base_model, adapter).merge_and_unload()
    merged_dir = out / "merged"
    merged.save_pretrained(merged_dir, safe_serialization=True)
    tokenizer.save_pretrained(merged_dir)
    del merged, base_model

    gguf = out / "model.gguf"
    converter = Path(job["converter"])
    emit(
        "stage",
        message=f"writing the GGUF ({job.get('gguf_type', 'q8_0')}) with llama.cpp's converter",
    )
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [
                str(converter.parent),
                str(converter.parent / "gguf-py"),
                os.environ.get("PYTHONPATH", ""),
            ]
        ),
    }
    proc = subprocess.run(
        [
            sys.executable,
            str(converter),
            str(merged_dir),
            "--outfile",
            str(gguf),
            "--outtype",
            str(job.get("gguf_type", "q8_0")),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    for line in (proc.stdout + proc.stderr).splitlines()[-15:]:
        emit("log", message=line)
    if proc.returncode != 0 or not gguf.is_file():
        raise SystemExit(f"the converter failed (exit {proc.returncode})")
    if not recipe.get("keep_merged"):
        import shutil

        shutil.rmtree(merged_dir, ignore_errors=True)
    return {
        "cancelled": False,
        "steps": max_steps,
        "examples": len(encoded),
        "final_loss": losses[-1],
        "first_loss": losses[0],
        "losses": losses[-50:],
        "device": device,
        "four_bit": four_bit,
        "lora_targets": targets,
        "seconds": round(time.time() - started, 1),
        "gguf": str(gguf),
        "gguf_sha256": sha256(gguf),
        "versions": {
            "torch": torch.__version__,
            "transformers": __import__("transformers").__version__,
            "peft": __import__("peft").__version__,
        },
    }


def dry_run(job: dict[str, Any]) -> dict[str, Any]:
    """Everything but the training: the job read, the examples counted, an output written. For
    checking the plumbing where PyTorch is not installed."""
    out = Path(job["out"])
    out.mkdir(parents=True, exist_ok=True)
    rows = load_examples(Path(job["train"]))
    steps = int((job.get("recipe") or {}).get("max_steps") or 3)
    for step in range(1, steps + 1):
        if (out / "cancel").exists():
            emit("cancelled", message=f"stopped at step {step - 1} of {steps}")
            return {"cancelled": True, "steps": step - 1}
        emit("step", step=step, max_steps=steps, loss=round(2.0 / step, 5), lr=0.0, seconds=0.0)
    gguf = out / "model.gguf"
    gguf.write_bytes(b"GGUF dry run " + str(len(rows)).encode())
    return {
        "cancelled": False,
        "steps": steps,
        "examples": len(rows),
        "final_loss": 2.0 / steps,
        "first_loss": 2.0,
        "losses": [],
        "device": "none",
        "four_bit": False,
        "lora_targets": [],
        "seconds": 0.0,
        "gguf": str(gguf),
        "gguf_sha256": sha256(gguf),
        "versions": {},
        "dry_run": True,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    job = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    try:
        result = dry_run(job) if job.get("dry_run") else train(job)
    except SystemExit as exc:
        finish(job, "failed", message=str(exc))
        emit("failed", message=str(exc))
        return 1
    except BaseException as exc:  # reported to ELI Legal, which records why the run failed
        import traceback

        message = f"{type(exc).__name__}: {exc}"
        trace = traceback.format_exc()[-4000:]
        finish(job, "failed", message=message, trace=trace)
        emit("failed", message=message, trace=trace)
        return 1
    Path(job["out"], "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    status = "cancelled" if result.get("cancelled") else "done"
    finish(job, status, result=result, message="cancelled" if status == "cancelled" else "")
    emit(status, result=result)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
