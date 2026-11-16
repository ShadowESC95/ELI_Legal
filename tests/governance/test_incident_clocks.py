"""EL-006: a serious incident's Art. 73 deadline counts from when the provider or deployer
became aware of it, not from when it was entered; it has an owner and a stand-in, and the
stand-in is told, once and on the record, when half the time to report is gone undecided."""

from __future__ import annotations

from datetime import timedelta

import pytest

from eli_legal.application.incident_service import needs_escalation, reporting_deadline
from eli_legal.domain.enums import IncidentSeverity
from eli_legal.domain.errors import InvalidInput, InvalidState
from eli_legal.domain.models import Incident, utcnow

A, S, G = "arb.keane", "sec.byrne", "gov.hale"


def _serious(sv, mid):
    return sv.incidents.create(
        mid, actor_id=A, category="wrong_output_relied_on",
        detail="A party relied on a superseded statement of the law from the memorandum.",
        severity=IncidentSeverity.SERIOUS,
    )  # fmt: skip


def test_the_deadline_counts_from_awareness_which_may_only_move_earlier(demo):
    sv, mid = demo
    incident = _serious(sv, mid)
    entered = reporting_deadline(incident)
    assert entered == incident.created_at + timedelta(days=15), "until awareness is recorded"
    aware = utcnow() - timedelta(days=6)
    noted = sv.incidents.record_awareness(
        mid, incident.incident_id, actor_id=A, aware_at=aware,
        basis="Respondent's counsel telephoned the tribunal secretary.",
        occurred_at=aware - timedelta(days=1),
    )  # fmt: skip
    assert reporting_deadline(noted) == aware + timedelta(days=15) < entered
    with pytest.raises(InvalidState, match="never later"):
        sv.incidents.record_awareness(mid, incident.incident_id, actor_id=A,
                                      aware_at=aware + timedelta(days=2), basis="A later note.")  # fmt: skip
    earlier = sv.incidents.record_awareness(
        mid, incident.incident_id, actor_id=A, aware_at=aware - timedelta(days=1),
        basis="An email to the arbitrator the day before.",
    )  # fmt: skip
    assert reporting_deadline(earlier) == aware - timedelta(days=1) + timedelta(days=15)
    with pytest.raises(InvalidInput, match="future"):
        sv.incidents.record_awareness(mid, incident.incident_id, actor_id=A,
                                      aware_at=utcnow() + timedelta(days=1), basis="Tomorrow?")  # fmt: skip
    with pytest.raises(InvalidInput, match="before it happened"):
        sv.incidents.record_awareness(mid, incident.incident_id, actor_id=A, aware_at=aware,
                                      basis="Out of order.", occurred_at=utcnow())  # fmt: skip
    for kind, days in (("death", 10), ("widespread", 2)):
        decided = sv.incidents.decide_reporting(
            mid, incident.incident_id, actor_id=A, reportable=True,
            reason="Reportable: a serious incident under Art. 3(49).", serious_kind=kind,
        )  # fmt: skip
        assert reporting_deadline(decided) == decided.aware_at + timedelta(days=days)


def test_an_owner_and_a_different_stand_in_who_may_manage_incidents(demo):
    sv, mid = demo
    incident = _serious(sv, mid)
    with pytest.raises(InvalidInput, match="different person"):
        sv.incidents.assign(mid, incident.incident_id, actor_id=A, owner=A, backup=A)
    with pytest.raises(InvalidInput, match="may not manage incidents|not an active user"):
        sv.incidents.assign(mid, incident.incident_id, actor_id=A, owner=A, backup=S)
    sv.matters.grant(mid, actor_id=A, user_id=G)
    assigned = sv.incidents.assign(mid, incident.incident_id, actor_id=A, owner=A, backup=G)
    assert (assigned.owner_user_id, assigned.backup_user_id) == (A, G)


def test_the_stand_in_is_told_once_when_half_the_time_is_gone_undecided(demo):
    sv, mid = demo
    incident = _serious(sv, mid)
    sv.matters.grant(mid, actor_id=A, user_id=G)
    sv.incidents.assign(mid, incident.incident_id, actor_id=A, owner=A, backup=G)
    sv.incidents.record_awareness(mid, incident.incident_id, actor_id=A,
                                  aware_at=utcnow() - timedelta(days=9),
                                  basis="Found in the monitoring report nine days ago.")  # fmt: skip
    open_work = {r.check_id: r for r in sv.checks.run().results}["open_work"]
    assert any("Escalated a serious incident" in a and G in a for a in open_work.acted)
    stored = sv.ctx.store.get(Incident, mid, incident.incident_id)
    assert stored.escalated_at is not None and not needs_escalation(stored)
    again = {r.check_id: r for r in sv.checks.run().results}["open_work"]
    assert not again.acted, "told once"
    events = [
        e for e in sv.ctx.audit.events(matter_id=mid) if e["event_type"] == "incident_escalated"
    ]
    assert len(events) == 1 and events[0]["payload"]["counted_from"] == "awareness"
    assert "due by" in " ".join(i.text for i in again.items), "the deadline is still shown"
