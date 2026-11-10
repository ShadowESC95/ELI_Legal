"""Searching by meaning: approved sources' passages as vectors from a local embedding model.

Keyword search finds the passages that use the words of the question. Lawyers and the texts
they cite often use different words for the same thing ("lost the right to reject" and
"deemed to have accepted"), so each passage is also turned into vectors by an embedding model
and found by closeness of meaning; ``CaseLawRetriever`` fuses the two rankings.

What this changes and what it does not: it changes which passages are offered and in what
order. It never decides whether a source says something: a passage found by meaning is quoted
word for word and checked exactly like one found by its words.

Each passage is embedded in windows of a few sentences, under its heading, and is as close to
a question as its closest window. Vectors are stored per model, so changing the model never
mixes two models' vectors; a passage that is replaced loses its vectors with it.
"""

from __future__ import annotations

import array
import hashlib
import importlib
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from eli_legal.domain.models import AuthorityPassage
from eli_legal.domain.stopping import check_stop
from eli_legal.legal.dates import split_sentences
from eli_legal.persistence.sqlite import Store
from eli_legal.ports.embedding import EmbeddingPort

WINDOW_CHARS = 800
INDEX_BATCH = 64

# numpy comes with llama.cpp for Python, which any real embedding model needs. Imported by name:
# its type stubs need a newer Python than this package supports.
_np: Any
try:
    _np = importlib.import_module("numpy")
except ImportError:  # pragma: no cover - the pure-Python path is what the tests' fake uses
    _np = None


def windows(passage: AuthorityPassage) -> list[str]:
    """The passage in windows of whole sentences, each under the passage's heading."""
    pieces: list[str] = []
    for line in passage.text.splitlines() or [passage.text]:
        line = line.strip()
        if not line:
            continue
        pieces.extend(split_sentences(line) if len(line) > WINDOW_CHARS else [line])
    out: list[str] = []
    current = ""
    for piece in pieces:
        piece = piece[: WINDOW_CHARS * 2]
        if current and len(current) + len(piece) + 1 > WINDOW_CHARS:
            out.append(current)
            current = piece
        else:
            current = f"{current} {piece}".strip()
    if current:
        out.append(current)
    head = passage.heading.strip()
    return [f"{head}\n{w}" if head else w for w in out] or [head or passage.locator]


def _pack(vector: Sequence[float]) -> bytes:
    return array.array("f", vector).tobytes()


def _unpack(blob: bytes) -> array.array[float]:
    out = array.array("f")
    out.frombytes(blob)
    return out


@dataclass(frozen=True, slots=True)
class Coverage:
    indexed_now: int
    total: int
    missing: int

    @property
    def complete(self) -> bool:
        return self.missing == 0


