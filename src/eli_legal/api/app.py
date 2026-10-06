"""HTTP API. A thin shell over the application services.

Every route except ``/health`` and ``/boundaries`` requires a bearer token that maps to a named
user; what that user may do is decided by the same services the CLI uses. Start it with::

    uvicorn --factory eli_legal.api.app:create_app
"""

# No "from __future__ import annotations" here: FastAPI resolves the route annotations at
# definition time, and they refer to names local to create_app().
from pathlib import Path
from typing import Annotated, Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from eli_legal import __version__
from eli_legal.application.services import Services, build_services
from eli_legal.domain.enums import (
    AccessScope,
    DocumentType,
    Profile,
    ReviewDecision,
    VerificationStatus,
)
from eli_legal.domain.errors import (
    AuditIntegrityError,
    AuthenticationFailed,
    EliLegalError,
    InvalidInput,
    InvalidState,
    MatterAccessDenied,
    NotFound,
    PolicyDenied,
    VerificationGateFailed,
)
from eli_legal.persistence import codec

from . import schemas

_STATUS: tuple[tuple[type[EliLegalError], int], ...] = (
    (AuthenticationFailed, 401),
    (PolicyDenied, 403),
    (MatterAccessDenied, 403),
    (NotFound, 404),
    (InvalidInput, 422),
    (VerificationGateFailed, 409),
    (InvalidState, 409),
    (AuditIntegrityError, 500),
)
MAX_UPLOAD_BYTES = 250 * 1024 * 1024


