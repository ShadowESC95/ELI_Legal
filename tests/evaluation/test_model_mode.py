"""With a model configured: it may select and draft, but only from what it was given."""

import re

from eli_legal.application.services import build_services
from eli_legal.demo import build_demo_workspace
from eli_legal.demo_run import ARBITRATOR, SECRETARY, demo_settings, setup_demo
from eli_legal.domain.enums import ClaimKind, ClaimStatus
from tests.conftest import FakeInference


def _labels(prompt: str, prefix: str) -> list[str]:
    return re.findall(rf"^({prefix}\d+)", prompt, re.M)


def _arguments(prompt: str) -> dict:
    facts, authorities = _labels(prompt, "F"), _labels(prompt, "A")
    relied = [facts[0], *authorities[:1]] if facts else []
    return {
        "arguments": [
            {
                "party": "Harbour Freight Ltd",
                "argument": "Harbour Freight Ltd may argue that the delivery date had passed when it gave notice.",
                "relies_on": relied,
            },
            {
                "party": "Northwind Logistics Ltd",
                "argument": "The tribunal should find for Northwind Logistics Ltd.",
                "relies_on": relied,
            },
            {
                "party": "Northwind Logistics Ltd",
                "argument": "Northwind Logistics Ltd may argue that Zeta v Omega [2020] XXSC 55 excuses the delay.",
                "relies_on": relied,
            },
            {
                "party": "Northwind Logistics Ltd",
                "argument": "Northwind Logistics Ltd may argue that only 3 containers were late.",
                "relies_on": relied,
            },
            {
                "party": "Harbour Freight Ltd",
                "argument": "An argument resting on nothing.",
                "relies_on": ["F999"],
            },
        ]
    }


def _run(tmp_path, script, verifier=None):
    model = FakeInference(script)
    workspace = build_demo_workspace(tmp_path / "demo")
    sv = build_services(
        demo_settings(tmp_path, workspace),
        inference=model,
        verifier=verifier,
        install_network_guard=False,
    )
    mid = setup_demo(sv, workspace)
    run = sv.runs.start(mid, actor_id=SECRETARY)
    return sv, mid, run.run_id, model


SCRIPT = {
    "fact_select": {"selected": ["S1", "S2", 999, "nonsense"]},
    "issue_propose": {
        "issues": ["Whether the closure of the Varen Strait excused the delay in delivery"]
    },
    "fact_issue_link": {"links": [{"fact": 1, "issues": [1, 99]}, {"fact": 4242, "issues": [1]}]},
    "arguments": _arguments,
}


def test_model_selection_widens_the_facts_but_cannot_supply_wording(tmp_path):
    sv, mid, rid, _ = _run(tmp_path, SCRIPT)
    facts = [
        c for c in sv.verification.claims(mid, rid, actor_id=ARBITRATOR) if c.kind is ClaimKind.FACT
    ]
    by_model = [c for c in facts if c.origin.startswith("model:")]
    assert by_model, "the model added sentences the date rule did not pick"
    for fact in facts:
        chunk = sv.ctx.store.get_chunk(mid, fact.evidence[0].chunk_id)
        assert fact.text in chunk.text.replace("\n", " "), "still the document's own words"


def test_a_model_proposed_issue_is_labelled_for_the_reviewer_to_confirm(tmp_path):
    from eli_legal.domain.models import Issue

    sv, mid, rid, _ = _run(tmp_path, SCRIPT)
    issues = sv.ctx.store.list(Issue, mid, run_id=rid)
    proposed = [i for i in issues if i.source == "model_proposed"]
    assert [i.label for i in proposed] == [
        "Whether the closure of the Varen Strait excused the delay in delivery"
    ]
    report = open(sv.runs.summary(mid, rid, actor_id=ARBITRATOR)["report"]["path"]).read()
    assert "proposed by the model — confirm or discard" in report


