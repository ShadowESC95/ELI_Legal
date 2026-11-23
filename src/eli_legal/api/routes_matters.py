"""Matters, the documents in them, grounded questions about them, and what the system is."""

# No "from __future__ import annotations": see routes_auth.
import contextvars
import re
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from eli_legal import __version__
from eli_legal.application.matter_service import TeamMember
from eli_legal.application.services import Services
from eli_legal.domain.enums import AccessScope, DocumentType, Profile, VerificationType
from eli_legal.domain.models import Document
from eli_legal.domain.profiles import PROFILES
from eli_legal.persistence import codec
from eli_legal.workflows.agents import agent_for, layers

from . import schemas
from .auth import Access
from .config import ServerConfig
from .routes_oversight import _public

_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f/\\]")


def document_row(d: Document) -> dict[str, Any]:
    return {
        "document_id": d.document_id,
        "filename": d.filename,
        "title": d.title,
        "status": d.status.value,
        "doc_type": d.doc_type.value,
        "access_scope": d.access_scope.value,
        "party_id": d.party_id,
        "custodian": d.custodian,
        "sha256": d.sha256,
        "size_bytes": d.size_bytes,
        "passages": d.segment_count,
        "injection_flags": d.injection_flags,
        "error": d.error,
        "ingested_by": d.ingested_by,
        "ingested_at": d.ingested_at.isoformat(),
        "waived_by": d.waived_by,
    }


