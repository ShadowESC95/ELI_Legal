"""Gold evaluation on the synthetic matter.

Each test plants one known defect in the papers or the sources and asserts the control that is
supposed to catch it did so, for the stated reason. Failures and inconclusive results are part
of the expected output, not noise to be filtered away.
"""

from datetime import date

from eli_legal.domain.enums import ClaimKind, ClaimStatus
from eli_legal.domain.models import VerificationResult, VerificationTask
from eli_legal.governance.gates import effective_results

A = "arb.keane"


def _claims(sv, mid, rid):
    return sv.verification.claims(mid, rid, actor_id=A)


def _checks(sv, mid, rid, claim):
    results = [
        r
        for r in sv.ctx.store.list(VerificationResult, mid, run_id=rid)
        if r.claim_id == claim.claim_id
    ]
    return {t: r for t, r in effective_results(results).items()}


def _party_citation(sv, mid, rid, citation):
    return next(
        c
        for c in _claims(sv, mid, rid)
        if c.kind is ClaimKind.PARTY_AUTHORITY and c.citation == citation
    )


def test_outdated_authority_is_held_wherever_it_appears(held_run):
    """The core scenario: a party relies on a case that has since been overruled."""
    sv, mid, rid = held_run
    cited = _party_citation(sv, mid, rid, "[2011] XXSC 14")
    checks = _checks(sv, mid, rid, cited)
    assert checks["citation"].status.value == "verified", "it exists — which is exactly the trap"
    assert checks["current_law"].status.value == "failed"
    assert "overruled 2022-06-10 by [2022] XXSC 7" in checks["current_law"].detail
    assert cited.status is ClaimStatus.HELD
    retrieved = [
        c
        for c in _claims(sv, mid, rid)
        if c.kind is ClaimKind.LEGAL_PROPOSITION and c.citation == "[2011] XXSC 14"
    ]
    assert retrieved and all(c.status is ClaimStatus.HELD for c in retrieved), (
        "also held when research finds it"
    )
    assert not [
        c
        for c in _claims(sv, mid, rid)
        if c.citation == "[2011] XXSC 14" and c.status is ClaimStatus.VERIFIED
    ]


def test_the_authority_that_overruled_it_is_found_and_verified(held_run):
    sv, mid, rid = held_run
    current = [c for c in _claims(sv, mid, rid) if c.citation == "[2022] XXSC 7"]
    assert {c.kind for c in current} == {ClaimKind.PARTY_AUTHORITY, ClaimKind.LEGAL_PROPOSITION}
    assert all(c.status is ClaimStatus.VERIFIED for c in current)


def test_a_citation_that_does_not_exist_fails_citation_verification(held_run):
    sv, mid, rid = held_run
    fabricated = _party_citation(sv, mid, rid, "[2019] XXSC 99")
    checks = _checks(sv, mid, rid, fabricated)
    assert checks["citation"].status.value == "failed"
    assert "non-existent authority" in checks["citation"].detail
    assert checks["current_law"].status.value == "not_run"
    assert fabricated.status is ClaimStatus.HELD


def test_stale_status_information_is_inconclusive_and_routed_to_a_person(held_run):
    sv, mid, rid = held_run
    stale = _party_citation(sv, mid, rid, "[2018] XXCA 33")
    assert _checks(sv, mid, rid, stale)["current_law"].status.value == "inconclusive"
    assert stale.status is ClaimStatus.HELD
    tasks = sv.ctx.store.list(VerificationTask, mid, run_id=rid, status="open")
    assert any(t.claim_id == stale.claim_id and t.verification_type == "current_law" for t in tasks)


def test_legislation_resolves_to_the_version_in_force_on_the_relevant_date(held_run):
    sv, mid, rid = held_run
    act = _party_citation(sv, mid, rid, "Commercial Contracts Act 2009")
    authority = sv.ctx.store.get_authority(act.authority_id)
    assert authority.effective_from == date(2021, 1, 1), "the 2021 text, not the text as enacted"
    assert act.status is ClaimStatus.VERIFIED
    assert "status on 2023-04-28: in_force" in _checks(sv, mid, rid, act)["current_law"].detail
    offered = [
        c
        for c in _claims(sv, mid, rid)
        if c.kind is ClaimKind.LEGAL_PROPOSITION and c.citation == "Commercial Contracts Act 2009"
    ]
    assert all("14 days" not in c.text for c in offered), (
        "the superseded version is not offered as the law"
    )


