from __future__ import annotations

from dataclasses import dataclass

from eli_legal.domain.errors import PolicyDenied


@dataclass(frozen=True, slots=True)
class RegisteredSource:
    source_id: str
    name: str
    approved: bool
    jurisdictions: frozenset[str]
    connector: str


class SourceRegistry:
    def __init__(self, sources: list[RegisteredSource] | None = None) -> None:
        self._sources = {s.source_id: s for s in (sources or [])}

    def add(self, source: RegisteredSource) -> None:
        self._sources[source.source_id] = source

    def require_approved(self, source_id: str, jurisdiction: str | None = None) -> RegisteredSource:
        source = self._sources.get(source_id)
        if source is None or not source.approved:
            raise PolicyDenied(f"source is not approved: {source_id}")
        if jurisdiction and jurisdiction not in source.jurisdictions:
            raise PolicyDenied(f"source {source_id} not approved for jurisdiction {jurisdiction}")
        return source
