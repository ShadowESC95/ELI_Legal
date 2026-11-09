"""Workflow definition and runner.

The runner executes steps in dependency order and records each outcome. Its rules are the
governance guarantees: a step that does not finish cleanly stops everything downstream; every
outcome is written to the audit ledger; and if the ledger cannot be written the run stops, because
work that cannot be accounted for must not continue.

Orchestration is deliberately kept inside ELI Legal rather than delegated to a host scheduler, so
these rules hold identically standalone and inside ELI.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eli_legal.domain.enums import HoldScope, RunStatus, StepStatus
from eli_legal.domain.errors import AuditIntegrityError, HoldRaised
from eli_legal.domain.models import AuditEvent, Matter, Run, RunStep, utcnow
from eli_legal.governance.holds import HoldBook
from eli_legal.persistence.sqlite import Store
from eli_legal.ports.audit import AuditPort


@dataclass(frozen=True, slots=True)
class StepDef:
    id: str
    depends_on: tuple[str, ...] = ()
    manual: bool = False
    description: str = ""


@dataclass(frozen=True, slots=True)
class WorkflowDef:
    workflow_id: str
    version: str
    purpose: str
    steps: tuple[StepDef, ...]
    hard_gate_failures: tuple[str, ...] = ()

    def step(self, step_id: str) -> StepDef:
        for s in self.steps:
            if s.id == step_id:
                return s
        raise KeyError(step_id)

    def order(self) -> list[StepDef]:
        """Topological order; ties keep the order of the definition file."""
        done: list[StepDef] = []
        placed: set[str] = set()
        remaining = list(self.steps)
        while remaining:
            ready = [s for s in remaining if set(s.depends_on) <= placed]
            if not ready:
                raise ValueError("workflow has a dependency cycle")
            for s in ready:
                done.append(s)
                placed.add(s.id)
                remaining.remove(s)
        return done

    def descendants(self, step_id: str) -> set[str]:
        out: set[str] = set()
        frontier = [step_id]
        while frontier:
            current = frontier.pop()
            for s in self.steps:
                if current in s.depends_on and s.id not in out:
                    out.add(s.id)
                    frontier.append(s.id)
        return out

    @property
    def automated(self) -> list[StepDef]:
        return [s for s in self.order() if not s.manual]


def load_workflow(path: str | Path) -> WorkflowDef:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    steps = tuple(
        StepDef(
            id=s["id"],
            depends_on=tuple(s.get("depends_on", [])),
            manual=bool(s.get("manual", False)),
            description=s.get("description", ""),
        )
        for s in raw["steps"]
    )
    ids = [s.id for s in steps]
    if len(set(ids)) != len(ids):
        raise ValueError("workflow has duplicate step ids")
    for s in steps:
        unknown = set(s.depends_on) - set(ids)
        if unknown:
            raise ValueError(f"step {s.id} depends on unknown step(s): {sorted(unknown)}")
    workflow = WorkflowDef(
        workflow_id=raw["workflow_id"],
        version=str(raw.get("version", "0")),
        purpose=raw.get("purpose", ""),
        steps=steps,
        hard_gate_failures=tuple(raw.get("hard_gate_failures", [])),
    )
    workflow.order()  # raises on a cycle
    return workflow


@dataclass(slots=True)
class StepContext:
    run: Run
    matter: Matter
    actor_id: str
    shared: dict[str, Any] = field(default_factory=dict)


StepHandler = Callable[[StepContext], Mapping[str, Any] | None]


def audit_step(audit: AuditPort, record: RunStep, actor_id: str) -> None:
    """The ledger event for a step's outcome: one form for automated steps and people's."""
    audit.append(
        AuditEvent(
            event_type="step_completed",
            actor_id=actor_id,
            matter_id=record.matter_id,
            run_id=record.run_id,
            action=f"workflow.step.{record.step_id}",
            subject_id=record.record_id,
            outcome=record.status.value,
            object_type="run_step",
            output_hash=outputs_hash(record.outputs),
            payload={"attempt": record.attempt},
        )
    )


def record_person_step(
    store: Store,
    audit: AuditPort,
    *,
    matter_id: str,
    run_id: str,
    step_id: str,
    status: StepStatus,
    actor_id: str,
    detail: str,
    outputs: Mapping[str, Any] | None = None,
) -> RunStep:
    """Record what a person did at one of the workflow's person steps (review, release
    preparation, recipient approval, delivery), so the graph and the run record show it. A step
    put back to pending (a restart) is stored without an event: nothing was done."""
    existing = store.get(RunStep, matter_id, f"{run_id}:{step_id}")
    record = existing or RunStep(matter_id=matter_id, run_id=run_id, step_id=step_id)
    record.status = status
    record.detail = detail[:280]
    record.outputs = dict(outputs or {})
    record.attempt += 1
    now = utcnow()
    record.started_at = record.started_at or now
    record.finished_at = None if status is StepStatus.PENDING else now
    store.put(record)
    if status is not StepStatus.PENDING:
        audit_step(audit, record, actor_id)
    return record


def outputs_hash(outputs: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(outputs, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


@dataclass(slots=True)
class WorkflowRunner:
    store: Store
    audit: AuditPort
    holds: HoldBook

    def execute(
        self,
        *,
        workflow: WorkflowDef,
        run: Run,
        matter: Matter,
        handlers: Mapping[str, StepHandler],
        actor_id: str,
        from_step: str | None = None,
    ) -> list[RunStep]:
        missing = [s.id for s in workflow.automated if s.id not in handlers]
        if missing:
            raise ValueError(f"no handler for step(s): {missing}")
        rerun = (
            {from_step} | workflow.descendants(from_step)
            if from_step
            else {s.id for s in workflow.steps}
        )
        existing = {
            s.step_id: s for s in self.store.list(RunStep, matter.matter_id, run_id=run.run_id)
        }
        context = StepContext(run=run, matter=matter, actor_id=actor_id)
        statuses: dict[str, StepStatus] = {}
        records: list[RunStep] = []
        try:
            for step in workflow.automated:
                record = existing.get(step.id) or RunStep(
                    matter_id=matter.matter_id, run_id=run.run_id, step_id=step.id
                )
                if step.id not in rerun and record.status is StepStatus.OK:
                    statuses[step.id] = StepStatus.OK
                    records.append(record)
                    continue
                current = self.store.get(Run, matter.matter_id, run.run_id)
                stopped = current is not None and current.status is RunStatus.STOPPED
                blocked_by = next(
                    (d for d in step.depends_on if statuses.get(d) is not StepStatus.OK), None
                )
                if stopped or blocked_by:
                    record.status = StepStatus.SKIPPED
                    record.detail = (
                        "run was stopped"
                        if stopped
                        else f"upstream step '{blocked_by}' did not complete"
                    )
                    record.outputs = {}
                    record.finished_at = utcnow()
                else:
                    record.status = StepStatus.RUNNING
                    record.attempt += 1
                    record.started_at = utcnow()
                    record.detail = ""
                    self.store.put(record)
                    self._run_step(step, record, context, handlers[step.id])
                self.store.put(record)
                self._audit_step(record, actor_id)
                statuses[step.id] = record.status
                records.append(record)
        except AuditIntegrityError:
            # Fail closed: stop the run and leave a state that cannot be mistaken for success.
            run.status = RunStatus.BLOCKED
            if "audit_integrity_failure" not in run.hard_gate_reasons:
                run.hard_gate_reasons.append("audit_integrity_failure")
            self.store.put(run)
            raise
        return records

    def _run_step(
        self, step: StepDef, record: RunStep, context: StepContext, handler: StepHandler
    ) -> None:
        try:
            outputs = handler(context)
            record.outputs = dict(outputs or {})
            record.status = StepStatus.OK
        except HoldRaised as held:
            record.status = StepStatus.HELD
            record.detail = str(held)[:280]
            record.outputs = {}
            self.holds.raise_hold(
                matter_id=record.matter_id,
                run_id=record.run_id,
                scope=HoldScope.STEP,
                subject_id=step.id,
                reason_code=held.reason_code,
                detail=held.detail,
                actor_id=context.actor_id,
            )
        except AuditIntegrityError:
            raise
        except Exception as exc:  # a step failure is an outcome to record, not a crash to hide
            record.status = StepStatus.FAILED
            record.detail = f"{type(exc).__name__}: {str(exc)[:240]}"
            record.outputs = {}
            self.holds.raise_hold(
                matter_id=record.matter_id,
                run_id=record.run_id,
                scope=HoldScope.STEP,
                subject_id=step.id,
                reason_code="step_failed",
                detail=type(exc).__name__,
                actor_id=context.actor_id,
            )
        record.finished_at = utcnow()

    def _audit_step(self, record: RunStep, actor_id: str) -> None:
        audit_step(self.audit, record, actor_id)
