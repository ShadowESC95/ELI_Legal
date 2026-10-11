"""GGUF models run in this process with llama.cpp, as ELI v2 and v3 run them.

Nothing leaves the machine: the model file is read from disk and llama.cpp runs on this
computer's processor and its graphics card. How much of the model goes on the card and how long
its context is are worked out, at the moment of loading, from the model's own file and the
memory free then (``fit``, ``hardware``, ``gguf_sizes``); llama.cpp's own account of the load is
what is reported and recorded, not what was asked for. The model is loaded on first use and kept
loaded; two settings that name the same file share one copy.

Finding models: the folders ELI v2 and v3 keep theirs in, ELI Legal's own ``models`` folder, the
folders of other local-model tools, and any folders the administrator adds.
"""

from __future__ import annotations

import gc
import hashlib
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from eli_legal.adapters.inference import (
    fit,
    gguf_sizes,
    gpu_runtime,
    hardware,
    load_diagnostics,
    moe_offload,
)
from eli_legal.domain.errors import InferenceUnavailable, InvalidInput
from eli_legal.paths import data_roots

# A reasoning model's working, closed or cut off by the token limit, is never part of the answer.
_THINK = re.compile(r"<think>.*?(?:</think>\s*|\Z)", re.S | re.I)
# Files that are GGUF but not chat models: vision projectors, embedders, speech, adapters.
_NOT_CHAT = re.compile(r"mmproj|embed|whisper|wakeword|lora|adapter|reranker|vocab", re.I)
# Tokens a chat template adds around two messages (role markers, start and end tokens). Every
# template in use adds fewer; the figure is replaced, per loaded model, by what llama.cpp counts
# at the first answer.
_TEMPLATE_TOKENS = 32
_LOAD_ATTEMPTS = 6

_LOAD_LOCK = threading.RLock()


@dataclass(frozen=True, slots=True)
class LoadReport:
    """What a load did, by llama.cpp's own account."""

    model: str
    n_ctx: int
    layers_on_card: int  # counted as llama.cpp counts: the output layer is one of them
    layers_total: int
    n_batch: int
    n_threads: int
    experts_in_memory: bool
    runtime: str
    seconds: float
    notes: tuple[str, ...]

    def describe(self) -> str:
        if self.layers_on_card <= 0:
            placed = "processor only"
        elif self.layers_on_card >= self.layers_total:
            placed = f"all {self.layers_total} layers on the graphics card"
        else:
            placed = f"{self.layers_on_card} of {self.layers_total} layers on the graphics card"
        return f"{self.n_ctx} tokens of context, {placed}, {self.runtime}"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self) | {"summary": self.describe()}


@dataclass(slots=True)
class _Loaded:
    llm: Any
    report: LoadReport
    template_tokens: int = _TEMPLATE_TOKENS


_LOADED: dict[tuple[str, int, int, int], _Loaded] = {}


def llama_available() -> bool:
    module = gpu_runtime.llama()
    return module is not None and hasattr(module, "Llama")


def fingerprint(path: Path) -> str:
    """A quick identity for a model file: its size and the hash of its first and last 4 MB.
    Enough to tell two files apart in the record of a run without reading gigabytes."""
    size = path.stat().st_size
    digest = hashlib.sha256(str(size).encode())
    with path.open("rb") as fh:
        digest.update(fh.read(4 * 1024 * 1024))
        if size > 8 * 1024 * 1024:
            fh.seek(-4 * 1024 * 1024, os.SEEK_END)
            digest.update(fh.read())
    return digest.hexdigest()


def _close(loaded: _Loaded) -> None:
    close = getattr(loaded.llm, "close", None)
    if callable(close):
        try:
            close()
        except Exception:  # a model that will not close cleanly is still let go
            pass
    loaded.llm = None
    gc.collect()


def release(keep: set[Path] | None = None) -> None:
    """Unload every model whose file is not in ``keep``, giving its memory back before another
    is sized. The memory free now is what a fit is made from."""
    wanted = {str(Path(p).resolve()) for p in (keep or set())}
    with _LOAD_LOCK:
        for key in [k for k in _LOADED if k[0] not in wanted]:
            _close(_LOADED.pop(key))


