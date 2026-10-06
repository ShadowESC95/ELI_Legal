from eli_legal.domain.models import Claim, Run, VerificationResult
from eli_legal.governance.gates import apply_verification_gate


class VerificationService:
    def apply(self, run: Run, claim: Claim, results: list[VerificationResult]) -> None:
        apply_verification_gate(run, claim, results)
