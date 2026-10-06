from __future__ import annotations

from eli_legal.domain.enums import ReviewDecision, RunStatus
from eli_legal.domain.errors import VerificationGateFailed
from eli_legal.domain.models import HumanReview, Run


class HumanReviewGate:
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
        if review.decision is not ReviewDecision.APPROVE:
            run.status = RunStatus.REJECTED
            return run
        run.status = RunStatus.APPROVED_FOR_RELIANCE
        return run
