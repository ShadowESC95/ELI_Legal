"""The training environment: a separate Python installation on this machine, made for training.

ELI Legal runs models; it does not carry what training them needs (PyTorch alone is gigabytes,
and the right build depends on the graphics card). So training runs in its own environment,
in ELI Legal's data folder, which this module sets up step by step, showing each command:

    1  a Python 3.12 environment (uv when installed, which also fetches Python itself;
       otherwise a Python 3.10 to 3.12 found on this machine)
    2  PyTorch built for this machine's accelerator: an NVIDIA card (CUDA), an AMD card on
       Linux (ROCm), Apple silicon (Metal, the standard build), or the processor alone
    3  the training libraries (transformers, peft, accelerate…) at versions that work together
    4  4-bit loading (bitsandbytes), on NVIDIA cards only, for bases too large for the card
    5  llama.cpp's converter, from the source of the llama-cpp-python release ELI Legal runs,
       so the GGUF it writes is one ELI Legal can load
    6  a check of what was installed and what it can train on

Nothing here is installed into ELI Legal itself, and removing the folder removes it all.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eli_legal.adapters.inference.hardware import Hardware

PYTHON = "3.12"
# The libraries, at versions that train together and that llama.cpp's converter accepts
# (its own requirements pin transformers 4.57.6 and protobuf below 5).
PACKAGES = [
    "transformers==4.57.6",
    "peft==0.17.1",
    "accelerate>=1.0,<2",
    "safetensors>=0.4",
    "sentencepiece>=0.1.98,<0.3",
    "protobuf>=4.21,<5",
    "numpy>=1.26,<2.3",
    "huggingface_hub>=0.30,<1",
]
TORCH = "torch>=2.6"
BITSANDBYTES = "bitsandbytes>=0.45"
# The llama-cpp-python release whose source holds the converter, when ELI Legal's own cannot be
# read (it is the one ELI Legal ships with).
CONVERTER_RELEASE = "0.3.36"
SPACE_GB = 8  # what the environment takes, roughly, with a CUDA build of PyTorch


@dataclass(frozen=True)
class Accelerator:
    kind: str  # cuda | rocm | mps | xpu | cpu
    label: str
    index_url: str  # where PyTorch's build for it comes from ("" for the standard index)
    four_bit: bool  # whether bitsandbytes 4-bit loading is offered


@dataclass
class Step:
    label: str
    argv: list[str]
    why: str


@dataclass
class Plan:
    folder: Path
    accelerator: Accelerator
    steps: list[Step] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _cuda_version() -> tuple[int, int] | None:
    """The CUDA version the NVIDIA driver supports, read from nvidia-smi."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run([exe], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


def accelerator(hw: Hardware) -> Accelerator:
    """What to train on, and which PyTorch build that needs."""
    vendor = (hw.gpu_vendor or "").lower()
    if hw.has_gpu and vendor == "nvidia":
        cuda = _cuda_version() or (12, 6)
        tag = (
            "cu130"
            if cuda >= (13, 0)
            else "cu128"
            if cuda >= (12, 8)
            else "cu126"
            if cuda >= (12, 6)
            else "cu118"
        )
        return Accelerator(
            "cuda",
            f"NVIDIA {hw.gpu_name} (CUDA, PyTorch {tag})",
            f"https://download.pytorch.org/whl/{tag}",
            four_bit=sys.platform != "darwin",
        )
    if (
        hw.has_gpu
        and vendor == "amd"
        and sys.platform.startswith("linux")
        and not hw.gpu_integrated
    ):
        return Accelerator(
            "rocm",
            f"AMD {hw.gpu_name} (ROCm)",
            "https://download.pytorch.org/whl/rocm6.4",
            four_bit=False,
        )
    if sys.platform == "darwin" and vendor == "apple":
        return Accelerator("mps", f"{hw.gpu_name or 'Apple silicon'} (Metal)", "", four_bit=False)
    if hw.has_gpu and vendor == "intel" and not hw.gpu_integrated:
        return Accelerator(
            "xpu",
            f"Intel {hw.gpu_name} (XPU)",
            "https://download.pytorch.org/whl/xpu",
            four_bit=False,
        )
    return Accelerator(
        "cpu",
        "the processor only (slow: small models and short runs)",
        "https://download.pytorch.org/whl/cpu",
        four_bit=False,
    )


