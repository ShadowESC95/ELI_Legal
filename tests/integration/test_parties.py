"""Everyone in the case signs in to the court's server with their own account.

The tribunal's people (arbitrator, registrar) see the whole matter. Each party's people
(prosecution, defence, a claimant's or respondent's lawyers, a party acting for themselves) join
the court's matter as that party's representative: they read what is served on all parties and
what their own side filed, file papers for their own side, and answer holds on their own
filings, on their own screen. The tribunal decides each hold, and its analysis is never shown to
a party. Every filing and every answer is in the audit trail under the name of whoever made it.
"""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from eli_legal.api.app import create_app
from eli_legal.application.matter_service import hash_passphrase
from eli_legal.domain.enums import HoldStatus, Profile
from eli_legal.domain.errors import (
    InvalidInput,
    InvalidState,
    MatterAccessDenied,
    NotFound,
    PolicyDenied,
)

A, S = "arb.keane", "sec.byrne"
CLAIMANT, RESPONDENT = "Harbour Freight Ltd", "Northwind Logistics Ltd"
C_SOL, R_BAR, IN_PERSON = "sol.harbour", "bl.northwind", "pat.inperson"


@pytest.fixture
def parties(held_run):
    """The held demo matter, with a lawyer on each side signed up to the court's server."""
    sv, mid, rid = held_run
    for uid, name, role in (
        (C_SOL, "Claimant's solicitor", "solicitor"),
        (R_BAR, "Respondent's barrister", "barrister"),
        (IN_PERSON, "A party in person", "self_represented"),
    ):
        sv.users.add_user(actor_id="admin", user_id=uid, display_name=name, roles=[role])
    sv.matters.grant(mid, actor_id=A, user_id=C_SOL, party=CLAIMANT)
    sv.matters.grant(mid, actor_id=A, user_id=R_BAR, matter_role="party", party=RESPONDENT)
    return sv, mid, rid


def _kinds(sv, user):
    return {n["kind"]: n for n in sv.notifications.inbox(user)}


def _hold(sv, mid, user, reason):
    return next(h for h in sv.parties.case(mid, user)["holds"] if h["reason"] == reason)


def test_a_partys_people_join_the_courts_matter_only_as_that_partys_representative(held_run):
    sv, mid, _rid = held_run
    sv.users.add_user(
        actor_id="admin", user_id=C_SOL, display_name="Solicitor", roles=["solicitor"]
    )
    sv.users.add_user(
        actor_id="admin", user_id="dpp", display_name="Prosecutor", roles=["prosecutor"]
    )
    with pytest.raises(InvalidInput, match="which party"):
        sv.matters.grant(mid, actor_id=A, user_id=C_SOL)
    with pytest.raises(PolicyDenied, match="no role that is valid"):
        sv.matters.grant(mid, actor_id=A, user_id=C_SOL, matter_role="case_worker")
    sv.matters.grant(mid, actor_id=A, user_id=C_SOL, party=CLAIMANT)
    sv.matters.grant(mid, actor_id=A, user_id="dpp", party=RESPONDENT)
    matter = sv.matters.get(mid, A)
    assert matter.member_roles[C_SOL] == matter.member_roles["dpp"] == "party"
    with pytest.raises(InvalidState, match="one named party"):
        sv.matters.set_member(mid, actor_id=A, user_id=C_SOL, clear_party=True)
    with pytest.raises(PolicyDenied):
        sv.matters.set_reviewers(mid, actor_id=A, reviewer_ids=[A, C_SOL])


def test_a_party_sees_its_filings_and_what_is_served_never_the_tribunals_analysis(parties):
    sv, mid, rid = parties
    mine = sv.parties.case(mid, C_SOL)
    assert mine["you_act_for"] == CLAIMANT
    assert {p["filename"] for p in mine["papers"] if p["yours"]} == {
        "01_statement_of_claim.txt",
        "04_letter_3_april_2023.eml",
        "07_site_photo.jpg",
    }
    assert "02_defence.txt" in {p["filename"] for p in mine["papers"]}, "served on all parties"
    for attempt in (
        lambda: sv.matters.get(mid, C_SOL),
        lambda: sv.matters.documents(mid, C_SOL),
        lambda: sv.verification.claims(mid, rid, actor_id=C_SOL),
        lambda: sv.holds.list(mid, rid, actor_id=C_SOL),
        lambda: sv.runs.summary(mid, rid, actor_id=C_SOL),
        lambda: sv.chat.ask(mid, actor_id=C_SOL, question="Who is likely to win?"),
    ):
        with pytest.raises(PolicyDenied):
            attempt()
    assert sv.matters.list_for(C_SOL) == [], "the tribunal's matter list is the tribunal's"
    assert [c["party_name"] for c in sv.parties.cases(C_SOL)] == [CLAIMANT]
    with pytest.raises(PolicyDenied):
        sv.parties.case(mid, A)  # the tribunal uses its own pages
    with pytest.raises(MatterAccessDenied):
        sv.parties.case(mid, IN_PERSON)  # not on this matter


