"""Roles on a matter, clearance and redaction.

Account role, matter role and clearance must all agree. Whatever a person is not cleared for is
withheld from them everywhere it could appear, and they are told it was withheld and why."""

import json
from pathlib import Path

import pytest

from eli_legal.application.matter_service import TeamMember
from eli_legal.domain.enums import AccessScope, ClaimKind, DocumentType, Profile
from eli_legal.domain.errors import InvalidInput, InvalidState, PolicyDenied
from eli_legal.domain.models import Claim, Matter
from eli_legal.security import access
from eli_legal.security.authorizer import MatterAuthorizer
from eli_legal.security.rbac import RoleBindings
from eli_legal.security.redaction import mask_personal_data

A, S, G = "arb.keane", "sec.byrne", "gov.hale"
SECRET = "On 3 May 2023 the Respondent said it would accept €40,000 to settle the claim quietly."


def _add(sv, user_id, roles, name=""):
    sv.users.add_user(actor_id="admin", user_id=user_id, display_name=name or user_id, roles=roles)


def _confidential(sv, mid, scope=AccessScope.PARTY_CONFIDENTIAL, party_role="respondent"):
    matter = sv.matters.get(mid, A)
    party = next(p for p in matter.parties if p.role == party_role)
    document = sv.ingestion.register(
        matter=matter,
        actor_id=A,
        filename="without_prejudice_note.txt",
        raw=(SECRET + "\n").encode(),
        doc_type=DocumentType.CORRESPONDENCE,
        party_id=party.party_id,
        access_scope=scope,
    )
    return sv.ingestion.process(document, actor_id=A, type_given=True), party


def test_someone_already_on_a_matter_keeps_everything_their_account_allowed():
    """Matter roles came after matters: a member with no role set gets the narrowest role that
    takes nothing away, so no one loses a permission they had."""
    for account, expected in {
        "arbitrator": "lead",
        "tribunal_secretary": "case_worker",
        "paralegal": "assistant",
        "read_only": "observer",
        "auditor": "auditor",
        "governance_officer": "decision_maker",
        "solicitor": "case_worker",
    }.items():
        assert access.covering_role({account}, allow_lead=True) == expected, account
        held = access.account_matter_actions({account})
        assert held <= access.MATTER_ROLES[expected].actions, account
    # Newly added people never lead unless someone chooses that.
    assert access.covering_role({"arbitrator"}, allow_lead=False) == "decision_maker"


def test_a_matter_role_narrows_what_an_account_role_allows_and_never_widens_it():
    bindings = RoleBindings()
    bindings.bind("judge.a", "judge")
    bindings.bind("judge.b", "judge")
    bindings.bind("clerk", "paralegal")
    matter = Matter("M", "p", "EU", "judge.a", authorised_user_ids={"judge.a", "judge.b", "clerk"})
    matter.member_roles = {"judge.b": "observer", "clerk": "lead"}
    authz = MatterAuthorizer(bindings)
    with pytest.raises(PolicyDenied, match="as observer on this matter"):
        authz.require_matter(matter, "judge.b", "report.approve")
    authz.require_matter(matter, "judge.b", "document.read")
    with pytest.raises(PolicyDenied):  # leading the matter gives a paralegal no approval
        authz.require_matter(matter, "clerk", "report.approve")
    assert authz.can_matter(matter, "judge.a", "report.approve")
    assert not authz.can_matter(matter, "judge.b", "workflow.run")


def test_a_new_member_gets_a_role_and_only_the_lead_manages_the_team(demo):
    sv, mid = demo
    _add(sv, "arb.two", ["arbitrator"], "Second arbitrator")
    matter = sv.matters.grant(mid, actor_id=A, user_id="arb.two")
    assert matter.member_roles["arb.two"] == "decision_maker"
    _add(sv, "arb.three", ["arbitrator"])
    with pytest.raises(PolicyDenied, match="may not change the matter"):
        sv.matters.grant(mid, actor_id="arb.two", user_id="arb.three")
    denied = [e for e in sv.ctx.audit.events(matter_id=mid) if e["event_type"] == "access_denied"]
    assert denied[-1]["payload"]["reason"] == "matter_role_lacks_permission"
    with pytest.raises(InvalidInput, match="unknown role on a matter"):
        sv.matters.grant(mid, actor_id=A, user_id="arb.three", matter_role="boss")
    with pytest.raises(InvalidState, match="always leads"):
        sv.matters.set_member(mid, actor_id=A, user_id=A, matter_role="observer")


