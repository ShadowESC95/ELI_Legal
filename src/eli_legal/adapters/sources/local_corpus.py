"""Approved local corpus of legal authorities.

A deployer loads authorities it is entitled to use, each with a metadata record stating what the
authority is, where it came from, and its legal status as last confirmed at source. The connector
answers from that corpus only: no network, and no answer the corpus does not contain.

Status is computed for a date. An authority's history is a list of dated treatments, so the
connector can say both what the position was on the matter's relevant date and what it is now.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from eli_legal.adapters.local.parsers import LocalDocumentParser
from eli_legal.domain.enums import AuthorityKind, AuthorityStatus
from eli_legal.domain.errors import ConnectorError
from eli_legal.domain.models import Authority, AuthorityPassage, Treatment, utcnow
from eli_legal.legal.authority_status import status_at
from eli_legal.legal.citations import normalise_citation
from eli_legal.legal.source_registry import RegisteredSource
from eli_legal.persistence.sqlite import Store
from eli_legal.ports.legal_sources import AuthorityHit, ConnectorDeclaration, StatusFinding


class LocalCorpusConnector:
    def __init__(self, store: Store, source: RegisteredSource) -> None:
        self.store = store
        self.source = source
        self.source_id = source.source_id

    def describe(self) -> ConnectorDeclaration:
        s = self.source
        return ConnectorDeclaration(
            source_id=s.source_id,
            name=s.name,
            authority_owner=s.authority_owner,
            licence=s.licence,
            jurisdictions=tuple(sorted(s.jurisdictions)),
            source_types=s.source_types,
            network_required=False,
            freshness=s.freshness,
            treatment_semantics=s.treatment_semantics,
            authoritative_for=s.authoritative_for,
            inspection=s.inspection,
        )

    def search(
        self, *, jurisdictions: Sequence[str], query: str, limit: int = 10
    ) -> Sequence[AuthorityHit]:
        rows = self.store.search_passages(
            query, [self.source_id], jurisdictions=jurisdictions, limit=limit
        )
        return [AuthorityHit(authority, passage, score) for passage, authority, score in rows]

    def resolve(self, *, citation_key: str) -> Sequence[Authority]:
        return self.store.authorities_by_citation(citation_key, [self.source_id])

    def get(self, *, authority_id: str) -> Authority | None:
        authority = self.store.get_authority(authority_id)
        return authority if authority and authority.source_id == self.source_id else None

    def passages(self, *, authority_id: str) -> Sequence[AuthorityPassage]:
        return self.store.passages_for(authority_id) if self.get(authority_id=authority_id) else []

    def status(self, *, authority: Authority, as_of: date | None = None) -> StatusFinding:
        today = utcnow().date()
        now = status_at(authority, today)
        # A curator may record only the current position, without a dated history.
        if now is AuthorityStatus.IN_FORCE and authority.status not in (
            AuthorityStatus.IN_FORCE,
            AuthorityStatus.UNKNOWN,
        ):
            now = authority.status
        then = status_at(authority, as_of) if as_of else None
        return StatusFinding(
            status_now=now,
            status_at_relevant_date=then,
            checked_at=authority.status_checked_at,
            basis=authority.status_basis,
            events=tuple(authority.treatments),
        )


# ── corpus import ────────────────────────────────────────────────────────────
def _parse_date(value: Any) -> date | None:
    return date.fromisoformat(value) if value else None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def import_corpus(store: Store, source: RegisteredSource, directory: str | Path) -> list[Authority]:
    """Load ``*.json`` authority records from a directory into the corpus for ``source``.

    Each record needs ``citation``, ``title``, ``jurisdiction`` and one of ``text``,
    ``text_file`` (a path relative to the record) or ``passages`` (the text already divided:
    ``[{"locator": "s.10", "text": "…", "heading": "…"}]``). Re-importing a record with the same citation
    replaces the earlier version.
    """
    root = Path(directory)
    if not root.is_dir():
        raise ConnectorError(f"corpus directory not found: {root}")
    records: list[tuple[str, Any]] = []
    for record_path in sorted(root.glob("*.json")):
        try:
            records.append((record_path.name, json.loads(record_path.read_text(encoding="utf-8"))))
        except ValueError as exc:
            raise ConnectorError(f"invalid corpus record {record_path.name}: {exc}") from exc
    return import_records(store, source, records, root=root)


def import_records(
    store: Store,
    source: RegisteredSource,
    records: Sequence[tuple[str, Any]],
    *,
    root: Path | None = None,
) -> list[Authority]:
    """Load authority records (name, record) into the corpus for ``source``. ``root`` is where
    a record's ``text_file`` is looked for; without one, records carry their text."""
    parser = LocalDocumentParser()
    imported: list[Authority] = []
    for name, meta in records:
        record_path = (root or Path(".")) / name
        try:
            citation = str(meta["citation"]).strip()
            jurisdiction = str(meta["jurisdiction"]).strip()
            title = str(meta.get("title") or citation)
        except (ValueError, KeyError, TypeError) as exc:
            raise ConnectorError(f"invalid corpus record {name}: {exc}") from exc
        if jurisdiction not in source.jurisdictions:
            raise ConnectorError(
                f"{record_path.name}: jurisdiction {jurisdiction} is outside source "
                f"{source.source_id}"
            )
        headings: list[str] = []
        if isinstance(meta.get("passages"), list):
            # Already divided by its publisher: each passage with its own locator ("s.10",
            # "Art. 17(1)") and, if the source prints one, its heading.
            try:
                given = [(str(x["locator"]), str(x["text"]), str(x.get("heading") or ""))
                         for x in meta["passages"] if str(x.get("text") or "").strip()]  # fmt: skip
            except (KeyError, TypeError) as exc:
                raise ConnectorError(f"{record_path.name}: invalid passage: {exc}") from exc
            if not given:
                raise ConnectorError(f"{record_path.name}: no passage has any text")
            segments = [(loc, text) for loc, text, _ in given]
            headings = [head for _, _, head in given]
            raw_for_hash = json.dumps(meta["passages"], sort_keys=True).encode("utf-8")
        elif meta.get("text_file"):
            if root is None:
                raise ConnectorError(f"{name}: a text_file needs the corpus folder it is in")
            file_path = (record_path.parent / meta["text_file"]).resolve()
            if root.resolve() not in file_path.parents:
                raise ConnectorError(f"{record_path.name}: text_file must be inside the corpus")
            parsed = parser.parse(file_path.name, file_path.read_bytes())
            segments = [(s.locator, s.text) for s in parsed.segments]
            raw_for_hash = file_path.read_bytes()
        else:
            text = str(meta.get("text") or "")
            if not text.strip():
                raise ConnectorError(f"{record_path.name}: no text or text_file")
            parsed = parser.parse("record.txt", text.encode("utf-8"))
            segments = [(s.locator, s.text) for s in parsed.segments]
            raw_for_hash = text.encode("utf-8")
        key = normalise_citation(citation)
        existing = store.authorities_by_citation(key, [source.source_id])
        authority = Authority(
            source_id=source.source_id,
            citation=citation,
            title=title,
            jurisdiction=jurisdiction,
            kind=AuthorityKind(meta.get("kind", "case")),
            uri=str(meta.get("uri") or ""),
            content_hash=hashlib.sha256(raw_for_hash).hexdigest(),
            court=str(meta.get("court") or ""),
            decision_date=_parse_date(meta.get("decision_date")),
            effective_from=_parse_date(meta.get("effective_from")),
            effective_to=_parse_date(meta.get("effective_to")),
            status=AuthorityStatus(meta.get("status", "unknown")),
            status_checked_at=_parse_datetime(meta.get("status_checked_at")),
            status_basis=str(meta.get("status_basis") or ""),
            treatments=[
                Treatment(
                    treatment=str(t["treatment"]),
                    effective_date=date.fromisoformat(t["effective_date"]),
                    by_citation=str(t.get("by_citation") or ""),
                    note=str(t.get("note") or ""),
                )
                for t in meta.get("treatments", [])
            ],
            aliases=[str(a) for a in meta.get("aliases", [])],
        )
        # Re-importing replaces the same version; a different effective date is a new version
        # of the same instrument and is kept beside the others.
        same_version = [a for a in existing if a.effective_from == authority.effective_from]
        if same_version:
            authority.authority_id = same_version[0].authority_id
        passages = [
            AuthorityPassage(
                authority_id=authority.authority_id,
                ordinal=i,
                locator=locator,
                text=text,
                text_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                heading=headings[i] if i < len(headings) else "",
            )
            for i, (locator, text) in enumerate(segments)
        ]
        keys = [key, *(normalise_citation(a) for a in authority.aliases)]
        store.put_authority(authority, passages, keys)
        imported.append(authority)
    return imported
