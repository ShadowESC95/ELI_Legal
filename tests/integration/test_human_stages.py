"""The human stages at the end of the workflow: review, release preparation, recipient approval
and delivery. Each is recorded when a person does it, and a person can hold the work at any of
them, or suspend reliance on an approved report, until a decision-maker lifts the hold."""

from pathlib import Path

import pytest

from eli_legal.demo_run import resolve_demo_holds
from eli_legal.domain.enums import ReviewDecision, RunStatus, StepStatus
from eli_legal.domain.errors import (
    AuditIntegrityError,
    InvalidInput,
    InvalidState,
    PolicyDenied,
    VerificationGateFailed,
)
from eli_legal.domain.models import RunStep
from eli_legal.workflows.case_preparation import warning_id

A, S = "arb.keane", "sec.byrne"
PERSON_STEPS = ("human_review", "prepare_release", "recipient_approval", "controlled_delivery")


@pytest.fixture
def awaiting(held_run):
    sv, mid, rid = held_run
    resolve_demo_holds(sv, mid, rid)
    sv.runs.resume(mid, rid, actor_id=A, reason="All holds resolved by the tribunal.")
    assert sv.runs.get(mid, rid, actor_id=A).status is RunStatus.AWAITING_HUMAN_REVIEW
    return sv, mid, rid


def _steps(sv, mid, rid):
    return {s.step_id: s for s in sv.ctx.store.list(RunStep, mid, run_id=rid)}


def _approve(sv, mid, rid):
    report = sv.runs.summary(mid, rid, actor_id=A)["report"]
    return sv.reviews.decide(
        mid,
        rid,
        actor_id=A,
        decision=ReviewDecision.APPROVE,
        reasons="Read in full against the papers; limits acknowledged.",
        report_hash=report["sha256"],
        acknowledged=[warning_id(w) for w in report["warnings"]],
    )


def test_each_person_step_is_recorded_when_a_person_does_it(lifecycle):
    """The demonstration approves, prepares, confirms and stages: all four show as done, and
    the run's record still reconciles with the ledger."""
    summary = lifecycle.summary
    steps = {s["step"]: s for s in summary["steps"]}
    for step in PERSON_STEPS:
        assert steps[step]["status"] == "ok", step
    assert "approved for reliance by arb.keane" in steps["human_review"]["detail"]
    assert "nothing was sent" in steps["controlled_delivery"]["detail"]


def test_the_run_record_reconciles_with_the_person_steps(awaiting):
    sv, mid, rid = awaiting
    _approve(sv, mid, rid)
    sv.releases.prepare(mid, rid, actor_id=A, recipients=[(A, "Aoife Keane", "outbox")])
    record = sv.run_record(mid, rid, actor_id=A)
    assert record.ok, record.gaps
    assert _steps(sv, mid, rid)["prepare_release"].status is StepStatus.OK


def test_a_person_can_hold_the_review_and_only_a_decision_maker_can_lift_it(awaiting):
    sv, mid, rid = awaiting
    hold = sv.holds.place(mid, rid, actor_id=S, reason="A late exhibit has been filed; wait.")
    assert sv.runs.get(mid, rid, actor_id=A).status is RunStatus.HELD
    assert _steps(sv, mid, rid)["human_review"].status is StepStatus.HELD
    with pytest.raises(VerificationGateFailed):
        _approve(sv, mid, rid)
    with pytest.raises(InvalidState, match="lift that hold"):
        sv.runs.resume(mid, rid, actor_id=A, reason="Trying to restart over the hold.")
    with pytest.raises(PolicyDenied):  # a case worker may hold work, not release it
        sv.holds.resolve(mid, hold.hold_id, actor_id=S, action="lift", reason="Lifting it myself.")
    with pytest.raises(InvalidState, match="action 'lift'"):
        sv.holds.resolve(mid, hold.hold_id, actor_id=A, action="exclude", reason="Wrong action.")
    sv.holds.resolve(
        mid, hold.hold_id, actor_id=A, action="lift", reason="Exhibit read; no change."
    )
    assert sv.runs.get(mid, rid, actor_id=A).status is RunStatus.AWAITING_HUMAN_REVIEW
    assert _steps(sv, mid, rid)["human_review"].status is StepStatus.PENDING
    _approve(sv, mid, rid)
    assert _steps(sv, mid, rid)["human_review"].status is StepStatus.OK
    assert sv.run_record(mid, rid, actor_id=A).ok


def test_reliance_on_an_approved_report_can_be_suspended_and_its_release_stops(awaiting):
    sv, mid, rid = awaiting
    _approve(sv, mid, rid)
    hold = sv.holds.place(mid, rid, actor_id=A, reason="The authority relied on was overruled.")
    assert _steps(sv, mid, rid)["prepare_release"].status is StepStatus.HELD
    with pytest.raises(VerificationGateFailed):
        sv.releases.prepare(mid, rid, actor_id=A, recipients=[(A, "Aoife Keane", "outbox")])
    sv.holds.resolve(mid, hold.hold_id, actor_id=A, action="lift", reason="Checked: unaffected.")
    assert sv.runs.get(mid, rid, actor_id=A).status is RunStatus.APPROVED_FOR_RELIANCE
    sv.releases.prepare(mid, rid, actor_id=A, recipients=[(A, "Aoife Keane", "outbox")])