def test_a_reviewer_must_be_able_to_approve_on_the_matter(demo):
    sv, mid = demo
    _add(sv, "arb.two", ["arbitrator"])
    sv.matters.grant(mid, actor_id=A, user_id="arb.two", matter_role="observer")
    with pytest.raises(PolicyDenied, match="cannot approve; make them decision-maker"):
        sv.matters.set_reviewers(mid, actor_id=A, reviewer_ids=[A, "arb.two"])
    sv.matters.set_member(mid, actor_id=A, user_id="arb.two", matter_role="decision_maker")
    sv.matters.set_reviewers(mid, actor_id=A, reviewer_ids=[A, "arb.two"])
    with pytest.raises(InvalidState, match="named reviewer"):
        sv.matters.set_member(mid, actor_id=A, user_id="arb.two", matter_role="case_worker")


def test_material_given_in_confidence_is_withheld_with_the_reason_everywhere(demo):
    sv, mid = demo
    document, party = _confidential(sv, mid)
    # The secretary works the matter as case worker: confidential material is in their clearance.
    assert any(SECRET in c.text for c in sv.matters.passages(mid, document.document_id, S))
    # Acting for the claimant, they no longer see what the respondent gave in confidence.
    claimant = next(p for p in sv.matters.get(mid, A).parties if p.role == "claimant")
    sv.matters.set_member(
        mid, actor_id=A, user_id=S, matter_role="case_worker", party=claimant.name
    )
    listed = {d.document_id: d for d in sv.matters.documents(mid, S)}[document.document_id]
    assert listed.filename == f"{access.WITHHELD} given in confidence by {party.name}"
    assert listed.sha256 == document.sha256  # it exists and can be identified, not read
    passages = sv.matters.passages(mid, document.document_id, S)
    assert len(passages) == 1 and SECRET not in passages[0].text
    assert access.is_withheld(passages[0].text)
    withheld = [
        e for e in sv.ctx.audit.events(matter_id=mid) if e["event_type"] == "content_withheld"
    ]
    assert withheld and withheld[-1]["actor_id"] == S and "text" not in withheld[-1]["payload"]
    # The arbitrator, who leads, sees all of it.
    assert any(SECRET in c.text for c in sv.matters.passages(mid, document.document_id, A))


def test_findings_and_chat_withhold_what_the_reader_is_not_cleared_for(demo):
    sv, mid = demo
    _confidential(sv, mid, scope=AccessScope.NEUTRAL_ONLY)
    run = sv.runs.start(mid, actor_id=A)
    mine = [c for c in sv.verification.claims(mid, run.run_id, actor_id=A) if SECRET[:40] in c.text]
    assert mine, "the lead sees the finding taken from the neutral's own note"
    # The secretary, as case worker, is not cleared for the neutral's own material.
    theirs = {c.claim_id: c for c in sv.verification.claims(mid, run.run_id, actor_id=S)}
    hidden = theirs[mine[0].claim_id]
    assert hidden.text == f"{access.WITHHELD} for the neutral only" and hidden.citation is None
    assert all(not e.quote and not e.target_id for e in hidden.evidence)
    answer = sv.chat.ask(mid, actor_id=S, question="Respondent accept settle claim quietly")
    assert not any(SECRET[:30] in s.text for s in answer.sources)
    assert any("withheld from you (for the neutral only)" in n for n in answer.notes)
    assert any(
        SECRET[:30] in s.text
        for s in sv.chat.ask(
            mid, actor_id=A, question="Respondent accept settle claim quietly"
        ).sources
    )


def test_an_observer_reads_what_is_before_all_parties_with_contact_details_masked(demo):
    sv, mid = demo
    _add(sv, "obs.one", ["read_only"], "Observer")
    sv.matters.grant(mid, actor_id=A, user_id="obs.one")
    member = {m.user_id: m for m in sv.matters.members(mid, A)}["obs.one"]
    assert member.matter_role == "observer" and member.reads == ["all_parties"]
    matter = sv.matters.get(mid, A)
    document = sv.ingestion.register(
        matter=matter,
        actor_id=A,
        filename="contact.txt",
        raw=b"Write to claims@harbourfreight.example or call +353 1 555 0199 by 2023-04-28.\n",
    )
    sv.ingestion.process(document, actor_id=A, type_given=False)
    text = " ".join(c.text for c in sv.matters.passages(mid, document.document_id, "obs.one"))
    assert "[email]" in text and "[phone]" in text and "2023-04-28" in text
    with pytest.raises(PolicyDenied):
        sv.runs.start(mid, actor_id="obs.one")


