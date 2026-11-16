"""Runs and everything a person does with one: findings, holds, checks, review, release."""

# No "from __future__ import annotations": see routes_auth.
import io
import zipfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Response
from fastapi.responses import PlainTextResponse

from eli_legal.application.services import Services
from eli_legal.domain.enums import IncidentSeverity, ReviewDecision, VerificationStatus
from eli_legal.domain.errors import NotFound
from eli_legal.persistence import codec

from . import schemas
from .auth import Access
from .config import ServerConfig


def register(app: FastAPI, sv: Services, cfg: ServerConfig, access: Access) -> None:
    Actor = Annotated[str, Depends(access.user)]
    js = codec.to_jsonable

    def summary(matter_id: str, run_id: str, actor: str) -> dict[str, Any]:
        out = dict(sv.runs.summary(matter_id, run_id, actor_id=actor))
        if out.get("report"):  # where the file sits on the server is nobody's business
            out["report"] = {k: v for k, v in out["report"].items() if k != "path"}
        return out

    @app.post("/v1/matters/{matter_id}/runs", status_code=202)
    def start_run(matter_id: str, actor: Actor) -> dict[str, Any]:
        """Start a run. It executes on the server; ask for the run to watch it progress."""
        run = sv.runs.create(matter_id, actor_id=actor)
        app.state.jobs.start(lambda: sv.runs.execute(matter_id, run.run_id, actor_id=actor))
        return {"run_id": run.run_id, "status": run.status.value}

    @app.get("/v1/matters/{matter_id}/runs")
    def runs(matter_id: str, actor: Actor) -> Any:
        """The runs of a matter."""
        return [
            {
                "run_id": r.run_id,
                "status": r.status.value,
                "started_by": r.initiated_by,
                "created_at": r.created_at.isoformat(),
            }
            for r in sv.runs.list(matter_id, actor_id=actor)
        ]

    @app.get("/v1/matters/{matter_id}/runs/{run_id}")
    def run(matter_id: str, run_id: str, actor: Actor) -> Any:
        """One run: every step and its outcome, findings by status, open holds, open checks, the report."""
        return summary(matter_id, run_id, actor)

    @app.post("/v1/matters/{matter_id}/runs/{run_id}/resume", status_code=202)
    def resume(matter_id: str, run_id: str, body: schemas.ResumeIn, actor: Actor) -> Any:
        # Checked now, so a refusal reaches the person; the work itself continues in the background.
        """Restart a held or stopped run, with reasons. A decision. Continues on the server."""
        sv.ctx.matter_for(matter_id, actor, "workflow.restart")
        from eli_legal.security import authn

        authn.require_step_up(actor, "restart a run")
        app.state.jobs.start(
            lambda: sv.runs.resume(
                matter_id, run_id, actor_id=actor, reason=body.reason, from_step=body.from_step
            )
        )
        return {"run_id": run_id, "status": "running"}

    @app.post("/v1/matters/{matter_id}/runs/{run_id}/stop")
    def stop(matter_id: str, run_id: str, body: schemas.Reasoned, actor: Actor) -> Any:
        """Stop a run, with reasons."""
        stopped = sv.runs.stop(matter_id, run_id, actor_id=actor, reason=body.reason)
        return {"run_id": stopped.run_id, "status": stopped.status.value}

    @app.get("/v1/matters/{matter_id}/runs/{run_id}/record")
    def record(matter_id: str, run_id: str, actor: Actor) -> Any:
        """Does the audit ledger account for everything the store says happened in this run?"""
        return js(sv.run_record(matter_id, run_id, actor_id=actor))

    # ── findings ─────────────────────────────────────────────────────────────
    @app.get("/v1/matters/{matter_id}/runs/{run_id}/claims")
    def claims(matter_id: str, run_id: str, actor: Actor) -> Any:
        """Every finding of the run, with its source passages and status."""
        return js(sv.verification.claims(matter_id, run_id, actor_id=actor))

    @app.get("/v1/matters/{matter_id}/runs/{run_id}/issues")
    def issues(matter_id: str, run_id: str, actor: Actor) -> Any:
        """The issues in the run: stated at intake, lifted from the papers, or proposed."""
        return js(sv.verification.issues(matter_id, run_id, actor_id=actor))

    @app.get("/v1/matters/{matter_id}/claims/{claim_id}/verifications")
    def verifications(matter_id: str, claim_id: str, actor: Actor) -> Any:
        """Every check made on a finding, by rule, model or person."""
        return js(sv.verification.results_for(matter_id, claim_id, actor_id=actor))

    @app.post("/v1/matters/{matter_id}/claims/{claim_id}/verifications", status_code=201)
    def verify(matter_id: str, claim_id: str, body: schemas.VerificationIn, actor: Actor) -> Any:
        """Record a check made by hand, with what it was checked against. A decision."""
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

    @app.get("/v1/matters/{matter_id}/runs/{run_id}/holds")
    def holds(matter_id: str, run_id: str, actor: Actor, open_only: bool = True) -> Any:
        """The holds on the run. Nothing reaches review while one is open."""
        return js(sv.holds.list(matter_id, run_id, actor_id=actor, open_only=open_only))

    @app.post("/v1/matters/{matter_id}/runs/{run_id}/hold", status_code=201)
    def hold_run(matter_id: str, run_id: str, body: schemas.Reasoned, actor: Actor) -> Any:
        """Put a run on hold while it waits for review or once approved (suspending reliance
        and its release), with reasons. A decision; lifting it needs someone who may resolve
        holds."""
        return js(sv.holds.place(matter_id, run_id, actor_id=actor, reason=body.reason))

    @app.post("/v1/matters/{matter_id}/holds/{hold_id}/resolve")
    def resolve_hold(
        matter_id: str, hold_id: str, body: schemas.HoldResolveIn, actor: Actor
    ) -> Any:
        """Close a hold by a named decision, `exclude` or `waive` (or `lift`, for a run a person
        put on hold), with reasons. A decision."""
        return js(
            sv.holds.resolve(
                matter_id, hold_id, actor_id=actor, action=body.action, reason=body.reason
            )
        )

    @app.get("/v1/matters/{matter_id}/runs/{run_id}/tasks")
    def tasks(matter_id: str, run_id: str, actor: Actor) -> Any:
        """Checks waiting for a person."""
        return js(sv.verification.tasks(matter_id, run_id, actor_id=actor))

    # ── report, review, release ──────────────────────────────────────────────
    def report_of(matter_id: str, run_id: str, actor: str) -> tuple[str, dict[str, Any]]:
        sv.ctx.matter_for(matter_id, actor, "report.review")
        current = sv.runs.summary(matter_id, run_id, actor_id=actor)["report"]
        if not current:
            raise NotFound("no report has been drafted for this run")
        text, withheld = sv.reviews.report_text(matter_id, run_id, actor_id=actor)
        return text, current | {"withheld": withheld}

    @app.get("/v1/matters/{matter_id}/runs/{run_id}/report")
    def report(matter_id: str, run_id: str, actor: Actor) -> dict[str, Any]:
        """The report text, its SHA-256, its release state and the limits a reviewer must acknowledge."""
        text, current = report_of(matter_id, run_id, actor)
        return {
            "text": text,
            "sha256": current["sha256"],
            "version": current["version"],
            "release_status": current["release_status"],
            "warnings": sv.reviews.pending_warnings(matter_id, run_id, actor_id=actor),
            "withheld": current["withheld"],
        }

    @app.get("/v1/matters/{matter_id}/runs/{run_id}/report.md", response_class=PlainTextResponse)
    def report_file(matter_id: str, run_id: str, actor: Actor) -> PlainTextResponse:
        """The report as a Markdown file."""
        text, current = report_of(matter_id, run_id, actor)
        return PlainTextResponse(
            text,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="report_{run_id}.md"',
                "X-Report-SHA256": current["sha256"],
                "X-Release-Status": current["release_status"],
            },
        )

    @app.post("/v1/matters/{matter_id}/runs/{run_id}/review", status_code=201)
    def review(matter_id: str, run_id: str, body: schemas.ReviewIn, actor: Actor) -> Any:
        """The named reviewer's decision on this exact version of the report."""
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

    @app.post("/v1/matters/{matter_id}/runs/{run_id}/releases", status_code=201)
    def prepare_release(matter_id: str, run_id: str, body: schemas.ReleaseIn, actor: Actor) -> Any:
        """Stage an approved report for named recipients; says which are entitled to this matter."""
        package = sv.releases.prepare(
            matter_id,
            run_id,
            actor_id=actor,
            recipients=[(r.recipient_id, r.display_name, r.address) for r in body.recipients],
        )
        return {
            "release_id": package.release_id,
            "recipients": [
                {
                    "recipient_id": r.recipient_id,
                    "display_name": r.display_name,
                    "entitled": r.authorised_for_matter,
                }
                for r in package.recipients
            ],
        }

    @app.post("/v1/matters/{matter_id}/releases/{release_id}/send")
    def send(matter_id: str, release_id: str, body: schemas.SendIn, actor: Actor) -> Any:
        """Stage the approved report for the confirmed recipients. Nothing leaves this system."""
        receipts = sv.delivery.distribute(
            matter_id,
            release_id,
            actor_id=actor,
            confirmed_recipient_ids=body.confirmed_recipient_ids,
        )
        return [
            {"recipient_id": r.recipient_id, "status": r.status, "detail": r.detail}
            for r in receipts
        ]

    @app.post("/v1/matters/{matter_id}/runs/{run_id}/evidence-pack")
    def evidence(matter_id: str, run_id: str, actor: Actor) -> Response:
        """The run's evidence pack as one archive: identifiers, hashes, versions, decisions."""
        folder = Path(sv.evidence_pack(matter_id, run_id, actor_id=actor))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(p for p in folder.rglob("*") if p.is_file()):
                archive.write(path, path.relative_to(folder.parent).as_posix())
        return Response(
            buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{folder.name}.zip"'},
        )

    # ── preservation holds ───────────────────────────────────────────────────
    @app.get("/v1/matters/{matter_id}/preservation-holds")
    def preservation_holds(matter_id: str, actor: Actor) -> Any:
        """Preservation holds on the matter: what they keep from deletion, and why."""
        return js(sv.preservation.list(matter_id, actor_id=actor))

    @app.post("/v1/matters/{matter_id}/preservation-holds", status_code=201)
    def place_preservation_hold(matter_id: str, body: schemas.PreservationIn, actor: Actor) -> Any:
        """Keep the matter, or named documents, from deletion. A decision: send your
        passphrase."""
        return js(
            sv.preservation.place(
                matter_id,
                actor_id=actor,
                legal_basis=body.legal_basis,
                authority=body.authority,
                document_ids=list(body.document_ids),
                review_by=body.review_by,
            )
        )

    @app.post("/v1/matters/{matter_id}/preservation-holds/{hold_id}/release")
    def release_preservation_hold(
        matter_id: str, hold_id: str, body: schemas.PreservationRelease, actor: Actor
    ) -> Any:
        """End a preservation hold: the legal or data-protection owner, with the reason. A
        decision: send your passphrase."""
        return js(sv.preservation.release(matter_id, hold_id, actor_id=actor, reason=body.reason))

    # ── reliance on approved reports ─────────────────────────────────────────
    @app.get("/v1/matters/{matter_id}/reliance-blocks")
    def reliance_blocks(matter_id: str, actor: Actor) -> Any:
        """Approved reports of the matter suspended from reliance, and how each ended."""
        return js(sv.reliance.list(matter_id, actor_id=actor))

    @app.post("/v1/matters/{matter_id}/reliance-blocks/{block_id}/resolve")
    def resolve_reliance_block(
        matter_id: str, block_id: str, body: schemas.RelianceResolveIn, actor: Actor
    ) -> Any:
        """End a suspension: the law confirmed again for the report, or a later run, re-checked
        and approved, that replaces it. A decision: send your passphrase."""
        return js(
            sv.reliance.resolve(
                matter_id,
                block_id,
                actor_id=actor,
                basis=body.basis,
                superseded_by_run_id=body.superseded_by_run_id,
            )
        )

    # ── incidents ────────────────────────────────────────────────────────────
    @app.get("/v1/matters/{matter_id}/incidents")
    def incidents(matter_id: str, actor: Actor, open_only: bool = False) -> Any:
        """Incidents recorded for the matter."""
        return js(sv.incidents.list(matter_id, actor_id=actor, open_only=open_only))

    @app.post("/v1/matters/{matter_id}/incidents", status_code=201)
    def open_incident(matter_id: str, body: schemas.IncidentIn, actor: Actor) -> Any:
        """Open an incident."""
        return js(
            sv.incidents.create(
                matter_id,
                actor_id=actor,
                category=body.category,
                detail=body.detail,
                severity=IncidentSeverity(body.severity),
                run_id=body.run_id,
            )
        )

    @app.post("/v1/matters/{matter_id}/incidents/{incident_id}/close")
    def close_incident(
        matter_id: str, incident_id: str, body: schemas.IncidentClose, actor: Actor
    ) -> Any:
        """Close an incident, recording what contained it and why it can be closed."""
        return js(
            sv.incidents.close(
                matter_id,
                incident_id,
                actor_id=actor,
                containment=body.containment,
                reason=body.reason,
            )
        )
