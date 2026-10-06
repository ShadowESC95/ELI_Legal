from eli_legal.domain.models import HumanReview, Run
from eli_legal.legal.human_review_gate import HumanReviewGate


class ReviewService:
    def __init__(self, gate: HumanReviewGate | None = None) -> None:
        self.gate = gate or HumanReviewGate()

    def release_for_reliance(self, run: Run, review: HumanReview | None) -> Run:
        return self.gate.release(run, review)