def create_app(services: Services | None = None) -> FastAPI:
    sv = services or build_services()
    app = FastAPI(title="ELI Legal", version=__version__)

    @app.exception_handler(EliLegalError)
    async def _refused(request: Request, exc: EliLegalError) -> JSONResponse:
        code = next((status for kind, status in _STATUS if isinstance(exc, kind)), 400)
        return JSONResponse({"error": type(exc).__name__, "detail": str(exc)}, status_code=code)

    def user(authorization: Annotated[str | None, Header()] = None) -> str:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "a bearer token is required", {"WWW-Authenticate": "Bearer"})
        user_id = sv.ctx.store.user_for_token(authorization[7:].strip())
        if user_id is None:
            raise HTTPException(401, "unknown or revoked token", {"WWW-Authenticate": "Bearer"})
        sv.ctx.user(user_id)  # refuses a deactivated user
        return user_id

    Actor = Annotated[str, Depends(user)]

    def js(value: Any) -> Any:
        return codec.to_jsonable(value)

    @app.get("/health", response_model=schemas.HealthResponse)
    def health() -> schemas.HealthResponse:
        s = sv.ctx.settings
        return schemas.HealthResponse(
            status="ok", mode=s.mode, network_default=s.network_default, version=__version__
        )

    @app.get("/boundaries")
    def boundaries() -> dict[str, Any]:
        return {
            "decision_support_only": True,
            "renders_verdict_or_award": False,
            "human_release_required": True,
            "contacts_parties": False,
            "personal_assistant_capabilities": False,
            "general_shell": False,
            "network_default": "deny",
            "prohibited_actions": sorted(sv.ctx.policy.prohibited_actions),
        }

    @app.get("/me")
    def me(actor: Actor) -> dict[str, Any]:
        u = sv.ctx.user(actor)
        return {"user_id": u.user_id, "display_name": u.display_name, "roles": sorted(u.roles)}

    # ── matters ──────────────────────────────────────────────────────────────
    @app.get("/matters")
    def matters(actor: Actor) -> list[dict[str, Any]]:
        return [
            {
                "matter_id": m.matter_id,
                "name": m.name,
                "status": m.status.value,
                "profile": m.profile.value,
            }
            for m in sv.matters.list_for(actor)
        ]

    @app.post("/matters", status_code=201)
    def create_matter(body: schemas.MatterCreate, actor: Actor) -> dict[str, Any]:
        matter = sv.matters.create(
            actor_id=actor,
            name=body.name,
            purpose=body.purpose,
            jurisdiction=body.jurisdiction,
            profile=Profile(body.profile),
            governing_law=body.governing_law,
            forum=body.forum,
            procedural_rules=body.procedural_rules,
            relevant_date=body.relevant_date,
            parties=[(p.name, p.role) for p in body.parties],
            stated_issues=body.stated_issues,
            represented_party=body.represented_party,
        )
        return {"matter_id": matter.matter_id}

    @app.get("/matters/{matter_id}")
    def matter(matter_id: str, actor: Actor) -> Any:
        return js(sv.matters.get(matter_id, actor))

    @app.post("/matters/{matter_id}/members/{user_id}", status_code=204)
    def grant(matter_id: str, user_id: str, actor: Actor) -> None:
        sv.matters.grant(matter_id, actor_id=actor, user_id=user_id)

    @app.delete("/matters/{matter_id}/members/{user_id}", status_code=204)
    def revoke(matter_id: str, user_id: str, actor: Actor) -> None:
        sv.matters.revoke(matter_id, actor_id=actor, user_id=user_id)

    @app.put("/matters/{matter_id}/reviewers", status_code=204)
    def reviewers(matter_id: str, body: schemas.IdList, actor: Actor) -> None:
        sv.matters.set_reviewers(matter_id, actor_id=actor, reviewer_ids=body.ids)

    @app.put("/matters/{matter_id}/sources", status_code=204)
    def matter_sources(matter_id: str, body: schemas.IdList, actor: Actor) -> None:
        sv.matters.set_sources(matter_id, actor_id=actor, source_ids=body.ids)

    # ── documents ────────────────────────────────────────────────────────────
    @app.get("/matters/{matter_id}/documents")
    def documents(matter_id: str, actor: Actor) -> Any:
        return [
            {
                "document_id": d.document_id,
                "filename": d.filename,
                "status": d.status.value,
                "doc_type": d.doc_type.value,
                "sha256": d.sha256,
                "injection_flags": d.injection_flags,
                "error": d.error,
            }
            for d in sv.matters.documents(matter_id, actor)
        ]

    @app.put("/matters/{matter_id}/documents/{filename}", status_code=201)
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
        raw = await request.body()
        if len(raw) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "file is too large")
        m = sv.ctx.matter_for(matter_id, actor, "document.ingest")
        given = DocumentType(doc_type) if doc_type else None
        document = sv.ingestion.register(
            matter=m,
            actor_id=actor,
            filename=Path(filename).name,
            raw=raw,
            doc_type=given,
            party_id=party_id,
            access_scope=AccessScope(scope),
            custodian=custodian,
        )
        if document.status.value == "registered":
            document = sv.ingestion.process(document, actor_id=actor, type_given=given is not None)
        return {
            "document_id": document.document_id,
            "status": document.status.value,
            "sha256": document.sha256,
        }

    # ── runs ─────────────────────────────────────────────────────────────────
    @app.post("/matters/{matter_id}/runs", status_code=202)
    def start_run(matter_id: str, actor: Actor, background: BackgroundTasks) -> dict[str, Any]:
        run = sv.runs.create(matter_id, actor_id=actor)
        background.add_task(sv.runs.execute, matter_id, run.run_id, actor_id=actor)
        return {"run_id": run.run_id, "status": run.status.value}

    @app.get("/matters/{matter_id}/runs")
    def runs(matter_id: str, actor: Actor) -> Any:
        return [
            {"run_id": r.run_id, "status": r.status.value, "initiated_by": r.initiated_by}
            for r in sv.runs.list(matter_id, actor_id=actor)
        ]

    @app.get("/matters/{matter_id}/runs/{run_id}")
    def run_status(matter_id: str, run_id: str, actor: Actor) -> Any:
        return sv.runs.summary(matter_id, run_id, actor_id=actor)

    @app.post("/matters/{matter_id}/runs/{run_id}/resume")
    def resume(matter_id: str, run_id: str, body: schemas.ResumeIn, actor: Actor) -> Any:
        sv.runs.resume(
            matter_id, run_id, actor_id=actor, reason=body.reason, from_step=body.from_step
        )
        return sv.runs.summary(matter_id, run_id, actor_id=actor)

    @app.post("/matters/{matter_id}/runs/{run_id}/stop")
    def stop(matter_id: str, run_id: str, body: schemas.Reasoned, actor: Actor) -> Any:
        return {
            "status": sv.runs.stop(
                matter_id, run_id, actor_id=actor, reason=body.reason
            ).status.value
        }

    # ── findings, holds, verification ────────────────────────────────────────
    @app.get("/matters/{matter_id}/runs/{run_id}/claims")
    def claims(matter_id: str, run_id: str, actor: Actor) -> Any:
        return js(sv.verification.claims(matter_id, run_id, actor_id=actor))

    @app.get("/matters/{matter_id}/runs/{run_id}/holds")
    def holds(matter_id: str, run_id: str, actor: Actor, all: bool = False) -> Any:
        return js(sv.holds.list(matter_id, run_id, actor_id=actor, open_only=not all))

    @app.post("/matters/{matter_id}/holds/{hold_id}/resolve")
    def resolve_hold(
        matter_id: str, hold_id: str, body: schemas.HoldResolveIn, actor: Actor
    ) -> Any:
        return js(
            sv.holds.resolve(
                matter_id, hold_id, actor_id=actor, action=body.action, reason=body.reason
            )
        )

    @app.get("/matters/{matter_id}/runs/{run_id}/tasks")
    def tasks(matter_id: str, run_id: str, actor: Actor) -> Any:
        return js(sv.verification.tasks(matter_id, run_id, actor_id=actor))

    @app.post("/matters/{matter_id}/claims/{claim_id}/verifications", status_code=201)
    def verify(matter_id: str, claim_id: str, body: schemas.VerificationIn, actor: Actor) -> Any:
        return js(
            sv.verification.record_human_result(
                matter_id,
                claim_id,
                actor_id=actor,
                verification_type=body.check,
                status=VerificationStatus(body.result),
                reason=body.reason,
            )
        )

    # ── report, review, release ──────────────────────────────────────────────
    @app.get("/matters/{matter_id}/runs/{run_id}/report", response_class=PlainTextResponse)
    def report(matter_id: str, run_id: str, actor: Actor) -> PlainTextResponse:
        sv.ctx.matter_for(matter_id, actor, "report.review")
        current = sv.runs.summary(matter_id, run_id, actor_id=actor)["report"]
        if not current:
            raise NotFound("no report has been drafted for this run")
        return PlainTextResponse(
            Path(current["path"]).read_text(encoding="utf-8"),
            media_type="text/markdown",
            headers={
                "X-Report-SHA256": current["sha256"],
                "X-Release-Status": current["release_status"],
            },
        )

    @app.post("/matters/{matter_id}/runs/{run_id}/review", status_code=201)
    def review(matter_id: str, run_id: str, body: schemas.ReviewIn, actor: Actor) -> Any:
        decided = sv.reviews.decide(
            matter_id,
            run_id,
            actor_id=actor,
            decision=ReviewDecision(body.decision),
            reasons=body.reasons,
            report_hash=body.report_hash,
            acknowledged=body.acknowledged,
        )
        return {"review_id": decided.review_id, "decision": decided.decision.value}

    @app.post("/matters/{matter_id}/runs/{run_id}/releases", status_code=201)
    def prepare_release(matter_id: str, run_id: str, body: schemas.ReleaseIn, actor: Actor) -> Any:
        package = sv.releases.prepare(
            matter_id,
            run_id,
            actor_id=actor,
            recipients=[(r.recipient_id, r.display_name, r.address) for r in body.recipients],
        )
        return {
            "release_id": package.release_id,
            "recipients": [
                {"recipient_id": r.recipient_id, "entitled": r.authorised_for_matter}
                for r in package.recipients
            ],
        }

    @app.post("/matters/{matter_id}/releases/{release_id}/send")
    def send(matter_id: str, release_id: str, body: schemas.SendIn, actor: Actor) -> Any:
        receipts = sv.delivery.distribute(
            matter_id,
            release_id,
            actor_id=actor,
            confirmed_recipient_ids=body.confirmed_recipient_ids,
        )
        return [{"recipient_id": r.recipient_id, "status": r.status} for r in receipts]

    # ── oversight ────────────────────────────────────────────────────────────
    @app.get("/sources")
    def sources(actor: Actor) -> Any:
        return [
            {
                "source_id": s.source_id,
                "name": s.name,
                "approved": s.approved,
                "jurisdictions": sorted(s.jurisdictions),
            }
            for s in sv.sources.list()
        ]

    @app.get("/audit/verify")
    def audit_verify(actor: Actor) -> Any:
        sv.ctx.authorizer().require_global(actor, "audit.verify")
        chain = sv.ctx.audit.report()
        return {"ok": chain.ok, "events": chain.count, "error": chain.error}

    @app.get("/monitoring")
    def monitoring(actor: Actor) -> Any:
        return sv.monitoring.snapshot(actor_id=actor).to_dict()

    @app.post("/matters/{matter_id}/runs/{run_id}/evidence-pack", status_code=201)
    def evidence(matter_id: str, run_id: str, actor: Actor) -> Any:
        return {"path": str(sv.evidence_pack(matter_id, run_id, actor_id=actor))}

    return app
