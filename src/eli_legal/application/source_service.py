from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eli_legal.adapters.sources.local_corpus import import_corpus
from eli_legal.application.container import AppContext
from eli_legal.domain.errors import NotFound
from eli_legal.domain.models import Authority
from eli_legal.legal.source_registry import RegisteredSource
from eli_legal.ports.legal_sources import ConnectorDeclaration
from eli_legal.security import authn

# The class below has a method named `list`; this is the builtin, for annotations.
_List = list


@dataclass(slots=True)
class SourceService:
    """Manages the approved-source register. There is no path to a source that bypasses it."""

    ctx: AppContext

    def list(self) -> _List[RegisteredSource]:
        return self.ctx.sources.list()

    def register(self, source: RegisteredSource, *, actor_id: str) -> RegisteredSource:
        self.ctx.authorizer().require_global(actor_id, "source.manage")
        source.approved = False  # registration never approves; approval is its own decision
        source.approved_by = source.approved_at = None
        self.ctx.sources.add(source)
        self._log(source.source_id, actor_id, "source_registered", "registered")
        return source

    def approve(self, source_id: str, *, actor_id: str) -> RegisteredSource:
        authn.require_step_up(actor_id, "approve a legal source")
        self.ctx.authorizer().require_global(actor_id, "source.manage")
        source = self.ctx.sources.approve(source_id, approved_by=actor_id)
        if source.network_required:
            for host in source.hosts:
                self.ctx.guard.approve_host(host)
        self._log(source_id, actor_id, "source_approved", "approved")
        return source

    def revoke(self, source_id: str, *, actor_id: str) -> None:
        self.ctx.authorizer().require_global(actor_id, "source.manage")
        self.ctx.sources.revoke(source_id)
        self._log(source_id, actor_id, "source_revoked", "revoked")

    def import_corpus(
        self, source_id: str, directory: str | Path, *, actor_id: str
    ) -> _List[Authority]:
        self.ctx.authorizer().require_global(actor_id, "source.manage")
        source = self.ctx.sources.get(source_id)
        if source is None:
            raise NotFound(f"unknown source: {source_id}")
        imported = import_corpus(self.ctx.store, source, directory)
        self.ctx.log(
            "corpus_imported",
            actor_id=actor_id,
            matter_id="-",
            action="source.manage",
            subject_id=source_id,
            outcome="imported",
            object_type="source",
            source_ids=[source_id],
            payload={
                "authorities": len(imported),
                "versions": [a.source_version_id for a in imported][:50],
            },
        )
        return imported

    def describe(self, source_id: str) -> ConnectorDeclaration:
        source = self.ctx.sources.get(source_id)
        if source is None:
            raise NotFound(f"unknown source: {source_id}")
        return ConnectorDeclaration(
            source_id=source.source_id,
            name=source.name,
            authority_owner=source.authority_owner,
            licence=source.licence,
            jurisdictions=tuple(sorted(source.jurisdictions)),
            source_types=source.source_types,
            network_required=source.network_required,
            hosts=source.hosts,
            freshness=source.freshness,
            treatment_semantics=source.treatment_semantics,
            authoritative_for=source.authoritative_for,
            inspection=source.inspection,
        )

    def require_source(self, source_id: str, jurisdiction: str) -> RegisteredSource:
        return self.ctx.sources.require_approved(source_id, jurisdiction)

    def _log(self, source_id: str, actor_id: str, event: str, outcome: str) -> None:
        self.ctx.log(
            event,
            actor_id=actor_id,
            matter_id="-",
            action="source.manage",
            subject_id=source_id,
            outcome=outcome,
            object_type="source",
            source_ids=[source_id],
        )
