from __future__ import annotations

from eli_legal.domain.enums import ReviewDecision, RunStatus
from eli_legal.domain.errors import VerificationGateFailed
from eli_legal.domain.models import HumanReview, Run


class HumanReviewGate:
    """The state change from 'draft' to 'may be relied on'.

    This gate checks the shape of the decision. Who the reviewer is — a real human, named on the
    matter, holding a reviewing role — is established by ``ReviewService`` from the user record
    before it gets here; the actor-type field on the review is a second check, not the first.
    """

    def release(self, run: Run, review: HumanReview | None) -> Run:
        if run.hard_gate_reasons:
            raise VerificationGateFailed(
                "run has unresolved hard gates: " + ", ".join(run.hard_gate_reasons)
            )
        if review is None:
            raise VerificationGateFailed("named human review is required")
        if review.run_id != run.run_id or review.matter_id != run.matter_id:
            raise VerificationGateFailed("review does not belong to this matter/run")
        if review.reviewer_actor_type.lower() != "human":
            raise VerificationGateFailed(
                "an agent/system actor cannot approve release for reliance"
            )
        if not review.reviewer_user_id.strip():
            raise VerificationGateFailed("the reviewer must be named")
        if review.decision is ReviewDecision.REJECT:
            run.status = RunStatus.REJECTED
            return run
        if review.decision is ReviewDecision.RETURN_FOR_CORRECTION:
            run.status = RunStatus.RETURNED_FOR_CORRECTION
            return run
        run.status = RunStatus.APPROVED_FOR_RELIANCE
        return run
