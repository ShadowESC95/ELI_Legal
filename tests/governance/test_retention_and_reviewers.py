"""Retention is chosen and enforced, matter by matter; and nobody checks their own work.

A matter may keep its content for its own period once closed, else the organisation's; the
routine checks delete it when that period ends, and report an open matter that has been idle
longer than the organisation allows. Whoever ran the work does not review it, by default, and is
not asked to; the person who proposed a deployment authorisation does not sign it.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest

from eli_legal.demo_run import resolve_demo_holds
from eli_legal.domain.enums import ReviewDecision
from eli_legal.domain.errors import InvalidInput, PolicyDenied
from eli_legal.domain.models import utcnow
from eli_legal.domain.policy import RuntimePolicy
from eli_legal.workflows.case_preparation import warning_id

A, S, G = "arb.keane", "sec.byrne", "gov.hale"
TODAY = utcnow().date()


def _retention(sv, today):
    return {r.check_id: r for r in sv.checks.run(today=today).results}["retention"]


def test_a_matter_keeps_its_content_for_its_own_period_then_it_is_deleted(demo):
    sv, mid = demo
    with pytest.raises(InvalidInput):
        sv.matters.update(mid, actor_id=A, retention_days=-1)
    sv.compliance.set_retention(actor_id=G, audit_days=400, closed_matter_days=3650)
    sv.matters.update(mid, actor_id=A, retention_days=30)
    sv.matters.close(mid, actor_id=A, purge_content=False, reason="Award issued; file closed.")
    _retention(sv, TODAY)
    assert sv.ctx.store.chunks_for(mid), "kept for its own 30 days"
    result = _retention(sv, TODAY + timedelta(days=31))
    assert not sv.ctx.store.chunks_for(mid), "deleted when its own period ended"
    assert any("30-day retention (this matter's)" in line for line in result.acted)
    purged = [e for e in sv.ctx.audit.events(matter_id=mid) if e["event_type"] == "retention_purge"]
    assert len(purged) == 1 and purged[0]["actor_id"] == "system"
    assert "this matter's retention of 30 days" in purged[0]["payload"]["why"]


def test_a_matter_can_return_to_the_organisations_period(demo):
    sv, mid = demo
    sv.matters.update(mid, actor_id=A, retention_days=10)
    assert sv.matters.get(mid, A).retention_days == 10
    sv.matters.update(mid, actor_id=A, organisation_retention=True)
    assert sv.matters.get(mid, A).retention_days is None
    sv.compliance.set_retention(actor_id=G, audit_days=400, closed_matter_days=3650)
    sv.matters.close(mid, actor_id=A, purge_content=False, reason="Award issued; file closed.")
    _retention(sv, TODAY + timedelta(days=11))
    assert sv.ctx.store.chunks_for(mid), "the organisation's ten years apply, not ten days"


def test_an_open_matter_idle_longer_than_the_organisation_allows_is_reported(demo):
    sv, mid = demo
    record = sv.compliance.set_retention(
        actor_id=G, audit_days=400, closed_matter_days=365, inactive_matter_days=30
    )
    assert "an open matter idle for 30 days is reported" in record.summary
    assert sv.compliance.retention().inactive_matter_days == 30
    now = _retention(sv, TODAY)
    assert now.state == "ok" and not now.items
    later = _retention(sv, TODAY + timedelta(days=45))
    assert later.state == "attention"
    assert [i.matter_id for i in later.items] == [mid]
    assert "no recorded activity" in later.items[0].text
    sv.compliance.set_retention(actor_id=G, audit_days=400, closed_matter_days=365)
    assert _retention(sv, TODAY + timedelta(days=45)).state == "ok", "0 days: not reported"


def test_the_person_who_ran_the_work_does_not_review_it_unless_the_policy_allows(demo, monkeypatch):
    field = RuntimePolicy.__dataclass_fields__["require_reviewer_distinct_from_operator"]
    assert field.default is True, "on by default"
    sv, mid = demo
    assert sv.ctx.policy.require_reviewer_distinct_from_operator, "and in the shipped policy"
    rid = sv.runs.start(mid, actor_id=A).run_id  # the arbitrator runs it, and is the only reviewer
    resolve_demo_holds(sv, mid, rid)
    sv.runs.resume(mid, rid, actor_id=A, reason="All holds resolved; rebuild the report.")
    report = sv.runs.summary(mid, rid, actor_id=A)["report"]

    def approve():
        return sv.reviews.decide(
            mid,
            rid,
            actor_id=A,
            decision=ReviewDecision.APPROVE,
            reasons="Checked each finding against its source; the limits are accepted.",
            report_hash=report["sha256"],
            acknowledged=[warning_id(w) for w in report["warnings"]],
        )

    with pytest.raises(PolicyDenied, match="other than the person who ran it"):
        approve()
    told = {n["kind"]: n for n in sv.notifications.inbox(A)}
    assert "review_required" not in told, "not asked to review their own work"
    assert told["reviewer_needed"]["page"] == "matter"
    refused = [e for e in sv.ctx.audit.events(matter_id=mid) if e["event_type"] == "access_denied"]
    assert (
        refused[-1]["actor_id"] == A
        and "other than the person who ran it" in refused[-1]["payload"]["reason"]
    ), "the refusal is recorded"
    # A sole practitioner's organisation may allow it, in its policy file.
    monkeypatch.setattr(
        sv.ctx,
        "policy",
        dataclasses.replace(sv.ctx.policy, require_reviewer_distinct_from_operator=False),
    )
    assert approve().decision is ReviewDecision.APPROVE
