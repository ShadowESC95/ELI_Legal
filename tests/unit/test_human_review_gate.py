import pytest

from eli_legal.domain.enums import ReviewDecision, RunStatus
from eli_legal.domain.errors import VerificationGateFailed
from eli_legal.domain.models import HumanReview, Run
from eli_legal.legal.human_review_gate import HumanReviewGate


def test_missing_reviewer_blocks_release():
    run = Run(matter_id="m1", initiated_by="agent1")
    with pytest.raises(VerificationGateFailed):
        HumanReviewGate().release(run, None)


def test_human_approval_releases_clean_run():
    run = Run(matter_id="m1", initiated_by="agent1")
    review = HumanReview(
        matter_id="m1",
        run_id=run.run_id,
        reviewer_user_id="human1",
        decision=ReviewDecision.APPROVE,
        reasons="checked",
    )
    HumanReviewGate().release(run, review)
    assert run.status is RunStatus.APPROVED_FOR_RELIANCE