def test_only_a_grounded_neutral_argument_survives(tmp_path):
    sv, mid, rid, model = _run(tmp_path, SCRIPT)
    arguments = [
        c
        for c in sv.verification.claims(mid, rid, actor_id=ARBITRATOR)
        if c.kind is ClaimKind.APPLICATION
    ]
    kept = [c for c in arguments if c.status is ClaimStatus.VERIFIED]
    rejected = {c.text: c.status_reason for c in arguments if c.status is ClaimStatus.REJECTED}
    assert kept and all(
        c.text
        == "Harbour Freight Ltd may argue that the delivery date had passed when it gave notice."
        for c in kept
    )
    assert len(kept) == 1, "the same argument under several issues is stored once"
    assert all(c.depends_on and c.party_id for c in kept)
    assert any(
        "says which party should succeed" in r
        for t, r in rejected.items()
        if "should find for" in t
    )
    assert any(
        "cites an authority that is not among" in r
        for t, r in rejected.items()
        if "[2020] XXSC 55" in t
    )
    assert any(
        "states a figure that is not in" in r
        for t, r in rejected.items()
        if "only 3 containers" in t
    )
    assert not any("resting on nothing" in c.text for c in arguments), (
        "an argument with no real basis is not even stored"
    )
    steps = {s["step"]: s for s in sv.runs.summary(mid, rid, actor_id=ARBITRATOR)["steps"]}
    assert steps["analysis"]["outputs"]["rejected"] >= 3
    assert (
        steps["analysis"]["outputs"]["model_items_rejected"] >= 3
    )  # bad numbers and labels were counted
    report = open(sv.runs.summary(mid, rid, actor_id=ARBITRATOR)["report"]["path"]).read()
    assert "should find for" not in report and "[2020] XXSC 55" not in report
    assert "drafted by a model from the verified items cited" in report


def test_arguments_never_rest_on_a_held_authority(tmp_path):
    sv, mid, rid, model = _run(tmp_path, SCRIPT)
    prompts = [p for p in model.prompts if "Task arguments/" in p]
    assert prompts and not any("[2011] XXSC 14" in p for p in prompts), (
        "the overruled case is never offered to the model as law"
    )


def test_a_model_that_returns_rubbish_contributes_nothing_and_the_run_still_completes(tmp_path):
    sv, mid, rid, _ = _run(
        tmp_path,
        {
            t: "I cannot help with that."
            for t in ("fact_select", "issue_propose", "fact_issue_link", "arguments")
        },
    )
    summary = sv.runs.summary(mid, rid, actor_id=ARBITRATOR)
    assert {s["step"]: s["status"] for s in summary["steps"]}["final_validation"] == "ok"
    claims = sv.verification.claims(mid, rid, actor_id=ARBITRATOR)
    assert not [c for c in claims if c.kind is ClaimKind.APPLICATION]
    assert all(c.origin.startswith("rule:") for c in claims if c.kind is ClaimKind.FACT)
    assert any("model call(s) failed" in w for w in summary["report"]["warnings"])


def test_a_second_model_can_only_make_a_proposition_check_stricter(tmp_path):
    from eli_legal.domain.enums import VerificationStatus as V
    from eli_legal.domain.models import Claim, EvidenceLink
    from eli_legal.legal.llm import LegalModel
    from eli_legal.legal.proposition_verifier import PropositionVerifier
    from eli_legal.legal.provenance import ProvenanceVerifier

    sv, mid, rid, _ = _run(tmp_path, SCRIPT)
    quoted = next(
        c
        for c in sv.verification.claims(mid, rid, actor_id=ARBITRATOR)
        if c.kind is ClaimKind.LEGAL_PROPOSITION and c.status is ClaimStatus.VERIFIED
    )
    link = quoted.evidence[0]
    reworded = Claim(
        matter_id=mid,
        run_id=rid,
        text="Delivery dates never matter in commerce.",
        kind=ClaimKind.LEGAL_PROPOSITION,
        authority_id=quoted.authority_id,
        citation=quoted.citation,
        evidence=[
            EvidenceLink(
                "authority",
                link.target_id,
                link.locator,
                link.quote,
                link.quote_hash,
                link.chunk_id,
            )
        ],
    )
    provenance = ProvenanceVerifier(sv.ctx.store, sv.ctx.vault, {"examplia-law-reports"})

    def verdict(answer, validated=False, model_id="other-model"):
        verifier = PropositionVerifier(
            provenance=provenance,
            verifier_model=LegalModel(
                FakeInference({"support_check": {"verdict": answer}}, model_id=model_id)
            ),
            generator_model_id="fake-model",
            model_verification_validated=validated,
        )
        return verifier.verify_claim(reworded).status

    assert (
        PropositionVerifier(provenance=provenance).verify_claim(reworded).status is V.INCONCLUSIVE
    )
    assert verdict("supported") is V.INCONCLUSIVE, (
        "agreement between two models is not verification"
    )
    assert verdict("not_supported") is V.CONFLICT
    assert verdict("supported", model_id="fake-model") is V.INCONCLUSIVE, (
        "the same model is not independent"
    )
    assert verdict("supported", validated=True) is V.VERIFIED, (
        "only after the deployer has validated that verifier"
    )
    assert PropositionVerifier(provenance=provenance).verify_claim(quoted).status is V.VERIFIED
