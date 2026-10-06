from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from eli_legal.application.container import AppContext
from eli_legal.domain.enums import IncidentSeverity
from eli_legal.domain.errors import InvalidInput, InvalidState, NotFound
from eli_legal.domain.models import Incident, Run, utcnow
from eli_legal.security.redaction import content_hash

# Hold reasons that are incidents in their own right, not just work to be done.
SYSTEM_INCIDENT_REASONS = {
    "prompt_injection_detected": IncidentSeverity.HIGH,
    "audit_gap": IncidentSeverity.HIGH,
    "audit_integrity_failure": IncidentSeverity.SERIOUS,
}


@dataclass(slots=True)
class IncidentService:
    ctx: AppContext

    def open_for_run(self, run: Run) -> list[Incident]:
        """Open an incident for each incident-grade hold on the run that has none yet."""
        ctx = self.ctx
        existing = {
            i.category
            for i in ctx.store.list(Incident, run.matter_id, run_id=run.run_id)
            if i.status == "open"
        }
        opened: list[Incident] = []
        for reason in run.hard_gate_reasons:
            severity = SYSTEM_INCIDENT_REASONS.get(reason)
            if severity is None or reason in existing:
                continue
            incident = Incident(
                matter_id=run.matter_id,
                run_id=run.run_id,
                category=reason,
                detail=f"raised automatically by hard gate '{reason}'",
                created_by="system",
                severity=severity,
            )
            ctx.store.put(incident)
            self._log(incident, "system", "incident_opened", "open")
            opened.append(incident)
        return opened

    def create(
        self,
        matter_id: str,
        *,
        actor_id: str,
        category: str,
        detail: str,
        severity: IncidentSeverity = IncidentSeverity.MEDIUM,
        run_id: str | None = None,
        affected_claim_ids: Sequence[str] = (),
        affected_source_ids: Sequence[str] = (),
    ) -> Incident:
        matter = self.ctx.matter_for(matter_id, actor_id, "incident.manage")
        incident = Incident(
            matter_id=matter.matter_id,
            run_id=run_id,
            category=category,
            detail=detail.strip(),
            created_by=actor_id,
            severity=severity,
            affected_claim_ids=list(affected_claim_ids),
            affected_source_ids=list(affected_source_ids),
        )
        self.ctx.store.put(incident)
        self._log(incident, actor_id, "incident_opened", "open")
        return incident

    def list(self, matter_id: str, *, actor_id: str, open_only: bool = False) -> list[Incident]:
        matter = self.ctx.matter_for(matter_id, actor_id, "matter.read")
        incidents = self.ctx.store.list(Incident, matter.matter_id)
        return [i for i in incidents if not open_only or i.status == "open"]

    def close(
        self, matter_id: str, incident_id: str, *, actor_id: str, containment: str, reason: str
    ) -> Incident:
        matter = self.ctx.matter_for(matter_id, actor_id, "incident.manage")
        incident = self.ctx.store.get(Incident, matter.matter_id, incident_id)
        if incident is None:
            raise NotFound(f"incident not found in this matter: {incident_id}")
        if incident.status != "open":
            raise InvalidState("incident is already closed")
        if len(containment.strip()) < 10 or len(reason.strip()) < 10:
            raise InvalidInput("record what was done to contain it and why it can be closed")
        incident.status = "closed"
        incident.containment = containment.strip()
        incident.closure_reason = reason.strip()
        incident.closed_by, incident.closed_at = actor_id, utcnow()
        self.ctx.store.put(incident)
        self._log(incident, actor_id, "incident_closed", "closed", content_hash(reason))
        return incident

    def _log(
        self,
        incident: Incident,
        actor_id: str,
        event: str,
        outcome: str,
        reason_hash: str | None = None,
    ) -> None:
        self.ctx.log(
            event,
            actor_id=actor_id,
            matter_id=incident.matter_id,
            run_id=incident.run_id,
            action="incident.manage",
            subject_id=incident.incident_id,
            outcome=outcome,
            object_type="incident",
            input_hash=reason_hash,
            source_ids=list(incident.affected_source_ids),
            payload={
                "category": incident.category,
                "severity": incident.severity.value,
                "affected_findings": len(incident.affected_claim_ids),
            },
        )
