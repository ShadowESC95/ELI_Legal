from __future__ import annotations

from dataclasses import dataclass

from eli_legal.domain.enums import HoldResolution, HoldScope, HoldStatus
from eli_legal.domain.errors import InvalidInput
from eli_legal.domain.models import AuditEvent, Hold, Run, utcnow
from eli_legal.persistence.sqlite import Store
from eli_legal.ports.audit import AuditPort
from eli_legal.security.redaction import content_hash


@dataclass(slots=True)
class HoldBook:
    """Holds are records, not log lines: raised, visible, and closed only by a named person."""

    store: Store
    audit: AuditPort

    def open_holds(self, matter_id: str, run_id: str) -> list[Hold]:
        return self.store.list(Hold, matter_id, run_id=run_id, status=HoldStatus.OPEN.value)

    def all_holds(self, matter_id: str, run_id: str) -> list[Hold]:
        return self.store.list(Hold, matter_id, run_id=run_id)

    def raise_hold(
        self,
        *,
        matter_id: str,
        run_id: str,
        scope: HoldScope,
        subject_id: str,
        reason_code: str,
        detail: str = "",
        actor_id: str = "system",
    ) -> Hold:
        for existing in self.open_holds(matter_id, run_id):
            if (existing.scope, existing.subject_id, existing.reason_code) == (
                scope,
                subject_id,
                reason_code,
            ):
                return existing
        hold = Hold(
            matter_id=matter_id,
            run_id=run_id,
            scope=scope,
            subject_id=subject_id,
            reason_code=reason_code,
            detail=detail[:280],
        )
        self.store.put(hold)
        self.audit.append(
            AuditEvent(
                event_type="hold_raised",
                actor_id=actor_id,
                matter_id=matter_id,
                run_id=run_id,
                action="workflow.hold",
                subject_id=hold.hold_id,
                outcome="held",
                object_type=f"hold:{scope.value}",
                payload={"reason_code": reason_code, "held_subject": subject_id},
            )
        )
        return hold

    def resolve(
        self, hold: Hold, *, resolved_by: str, resolution: HoldResolution, reason: str
    ) -> Hold:
        if not reason.strip():
            raise InvalidInput("a reason is required to resolve a hold")
        hold.status = HoldStatus.RESOLVED
        hold.resolved_by = resolved_by
        hold.resolved_at = utcnow()
        hold.resolution = resolution
        hold.resolution_reason = reason
        self.store.put(hold)
        self.audit.append(
            AuditEvent(
                event_type="hold_resolved",
                actor_id=resolved_by,
                matter_id=hold.matter_id,
                run_id=hold.run_id,
                action="hold.resolve",
                subject_id=hold.hold_id,
                outcome=resolution.value,
                object_type=f"hold:{hold.scope.value}",
                reviewer_id=resolved_by,
                input_hash=content_hash(reason),
                payload={"reason_code": hold.reason_code, "held_subject": hold.subject_id},
            )
        )
        return hold

    def close_superseded(
        self,
        matter_id: str,
        run_id: str,
        *,
        scope: HoldScope,
        keep: set[tuple[str, str]],
        actor_id: str = "system",
    ) -> int:
        """Close system holds of ``scope`` whose cause no longer exists after a re-check."""
        closed = 0
        for hold in self.open_holds(matter_id, run_id):
            if hold.scope is scope and (hold.subject_id, hold.reason_code) not in keep:
                self.resolve(
                    hold,
                    resolved_by=actor_id,
                    resolution=HoldResolution.REVERIFIED,
                    reason="the condition that raised this hold no longer applies on re-check",
                )
                closed += 1
        return closed

    def sync_run(self, run: Run) -> Run:
        """Mirror the open holds onto the run so its state can be read at a glance."""
        run.hard_gate_reasons = sorted(
            {h.reason_code for h in self.open_holds(run.matter_id, run.run_id)}
        )
        return run