def register(app: FastAPI, sv: Services, cfg: ServerConfig, access: Access) -> None:
    Actor = Annotated[str, Depends(access.user)]
    js = codec.to_jsonable

    @app.get("/v1/system")
    def system(actor: Actor) -> dict[str, Any]:
        """What this installation is, for the screens that need to offer choices."""
        chain = sv.ctx.audit.report()
        packs = [sv.ctx.jurisdictions.get(code) for code in sv.ctx.jurisdictions.codes()]
        return {
            "version": __version__,
            "model": _public(sv.config.current()),
            "network_default": sv.ctx.settings.network_default,
            "network": sv.network.status(),
            "audit": {"ok": chain.ok, "events": chain.count, "error": chain.error},
            "second_factor_required": cfg.require_second_factor,
            "profiles": [
                {
                    "profile": p.profile.value,
                    "label": p.label,
                    "roles": sorted(p.roles),
                    "reviewer_roles": sorted(p.reviewer_roles),
                    "outcome_policy": p.outcome_policy,
                    "disclaimer": p.disclaimer,
                    "regulatory_note": p.regulatory_note,
                }
                for p in PROFILES.values()
            ],
            "jurisdictions": [
                {
                    "code": p.code,
                    "name": p.name,
                    "legal_family": p.legal_family,
                    "validated": p.validated,
                    "validated_by": p.validated_by,
                    "status_max_age_days": p.status_max_age_days,
                }
                for p in packs
            ],
            "document_types": [t.value for t in DocumentType],
            "access_scopes": [s.value for s in AccessScope],
            "checks": [t.value for t in VerificationType],
        }

    @app.get("/v1/workflow")
    def workflow(actor: Actor) -> dict[str, Any]:
        """The steps as a graph, and each step as an agent with a fixed mandate."""
        wf = sv.ctx.workflow
        return {
            "workflow_id": wf.workflow_id,
            "version": wf.version,
            "purpose": wf.purpose,
            "layers": layers(wf),
            "steps": [
                {
                    "id": s.id,
                    "depends_on": list(s.depends_on),
                    "manual": s.manual,
                    "agent": js(agent_for(s.id)),
                }
                for s in wf.steps
            ],
        }

    # ── matters ──────────────────────────────────────────────────────────────
    @app.get("/v1/matters")
    def matters(actor: Actor) -> Any:
        """The matters you have access to."""
        return [
            {
                "matter_id": m.matter_id,
                "name": m.name,
                "status": m.status.value,
                "profile": m.profile.value,
                "jurisdiction": m.jurisdiction,
            }
            for m in sv.matters.list_for(actor)
        ]

    @app.post("/v1/matters", status_code=201)
    def create_matter(body: schemas.MatterCreate, actor: Actor) -> Any:
        """Open a matter under a profile, with its legal system, parties, issues and relevant date."""
        m = sv.matters.create(
            actor_id=actor,
            name=body.name,
            purpose=body.purpose,
            jurisdiction=body.jurisdiction,
            profile=schemas.choice(Profile, body.profile, "profile"),
            governing_law=body.governing_law,
            forum=body.forum,
            procedural_rules=body.procedural_rules,
            relevant_date=body.relevant_date,
            parties=[(p.name, p.role) for p in body.parties],
            stated_issues=body.stated_issues,
            represented_party=body.represented_party,
            frameworks=body.frameworks,
            recommended_frameworks=body.recommended_frameworks,
            team=[TeamMember(t.user_id, t.matter_role, t.party) for t in body.team],
            reviewers=body.reviewers,
            sources=body.sources,
            real=body.real,
            retention_days=body.retention_days,
        )
        return js(m)

    @app.get("/v1/matters/{matter_id}")
    def matter(matter_id: str, actor: Actor) -> Any:
        """One matter: parties, issues, who has access, the named reviewers, the approved sources."""
        return js(sv.matters.get(matter_id, actor))

    @app.patch("/v1/matters/{matter_id}")
    def update_matter(matter_id: str, body: schemas.MatterUpdate, actor: Actor) -> Any:
        """Change the relevant date, issues, forum or rules, add parties, or set how long the
        matter's content is kept once it is closed."""
        return js(
            sv.matters.update(
                matter_id,
                actor_id=actor,
                relevant_date=body.relevant_date,
                stated_issues=body.stated_issues,
                forum=body.forum,
                procedural_rules=body.procedural_rules,
                add_parties=[(p.name, p.role) for p in body.add_parties],
                retention_days=body.retention_days,
                organisation_retention=body.organisation_retention,
            )
        )

    @app.get("/v1/matters/{matter_id}/members")
    def members(matter_id: str, actor: Actor) -> Any:
        """Who is on the matter: their role on it, whom they act for, what they may read."""
        return js(sv.matters.members(matter_id, actor))

    @app.post("/v1/matters/{matter_id}/members/{user_id}", status_code=204)
    def grant(
        matter_id: str, user_id: str, actor: Actor, body: schemas.MemberIn | None = None
    ) -> None:
        """Give a user access to the matter, optionally in a given role on it and acting for a
        party. Their account role must fit the matter's profile."""
        sv.matters.grant(
            matter_id,
            actor_id=actor,
            user_id=user_id,
            matter_role=body.matter_role if body else None,
            party=body.party if body else None,
        )

    @app.patch("/v1/matters/{matter_id}/members/{user_id}", status_code=204)
    def set_member(matter_id: str, user_id: str, body: schemas.MemberIn, actor: Actor) -> None:
        """Change a member's role on the matter, the party they act for, or what they read."""
        sv.matters.set_member(
            matter_id,
            actor_id=actor,
            user_id=user_id,
            matter_role=body.matter_role,
            party=body.party,
            clear_party=body.clear_party,
            reads=body.reads,
        )

    @app.delete("/v1/matters/{matter_id}/members/{user_id}", status_code=204)
    def revoke(matter_id: str, user_id: str, actor: Actor) -> None:
        """Remove a user's access to the matter."""
        sv.matters.revoke(matter_id, actor_id=actor, user_id=user_id)

    @app.put("/v1/matters/{matter_id}/reviewers", status_code=204)
    def reviewers(matter_id: str, body: schemas.IdList, actor: Actor) -> None:
        """Name the people who must approve before anything is relied on."""
        sv.matters.set_reviewers(matter_id, actor_id=actor, reviewer_ids=body.ids)

    @app.put("/v1/matters/{matter_id}/sources", status_code=204)
    def matter_sources(matter_id: str, body: schemas.IdList, actor: Actor) -> None:
        """Choose which approved legal sources this matter may use."""
        sv.matters.set_sources(matter_id, actor_id=actor, source_ids=body.ids)

    @app.post("/v1/matters/{matter_id}/close")
    def close(matter_id: str, body: schemas.CloseIn, actor: Actor) -> Any:
        """Close the matter, optionally deleting its documents and extracted text. The audit trail is kept. A decision."""
        return js(
            sv.matters.close(
                matter_id, actor_id=actor, purge_content=body.purge_content, reason=body.reason
            )
        )

    # ── documents ────────────────────────────────────────────────────────────
    @app.get("/v1/matters/{matter_id}/documents")
    def documents(matter_id: str, actor: Actor) -> Any:
        """The documents filed in the matter, with what was read, what was not, and what was flagged."""
        return [document_row(d) for d in sv.matters.documents(matter_id, actor)]

    @app.post("/v1/matters/{matter_id}/documents", status_code=201)
    async def upload(
        matter_id: str,
        filename: str,
        request: Request,
        actor: Actor,
        party_id: str | None = None,
        doc_type: str | None = None,
        scope: str = AccessScope.ALL_PARTIES.value,
        custodian: str = "",
    ) -> dict[str, Any]:
        """File a document. The body is the file itself; its name and filing details are in the
        query. It is stored once, read-only, addressed by its SHA-256, and then read."""
        name = _UNSAFE_NAME.sub("", filename).strip().lstrip(".")
        if not name or len(name) > 255:
            raise HTTPException(400, "give the file's name, without any folder")
        raw = await request.body()
        if len(raw) > cfg.max_upload_bytes:
            raise HTTPException(413, "the file is too large")
        try:
            given = DocumentType(doc_type) if doc_type else None
            access = AccessScope(scope)
        except ValueError as exc:
            raise HTTPException(422, "unknown document type or scope") from exc

        def file_it() -> Document:
            m = sv.ctx.matter_for(matter_id, actor, "document.ingest")
            document = sv.ingestion.register(
                matter=m,
                actor_id=actor,
                filename=name,
                raw=raw,
                doc_type=given,
                party_id=party_id or None,
                access_scope=access,
                custodian=custodian[:200],
            )
            if document.status.value == "registered":
                document = sv.ingestion.process(
                    document, actor_id=actor, type_given=given is not None
                )
            return document

        # Reading a long scan by OCR takes a while: it runs on a worker thread, as the person
        # who filed it, so every other session and every run's progress stays responsive.
        return document_row(await run_in_threadpool(contextvars.copy_context().run, file_it))

    @app.get("/v1/matters/{matter_id}/documents/{document_id}/passages")
    def passages(matter_id: str, document_id: str, actor: Actor) -> Any:
        """A document as the located passages every finding points back to."""
        return [
            {"ordinal": c.ordinal, "locator": c.locator, "text": c.text}
            for c in sv.matters.passages(matter_id, document_id, actor)
        ]

    # ── questions ────────────────────────────────────────────────────────────
    @app.post("/v1/matters/{matter_id}/chat")
    def chat(matter_id: str, body: schemas.ChatIn, actor: Actor) -> Any:
        """Ask about the matter. The answer is its sources; nothing can be decided here."""
        return js(
            sv.chat.ask(
                matter_id,
                actor_id=actor,
                question=body.question,
                run_id=body.run_id,
                use_model=body.use_model,
            )
        )
