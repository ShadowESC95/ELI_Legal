from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from eli_legal.application.container import AppContext
from eli_legal.domain.enums import IncidentSeverity
from eli_legal.domain.errors import InvalidInput, InvalidState, NotFound
from eli_legal.domain.models import Incident, Run, utcnow
from eli_legal.security import access, authn
from eli_legal.security.redaction import content_hash

# Hold reasons that are incidents in their own right, not just work to be done.
SYSTEM_INCIDENT_REASONS = {
    "prompt_injection_detected": IncidentSeverity.HIGH,
    "audit_gap": IncidentSeverity.HIGH,
    "audit_integrity_failure": IncidentSeverity.SERIOUS,
}


# EU AI Act Art. 73(2)-(4): a serious incident is reported immediately once a causal link (or
# its reasonable likelihood) is established, and at the latest within these many days of the
# provider or deployer becoming aware of it. Counted from the recorded awareness; until one is
# recorded, from when the incident was entered here, which can only be later (EL-006).
REPORTING_DAYS = {"general": 15, "death": 10, "widespread": 2}
DEADLINE_RULE = (
    "AI Act Art. 73(2)-(4) as amended by Regulation (EU) 2026/1744; counted from awareness"
)


def reporting_deadline(incident: Incident) -> datetime | None:
    """When a serious incident must have been reported, unless a person decided it is not
    reportable or it has been reported."""
    if incident.severity is not IncidentSeverity.SERIOUS or incident.reportable is False:
        return None
    if incident.reported_at is not None:
        return None
    days = REPORTING_DAYS.get(incident.serious_kind or "general", REPORTING_DAYS["general"])
    return counted_from(incident) + timedelta(days=days)


def counted_from(incident: Incident) -> datetime:
    """Awareness, where it was recorded; otherwise when the incident was entered here."""
    return incident.aware_at or incident.created_at


def needs_escalation(incident: Incident, now: datetime | None = None) -> bool:
    """Half the reporting window gone with no decision recorded: the stand-in is told."""
    deadline = reporting_deadline(incident)
    if deadline is None or incident.reportable is not None or incident.escalated_at is not None:
        return False
    start = counted_from(incident)
    return (now or utcnow()) >= start + (deadline - start) / 2


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

    def decide_reporting(
        self,
        matter_id: str,
        incident_id: str,
        *,
        actor_id: str,
        reportable: bool,
        reason: str,
        serious_kind: str = "general",
        reported_on: datetime | None = None,
        reference: str = "",
    ) -> Incident:
        """A person's decision on a serious incident: whether it must be reported to the market
        surveillance authority (Art. 73), and if it was, when and under what reference."""
        authn.require_step_up(actor_id, "decide whether an incident is reportable")
        matter = self.ctx.matter_for(matter_id, actor_id, "incident.manage")
        incident = self.ctx.store.get(Incident, matter.matter_id, incident_id)
        if incident is None:
            raise NotFound(f"incident not found in this matter: {incident_id}")
        if serious_kind not in REPORTING_DAYS:
            raise InvalidInput("the kind is general, death or widespread")
        if len(reason.strip()) < 10:
            raise InvalidInput("give the reasons for the decision")
        if reported_on is not None and not reportable:
            raise InvalidInput("an incident decided not reportable has no report date")
        incident.severity = IncidentSeverity.SERIOUS
        incident.serious_kind = serious_kind
        incident.reportable = reportable
        incident.report_decided_by = actor_id
        incident.report_reason = reason.strip()
        if reported_on is not None:
            incident.reported_at, incident.report_reference = reported_on, reference.strip()
        self.ctx.store.put(incident)
        self._log(
            incident,
            actor_id,
            "incident_reporting_decided",
            "reported" if reported_on else ("reportable" if reportable else "not_reportable"),
            content_hash(reason),
        )
        return incident

    def record_awareness(
        self,
        matter_id: str,
        incident_id: str,
        *,
        actor_id: str,
        aware_at: datetime,
        basis: str,
        aware_by: str = "",
        occurred_at: datetime | None = None,
    ) -> Incident:
        """When the provider or deployer became aware of the incident, and how. The deadline
        counts from it. Once recorded it may be moved earlier, never later: a later date would
        lengthen the time to report."""
        authn.require_step_up(actor_id, "record when an incident became known")
        matter = self.ctx.matter_for(matter_id, actor_id, "incident.manage")
        now = utcnow()
        if aware_at > now or (occurred_at is not None and occurred_at > now):
            raise InvalidInput("awareness and occurrence cannot be in the future")
        if occurred_at is not None and occurred_at > aware_at:
            raise InvalidInput("it cannot have been known before it happened")
        basis = " ".join(basis.split())
        if len(basis) < 10:
            raise InvalidInput("say how it became known (a report, an alert, a call)")

        def note(i: Incident) -> None:
            if i.aware_at is not None and aware_at > i.aware_at:
                raise InvalidState(
                    "awareness was recorded earlier; it may be moved earlier, never later"
                )
            i.aware_at, i.aware_by = aware_at, aware_by or actor_id
            i.awareness_basis = basis
            if occurred_at is not None:
                i.occurred_at = occurred_at

        incident = self.ctx.store.change(Incident, matter.matter_id, incident_id, note)
        self._log(
            incident, actor_id, "incident_awareness_recorded", "recorded", content_hash(basis)
        )
        return incident

    def assign(
        self, matter_id: str, incident_id: str, *, actor_id: str, owner: str, backup: str
    ) -> Incident:
        """Who owns the incident and who stands in: two different people who may manage
        incidents on the matter. The stand-in is told when half the time to report is gone."""
        matter = self.ctx.matter_for(matter_id, actor_id, "incident.manage")
        if not owner or not backup or owner == backup:
            raise InvalidInput("name an owner and a different person to stand in")
        for uid in (owner, backup):
            user = self.ctx.store.get_user(uid)
            if user is None or not user.active:
                raise InvalidInput(f"{uid!r} is not an active user")
            if not (
                self.ctx.authorizer().bindings.can(uid, "incident.manage")
                and access.permits(matter, uid, user.roles, "incident.manage")
            ):
                raise InvalidInput(f"{uid!r} may not manage incidents on this matter")

        def give(i: Incident) -> None:
            i.owner_user_id, i.backup_user_id = owner, backup

        incident = self.ctx.store.change(Incident, matter.matter_id, incident_id, give)
        self._log(incident, actor_id, "incident_assigned", "assigned")
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