class GgufInference:
    """A GGUF model on this machine, through llama.cpp.

    ``n_ctx`` 0 and ``n_gpu_layers`` -1 mean automatic: sized to the model and to this machine
    as it is when the model loads. A context length is otherwise the administrator's choice,
    reduced only if it cannot be held; a layer count is a ceiling; 0 layers keeps the model on
    the processor. ``working_ctx`` is the context the application's own steps need.
    """

    available = True

    def __init__(
        self,
        model_path: str | Path,
        *,
        n_ctx: int = 0,
        n_gpu_layers: int = -1,
        n_threads: int = 0,
        working_ctx: int = 0,
        priority: str = "balanced",
    ) -> None:
        path = Path(model_path).expanduser()
        if path.suffix.lower() != ".gguf" or not path.is_file():
            raise InvalidInput(f"no GGUF model file at {path}")
        self.path = path.resolve()
        self.want_ctx = max(0, int(n_ctx))
        self.want_layers = -1 if int(n_gpu_layers) < 0 else int(n_gpu_layers)
        self.want_threads = max(0, int(n_threads))
        self.working_ctx = max(0, int(working_ctx))
        self.priority = priority
        self.model_id = f"gguf:{self.path.name}@{fingerprint(self.path)[:12]}"
        # Called once with the report of each load, so the application can record it.
        self.on_load: Callable[[LoadReport], None] | None = None
        self._lock = threading.Lock()

    @property
    def _key(self) -> tuple[str, int, int, int]:
        return (str(self.path), self.want_ctx, self.want_layers, self.want_threads)

    @property
    def report(self) -> LoadReport | None:
        """How the model is loaded, or None while it is not."""
        loaded = _LOADED.get(self._key)
        return loaded.report if loaded else None

    def plan(
        self, *, margin_mb: int = 0, on_card: bool = True, ctx: int | None = None
    ) -> fit.LoadPlan:
        """What would be asked of llama.cpp if the model were loaded now."""
        module = gpu_runtime.llama()
        return fit.plan(
            self.path,
            hardware.detect(force=True),
            gpu_offload=gpu_runtime.supports_offload(),
            want_ctx=self.want_ctx if ctx is None else ctx,
            want_layers=self.want_layers if on_card else 0,
            want_threads=self.want_threads,
            working_ctx=self.working_ctx,
            priority=self.priority,
            margin_mb=margin_mb,
            expert_offload=module is not None and moe_offload.available(module),
        )

    def _construct(self, module: Any, plan: fit.LoadPlan) -> Any:
        kwargs = {
            "model_path": str(self.path),
            "n_ctx": plan.n_ctx,
            "n_gpu_layers": plan.n_gpu_layers,
            "n_batch": plan.n_batch,
            "n_threads": plan.n_threads,
            "verbose": False,
        }
        if plan.experts_in_ram:
            with moe_offload.experts_in_memory(module):
                return module.Llama(**kwargs)
        return module.Llama(**kwargs)

    def _load(self, module: Any) -> _Loaded:
        """Load by the plan; where llama.cpp refuses it for lack of memory, plan again from the
        memory free then with a wider margin, then on the processor, then with less context."""
        load_diagnostics.harden_destructor(module)
        runtime = gpu_runtime.current()
        tried: list[str] = []
        margin, on_card, ctx = 0, True, None
        last = "llama.cpp gave no reason"
        previous: fit.LoadPlan | None = None
        for _ in range(_LOAD_ATTEMPTS):
            plan = self.plan(margin_mb=margin, on_card=on_card, ctx=ctx)
            if previous is not None and (plan.n_ctx, plan.n_gpu_layers, plan.n_batch) == (
                previous.n_ctx,
                previous.n_gpu_layers,
                previous.n_batch,
            ):
                break  # nothing smaller to ask for
            previous = plan
            started = time.monotonic()
            lines: list[str] = []
            try:
                with load_diagnostics.capture(module) as lines:
                    llm = self._construct(module, plan)
            except Exception as exc:  # llama.cpp reports load failures as plain exceptions
                last = load_diagnostics.explain(
                    exc, lines, self.path.name, on_card=plan.n_gpu_layers > 0
                )
                if not load_diagnostics.retryable(lines):
                    raise InferenceUnavailable(last) from exc
                tried.append(f"{plan.n_ctx} tokens of context, {plan.on_card}: refused")
                gc.collect()
                if plan.n_gpu_layers > 0 and margin < plan.free_vram_mb // 2:
                    margin += max(hardware.vram_reserve_mb(), plan.free_vram_mb // 8)
                elif plan.n_gpu_layers > 0:
                    on_card = False
                else:
                    ctx = max(fit.CTX_UNIT, plan.n_ctx // 2)
                continue
            seconds = time.monotonic() - started
            gguf_sizes.record_load_report(self.path, lines)
            placed = load_diagnostics.layers_on_card(lines)
            if placed is None:
                # this llama.cpp did not say: a build without graphics support places none
                placed = (plan.n_gpu_layers if runtime.offload else 0, plan.blocks + 1)
            n_ctx = getattr(llm, "n_ctx", None)
            report = LoadReport(
                model=self.path.name,
                n_ctx=int(n_ctx()) if callable(n_ctx) else plan.n_ctx,
                layers_on_card=placed[0],
                layers_total=placed[1],
                n_batch=plan.n_batch,
                n_threads=plan.n_threads,
                experts_in_memory=plan.experts_in_ram,
                runtime=runtime.describe(),
                seconds=round(seconds, 1),
                notes=(*plan.notes, *tried),
            )
            return _Loaded(llm, report)
        raise InferenceUnavailable(
            last + (" Tried: " + "; ".join(tried) + "." if len(tried) > 1 else "")
        )

    def _loaded(self) -> _Loaded:
        key = self._key
        with _LOAD_LOCK:
            if key in _LOADED:
                return _LOADED[key]
            module = gpu_runtime.llama()
            if module is None or not hasattr(module, "Llama"):
                raise InferenceUnavailable(
                    "GGUF models need llama.cpp for Python, which is not installed here: "
                    "pip install 'eli-legal[gguf]'"
                )
            # One model in memory per file. The older setting's copy goes first: the memory
            # free now is what the new one is sized from.
            for old in [k for k in _LOADED if k[0] == key[0]]:
                _close(_LOADED.pop(old))
            loaded = self._load(module)
            _LOADED[key] = loaded
        if self.on_load is not None:
            self.on_load(loaded.report)
        return loaded

    def warm(self) -> LoadReport:
        """Load the model now rather than at the first question."""
        return self._loaded().report

    def context_tokens(self) -> int:
        """The context the model is loaded with (loading it if it is not)."""
        return self._loaded().report.n_ctx

    def count_tokens(self, text: str) -> int:
        """The length of this text as the model counts it, plus what its chat template adds
        around a system message and a question."""
        loaded = self._loaded()
        tokenize = getattr(loaded.llm, "tokenize", None)
        if not callable(tokenize):
            return 0
        with self._lock:
            return (
                len(tokenize(text.encode("utf-8"), add_bos=False, special=False))
                + loaded.template_tokens
            )

    def generate(
        self, *, system: str, prompt: str, max_tokens: int = 2048, json_mode: bool = False
    ) -> str:
        loaded = self._loaded()
        kwargs: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.0,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        name, window = self.path.name, loaded.report.n_ctx
        with self._lock:  # llama.cpp contexts are not safe to share between threads
            try:
                result = loaded.llm.create_chat_completion(**kwargs)
            except ValueError as exc:  # the material is longer than the context
                raise InferenceUnavailable(
                    f"this step's material does not fit the {window} tokens of context "
                    f"{name} is loaded with ({exc})"
                ) from exc
            except Exception as exc:
                raise InferenceUnavailable(f"{name} failed: {type(exc).__name__}: {exc}") from exc
        try:
            choice = result["choices"][0]
            text = str(choice["message"]["content"] or "")
        except (KeyError, IndexError, TypeError) as exc:
            raise InferenceUnavailable(f"{name} returned no text") from exc
        usage = result.get("usage") if isinstance(result, dict) else None
        if isinstance(usage, dict) and isinstance(usage.get("prompt_tokens"), int):
            tokenize = getattr(loaded.llm, "tokenize", None)
            if callable(tokenize):
                with self._lock:
                    plain = len(
                        tokenize((system + prompt).encode("utf-8"), add_bos=False, special=False)
                    )
                loaded.template_tokens = max(1, usage["prompt_tokens"] - plain)
        if json_mode and choice.get("finish_reason") == "length":
            # A reply cut off mid-object is not an answer; say why instead of handing on half.
            used = usage.get("completion_tokens") if isinstance(usage, dict) else None
            raise InferenceUnavailable(
                f"{name}'s reply was cut off"
                + (f" after {used} tokens" if used else "")
                + f": the step allows {max_tokens} and the context is {window} tokens"
            )
        return _THINK.sub("", text).strip()


# ── finding models on this machine ───────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ModelFile:
    path: Path
    size: int
    location: str  # which known folder it was found in

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def ref(self) -> str:
        """An opaque reference, so a remote screen can choose a model without seeing paths."""
        return hashlib.sha256(str(self.path).encode("utf-8")).hexdigest()[:16]

    def as_dict(self, *, with_path: bool = True) -> dict[str, Any]:
        out = {
            "ref": self.ref,
            "name": self.name,
            "size_gb": round(self.size / 1e9, 2),
            "location": self.location,
        }
        if with_path:
            out["path"] = str(self.path)
        return out


def model_folders(extra: str = "", home: Path | None = None) -> list[tuple[str, Path]]:
    """Every folder searched, labelled, in order of preference."""
    out: list[tuple[str, Path]] = []
    for part in [p for p in extra.split(os.pathsep) if p.strip()]:
        out.append(("added by the administrator", Path(part).expanduser()))
    if home is not None:
        out.append(("ELI Legal", home / "models"))
    for var in ("ELI_LEGAL_MODELS_DIR", "ELI_MODELS_DIR"):
        if os.environ.get(var):
            out.append((var, Path(os.environ[var]).expanduser()))
    for root in data_roots("ELI_v3"):
        out.append(("ELI v3", root / "models"))
    if os.environ.get("ELI_V3_ROOT"):
        out.append(("ELI v3", Path(os.environ["ELI_V3_ROOT"]) / "models"))
    for root in data_roots("ELI_v2"):
        out.append(("ELI v2", root / "models"))
    user = Path.home()
    out += [
        ("ELI", user / ".local" / "opt" / "eli" / "models"),
        ("LM Studio", user / ".lmstudio" / "models"),
        ("LM Studio", user / ".cache" / "lm-studio" / "models"),
        ("GPT4All", user / ".local" / "share" / "nomic.ai" / "GPT4All"),
        ("your models folder", user / "models"),
    ]
    seen: set[str] = set()
    unique = []
    for label, folder in out:
        key = str(folder.resolve()) if folder.exists() else str(folder)
        if key not in seen:
            seen.add(key)
            unique.append((label, folder))
    return unique


def discover(extra: str = "", home: Path | None = None, max_depth: int = 4) -> list[ModelFile]:
    """GGUF chat models in the known folders. Projectors, embedders and partial downloads are
    left out."""
    found: dict[str, ModelFile] = {}
    for label, folder in model_folders(extra, home):
        if not folder.is_dir():
            continue
        base_depth = len(folder.parts)
        for root, dirs, files in os.walk(folder):
            if len(Path(root).parts) - base_depth >= max_depth:
                dirs[:] = []
            dirs[:] = [d for d in dirs if not d.startswith((".", "__"))]
            for name in files:
                if not name.lower().endswith(".gguf") or _NOT_CHAT.search(name):
                    continue
                path = Path(root) / name
                try:
                    real = path.resolve()
                    size = real.stat().st_size
                except OSError:
                    continue
                if size < 50 * 1024 * 1024 or str(real) in found:
                    continue  # a stub or test file, or one already found through a link
                found[str(real)] = ModelFile(real, size, label)
    return sorted(found.values(), key=lambda m: (m.location != "ELI Legal", m.name.lower()))
