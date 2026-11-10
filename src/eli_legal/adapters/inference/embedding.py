"""Embedding models run in this process by llama.cpp, for searching by meaning.

The model is a GGUF file on this machine, found in the same folders as the chat models (a file
whose name says it embeds: nomic-embed, bge, e5, gte, mxbai, arctic-embed, …) or named in the
settings. Nothing leaves the machine. Each family of model is asked in the form it was trained
on: some want a query marked as a query and a passage as a passage.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eli_legal.adapters.inference import gguf_sizes, gpu_runtime
from eli_legal.adapters.inference.embedding_null import NullEmbedder
from eli_legal.adapters.inference.gguf import fingerprint, model_folders
from eli_legal.domain.errors import InferenceUnavailable
from eli_legal.ports.embedding import Kind

_BGE_QUERY = "Represent this sentence for searching relevant passages: "
# (name contains, query prefix, document prefix), first match wins.
_FAMILIES: tuple[tuple[str, str, str], ...] = (
    ("nomic-embed", "search_query: ", "search_document: "),
    ("multilingual-e5", "query: ", "passage: "),
    ("e5-", "query: ", "passage: "),
    ("bge-m3", "", ""),
    ("bge-", _BGE_QUERY, ""),
    ("mxbai-embed", _BGE_QUERY, ""),
    ("arctic-embed", _BGE_QUERY, ""),
    ("gte-", "", ""),
    ("embed", "", ""),
)
_EMBEDDERS = ("nomic-embed", "e5-", "bge-", "mxbai-embed", "arctic-embed", "gte-", "embed")
_NOT_EMBEDDERS = ("rerank", "mmproj", "vocab")
_BATCH = 16
_CONTEXT = 2048  # at most; never more than the model was trained on
_UNSTATED_CONTEXT = 512  # the shortest any embedding model in use is trained on


def prefixes(name: str) -> tuple[str, str]:
    lower = name.lower()
    for marker, query, document in _FAMILIES:
        if marker in lower:
            return query, document
    return "", ""


# Families measured on the shipped benchmark (python -m eli_legal evaluate) whose links from
# facts to issues were at least as precise as linking by words alone, best first. Others are
# used only when none of these is present, smallest first: bge-small ranked law best of those
# measured but linked facts less precisely than words (0.58 against 0.62).
_MEASURED_FIRST = ("nomic-embed",)


def _preference(path: Path) -> tuple[int, int]:
    name = path.name.lower()
    rank = next((i for i, m in enumerate(_MEASURED_FIRST) if m in name), len(_MEASURED_FIRST))
    return rank, path.stat().st_size


def discover(extra: str = "", home: Path | None = None) -> list[Path]:
    """Embedding GGUF files in the model folders: first those measured to link facts to
    issues at least as precisely as words do, then the rest smallest first (they are all
    quick; the smallest is the one most likely to fit beside a chat model)."""
    found: dict[str, Path] = {}
    for _label, folder in model_folders(extra, home):
        if not folder.is_dir():
            continue
        for path in folder.rglob("*.gguf"):
            name = path.name.lower()
            if any(m in name for m in _EMBEDDERS) and not any(m in name for m in _NOT_EMBEDDERS):
                try:
                    real = path.resolve()
                    if real.stat().st_size > 5 * 1024 * 1024:
                        found.setdefault(str(real), real)
                except OSError:
                    continue
    return sorted(found.values(), key=_preference)


@dataclass
class GgufEmbedder:
    path: Path
    n_gpu_layers: int = -1
    n_threads: int = 0
    available: bool = True
    reason: str = ""
    model_id: str = ""
    _llm: Any = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if not self.model_id:
            self.model_id = f"{self.path.name}@{fingerprint(self.path)[:12]}"
        self._query, self._document = prefixes(self.path.name)
        # A text longer than the model was trained on would read past its position table and
        # stop llama.cpp, and the program with it. Texts are cut to this many tokens instead.
        trained = gguf_sizes.trained_context(self.path)
        self.context = min(_CONTEXT, trained) if trained > 0 else _UNSTATED_CONTEXT

    def _model(self) -> Any:
        if self._llm is None:
            module = gpu_runtime.llama()
            if module is None or not hasattr(module, "Llama"):
                self.available = False
                self.reason = "llama.cpp for Python is not installed here"
                raise InferenceUnavailable(self.reason)
            kwargs: dict[str, Any] = {
                "model_path": str(self.path),
                "embedding": True,
                "n_ctx": self.context,
                "n_batch": self.context,  # llama.cpp cuts each text to this many tokens
                "n_ubatch": self.context,
                "n_gpu_layers": self.n_gpu_layers,
                "verbose": False,
            }
            if self.n_threads > 0:
                kwargs["n_threads"] = self.n_threads
            self._llm = module.Llama(**kwargs)
        return self._llm

    def embed(self, texts: Sequence[str], *, kind: Kind) -> list[list[float]]:
        prefix = self._query if kind == "query" else self._document
        out: list[list[float]] = []
        with self._lock:
            llm = self._model()
            for start in range(0, len(texts), _BATCH):
                batch = [f"{prefix}{t}" for t in texts[start : start + _BATCH]]
                for vector in llm.embed(batch, truncate=True):
                    out.append(_unit(vector))
        return out

    def close(self) -> None:
        with self._lock:
            close = getattr(self._llm, "close", None)
            if callable(close):
                close()
            self._llm = None


def _unit(vector: Any) -> list[float]:
    # Some models return one vector per token; the passage is their mean.
    if vector and isinstance(vector[0], list):
        width = len(vector[0])
        vector = [sum(row[i] for row in vector) / len(vector) for i in range(width)]
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [float(x) / norm for x in vector]


def from_settings(setting: str, *, extra_dirs: str = "", home: Path | None = None) -> Any:
    """'' or 'none': off. 'auto': the first embedding model found. Otherwise a file path."""
    value = (setting or "").strip()
    if value.lower() in ("", "none", "off"):
        return NullEmbedder("searching by meaning is switched off in the settings")
    # Whether llama.cpp can run it is found out when it is first used: loading llama.cpp here
    # would slow every command. If it cannot, research says so and ranks by words.
    if value.lower() == "auto":
        found = discover(extra_dirs, home)
        if not found:
            return NullEmbedder(
                "no embedding model was found in the model folders (put one there, for "
                "example nomic-embed-text-v1.5 or bge-small-en-v1.5 in GGUF form)"
            )
        return GgufEmbedder(found[0])
    path = Path(value).expanduser()
    if not path.is_file():
        return NullEmbedder(f"the embedding model {path} does not exist")
    return GgufEmbedder(path)