def test_an_auditor_on_a_matter_exports_the_record_without_its_content(lifecycle, tmp_path):
    """The demonstration exports its pack as the governance officer, whose account reads no
    documents: every record and hash is there, the report and the findings' words are not."""
    pack = Path(lifecycle.evidence_pack)
    manifest = json.loads((pack / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["content"].startswith("withheld")
    assert not any(name.endswith(".md") for name in manifest["files"])
    held_back = [n for n in manifest["files"] if n.endswith(".withheld.json")]
    assert held_back and all(
        len(json.loads((pack / n).read_text(encoding="utf-8"))["sha256"]) == 64 for n in held_back
    )
    claims = json.loads((pack / "claims.json").read_text(encoding="utf-8"))
    assert claims and all(access.is_withheld(c["text"]) for c in claims)


def test_an_argument_is_never_shown_more_widely_than_what_it_rests_on():
    def claim(scope):
        return Claim("m", "r", "t", kind=ClaimKind.FACT, access_scope=scope)

    public, private = claim(AccessScope.ALL_PARTIES), claim(AccessScope.PRIVILEGED)
    secret = claim(AccessScope.PARTY_CONFIDENTIAL)
    assert access.strictest_scope([public, public]) is AccessScope.ALL_PARTIES
    assert access.strictest_scope([public, private]) is AccessScope.PRIVILEGED
    assert access.strictest_scope([public, secret]) is AccessScope.NEUTRAL_ONLY
    assert access.strictest_scope([private, claim(AccessScope.NEUTRAL_ONLY)]) is (
        AccessScope.NEUTRAL_ONLY
    )


def test_oversight_lists_every_matter_without_reading_one_it_is_not_on(demo):
    sv, mid = demo
    _add(sv, "aud.one", ["auditor"], "Auditor")
    rows = {r["matter_id"]: r for r in sv.matters.register("aud.one")}
    row = rows[mid]
    assert not row["member"] and access.is_withheld(str(row["name"]))
    assert "Harbour" not in json.dumps(row) and row["profile"] == "adjudicator"
    with pytest.raises(PolicyDenied):
        sv.matters.register(S)  # a tribunal secretary does not oversee the system


def test_a_matter_can_be_opened_with_its_team_reviewers_and_sources_in_one_step(services):
    sv = services
    sv.users.bootstrap_admin("admin")
    _add(sv, "judge.a", ["judge"])
    _add(sv, "clerk.b", ["tribunal_secretary"])
    _add(sv, "judge.c", ["judge"])
    matter = sv.matters.create(
        actor_id="judge.a",
        name="A v B",
        purpose="Bench memorandum",
        jurisdiction="XX",
        profile=Profile.ADJUDICATOR,
        parties=[("A Ltd", "claimant"), ("B Ltd", "respondent")],
        team=[TeamMember("clerk.b"), TeamMember("judge.c", "decision_maker")],
        reviewers=["judge.a", "judge.c"],
    )
    assert matter.member_roles == {"clerk.b": "case_worker", "judge.c": "decision_maker"}
    assert matter.reviewer_user_ids == {"judge.a", "judge.c"}
    count = len(sv.ctx.store.list_matters())
    _add(sv, "sol.x", ["solicitor"])
    with pytest.raises(InvalidInput):  # a party's lawyer, for no named party: nothing is created
        sv.matters.create(
            actor_id="judge.a",
            name="C v D",
            purpose="p",
            jurisdiction="XX",
            profile=Profile.ADJUDICATOR,
            team=[TeamMember("sol.x")],
        )
    assert len(sv.ctx.store.list_matters()) == count


def test_personal_data_masking_leaves_what_the_dispute_is_about():
    text = (
        "Pay IE29 AIBK 9311 5212 3456 78, card 4111 1111 1111 1111, PPS 1234567T, "
        "phone +353 1 234 5678. On 28/04/2023 and 2023-04-28, 40 containers, €184,500.00, "
        "clause 4.1, [2011] XXSC 14."
    )
    masked = mask_personal_data(text)
    for gone in ("IE29", "4111", "1234567T", "234 5678"):
        assert gone not in masked
    for kept in ("28/04/2023", "2023-04-28", "40 containers", "€184,500.00", "[2011] XXSC 14"):
        assert kept in masked