def test_every_finding_is_verbatim_and_points_at_its_own_paragraph(held_run):
    sv, mid, rid = held_run
    facts = [c for c in _claims(sv, mid, rid) if c.kind is ClaimKind.FACT]
    assert len(facts) >= 20
    for fact in facts:
        link = fact.evidence[0]
        chunk = sv.ctx.store.get_chunk(mid, link.chunk_id)
        assert " ".join(fact.text.split()) in " ".join(chunk.text.split())
        assert link.locator == chunk.locator and "–" not in link.locator
        assert (
            _checks(sv, mid, rid, fact)["evidence_support"].detail
            == "verbatim from the source passage"
        )


def test_chronology_facts_carry_the_right_dates_and_parties(held_run):
    sv, mid, rid = held_run
    matter = sv.matters.get(mid, A)
    party = {p.party_id: p.role for p in matter.parties}
    by_text = {c.text: c for c in _claims(sv, mid, rid) if c.kind is ClaimKind.FACT}
    notice = by_text[
        "On 28 April 2023 the Claimant gave written notice terminating the Supply Agreement."
    ]
    assert notice.event_date == date(2023, 4, 28) and party[notice.party_id] == "claimant"
    phone = next(c for t, c in by_text.items() if t.startswith("On 21 March 2023 I telephoned"))
    assert phone.event_date == date(2023, 3, 21) and party[phone.party_id] == "respondent"
    assert phone.evidence[0].locator.startswith("p.1 ")
    clause = next(c for t, c in by_text.items() if t.startswith("4.1 The Supplier shall deliver"))
    assert clause.party_id is None and clause.event_date == date(2023, 3, 31)


def test_statements_that_contradict_each_other_are_pointed_out(held_run):
    from eli_legal.legal.evidence_mapper import EvidenceMapper

    sv, mid, rid = held_run
    facts = [c for c in _claims(sv, mid, rid) if c.kind is ClaimKind.FACT]
    by_id = {c.claim_id: c.text for c in facts}
    pairs = [
        (by_id[k.claim_a], by_id[k.claim_b], k.reason) for k in EvidenceMapper().conflicts(facts)
    ]
    assert any(
        "gave written notice terminating" in a and "did not receive the notice" in b
        for a, b, _ in pairs
    )
    assert any(
        "€184,500.00" in a + b and "€61,200.00" in a + b and r == "the parties state different sums"
        for a, b, r in pairs
    )


def test_unreadable_and_hostile_documents_are_each_held_for_a_person(held_run):
    sv, mid, rid = held_run
    holds = {(h.reason_code, h.scope.value) for h in sv.holds.list(mid, rid, actor_id=A)}
    assert ("coverage_gap", "document") in holds and (
        "prompt_injection_detected",
        "document",
    ) in holds


def test_planted_defect_scorecard(held_run):
    """Every planted defect caught; nothing planted as defective came out verified."""
    sv, mid, rid = held_run
    claims = _claims(sv, mid, rid)
    planted_bad = {"[2011] XXSC 14", "[2019] XXSC 99", "[2018] XXCA 33"}
    planted_good = {"[2022] XXSC 7", "Commercial Contracts Act 2009"}
    held = {c.citation for c in claims if c.citation and c.status is ClaimStatus.HELD}
    verified = {c.citation for c in claims if c.citation and c.status is ClaimStatus.VERIFIED}
    assert held == planted_bad, "no missed defect and no false hold"
    assert verified == planted_good
    assert not held & verified


def test_the_same_papers_always_produce_the_same_findings_in_the_same_order(tmp_path):
    """Document ids are random; the order of findings must not depend on them."""
    from eli_legal.application.services import build_services
    from eli_legal.demo import build_demo_workspace
    from eli_legal.demo_run import SECRETARY, demo_settings, setup_demo

    def findings(root):
        workspace = build_demo_workspace(root / "demo")
        sv = build_services(demo_settings(root, workspace), install_network_guard=False)
        mid = setup_demo(sv, workspace)
        run = sv.runs.start(mid, actor_id=SECRETARY)
        return [(c.kind.value, c.text, c.status.value) for c in _claims(sv, mid, run.run_id)]

    first, second = findings(tmp_path / "a"), findings(tmp_path / "b")
    assert first == second and len(first) > 25