def test_reliance_never_resumes_on_a_report_that_changed_while_held(awaiting):
    sv, mid, rid = awaiting
    _approve(sv, mid, rid)
    hold = sv.holds.place(mid, rid, actor_id=A, reason="Suspended pending a check of the file.")
    report = Path(sv.runs.summary(mid, rid, actor_id=A)["report"]["path"])
    report.chmod(0o600)
    report.write_text(report.read_text(encoding="utf-8") + "\nAltered.\n", encoding="utf-8")
    with pytest.raises(AuditIntegrityError):
        sv.holds.resolve(mid, hold.hold_id, actor_id=A, action="lift", reason="Lifting it now.")
    assert sv.runs.get(mid, rid, actor_id=A).status is RunStatus.HELD
    stopped = sv.runs.stop(mid, rid, actor_id=A, reason="The report file was altered.")
    assert stopped.status is RunStatus.STOPPED


def test_holding_is_for_the_human_stages_and_a_restart_sends_the_work_back_through_review(
    awaiting,
):
    sv, mid, rid = awaiting
    sv.reviews.decide(
        mid, rid, actor_id=A, decision=ReviewDecision.RETURN_FOR_CORRECTION,
        reasons="Add the reply to the defence first.",
    )  # fmt: skip
    assert _steps(sv, mid, rid)["human_review"].status is StepStatus.HELD
    with pytest.raises(InvalidState, match="waits for review or once it is approved"):
        sv.holds.place(mid, rid, actor_id=A, reason="Holding a returned run.")
    sv.runs.resume(mid, rid, actor_id=A, reason="Reply filed; run it again.")
    assert sv.runs.get(mid, rid, actor_id=A).status is RunStatus.AWAITING_HUMAN_REVIEW
    assert _steps(sv, mid, rid)["human_review"].status is StepStatus.PENDING
    assert sv.run_record(mid, rid, actor_id=A).ok


def test_the_guide_tells_people_what_a_held_run_needs(awaiting):
    sv, mid, rid = awaiting
    sv.holds.place(mid, rid, actor_id=S, reason="A late exhibit has been filed; wait.")
    guide = sv.guidance.for_matter(mid, actor_id=A)
    assert guide.steps[0].title == "Resolve 1 hold: put on hold by a person"
    assert "Lift the hold" in guide.steps[0].why and guide.steps[0].can_do
    assert not sv.guidance.for_matter(mid, actor_id=S).steps[0].can_do


def test_a_report_returned_for_correction_is_corrected_restarted_and_approved(awaiting):
    """Awaiting review → returned for correction → the correction is filed → restarted →
    awaiting review → approved. A restart that would skip reading the correction is refused,
    and with nothing chosen a returned run starts again from the papers."""
    from eli_legal.domain.enums import DocumentType
    from eli_legal.domain.models import Document

    sv, mid, rid = awaiting
    with pytest.raises(InvalidInput, match="reasons"):
        sv.reviews.decide(
            mid, rid, actor_id=A, decision=ReviewDecision.RETURN_FOR_CORRECTION,
            reasons="x",
        )  # fmt: skip
    sv.reviews.decide(
        mid, rid, actor_id=A, decision=ReviewDecision.RETURN_FOR_CORRECTION,
        reasons="The reply to the defence is missing; file it and run again.",
    )  # fmt: skip
    assert sv.runs.get(mid, rid, actor_id=A).status is RunStatus.RETURNED_FOR_CORRECTION
    with pytest.raises(VerificationGateFailed, match="only a run awaiting review"):
        _approve(sv, mid, rid)
    reader = _steps(sv, mid, rid)["ingest"].finished_at
    matter = sv.matters.get(mid, A)
    filed = sv.ingestion.register(
        matter=matter, actor_id=A, filename="reply_to_defence.txt",
        raw=b"Reply to the defence. The claimant joins issue on the defence.\n",
        doc_type=DocumentType.PLEADING,
    )  # fmt: skip
    sv.ingestion.process(filed, actor_id=A, type_given=True)
    with pytest.raises(InvalidState, match="added after this run read the papers"):
        sv.runs.resume(mid, rid, actor_id=A, reason="Reply filed.", from_step="verification_gate")
    with pytest.raises(InvalidState, match="Document reader or earlier"):
        sv.runs.resume(mid, rid, actor_id=A, reason="Reply filed.", from_step="facts")
    assert sv.runs.get(mid, rid, actor_id=A).status is RunStatus.RETURNED_FOR_CORRECTION
    sv.runs.resume(mid, rid, actor_id=A, reason="Reply to the defence filed; run it again.")
    steps = _steps(sv, mid, rid)
    assert steps["ingest"].finished_at > reader, "the papers were read again, the reply with them"
    assert sv.ctx.store.get(Document, mid, filed.document_id) is not None
    run = sv.runs.get(mid, rid, actor_id=A)
    if run.status is RunStatus.HELD:  # the new document may raise holds of its own
        resolve_demo_holds(sv, mid, rid)
        sv.runs.resume(mid, rid, actor_id=A, reason="Holds on the reply resolved.")
    assert sv.runs.get(mid, rid, actor_id=A).status is RunStatus.AWAITING_HUMAN_REVIEW
    _approve(sv, mid, rid)
    assert sv.runs.get(mid, rid, actor_id=A).status is RunStatus.APPROVED_FOR_RELIANCE