def test_a_party_files_for_its_own_side_and_the_other_side_never_sees_its_confidential_papers(
    parties,
):
    sv, mid, _rid = parties
    served = sv.parties.file(
        mid, actor_id=C_SOL, filename="reply.txt", raw=b"The claimant's reply to the defence."
    )
    sealed = sv.parties.file(
        mid,
        actor_id=C_SOL,
        filename="offer.txt",
        raw=b"A confidential offer, for the tribunal only.",
        confidential=True,
    )
    claimant = sv.matters.get(mid, A).parties[0].party_id
    assert served.party_id == sealed.party_id == claimant, "always filed for their own side"
    assert served.status.value == "processed", "read like any other document"
    other = {p["filename"] for p in sv.parties.case(mid, R_BAR)["papers"]}
    assert "reply.txt" in other and "offer.txt" not in other, "not even listed for the other side"
    with pytest.raises(NotFound):
        sv.parties.passages(mid, sealed.document_id, R_BAR)
    assert "confidential offer" in sv.parties.passages(mid, sealed.document_id, C_SOL)[0]["text"]
    tribunal = {d.filename for d in sv.matters.documents(mid, A)}
    assert {"reply.txt", "offer.txt"} <= tribunal, "the tribunal has both"
    with pytest.raises(InvalidState, match="already on the case"):
        sv.parties.file(
            mid,
            actor_id=R_BAR,
            filename="copy.txt",
            raw=b"A confidential offer, for the tribunal only.",
        )
    filed = [
        e
        for e in sv.ctx.audit.events(matter_id=mid)
        if e["event_type"] == "document_filed_by_party"
    ]
    assert [(e["actor_id"], e["payload"]["access_scope"]) for e in filed] == [
        (C_SOL, "all_parties"),
        (C_SOL, "party_confidential"),
    ]


def test_a_hold_on_a_partys_filing_asks_that_party_and_then_tells_the_tribunal(parties):
    sv, mid, rid = parties
    claimant = _kinds(sv, C_SOL)
    respondent = _kinds(sv, R_BAR)
    assert set(claimant) == set(respondent) == {"answer_needed"}, "each side, for its own filing"
    assert claimant["answer_needed"]["page"] == "filings"
    assert "07_site_photo.jpg" in claimant["answer_needed"]["detail"]
    assert "06_exhibit_c7" in respondent["answer_needed"]["detail"]
    assert "party_answered" not in _kinds(sv, A)

    photo = _hold(sv, mid, C_SOL, "coverage_gap")
    with pytest.raises(NotFound):
        sv.parties.answer(
            mid,
            photo["hold_id"],
            actor_id=R_BAR,
            kind="explain",
            reasons="Not ours to answer at all.",
        )
    with pytest.raises(InvalidInput, match="file the readable copy first"):
        sv.parties.answer(
            mid,
            photo["hold_id"],
            actor_id=C_SOL,
            kind="refiled",
            reasons="A readable copy is filed.",
        )
    copy = sv.parties.file(
        mid,
        actor_id=C_SOL,
        filename="site_photo_described.txt",
        raw=b"The terminal gate, shut, 3 April 2023.",
    )
    sv.parties.answer(
        mid,
        photo["hold_id"],
        actor_id=C_SOL,
        kind="refiled",
        reasons="A described copy of the photograph is filed for the tribunal.",
        replacement_document_id=copy.document_id,
    )
    assert "answer_needed" not in _kinds(sv, C_SOL), "answered: nothing waits for them"
    assert "answer_needed" in _kinds(sv, R_BAR), "the other side still owes its answer"
    told = _kinds(sv, A)["party_answered"]
    assert CLAIMANT in told["title"] and "refiled" in told["detail"]
    assert _kinds(sv, S) == {}, "the registrar does not decide holds, so is not told"

    hold = next(h for h in sv.holds.list(mid, rid, actor_id=A) if h.hold_id == photo["hold_id"])
    assert hold.status is HoldStatus.OPEN, "an answer closes nothing"
    assert (
        hold.answers[0].by == C_SOL and hold.answers[0].replacement_document_id == copy.document_id
    )
    with pytest.raises(PolicyDenied):
        sv.holds.resolve(
            mid, photo["hold_id"], actor_id=C_SOL, action="waive", reason="We say it is fine now."
        )
    sv.holds.resolve(
        mid,
        photo["hold_id"],
        actor_id=A,
        action="waive",
        reason="The described copy suffices; the photograph is not relied on.",
    )
    assert "party_answered" not in _kinds(sv, A)
    answered = [e for e in sv.ctx.audit.events(matter_id=mid) if e["event_type"] == "hold_answered"]
    assert [(e["actor_id"], e["outcome"]) for e in answered] == [(C_SOL, "refiled")]
    assert "described copy" not in str(answered), "the ledger holds identifiers, not what was said"
    assert sv.ctx.audit.report().ok
    assert sv.run_record(mid, rid, actor_id=A).ok


