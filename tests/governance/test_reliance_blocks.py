"""EL-001: an approved report stops leaving the matter the moment an authority it relies on is
found to be no longer good law, and stays stopped until a named reviewer ends that on a recorded
basis. Built on the demonstration, run to an approved report released to the arbitrator."""

from __future__ import annotations

from datetime import timedelta

import pytest

from eli_legal.demo_run import ARBITRATOR, SECRETARY
from eli_legal.domain.enums import RunStatus
from eli_legal.domain.errors import InvalidInput, InvalidState, VerificationGateFailed
from eli_legal.domain.models import Incident, RelianceBlock, Run, utcnow
from eli_legal.domain.release import ReleasePackage
from eli_legal.security import authn
from tests.governance.test_compliance_and_checks import (  # noqa: F401
    TODAY,
    _reimport,
    _services,
    approved,
)

OVERRULED = dict(
    status="overruled",
    status_checked_at=utcnow().isoformat(),
    treatments=[
        {
            "treatment": "overruled",
            "effective_date": (TODAY - timedelta(days=1)).isoformat(),
            "by_citation": "[2026] XXSC 1",
        }
    ],
)


def _matter_and_run(sv):
    matter = sv.ctx.store.list_matters()[0]
    [run] = [r for r in sv.ctx.store.list(Run, matter.matter_id)
             if r.status is RunStatus.APPROVED_FOR_RELIANCE]  # fmt: skip
    return matter, run


def _prepare(sv, mid, rid):
    return sv.releases.prepare(
        mid, rid, actor_id=ARBITRATOR,
        recipients=[(ARBITRATOR, "Aoife Keane", "a.keane@tribunal.example")],
    )  # fmt: skip


def _events(sv, kind):
    return [e for e in sv.ctx.audit.events() if e["event_type"] == kind]


def test_an_overruled_authority_suspends_reliance_on_the_released_report_once(approved):  # noqa: F811
    sv = _services(approved)
    matter, run = _matter_and_run(sv)
    mid = matter.matter_id
    with authn.harness("test-harness"):
        prepared = _prepare(sv, mid, run.run_id)  # before: it may leave
    _reimport(sv, approved, "corvin_2022_xxsc_7", **OVERRULED)
    found = {r.check_id: r for r in sv.checks.run().results}["authorities"]
    assert found.acted and "Suspended reliance" in found.acted[0]
    [block] = sv.ctx.store.list(RelianceBlock, mid)
    assert block.status == "active" and block.run_id == run.run_id
    assert block.report_hash and block.authority_ids and block.claim_ids
    assert ARBITRATOR in block.recipient_ids, "who already received it, to be told"
    [incident] = [i for i in sv.ctx.store.list(Incident, mid) if i.incident_id == block.incident_id]
    assert incident.status == "open" and "suspended" in incident.detail

    with authn.harness("test-harness"):
        with pytest.raises(VerificationGateFailed, match="reliance on this report is suspended"):
            _prepare(sv, mid, run.run_id)
        with pytest.raises(VerificationGateFailed, match="suspended"):
            sv.delivery.distribute(  # prepared before the suspension: still stopped
                mid, prepared.release_id, actor_id=ARBITRATOR,
                confirmed_recipient_ids=[ARBITRATOR],
            )  # fmt: skip
    assert len(_events(sv, "reliance_denied")) == 2
    assert sv.ctx.store.get(ReleasePackage, mid, prepared.release_id) is not None
    assert run.status is RunStatus.APPROVED_FOR_RELIANCE, "the approval stays in the record"
    assert sv.ctx.store.get(Run, mid, run.run_id).status is RunStatus.APPROVED_FOR_RELIANCE

    again = {r.check_id: r for r in sv.checks.run().results}["authorities"]
    assert not again.acted, "running the checks again changes nothing"
    assert len(sv.ctx.store.list(RelianceBlock, mid)) == 1
    assert len([i for i in sv.ctx.store.list(Incident, mid)
                if i.category == "authority_changed_after_approval"]) == 1  # fmt: skip


def test_an_earlier_approved_report_is_suspended_though_a_later_run_exists(approved):  # noqa: F811
    """The routine check once looked only at each matter's latest run, so a report released
    before a later run escaped it."""
    sv = _services(approved)
    matter, run = _matter_and_run(sv)
    with authn.harness("test-harness"):
        later = sv.runs.create(matter.matter_id, actor_id=ARBITRATOR)
    assert sv.ctx.store.list(Run, matter.matter_id)[-1].run_id == later.run_id
    _reimport(sv, approved, "corvin_2022_xxsc_7", **OVERRULED)
    sv.checks.run()
    [block] = sv.ctx.store.list(RelianceBlock, matter.matter_id)
    assert block.run_id == run.run_id


