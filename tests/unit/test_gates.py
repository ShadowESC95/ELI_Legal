from eli_legal.domain.enums import ClaimKind, ClaimStatus, RunStatus
from eli_legal.domain.enums import VerificationStatus as V
from eli_legal.domain.models import Claim, Run, VerificationResult
from eli_legal.governance.gates import (
    REQUIRED_CHECKS,
    apply_decision,
    apply_verification_gate,
    evaluate_claim,
    propagate_dependencies,
)


def _claim(kind: ClaimKind = ClaimKind.LEGAL_PROPOSITION, **kw) -> Claim:
    return Claim(matter_id="m", run_id="r", text="Old Case remains binding", kind=kind, **kw)


def _result(claim: Claim, vtype: str, status: V, **kw) -> VerificationResult:
    return VerificationResult("m", "r", claim.claim_id, vtype, status, "test", "detail", **kw)


def _all_pass(claim: Claim) -> list[VerificationResult]:
    return [_result(claim, t, V.VERIFIED) for t in REQUIRED_CHECKS[claim.kind]]


def test_citation_existing_is_not_enough_to_verify_an_authority():
    """The Week 1 failure: a citation check confirms the case exists, not that it still applies."""
    claim = _claim()
    decision = evaluate_claim(claim, [_result(claim, "citation", V.VERIFIED)])
    assert decision.status is ClaimStatus.HELD
    assert decision.reason_code == "verification_missing"
    assert "current_law" in decision.missing and "proposition" in decision.missing


def test_stale_authority_cannot_be_marked_verified():
    claim = _claim()
    results = [r for r in _all_pass(claim) if r.verification_type != "current_law"]
    results.append(_result(claim, "current_law", V.FAILED))
    run = Run(matter_id="m", initiated_by="agent")
    apply_verification_gate(run, claim, results)
    assert claim.status is ClaimStatus.HELD
    assert run.status is RunStatus.HELD
    assert run.hard_gate_reasons == ["material_verification_failed_or_inconclusive"]


def test_every_required_check_passing_verifies():
    for kind in ClaimKind:
        claim = _claim(kind)
        assert evaluate_claim(claim, _all_pass(claim)).status is ClaimStatus.VERIFIED


def test_one_passing_result_cannot_outvote_a_failing_one_for_the_same_check():
    claim = _claim()
    results = [*_all_pass(claim), _result(claim, "current_law", V.FAILED)]
    assert evaluate_claim(claim, results).status is ClaimStatus.HELD


def test_inconclusive_and_conflict_hold_a_material_finding():
    for status in (V.INCONCLUSIVE, V.CONFLICT, V.NOT_RUN):
        claim = _claim()
        results = [r for r in _all_pass(claim) if r.verification_type != "proposition"]
        results.append(_result(claim, "proposition", status))
        assert evaluate_claim(claim, results).status is ClaimStatus.HELD


def test_a_named_persons_result_replaces_the_automated_one_and_is_marked_as_an_override():
    claim = _claim()
    results = [r for r in _all_pass(claim) if r.verification_type != "current_law"]
    results.append(_result(claim, "current_law", V.FAILED))
    results.append(_result(claim, "current_law", V.VERIFIED, by_human=True, override=True))
    decision = evaluate_claim(claim, results)
    assert decision.status is ClaimStatus.VERIFIED
    assert decision.overridden == ("current_law",)


def test_non_material_finding_is_never_shown_as_verified_without_its_checks():
    claim = _claim(material=False)
    apply_decision(claim, evaluate_claim(claim, [_result(claim, "citation", V.VERIFIED)]))
    assert claim.status is ClaimStatus.UNVERIFIED


def test_a_human_exclusion_is_not_undone_by_later_passing_checks():
    claim = _claim()
    claim.status = ClaimStatus.EXCLUDED
    apply_decision(claim, evaluate_claim(claim, _all_pass(claim)))
    assert claim.status is ClaimStatus.EXCLUDED


def test_a_held_finding_holds_everything_that_relies_on_it():
    base, middle, top = _claim(), _claim(), _claim()
    base.status = ClaimStatus.HELD
    middle.status = top.status = ClaimStatus.VERIFIED
    middle.depends_on, top.depends_on = [base.claim_id], [middle.claim_id]
    changed = propagate_dependencies([top, middle, base])
    assert {c.claim_id for c in changed} == {middle.claim_id, top.claim_id}
    assert middle.status is top.status is ClaimStatus.HELD
