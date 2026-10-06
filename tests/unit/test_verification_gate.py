from eli_legal.domain.enums import ClaimStatus, RunStatus, VerificationStatus
from eli_legal.domain.models import Claim, Run, VerificationResult
from eli_legal.governance.gates import apply_verification_gate


def test_failed_verification_holds_material_claim_and_run():
    run = Run(matter_id="m1", initiated_by="agent")
    claim = Claim(matter_id="m1", run_id=run.run_id, text="Authority X applies")
    vr = VerificationResult(
        matter_id="m1",
        run_id=run.run_id,
        claim_id=claim.claim_id,
        verification_type="current_law",
        status=VerificationStatus.FAILED,
        verifier="citator",
        detail="overruled",
    )
    apply_verification_gate(run, claim, [vr])
    assert claim.status is ClaimStatus.HELD
    assert run.status is RunStatus.HELD
    assert run.hard_gate_reasons
