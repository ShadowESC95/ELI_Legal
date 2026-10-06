from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eli_legal.application.container import AppContext
from eli_legal.application.incident_service import IncidentService
from eli_legal.domain.enums import HoldResolution, HoldScope, MatterStatus, RunStatus, StepStatus
from eli_legal.domain.errors import InvalidInput, InvalidState, NotFound
from eli_legal.domain.models import (
    Claim,
    Hold,
    Matter,
    Report,
    Run,
    RunStep,
    VerificationTask,
    utcnow,
)
from eli_legal.security import authn
from eli_legal.security.redaction import content_hash
from eli_legal.workflows.case_preparation import CasePreparation
from eli_legal.workflows.runner import WorkflowRunner

_RESUMABLE = {
    RunStatus.HELD,
    RunStatus.BLOCKED,
    RunStatus.STOPPED,
    RunStatus.RETURNED_FOR_CORRECTION,
}


@dataclass(slots=True)
class RunService:
    ctx: AppContext

    def _runner(self) -> WorkflowRunner:
        return WorkflowRunner(store=self.ctx.store, audit=self.ctx.audit, holds=self.ctx.holds)

    def _load(self, matter: Matter, run_id: str, actor_id: str, action: str) -> Run:
        run = self.ctx.store.get(Run, matter.matter_id, run_id)
        if run is None:
            if self.ctx.store.owner_matter(Run, run_id) is not None:
                self.ctx.authorizer().record_cross_matter_attempt(
                    user_id=actor_id,
                    matter_id=matter.matter_id,
                    action=action,
                    object_type="run",
                    object_id=run_id,
                )
            raise NotFound(f"run not found in this matter: {run_id}")
        return run

    def create(self, matter_id: str, *, actor_id: str) -> Run:
        """Open a run and record that it started. ``execute`` does the work."""
        ctx = self.ctx
        matter = ctx.matter_for(matter_id, actor_id, "workflow.run")
        if matter.status is not MatterStatus.ACTIVE:
            raise InvalidState(f"matter is {matter.status.value}; a run needs an active matter")
        ctx.audit.verify_chain()  # never start governed work on a ledger that does not verify
        run = Run(matter_id=matter.matter_id, initiated_by=actor_id, status=RunStatus.RUNNING)
        ctx.store.put(run)
        ctx.log(
            "run_started",
            actor_id=actor_id,
            matter_id=matter.matter_id,
            run_id=run.run_id,
            action="workflow.run",
            subject_id=run.run_id,
            outcome="started",
            object_type="run",
            payload={"workflow": ctx.workflow.workflow_id, "version": ctx.workflow.version},
        )
        return run

    def execute(self, matter_id: str, run_id: str, *, actor_id: str) -> Run:
        ctx = self.ctx
        matter = ctx.matter_for(matter_id, actor_id, "workflow.run")
        run = ctx.store.require(Run, matter.matter_id, run_id)
        if run.status is not RunStatus.RUNNING:
            raise InvalidState(f"run is {run.status.value}; it is not waiting to execute")
        self._runner().execute(
            workflow=ctx.workflow,
            run=run,
            matter=matter,
            handlers=CasePreparation.for_run(ctx).handlers(),
            actor_id=actor_id,
        )
        return self._settle(matter, run.run_id, actor_id)

    def start(self, matter_id: str, *, actor_id: str) -> Run:
        run = self.create(matter_id, actor_id=actor_id)
        return self.execute(matter_id, run.run_id, actor_id=actor_id)

    def resume(
        self,
        matter_id: str,
        run_id: str,
        *,
        actor_id: str,
        reason: str,
        from_step: str | None = None,
    ) -> Run:
        """Controlled restart: a named, authorised person, with a recorded reason."""
        ctx = self.ctx
        authn.require_step_up(actor_id, "restart a run")
        matter = ctx.matter_for(matter_id, actor_id, "workflow.restart")
        run = self._load(matter, run_id, actor_id, "workflow.restart")
        if run.status not in _RESUMABLE:
            raise InvalidState(f"run is {run.status.value}; only a held or stopped run can restart")
        if not reason.strip():
            raise InvalidInput("a reason is required to restart a run")
        ctx.audit.verify_chain()
        steps = {s.step_id: s for s in ctx.store.list(RunStep, matter.matter_id, run_id=run_id)}
        if from_step is None:
            from_step = next(
                (
                    s.id
                    for s in ctx.workflow.automated
                    if s.id not in steps or steps[s.id].status is not StepStatus.OK
                ),
                "verification_gate",
            )
        ctx.workflow.step(from_step)  # raises KeyError for an unknown step
        rerun = {from_step} | ctx.workflow.descendants(from_step)
        for hold in ctx.holds.open_holds(matter.matter_id, run_id):
            if hold.scope is HoldScope.STEP and hold.subject_id in rerun:
                ctx.holds.resolve(
                    hold,
                    resolved_by=actor_id,
                    resolution=HoldResolution.CORRECTED,
                    reason=f"step re-run on authorised restart: {reason}",
                )
        run.status = RunStatus.RUNNING
        run.finished_at = None
        ctx.store.put(run)
        ctx.log(
            "run_restarted",
            actor_id=actor_id,
            matter_id=matter.matter_id,
            run_id=run_id,
            action="workflow.restart",
            subject_id=run_id,
            outcome="restarted",
            object_type="run",
            reviewer_id=actor_id,
            input_hash=content_hash(reason),
            payload={"from_step": from_step},
        )
        self._runner().execute(
            workflow=ctx.workflow,
            run=run,
            matter=matter,
            handlers=CasePreparation.for_run(ctx).handlers(),
            actor_id=actor_id,
            from_step=from_step,
        )
        return self._settle(matter, run_id, actor_id)

    def stop(self, matter_id: str, run_id: str, *, actor_id: str, reason: str) -> Run:
        matter = self.ctx.matter_for(matter_id, actor_id, "workflow.stop")
        run = self._load(matter, run_id, actor_id, "workflow.stop")
        if run.status in (RunStatus.APPROVED_FOR_RELIANCE, RunStatus.REJECTED):
            raise InvalidState(f"run is already {run.status.value}")
        run.status = RunStatus.STOPPED
        run.finished_at = utcnow()
        self.ctx.store.put(run)
        self.ctx.log(
            "run_stopped",
            actor_id=actor_id,
            matter_id=matter.matter_id,
            run_id=run_id,
            action="workflow.stop",
            subject_id=run_id,
            outcome="stopped",
            object_type="run",
            reviewer_id=actor_id,
            input_hash=content_hash(reason),
        )
        return run

    def _settle(self, matter: Matter, run_id: str, actor_id: str) -> Run:
        """Decide the run's state from what actually happened, then record it."""
        ctx = self.ctx
        run = ctx.store.require(Run, matter.matter_id, run_id)
        if run.status is not RunStatus.STOPPED:
            steps = ctx.store.list(RunStep, matter.matter_id, run_id=run_id)
            done = {s.step_id: s.status for s in steps}
            clean = all(done.get(s.id) is StepStatus.OK for s in ctx.workflow.automated)
            ctx.holds.sync_run(run)
            run.status = (
                RunStatus.AWAITING_HUMAN_REVIEW
                if clean and not run.hard_gate_reasons
                else RunStatus.HELD
            )
        run.finished_at = utcnow()
        ctx.store.put(run)
        IncidentService(ctx).open_for_run(run)
        ctx.log(
            "run_settled",
            actor_id=actor_id,
            matter_id=matter.matter_id,
            run_id=run_id,
            action="workflow.run",
            subject_id=run_id,
            outcome=run.status.value,
            object_type="run",
            payload={"open_hold_reasons": run.hard_gate_reasons},
        )
        return run

    # ── read side ────────────────────────────────────────────────────────────
    def get(self, matter_id: str, run_id: str, *, actor_id: str) -> Run:
        matter = self.ctx.matter_for(matter_id, actor_id, "matter.read")
        return self._load(matter, run_id, actor_id, "matter.read")

    def list(self, matter_id: str, *, actor_id: str) -> list[Run]:
        matter = self.ctx.matter_for(matter_id, actor_id, "matter.read")
        return self.ctx.store.list(Run, matter.matter_id)

    def summary(self, matter_id: str, run_id: str, *, actor_id: str) -> dict[str, Any]:
        matter = self.ctx.matter_for(matter_id, actor_id, "matter.read")
        run = self._load(matter, run_id, actor_id, "matter.read")
        mid = matter.matter_id
        steps = {s.step_id: s for s in self.ctx.store.list(RunStep, mid, run_id=run_id)}
        claims = self.ctx.store.list(Claim, mid, run_id=run_id)
        by_status: dict[str, int] = {}
        for claim in claims:
            key = f"{claim.kind.value}:{claim.status.value}"
            by_status[key] = by_status.get(key, 0) + 1
        holds: list[Hold] = self.ctx.holds.open_holds(mid, run_id)
        tasks = self.ctx.store.list(VerificationTask, mid, run_id=run_id, status="open")
        report = self.ctx.store.get(Report, mid, run.report_id) if run.report_id else None
        return {
            "run_id": run.run_id,
            "status": run.status.value,
            "started_by": run.initiated_by,
            "models": run.model_versions,
            "steps": [
                {
                    "step": s.id,
                    "manual": s.manual,
                    "status": steps[s.id].status.value if s.id in steps else "pending",
                    "detail": steps[s.id].detail if s.id in steps else "",
                    "outputs": steps[s.id].outputs if s.id in steps else {},
                }
                for s in self.ctx.workflow.order()
            ],
            "findings": by_status,
            "open_holds": [
                {
                    "hold_id": h.hold_id,
                    "scope": h.scope.value,
                    "subject": h.subject_id,
                    "reason": h.reason_code,
                    "detail": h.detail,
                }
                for h in holds
            ],
            "open_tasks": len(tasks),
            "report": (
                {
                    "report_id": report.report_id,
                    "version": report.version,
                    "sha256": report.sha256,
                    "path": report.artifact_ref,
                    "release_status": report.release_status,
                    "warnings": report.warnings,
                }
                if report
                else None
            ),
        }
