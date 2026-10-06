from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

from eli_legal.domain.enums import AuthorityStatus
from eli_legal.domain.models import Authority, AuthorityPassage, Treatment


@dataclass(frozen=True, slots=True)
class ConnectorDeclaration:
    """What a connector is and what its answers mean. Required before a source can be approved."""

    source_id: str
    name: str
    authority_owner: str  # who publishes the material
    licence: str  # terms under which it may be used
    jurisdictions: tuple[str, ...]
    source_types: tuple[str, ...]  # case, legislation, rule, treaty, secondary
    network_required: bool
    hosts: tuple[str, ...] = ()  # the only hosts the connector may contact
    freshness: str = ""  # how current the material is and how that is known
    treatment_semantics: str = ""  # what a status answer from this source means
    # Citation pattern ids for which absence from this source means the citation does not exist.
    authoritative_for: tuple[str, ...] = ()
    inspection: str = ""  # how a human can look at the original


@dataclass(frozen=True, slots=True)
class AuthorityHit:
    authority: Authority
    passage: AuthorityPassage
    score: float


@dataclass(frozen=True, slots=True)
class StatusFinding:
    status_now: AuthorityStatus
    status_at_relevant_date: AuthorityStatus | None
    checked_at: datetime | None  # when the source last confirmed the status
    basis: str
    events: tuple[Treatment, ...] = field(default_factory=tuple)


class LegalSourcePort(Protocol):
    source_id: str

    def describe(self) -> ConnectorDeclaration: ...

    def search(
        self, *, jurisdictions: Sequence[str], query: str, limit: int = 10
    ) -> Sequence[AuthorityHit]: ...

    def resolve(self, *, citation_key: str) -> Sequence[Authority]: ...

    def get(self, *, authority_id: str) -> Authority | None: ...

    def passages(self, *, authority_id: str) -> Sequence[AuthorityPassage]: ...

    def status(self, *, authority: Authority, as_of: date | None = None) -> StatusFinding: ...
