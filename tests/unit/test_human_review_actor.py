import pytest
from eli_legal.domain.enums import ReviewDecision
from eli_legal.domain.errors import VerificationGateFailed
from eli_legal.domain.models import HumanReview, Run
from eli_legal.legal.human_review_gate import HumanReviewGate


def test_agent_cannot_approve_release():
    run = Run(matter_id="m1", initiated_by="agent-a")
    review = HumanReview(matter_id="m1", run_id=run.run_id, reviewer_user_id="agent-b",
                         decision=ReviewDecision.APPROVE, reasons="self check", reviewer_actor_type="agent")
    with pytest.raises(VerificationGateFailed):
        HumanReviewGate().release(run, review)
