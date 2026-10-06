from eli_legal.domain.enums import ClaimStatus, VerificationStatus
from eli_legal.domain.models import Claim, Run, VerificationResult
from eli_legal.governance.gates import apply_verification_gate


def test_stale_authority_cannot_be_marked_verified():
    run = Run(matter_id="adr-1", initiated_by="research-agent")
    claim = Claim(matter_id="adr-1", run_id=run.run_id, text="Old Case remains binding")
    check = VerificationResult(
        matter_id="adr-1",
        run_id=run.run_id,
        claim_id=claim.claim_id,
        verification_type="current_law",
        status=VerificationStatus.FAILED,
        verifier="independent-status-check",
        detail="authority no longer good law",
    )
    apply_verification_gate(run, claim, [check])
    assert claim.status is ClaimStatus.HELD
