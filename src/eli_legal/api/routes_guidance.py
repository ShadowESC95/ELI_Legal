"""What to do next, the organisation's compliance work, the routine checks and oversight.

The same services as the desktop application: guidance reads only; recording compliance work,
confirming a law package is current and deciding on an incident's reporting are decisions in a
named person's name and need their passphrase with the request.
"""

# No "from __future__ import annotations": see routes_auth.
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import Depends, FastAPI

from eli_legal.application.services import Services
from eli_legal.domain import glossary, how_to, plain
from eli_legal.persistence import codec
from eli_legal.security import access as matter_access

from . import schemas
from .auth import Access
from .config import ServerConfig


def register(app: FastAPI, sv: Services, cfg: ServerConfig, access: Access) -> None:
    Actor = Annotated[str, Depends(access.user)]
    js = codec.to_jsonable

    @app.get("/v1/words")
    def words(actor: Actor) -> Any:
        """The words the system uses for its states, checks, holds, roles and scopes, so every
        screen says the same thing the same way."""
        out = plain.vocabulary()
        out["matter_roles"] = {
            code: {
                "label": r.label,
                "summary": r.summary,
                "reads": sorted(s.value for s in r.clearance),
            }
            for code, r in matter_access.MATTER_ROLES.items()
        }
        # What each word means and how to use the system, as the desktop application says it.
        out["glossary"] = dict(glossary.TERMS)
        out["how_to"] = how_to.as_dict()
        return out

    # ── guidance ─────────────────────────────────────────────────────────────
    @app.get("/v1/home")
    def home(actor: Actor) -> Any:
        """What is waiting for you on every matter you are on, the latest routine checks as you
        may see them, and where compliance stands."""
        latest = sv.checks.latest()
        return {
            "work": js(sv.guidance.my_work(actor_id=actor)),
            "checks": None
            if latest is None
            else {
                "state": latest.state,
                "headline": latest.headline,
                "finished_at": (latest.finished_at or latest.started_at).isoformat(),
                "by": latest.actor_id,
                "results": js(sv.checks.for_viewer(latest, actor_id=actor)),
            },
            "compliance": sv.compliance.overview(actor_id=actor).headline,
        }

    @app.get("/v1/matters/{matter_id}/guide")
    def guide(matter_id: str, actor: Actor) -> Any:
        """Where the matter stands, your role on it, what you read, and what to do next."""
        return js(sv.guidance.for_matter(matter_id, actor_id=actor))

    # ── compliance ───────────────────────────────────────────────────────────
    @app.get("/v1/compliance")
    def compliance(actor: Actor) -> Any:
        """Every requirement and where it stands; every organisation action, its form and its
        latest record."""
        overview = sv.compliance.overview(actor_id=actor)
        return {
            "headline": overview.headline,
            "requirements": [
                {
                    "id": r.requirement_id,
                    "instrument": r.instrument,
                    "reference": r.reference,
                    "requirement": r.requirement,
                    "who": r.who,
                    "state": r.state,
                    "how_met": r.how_met,
                    "controls": list(r.controls),
                    "actions": [a.action.action_id for a in r.actions],
                }
                for r in overview.requirements
            ],
            "actions": [
                {
                    "id": a.action.action_id,
                    "title": a.action.title,
                    "what_to_do": a.action.what_to_do,
                    "requirements": list(a.action.requirement_ids),
                    "owner": a.action.owner,
                    "evidence": a.action.evidence,
                    "statement": a.action.statement,
                    "form": [{"key": f.key, "label": f.label} for f in a.action.form],
                    "state": a.state,
                    "detail": a.detail,
                    "review_by": a.record.review_by.isoformat()
                    if a.record and a.record.review_by
                    else None,
                }
                for a in overview.actions
            ],
            "retention": js(sv.compliance.retention()),
        }

    @app.post("/v1/compliance/actions/{action_id}")
    def record(action_id: str, body: schemas.ComplianceIn, actor: Actor) -> Any:
        """Record an organisation action as done (a form, a statement, a registration number),
        or as not applying, with reasons. A decision: send your passphrase."""
        return js(
            sv.compliance.record(
                action_id,
                actor_id=actor,
                answers=body.answers,
                confirmed=body.confirmed,
                notes=body.notes,
                reference=body.reference,
                not_applicable=body.not_applicable,
            )
        )

    @app.post("/v1/compliance/retention")
    def retention(body: schemas.RetentionIn, actor: Actor) -> Any:
        """Set how long each kind of information is kept: the audit trail, and a closed case's papers, analysis, reports, evidence packs and decision record."""
        return js(
            sv.compliance.set_retention(
                actor_id=actor,
                audit_days=body.audit_days,
                closed_matter_days=body.closed_matter_days,
                notes=body.notes,
                inactive_matter_days=body.inactive_matter_days,
                analysis_days=body.analysis_days,
                reports_days=body.reports_days,
                evidence_days=body.evidence_days,
                record_days=body.record_days,
            )
        )

    @app.get("/v1/compliance/training")
    def training(actor: Actor) -> Any:
        """Training records, and who works on matters without a current one."""
        sv.ctx.authorizer().require_global(actor, "compliance.manage")
        return {
            "records": js(sv.compliance.training()),
            "untrained": sv.compliance.untrained(),
        }

    @app.post("/v1/compliance/training")
    def record_training(body: schemas.TrainingIn, actor: Actor) -> Any:
        """Record training a person has completed."""
        return js(
            sv.compliance.record_training(
                actor_id=actor,
                user_id=body.user_id,
                course=body.course,
                completed_on=body.completed_on,
                expires_on=body.expires_on,
            )
        )

    @app.post("/v1/compliance/evaluation")
    def evaluation(body: schemas.EvaluationIn, actor: Actor) -> Any:
        """Run the accuracy evaluation on the planted-defect matter, against the thresholds."""
        return js(sv.compliance.run_evaluation(actor_id=actor, thresholds=body.thresholds))

    @app.post("/v1/compliance/documents/{kind}")
    def document(kind: str, actor: Actor) -> Any:
        """Draft the Annex IV documentation (annex_iv) or the declaration (declaration)."""
        path, digest = sv.compliance.generate(kind, actor_id=actor)
        return {"kind": kind, "sha256": digest, "text": path.read_text(encoding="utf-8")}

    @app.post("/v1/compliance/actions/{action_id}/sign-off")
    def sign_off(action_id: str, body: schemas.SignOffIn, actor: Actor) -> Any:
        """Sign off a drafted document by its SHA-256, once completed and reviewed."""
        return js(
            sv.compliance.sign_off(action_id, actor_id=actor, sha256=body.sha256, notes=body.notes)
        )

    # ── routine checks ───────────────────────────────────────────────────────
    @app.get("/v1/checks")
    def checks(actor: Actor) -> Any:
        """The latest routine checks as you may see them, and when the earlier ones ran."""
        latest = sv.checks.latest()
        return {
            "latest": None
            if latest is None
            else {
                "run_id": latest.run_id,
                "state": latest.state,
                "headline": latest.headline,
                "by": latest.actor_id,
                "finished_at": (latest.finished_at or latest.started_at).isoformat(),
                "results": js(sv.checks.for_viewer(latest, actor_id=actor)),
            },
            "history": [
                {"run_id": r.run_id, "state": r.state, "at": r.started_at.isoformat()}
                for r in sv.checks.history()[:30]
            ],
            "every_hours": sv.ctx.settings.checks_every_hours,
        }

    @app.post("/v1/checks/run")
    def run_checks(actor: Actor) -> Any:
        """Run the routine checks now."""
        run = sv.checks.run(actor_id=actor)
        return {
            "state": run.state,
            "headline": run.headline,
            "results": js(sv.checks.for_viewer(run, actor_id=actor)),
        }

    @app.post("/v1/frameworks/{pack_id}/current", status_code=204)
    def law_current(pack_id: str, body: schemas.LawCurrentIn, actor: Actor) -> None:
        """Record that you checked a law package against its official text. A decision."""
        sv.checks.confirm_law_current(
            pack_id, actor_id=actor, checked_on=body.checked_on, note=body.note
        )

    # ── hard offline ─────────────────────────────────────────────────────────
    @app.get("/v1/network")
    def network(actor: Actor) -> Any:
        """Whether hard offline is on, what enforces it, and whether it is set for every start."""
        return sv.network.status()

    @app.post("/v1/network/offline")
    def network_offline(actor: Actor) -> Any:
        """Switch hard offline on now: from here until the server stops, the kernel refuses
        every connection it would open. It keeps answering on its own port."""
        return sv.network.go_offline(actor_id=actor)

    @app.put("/v1/network/at-start")
    def network_at_start(body: schemas.OnOff, actor: Actor) -> Any:
        """Start hard offline every time, or not. Needs the right to manage the configuration
        and the passphrase. Switching it off takes effect at the next start."""
        from eli_legal.settings import ENV_FILE

        return sv.network.set_at_every_start(actor_id=actor, on=body.on, persist_to=ENV_FILE)

    # ── oversight and incidents ──────────────────────────────────────────────
    @app.get("/v1/oversight/matters")
    def oversight(actor: Actor) -> Any:
        """Every matter, for those who oversee the system; content withheld where you are not
        on the matter."""
        return js(sv.matters.register(actor))

    @app.post("/v1/matters/{matter_id}/incidents/{incident_id}/reporting")
    def reporting(matter_id: str, incident_id: str, body: schemas.ReportingIn, actor: Actor) -> Any:
        """Decide whether a serious incident must be reported (EU AI Act Art. 73), and record
        the report. A decision: send your passphrase."""
        on = body.reported_on
        return js(
            sv.incidents.decide_reporting(
                matter_id,
                incident_id,
                actor_id=actor,
                reportable=body.reportable,
                reason=body.reason,
                serious_kind=body.serious_kind,
                reported_on=datetime(on.year, on.month, on.day, tzinfo=timezone.utc)
                if on
                else None,
                reference=body.reference,
            )
        )
