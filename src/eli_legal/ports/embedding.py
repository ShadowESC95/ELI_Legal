from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol

Kind = Literal["query", "document"]


class EmbeddingPort(Protocol):
    """Turns text into vectors whose closeness reflects closeness of meaning. Used to find and
    rank; never to decide whether a source says something."""

    model_id: str  # names the model and its file, so vectors of two models are never mixed
    available: bool
    reason: str  # why it is unavailable, in plain words

    def embed(self, texts: Sequence[str], *, kind: Kind) -> list[list[float]]: ...
