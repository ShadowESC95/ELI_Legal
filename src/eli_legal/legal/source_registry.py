from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from eli_legal.domain.errors import PolicyDenied
from eli_legal.domain.models import utcnow

if TYPE_CHECKING:
    from eli_legal.persistence.sqlite import Store

_KIND = "source"


@dataclass(slots=True)
class RegisteredSource:
    source_id: str
    name: str
    approved: bool = False
    jurisdictions: frozenset[str] = field(default_factory=frozenset)
    connector: str = "local_corpus"
    source_types: tuple[str, ...] = ()
    authority_owner: str = ""
    licence: str = ""
    terms_reviewed: bool = False
    network_required: bool = False
    hosts: tuple[str, ...] = ()
    freshness: str = ""
    treatment_semantics: str = ""
    authoritative_for: tuple[str, ...] = ()
    inspection: str = ""
    approved_by: str | None = None
    approved_at: datetime | None = None


# The class below has a method named `list`; this is the builtin, for annotations.
_List = list


class SourceRegistry:
    """The only list of legal sources the system may read. Unlisted or unapproved means refused."""

    def __init__(
        self, sources: _List[RegisteredSource] | None = None, *, store: Store | None = None
    ) -> None:
        self._store = store
        self._sources = {s.source_id: s for s in (sources or [])}
        if store is not None:
            for s in store.list_registry(_KIND, RegisteredSource):
                self._sources.setdefault(s.source_id, s)

    def add(self, source: RegisteredSource) -> None:
        self._sources[source.source_id] = source
        if self._store is not None:
            self._store.put_registry(_KIND, source.source_id, source)

    def get(self, source_id: str) -> RegisteredSource | None:
        return self._sources.get(source_id)

    def list(self) -> _List[RegisteredSource]:
        return sorted(self._sources.values(), key=lambda s: s.source_id)

    def approve(self, source_id: str, *, approved_by: str) -> RegisteredSource:
        source = self._sources.get(source_id)
        if source is None:
            raise PolicyDenied(f"unknown source: {source_id}")
        missing = [
            label
            for label, ok in (
                ("licence/terms recorded", bool(source.licence)),
                ("terms reviewed", source.terms_reviewed),
                ("authority owner recorded", bool(source.authority_owner)),
                ("jurisdictions declared", bool(source.jurisdictions)),
                ("status semantics declared", bool(source.treatment_semantics)),
                ("allowed hosts declared", bool(source.hosts) or not source.network_required),
            )
            if not ok
        ]
        if missing:
            raise PolicyDenied(
                f"source {source_id} cannot be approved; missing: {', '.join(missing)}"
            )
        source.approved = True
        source.approved_by = approved_by
        source.approved_at = utcnow()
        self.add(source)
        return source

    def revoke(self, source_id: str) -> None:
        source = self._sources.get(source_id)
        if source is not None:
            source.approved = False
            self.add(source)

    def require_approved(self, source_id: str, jurisdiction: str | None = None) -> RegisteredSource:
        source = self._sources.get(source_id)
        if source is None or not source.approved:
            raise PolicyDenied(f"source is not approved: {source_id}")
        if jurisdiction and jurisdiction not in source.jurisdictions:
            raise PolicyDenied(f"source {source_id} not approved for jurisdiction {jurisdiction}")
        return source

    def usable_for(self, source_ids: Iterable[str], jurisdictions: Iterable[str]) -> _List[str]:
        """Approved sources among ``source_ids`` that cover at least one of the jurisdictions."""
        wanted = set(jurisdictions)
        out = []
        for sid in sorted(set(source_ids)):
            source = self._sources.get(sid)
            if source is not None and source.approved and (source.jurisdictions & wanted):
                out.append(sid)
        return out