@dataclass
class SemanticIndex:
    store: Store
    embedder: EmbeddingPort
    _cache: dict[tuple[Any, ...], tuple[list[str], list[int], Any]] = field(
        default_factory=dict, repr=False
    )
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def available(self) -> bool:
        return bool(self.embedder.available)

    @property
    def model_id(self) -> str:
        return self.embedder.model_id

    # ── building ────────────────────────────────────────────────────────────
    def ensure(
        self,
        source_ids: Iterable[str],
        jurisdictions: Iterable[str] | None = None,
        *,
        budget: int = 4000,
    ) -> Coverage:
        """Embed passages of these sources that have no vectors for this model yet, up to
        ``budget`` passages. Returns what is covered."""
        ids = sorted(set(source_ids))
        js = sorted(set(jurisdictions)) if jurisdictions is not None else None
        todo = self.store.passages_without_vectors(self.model_id, ids, js, limit=max(budget, 0))
        done = 0
        for start in range(0, len(todo), INDEX_BATCH):
            check_stop()
            batch = todo[start : start + INDEX_BATCH]
            texts: list[str] = []
            owners: list[tuple[str, int]] = []
            for passage in batch:
                for part, text in enumerate(windows(passage)):
                    texts.append(text)
                    owners.append((passage.passage_id, part))
            vectors = self.embedder.embed(texts, kind="document")
            self.store.put_passage_vectors(
                self.model_id,
                [(pid, part, _pack(v)) for (pid, part), v in zip(owners, vectors, strict=True)],
            )
            done += len(batch)
        total = self.store.count_passages(ids, js)
        missing = len(self.store.passages_without_vectors(self.model_id, ids, js, limit=total))
        return Coverage(done, total, missing)

    # ── searching ───────────────────────────────────────────────────────────
    def query_vector(self, text: str) -> list[float]:
        key = hashlib.sha256(f"query\n{text}".encode()).hexdigest()
        held = self.store.text_vector(self.model_id, key)
        if held is not None:
            return list(_unpack(held))
        [vector] = self.embedder.embed([text], kind="query")
        self.store.put_text_vector(self.model_id, key, _pack(vector))
        return vector

    def document_vectors(self, texts: Sequence[str]) -> list[list[float]]:
        """Vectors for short texts (facts, issues), kept so a re-run need not embed again."""
        keys = [hashlib.sha256(f"document\n{t}".encode()).hexdigest() for t in texts]
        out: dict[int, list[float]] = {}
        todo: list[int] = []
        for i, key in enumerate(keys):
            held = self.store.text_vector(self.model_id, key)
            if held is None:
                todo.append(i)
            else:
                out[i] = list(_unpack(held))
        if todo:
            for i, vector in zip(
                todo, self.embedder.embed([texts[i] for i in todo], kind="document"), strict=True
            ):
                self.store.put_text_vector(self.model_id, keys[i], _pack(vector))
                out[i] = vector
        return [out[i] for i in range(len(texts))]

    def _matrix(self, ids: list[str], js: list[str] | None) -> tuple[list[str], list[int], Any]:
        version = self.store.vector_version(self.model_id)
        key = (self.model_id, tuple(ids), tuple(js) if js is not None else None, version)
        with self._lock:
            if key not in self._cache:
                rows = self.store.passage_vectors(self.model_id, ids, js)
                owners = [r[0] for r in rows]
                parts = [r[1] for r in rows]
                if _np is not None and rows:
                    matrix: Any = _np.frombuffer(b"".join(r[2] for r in rows), dtype=_np.float32)
                    matrix = matrix.reshape(len(rows), -1)
                else:
                    matrix = [_unpack(r[2]) for r in rows]
                self._cache = {key: (owners, parts, matrix)}  # one corpus at a time is plenty
            return self._cache[key]

    def search(
        self,
        query: str,
        source_ids: Iterable[str],
        jurisdictions: Iterable[str] | None = None,
        *,
        limit: int = 50,
        with_part: bool = False,
    ) -> list[Any]:
        """(passage_id, similarity), or with ``with_part`` (passage_id, similarity, window),
        for the passages closest in meaning, closest first."""
        ids = sorted(set(source_ids))
        js = sorted(set(jurisdictions)) if jurisdictions is not None else None
        if not ids or (js is not None and not js):
            return []
        owners, parts, matrix = self._matrix(ids, js)
        if not owners:
            return []
        q = self.query_vector(query)
        if _np is not None and not isinstance(matrix, list):
            sims = (matrix @ _np.asarray(q, dtype=_np.float32)).tolist()
        else:
            sims = [sum(a * b for a, b in zip(row, q, strict=True)) for row in matrix]
        best: dict[str, tuple[float, int]] = {}
        for owner, part, sim in zip(owners, parts, sims, strict=True):
            if owner not in best or sim > best[owner][0]:
                best[owner] = (float(sim), part)
        ranked = sorted(best.items(), key=lambda kv: -kv[1][0])[:limit]
        if with_part:
            return [(pid, sim, part) for pid, (sim, part) in ranked]
        return [(pid, sim) for pid, (sim, _part) in ranked]

    def closest(self, text: str, passages: Sequence[AuthorityPassage]) -> tuple[str, float] | None:
        """Of these passages (one authority's, say), the one closest in meaning to ``text``.
        Passages not yet embedded are embedded first."""
        if not passages:
            return None
        held = {pid for pid, _part, _v in self.store.vectors_for_passages(
            self.model_id, [p.passage_id for p in passages])}  # fmt: skip
        todo = [p for p in passages if p.passage_id not in held]
        if todo:
            texts, owners = [], []
            for passage in todo:
                for part, window in enumerate(windows(passage)):
                    texts.append(window)
                    owners.append((passage.passage_id, part))
            vectors = self.embedder.embed(texts, kind="document")
            self.store.put_passage_vectors(
                self.model_id,
                [(pid, part, _pack(v)) for (pid, part), v in zip(owners, vectors, strict=True)],
            )
        q = self.query_vector(text)
        best: tuple[str, float] | None = None
        for pid, _part, blob in self.store.vectors_for_passages(
            self.model_id, [p.passage_id for p in passages]
        ):
            sim = self.similarity(_unpack(blob), q)
            if best is None or sim > best[1]:
                best = (pid, sim)
        return best

    def similarity(self, a: Sequence[float], b: Sequence[float]) -> float:
        return float(sum(x * y for x, y in zip(a, b, strict=True)))
