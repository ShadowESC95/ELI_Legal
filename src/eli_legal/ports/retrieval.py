from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class RetrievalHit(Protocol):
    source_version_id: str
    locator: str
    text: str
    score: float


class RetrievalPort(Protocol):
    def search(
        self, *, matter_id: str, query: str, approved_source_ids: set[str], limit: int = 10
    ) -> Sequence[RetrievalHit]: ...