def test_closing_the_incident_does_not_end_the_suspension_only_a_reviewer_can(approved):  # noqa: F811
    sv = _services(approved)
    matter, run = _matter_and_run(sv)
    mid = matter.matter_id
    _reimport(sv, approved, "corvin_2022_xxsc_7", **OVERRULED)
    sv.checks.run()
    [block] = sv.ctx.store.list(RelianceBlock, mid)
    with authn.harness("test-harness"):
        sv.incidents.close(mid, block.incident_id, actor_id=ARBITRATOR,
                           containment="Told the arbitrator not to rely on the memorandum.",
                           reason="Recipients told; the report is suspended.")  # fmt: skip
        with pytest.raises(VerificationGateFailed):
            _prepare(sv, mid, run.run_id)
        basis = ("Checked the judgment itself: [2022] XXSC 7 was overruled by [2026] XXSC 1 "
                 "yesterday; the memorandum relies on it.")  # fmt: skip
        with pytest.raises(Exception, match="named reviewer|not permitted|may not"):
            sv.reliance.resolve(mid, block.block_id, actor_id=SECRETARY, basis=basis)
        with pytest.raises(InvalidInput, match="basis"):
            sv.reliance.resolve(mid, block.block_id, actor_id=ARBITRATOR, basis="fine now")
        with pytest.raises(InvalidState, match="still not confirmed as good law"):
            sv.reliance.resolve(mid, block.block_id, actor_id=ARBITRATOR, basis=basis)
        with pytest.raises(InvalidInput, match="later run"):
            sv.reliance.resolve(mid, block.block_id, actor_id=ARBITRATOR, basis=basis,
                                superseded_by_run_id=run.run_id)  # fmt: skip
        later = sv.runs.create(mid, actor_id=ARBITRATOR)
        with pytest.raises(InvalidState, match="not been approved"):
            sv.reliance.resolve(mid, block.block_id, actor_id=ARBITRATOR, basis=basis,
                                superseded_by_run_id=later.run_id)  # fmt: skip
    assert sv.ctx.store.get(RelianceBlock, mid, block.block_id).status == "active"


def test_a_suspension_is_lifted_when_the_law_is_confirmed_again_and_the_report_may_leave(
    approved,  # noqa: F811
):
    sv = _services(approved)
    matter, run = _matter_and_run(sv)
    mid = matter.matter_id
    _reimport(sv, approved, "corvin_2022_xxsc_7", **OVERRULED)
    sv.checks.run()
    [block] = sv.ctx.store.list(RelianceBlock, mid)
    # The source corrects itself: the judgment said to overrule it was set aside.
    _reimport(sv, approved, "corvin_2022_xxsc_7", status="in_force", treatments=[],
              status_checked_at=utcnow().isoformat())  # fmt: skip
    basis = ("The source withdrew the overruling: [2026] XXSC 1 was set aside on appeal; "
             "[2022] XXSC 7 stands and the memorandum is unaffected.")  # fmt: skip
    with authn.harness("test-harness"):
        lifted = sv.reliance.resolve(mid, block.block_id, actor_id=ARBITRATOR, basis=basis)
        assert lifted.status == "lifted" and lifted.resolved_by == ARBITRATOR
        assert lifted.resolution_basis == basis and lifted.resolved_at is not None
        with pytest.raises(InvalidState, match="already ended"):
            sv.reliance.resolve(mid, block.block_id, actor_id=ARBITRATOR, basis=basis)
        assert _prepare(sv, mid, run.run_id).release_id, "the report may leave again"
    [event] = _events(sv, "reliance_block_resolved")
    assert event["outcome"] == "lifted" and event["actor_id"] == ARBITRATOR


def test_the_evidence_pack_carries_the_suspension(approved, tmp_path):  # noqa: F811
    sv = _services(approved)
    matter, run = _matter_and_run(sv)
    _reimport(sv, approved, "corvin_2022_xxsc_7", **OVERRULED)
    sv.checks.run()
    with authn.harness("test-harness"):
        sv.matters.grant(matter.matter_id, actor_id=ARBITRATOR, user_id="gov.hale")
        pack = sv.evidence_pack(matter.matter_id, run.run_id, actor_id="gov.hale",
                                out_dir=tmp_path / "pack")  # fmt: skip
    import json
    from pathlib import Path

    rows = json.loads((Path(pack) / "reliance_blocks.json").read_text(encoding="utf-8"))
    assert [r["status"] for r in rows] == ["active"]
