from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from eli_legal.domain.models import SourceVersion


class LegalSourcePort(Protocol):
    def search(
        self, *, jurisdiction: str, query: str, limit: int = 20
    ) -> Sequence[SourceVersion]: ...
    def get_current_status(self, *, source_version_id: str, as_of: str | None = None) -> dict: ...
    def verify_citation(self, *, citation: str) -> dict: ...
