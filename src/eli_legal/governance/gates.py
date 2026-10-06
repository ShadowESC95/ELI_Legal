from __future__ import annotations
from eli_legal.domain.enums import ClaimStatus, RunStatus, VerificationStatus
from eli_legal.domain.models import Claim, Run, VerificationResult

HARD_VERIFICATION_TYPES = {"citation", "current_law", "proposition", "provenance"}


def apply_verification_gate(run: Run, claim: Claim, results: list[VerificationResult]) -> None:
    relevant = [r for r in results if r.claim_id == claim.claim_id and r.verification_type in HARD_VERIFICATION_TYPES]
    failed = [r for r in relevant if r.status in {VerificationStatus.FAILED, VerificationStatus.CONFLICT}]
    inconclusive = [r for r in relevant if r.status in {VerificationStatus.INCONCLUSIVE, VerificationStatus.NOT_RUN}]
    if failed or (claim.material and inconclusive):
        claim.status = ClaimStatus.HELD
        run.status = RunStatus.HELD
        reason = "material_verification_failed_or_inconclusive"
        if reason not in run.hard_gate_reasons:
            run.hard_gate_reasons.append(reason)
        return
    if claim.material and not relevant:
        claim.status = ClaimStatus.HELD
        run.status = RunStatus.HELD
        if "material_verification_missing" not in run.hard_gate_reasons:
            run.hard_gate_reasons.append("material_verification_missing")
        return
    claim.status = ClaimStatus.VERIFIED