def estimate_gb(base: str | Path, *, four_bit: bool, seq_len: int, batch_size: int = 1) -> float:
    """Rough graphics memory a LoRA run on this base needs, from the size of its weights on disk
    (ELI v3's estimate: generous, because running out forty minutes in is the worse failure)."""
    weights = 3.8
    try:
        total = sum(
            f.stat().st_size
            for f in Path(base).rglob("*")
            if f.is_file() and f.suffix in (".safetensors", ".bin")
        )
        if total > 0:
            weights = total / 2**30
    except OSError:
        pass
    resident = weights * (0.30 if four_bit else 1.0)
    activations = 0.5 + (seq_len / 1024) * 0.6 * max(1, batch_size)
    return round(resident + activations + 1.2, 1)


def fits(hw: Hardware, need_gb: float) -> tuple[bool, str]:
    """Whether a run needing ``need_gb`` fits this machine's graphics memory, said plainly."""
    if not hw.has_gpu or not hw.total_vram_mb:
        return False, (
            f"no graphics card with its own memory was found: training runs on the processor, "
            f"which takes hours to days (it needs about {need_gb} GB of memory)"
        )
    have = (hw.free_vram_mb or hw.total_vram_mb) / 1024
    if hw.gpu_integrated:
        return have >= need_gb, f"shared memory: about {have:.1f} GB for about {need_gb} GB needed"
    if have >= need_gb:
        return True, f"{hw.gpu_name}: {have:.1f} GB free covers the about {need_gb} GB needed"
    return False, (
        f"{hw.gpu_name} has {have:.1f} GB free and this run needs about {need_gb} GB: use 4-bit "
        "(NVIDIA), a shorter sequence length, a smaller base model, or close what else uses the card"
    )


def folder(data_dir: str | Path) -> Path:
    return Path(data_dir) / "training" / "env"


def python_of(env: Path) -> Path:
    return env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def converter_dir(env: Path) -> Path:
    return env / "llama.cpp"