def test_each_party_signs_in_to_the_server_and_answers_from_its_own_screen(parties):
    sv, mid, _rid = parties
    for uid in (C_SOL, R_BAR, A):
        user = sv.ctx.user(uid)
        user.passphrase_hash = hash_passphrase(f"{uid} passphrase")
        sv.ctx.store.put_user(user)
    client = TestClient(create_app(sv), base_url="http://localhost")
    auth = {}
    for uid in (C_SOL, R_BAR, A):
        got = client.post(
            "/v1/auth/login", json={"user_id": uid, "passphrase": f"{uid} passphrase"}
        )
        assert got.status_code == 200, got.text
        auth[uid] = {"X-ELI-CSRF": got.json()["csrf"]}
        client.cookies.clear()
        auth[uid]["Cookie"] = "; ".join(f"{k}={v}" for k, v in got.cookies.items())

    def call(uid, method, path, **kw):
        return client.request(method, path, headers={**auth[uid], **kw.pop("headers", {})}, **kw)

    assert call(C_SOL, "GET", "/v1/matters").json() == []
    assert call(C_SOL, "GET", f"/v1/matters/{mid}").status_code == 403
    cases = call(C_SOL, "GET", "/v1/party/cases").json()
    assert [(c["party_name"], c["waiting"]) for c in cases] == [(CLAIMANT, 1)]
    inbox = call(C_SOL, "GET", "/v1/notifications").json()
    assert [n["kind"] for n in inbox["items"]] == ["answer_needed"]

    filed = call(
        C_SOL,
        "POST",
        f"/v1/party/cases/{mid}/filings?filename=photo_note.txt",
        content=b"What the photograph shows: the gate, shut.",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert filed.status_code == 201, filed.text
    hold_id = call(C_SOL, "GET", f"/v1/party/cases/{mid}").json()["holds"][0]["hold_id"]
    body = {
        "kind": "refiled",
        "reasons": "The readable note of the photograph is filed.",
        "replacement_document_id": filed.json()["document_id"],
    }
    path = f"/v1/party/cases/{mid}/holds/{hold_id}/answer"
    assert call(C_SOL, "POST", path, json=body).status_code == 401, "it needs the passphrase again"
    phrase = base64.b64encode(f"{C_SOL} passphrase".encode()).decode()
    done = call(C_SOL, "POST", path, json=body, headers={"X-ELI-Passphrase-B64": phrase})
    assert done.status_code == 200, done.text
    assert done.json()["answers"][0]["kind"] == "refiled"
    assert (
        call(
            R_BAR,
            "POST",
            path,
            json={"kind": "explain", "reasons": "Trying another side's hold."},
            headers={
                "X-ELI-Passphrase-B64": base64.b64encode(f"{R_BAR} passphrase".encode()).decode()
            },
        ).status_code
        == 404
    )
    tribunal = call(A, "GET", "/v1/notifications").json()
    assert "party_answered" in {n["kind"] for n in tribunal["items"]}


def test_a_partys_people_reach_nothing_on_another_case_and_each_attempt_is_recorded(parties):
    sv, mid, rid = parties
    other = sv.matters.create(
        actor_id=A,
        name="Another dispute before the same arbitrator",
        purpose="A second matter, kept apart from the first",
        jurisdiction="XX",
        profile=Profile.ADJUDICATOR,
        parties=[("Westway Ltd", "claimant"), ("Eastway Ltd", "respondent")],
    )
    secret = sv.ingestion.register(
        matter=other, actor_id=A, filename="other.txt", raw=b"Material on another case entirely."
    )
    held = sv.holds.list(mid, rid, actor_id=A)[0]
    with pytest.raises(MatterAccessDenied):
        sv.parties.case(other.matter_id, C_SOL)
    with pytest.raises(MatterAccessDenied):
        sv.parties.file(
            other.matter_id, actor_id=C_SOL, filename="x.txt", raw=b"Filed on a case I am not on."
        )
    with pytest.raises(NotFound):
        sv.parties.passages(mid, secret.document_id, C_SOL)  # another case's paper, by its id
    with pytest.raises(NotFound):
        sv.parties.answer(
            mid,
            "hld_" + "0" * 32,
            actor_id=C_SOL,
            kind="explain",
            reasons="No such hold anywhere.",
        )
    photo = _hold(sv, mid, C_SOL, "coverage_gap")
    with pytest.raises(InvalidInput):
        sv.parties.answer(
            mid,
            photo["hold_id"],
            actor_id=C_SOL,
            kind="refiled",
            reasons="Naming another case's paper as my copy.",
            replacement_document_id=secret.document_id,
        )
    crossed = [
        e for e in sv.ctx.audit.events(matter_id=mid) if e["event_type"] == "cross_matter_access"
    ]
    assert {(e["actor_id"], e["subject_id"]) for e in crossed} == {(C_SOL, secret.document_id)}
    assert all(e["outcome"] == "denied" for e in crossed)
    assert held.matter_id == mid
