"""GGUF models run in this process with llama.cpp, as ELI v2 and v3 run them.

Nothing leaves the machine: the model file is read from disk and llama.cpp runs on this
computer's processor and, where the build supports it, its graphics card. The model is loaded on
first use and kept loaded; two settings that name the same file share one copy.

Finding models: the folders ELI v2 and v3 keep theirs in, ELI Legal's own ``models`` folder, the
folders of other local-model tools, and any folders the administrator adds.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eli_legal.domain.errors import InferenceUnavailable, InvalidInput

# A reasoning model's working, closed or cut off by the token limit, is never part of the answer.
_THINK = re.compile(r"<think>.*?(?:</think>\s*|\Z)", re.S | re.I)
# Files that are GGUF but not chat models: vision projectors, embedders, speech, adapters.
_NOT_CHAT = re.compile(r"mmproj|embed|whisper|wakeword|lora|adapter|reranker|vocab", re.I)
_LOADED: dict[tuple[str, int, int, int], Any] = {}
_LOAD_LOCK = threading.Lock()


def llama_available() -> bool:
    try:
        import llama_cpp  # noqa: F401
    except Exception:  # an import that fails for any reason means it cannot be used
        return False
    return True


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


class GgufInference:
    """A GGUF model on this machine, through llama.cpp."""

    available = True

    def __init__(
        self,
        model_path: str | Path,
        *,
        n_ctx: int = 8192,
        n_gpu_layers: int = 0,
        n_threads: int = 0,
    ) -> None:
        path = Path(model_path).expanduser()
        if path.suffix.lower() != ".gguf" or not path.is_file():
            raise InvalidInput(f"no GGUF model file at {path}")
        self.path = path.resolve()
        self.n_ctx = max(2048, int(n_ctx))
        self.n_gpu_layers = int(n_gpu_layers)
        self.n_threads = int(n_threads) or max(1, (os.cpu_count() or 4) - 2)
        self.model_id = f"gguf:{self.path.name}@{fingerprint(self.path)[:12]}"
        self._lock = threading.Lock()

    def _llama(self) -> Any:
        key = (str(self.path), self.n_ctx, self.n_gpu_layers, self.n_threads)
        with _LOAD_LOCK:
            if key in _LOADED:
                return _LOADED[key]
            try:
                from llama_cpp import Llama
            except Exception as exc:
                raise InferenceUnavailable(
                    "GGUF models need llama.cpp for Python, which is not installed here: "
                    "pip install 'eli-legal[gguf]'"
                ) from exc
            try:
                llm = Llama(
                    model_path=str(self.path),
                    n_ctx=self.n_ctx,
                    n_gpu_layers=self.n_gpu_layers,
                    n_threads=self.n_threads,
                    verbose=False,
                )
            except Exception as exc:  # llama.cpp reports load failures as plain exceptions
                raise InferenceUnavailable(f"could not load {self.path.name}: {exc}") from exc
            # One model in memory per file: a new setting for the same file replaces the old.
            for old in [k for k in _LOADED if k[0] == key[0]]:
                _LOADED.pop(old)
            _LOADED[key] = llm
            return llm

    def warm(self) -> None:
        """Load the model now rather than at the first question."""
        self._llama()

    def generate(
        self, *, system: str, prompt: str, max_tokens: int = 2048, json_mode: bool = False
    ) -> str:
        llm = self._llama()
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
        with self._lock:  # llama.cpp contexts are not safe to share between threads
            try:
                result = llm.create_chat_completion(**kwargs)
            except ValueError as exc:  # most often: the prompt does not fit the context
                raise InferenceUnavailable(f"{self.path.name}: {exc}") from exc
            except Exception as exc:
                raise InferenceUnavailable(
                    f"{self.path.name} failed: {type(exc).__name__}"
                ) from exc
        try:
            text = str(result["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError) as exc:
            raise InferenceUnavailable(f"{self.path.name} returned no text") from exc
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


def _data_roots(app: str) -> list[Path]:
    home = Path.home()
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        return [local / app, local / app.lower()]
    if sys.platform == "darwin":
        return [home / "Library" / "Application Support" / app]
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    return [data / app, data / app.lower()]


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
    for root in _data_roots("ELI_v3"):
        out.append(("ELI v3", root / "models"))
    if os.environ.get("ELI_V3_ROOT"):
        out.append(("ELI v3", Path(os.environ["ELI_V3_ROOT"]) / "models"))
    for root in _data_roots("ELI_v2"):
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