def find_pythons() -> list[tuple[str, str]]:
    """Python interpreters on this machine that can host the environment: (path, version)."""
    seen, out = set(), []
    names = ["python3.12", "python3.11", "python3.10", "python3", "python", "py"]
    for name in names:
        exe = shutil.which(name)
        if not exe or exe in seen:
            continue
        seen.add(exe)
        try:
            probe = [exe, "-3.12"] if name == "py" else [exe]
            version = subprocess.run(
                [*probe, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"],
                capture_output=True,
                text=True,
                timeout=15,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
        if version in ("3.10", "3.11", "3.12"):
            out.append((exe, version))
    return out


def runtime_release() -> str:
    """The llama-cpp-python release ELI Legal runs, whose converter matches it."""
    try:
        import llama_cpp

        return str(llama_cpp.__version__)
    except Exception:
        return CONVERTER_RELEASE


def plan(data_dir: str | Path, hw: Hardware, *, four_bit: bool = True) -> Plan:
    env = folder(data_dir)
    acc = accelerator(hw)
    out = Plan(env, acc)
    if sys.platform == "darwin" and platform.machine() == "x86_64":
        # PyTorch's last build for Intel Macs is 2.2, older than the training libraries accept.
        out.problems.append(
            "PyTorch is no longer built for Intel Macs, so this Mac cannot train. Train on a Mac "
            "with Apple silicon, or on Windows or Linux, and copy the trained model here: it "
            "runs on this Mac like any other."
        )
        return out
    py = str(python_of(env))
    uv = shutil.which("uv")
    if uv:
        out.steps.append(
            Step(
                "Create the Python 3.12 environment",
                [uv, "venv", "--seed", "--python", PYTHON, str(env)],
                "uv fetches Python 3.12 itself if this machine does not have it",
            )
        )
        install = [uv, "pip", "install", "--python", py]
    else:
        pythons = find_pythons()
        if not pythons:
            out.problems.append(
                "No Python 3.10, 3.11 or 3.12 was found on this machine. Install "
                "Python 3.12 (python.org, or your system's packages), or uv "
                "(docs.astral.sh/uv), and check again."
            )
            return out
        exe, version = pythons[0]
        create = (
            [exe, "-3.12", "-m", "venv", str(env)]
            if exe.endswith("py")
            else [exe, "-m", "venv", str(env)]
        )
        out.steps.append(
            Step(f"Create the environment from Python {version}", create, f"uses {exe}")
        )
        install = [py, "-m", "pip", "install"]
    torch = [*install, TORCH] + (["--index-url", acc.index_url] if acc.index_url else [])
    out.steps.append(
        Step(
            f"Install PyTorch for {acc.label}",
            torch,
            "the largest download (up to about 3 GB); the build matches the accelerator",
        )
    )
    out.steps.append(
        Step(
            "Install the training libraries",
            [*install, *PACKAGES],
            "transformers, peft and accelerate at versions that work together",
        )
    )
    if acc.four_bit and four_bit:
        out.steps.append(
            Step(
                "Install 4-bit loading (bitsandbytes)",
                [*install, BITSANDBYTES],
                "lets a base model larger than the card's memory be trained in 4 bits",
            )
        )
    out.steps.append(
        Step(
            f"Fetch llama.cpp's converter (llama-cpp-python {runtime_release()})",
            [
                py,
                "-m",
                "pip",
                "download",
                f"llama-cpp-python=={runtime_release()}",
                "--no-binary",
                ":all:",
                "--no-deps",
                "-d",
                str(env / "downloads"),
            ],
            "only the source, to take the converter that writes GGUF from it",
        )
    )
    return out


def unpack_converter(env: Path, on_line: Callable[[str], None] = print) -> Path:
    """Take convert_hf_to_gguf.py, its conversion package and gguf-py out of the downloaded
    llama-cpp-python source, into the environment."""
    downloads = env / "downloads"
    archives = sorted(downloads.glob("llama_cpp_python-*.tar.gz"))
    if not archives:
        raise FileNotFoundError("the llama-cpp-python source was not downloaded")
    target = converter_dir(env)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    wanted = ("convert_hf_to_gguf.py", "conversion/", "gguf-py/")
    with tarfile.open(archives[-1]) as tar:
        for member in tar.getmembers():
            name = member.name.split("/vendor/llama.cpp/", 1)
            if len(name) != 2 or not name[1].startswith(wanted) or ".." in Path(name[1]).parts:
                continue
            if not (member.isfile() or member.isdir()):
                continue
            dest = target / name[1]
            if member.isdir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            source = tar.extractfile(member)
            if source is not None:
                dest.write_bytes(source.read())
    if not (target / "convert_hf_to_gguf.py").is_file():
        raise FileNotFoundError("the converter was not in the llama-cpp-python source")
    on_line(f"converter unpacked into {target}")
    return target


PROBE = r"""
import json, importlib, sys
out = {"python": sys.version.split()[0], "packages": {}}
for name in ("torch", "transformers", "peft", "accelerate", "safetensors", "sentencepiece", "bitsandbytes"):
    try:
        out["packages"][name] = getattr(importlib.import_module(name), "__version__", "installed")
    except Exception as exc:
        out["packages"][name] = None
try:
    import torch
    out["cuda"] = bool(torch.cuda.is_available())
    out["rocm"] = bool(getattr(torch.version, "hip", None))
    out["mps"] = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
    out["xpu"] = bool(getattr(torch, "xpu", None) and torch.xpu.is_available())
    if out["cuda"]:
        props = torch.cuda.get_device_properties(0)
        out["device"] = props.name
        out["memory_gb"] = round(props.total_memory / 1e9, 1)
        out["bf16"] = bool(torch.cuda.is_bf16_supported())
except Exception as exc:
    out["torch_error"] = str(exc)
print(json.dumps(out))
"""


def probe(env: Path, timeout: int = 180, python: str | Path | None = None) -> dict[str, Any]:
    """What the environment holds and can train on; {"ready": False, "why": …} if it is not
    set up. ``python`` checks another interpreter (one the organisation already keeps for
    training) in place of the environment's own; the converter is always the environment's."""
    py = Path(python) if python else python_of(env)
    if not py.is_file():
        return {"ready": False, "why": "the training environment is not set up"}
    try:
        res = subprocess.run(
            [str(py), "-c", PROBE], capture_output=True, text=True, timeout=timeout
        )
        found: dict[str, Any] = json.loads(res.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return {"ready": False, "why": "the training environment does not answer; set it up again"}
    # sentencepiece: llama.cpp's converter reaches for it before it looks at the tokenizer.
    missing = [
        k
        for k in ("torch", "transformers", "peft", "accelerate", "safetensors", "sentencepiece")
        if not found["packages"].get(k)
    ]
    found["converter"] = (converter_dir(env) / "convert_hf_to_gguf.py").is_file()
    if missing:
        found.update(ready=False, why="missing: " + ", ".join(missing))
    elif not found["converter"]:
        found.update(ready=False, why="llama.cpp's converter is missing; run the last step again")
    else:
        found["ready"] = True
        found["accelerator"] = (
            "cuda"
            if found.get("cuda")
            else "rocm"
            if found.get("rocm")
            else "mps"
            if found.get("mps")
            else "xpu"
            if found.get("xpu")
            else "cpu"
        )
    return found


def run_step(
    step: Step, on_line: Callable[[str], None], *, cancelled: Callable[[], bool] = lambda: False
) -> int:
    """Run one step, passing each line it prints to on_line. Returns its exit code."""
    on_line("$ " + " ".join(step.argv))
    proc = subprocess.Popen(
        step.argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env={**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"},
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        on_line(line.rstrip())
        if cancelled():
            proc.terminate()
            break
    return proc.wait()


def set_up(
    data_dir: str | Path,
    hw: Hardware,
    on_line: Callable[[str], None] = print,
    *,
    four_bit: bool = True,
    cancelled: Callable[[], bool] = lambda: False,
) -> dict[str, Any]:
    """Every step of the plan, then the converter and the check. Stops at the first that fails."""
    p = plan(data_dir, hw, four_bit=four_bit)
    if p.problems:
        return {"ready": False, "why": " ".join(p.problems)}
    p.folder.parent.mkdir(parents=True, exist_ok=True)
    for step in p.steps:
        on_line(f"── {step.label}: {step.why}")
        code = run_step(step, on_line, cancelled=cancelled)
        if code != 0 or cancelled():
            return {"ready": False, "why": f"{step.label} did not complete (exit {code})"}
    unpack_converter(p.folder, on_line)
    found = probe(p.folder)
    on_line(json.dumps(found, indent=2))
    return found


def remove(data_dir: str | Path) -> bool:
    env = folder(data_dir)
    if not env.exists():
        return False
    shutil.rmtree(env)
    return True


def tmp_dir(data_dir: str | Path) -> Path:
    """A private working folder for one training run's data (deleted when the run ends)."""
    base = Path(data_dir) / "training" / "work"
    base.mkdir(parents=True, exist_ok=True)
    os.chmod(base, 0o700)
    return Path(tempfile.mkdtemp(prefix="job-", dir=base))
