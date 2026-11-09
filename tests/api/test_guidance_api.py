"""Guidance, roles on a matter, compliance and the routine checks over the server: the same
services and rules as the desktop application, with decisions needing the passphrase."""

import pytest

from eli_legal.api.app import create_app
from eli_legal.application.matter_service import hash_passphrase

from .helpers import Browser

A, S, G = "arb.keane", "sec.byrne", "gov.hale"
PHRASE = {
    A: "arbitrator passphrase",
    S: "secretary passphrase",
    G: "governance passphrase",
    "admin": "administrator phrase",
}


@pytest.fixture
def server(held_run):
    sv, mid, rid = held_run
    admin = sv.ctx.user("admin")
    admin.passphrase_hash = hash_passphrase(PHRASE["admin"])
    sv.ctx.store.put_user(admin)
    for user, phrase in PHRASE.items():
        if user != "admin":
            sv.users.set_passphrase(actor_id="admin", user_id=user, new=phrase)
    app = create_app(sv)
    return sv, mid, rid, (lambda user: Browser(app, user, PHRASE[user]))


def test_the_page_is_given_the_words_and_the_next_steps(server):
    _sv, mid, _rid, browse = server
    arbitrator = browse(A)
    words = arbitrator.get("/v1/words").json()
    assert words["states"]["awaiting_human_review"] == "Waiting for review"
    assert words["holds"]["coverage_gap"]["options"]
    assert words["matter_roles"]["observer"]["reads"] == ["all_parties"]
    guide = arbitrator.get(f"/v1/matters/{mid}/guide").json()
    assert guide["role"] == "Lead" and [s["key"] for s in guide["stages"]][3] == "holds"
    assert guide["steps"][0]["title"].startswith("Resolve") and guide["steps"][0]["can_do"]
    home = arbitrator.get("/v1/home").json()
    assert home["work"] and "requirements met" in home["compliance"]
    secretary = browse(S).get(f"/v1/matters/{mid}/guide").json()
    assert secretary["role"] == "Case worker" and not secretary["steps"][0]["can_do"]


def test_people_are_added_in_a_role_on_the_matter_and_only_the_lead_may_change_it(server):
    sv, mid, _rid, browse = server
    sv.users.add_user(actor_id="admin", user_id="obs.y", display_name="O", roles=["read_only"])
    arbitrator = browse(A)
    added = arbitrator.send("POST", f"/v1/matters/{mid}/members/obs.y", {"matter_role": "observer"})
    assert added.status_code == 204, added.text
    members = {m["user_id"]: m for m in arbitrator.get(f"/v1/matters/{mid}/members").json()}
    assert members["obs.y"]["matter_role"] == "observer" and members["obs.y"]["reads"] == [
        "all_parties"
    ]
    refused = browse(S).send("PATCH", f"/v1/matters/{mid}/members/obs.y", {"matter_role": "lead"})
    assert refused.status_code == 403
    changed = arbitrator.send("PATCH", f"/v1/matters/{mid}/members/{S}", {"reads": ["all_parties"]})
    assert changed.status_code == 204
    member = {m["user_id"]: m for m in arbitrator.get(f"/v1/matters/{mid}/members").json()}[S]
    assert member["reads"] == ["all_parties"]


def test_a_matter_is_opened_with_its_team_in_one_request(server):
    _sv, _mid, _rid, browse = server
    arbitrator = browse(A)
    made = arbitrator.send(
        "POST",
        "/v1/matters",
        {
            "name": "C v D",
            "purpose": "Bench memorandum",
            "jurisdiction": "XX",
            "profile": "adjudicator",
            "parties": [
                {"name": "C Ltd", "role": "claimant"},
                {"name": "D Ltd", "role": "respondent"},
            ],
            "team": [{"user_id": S, "matter_role": "assistant", "party": ""}],
            "reviewers": [A],
        },
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["member_roles"] == {S: "assistant"} and body["reviewer_user_ids"] == [A]


def test_compliance_is_read_by_anyone_and_recorded_only_with_the_right_and_the_passphrase(server):
    sv, _mid, _rid, browse = server
    overview = browse(A).get("/v1/compliance").json()
    assert {r["state"] for r in overview["requirements"]} <= {
        "software",
        "met",
        "waiting",
        "review_due",
    }
    form = next(a for a in overview["actions"] if a["id"] == "OA-01")["form"]
    assert form and all(f["label"] and f["key"] for f in form)
    refused = browse(A).decide("POST", "/v1/compliance/actions/OA-04", {"confirmed": True})
    assert refused.status_code == 403
    governance = browse(G)
    unconfirmed = governance.send("POST", "/v1/compliance/actions/OA-04", {"confirmed": True})
    assert unconfirmed.status_code == 401 and unconfirmed.json()["error"] == "StepUpRequired"
    done = governance.decide("POST", "/v1/compliance/actions/OA-04", {"confirmed": True})
    assert done.status_code == 200 and done.json()["recorded_by"] == G
    short = governance.decide(
        "POST", "/v1/compliance/retention", {"audit_days": 30, "closed_matter_days": 30}
    )
    assert short.status_code == 422 and "six months" in short.json()["detail"]
    drafted = governance.send("POST", "/v1/compliance/documents/annex_iv").json()
    assert len(drafted["sha256"]) == 64 and "Annex IV" in drafted["text"]
    signed = governance.decide(
        "POST", "/v1/compliance/actions/OA-05/sign-off", {"sha256": drafted["sha256"]}
    )
    assert signed.status_code == 200, signed.text
    states = {r["id"]: r["state"] for r in governance.get("/v1/compliance").json()["requirements"]}
    assert states["AIA-09"] == "met" and states["AIA-11"] == "met"


def test_the_checks_run_on_request_and_never_show_a_matter_to_someone_not_on_it(
    server, monkeypatch
):
    sv, mid, _rid, browse = server
    sv.users.add_user(actor_id="admin", user_id="aud.z", display_name="A", roles=["auditor"])
    sv.users.set_passphrase(actor_id="admin", user_id="aud.z", new="auditor passphrase")
    monkeypatch.setitem(PHRASE, "aud.z", "auditor passphrase")
    assert browse(A).send("POST", "/v1/checks/run").status_code == 403
    ran = browse(G).send("POST", "/v1/checks/run")
    assert ran.status_code == 200 and ran.json()["headline"]
    auditor = browse("aud.z")
    assert auditor.get("/v1/checks").json()["latest"]["by"] == G
    register = auditor.get("/v1/oversight/matters").json()
    assert (
        register and "Harbour" not in str(register) and register[0]["name"].startswith("[withheld]")
    )
    assert browse(S).get("/v1/oversight/matters").status_code == 403


def test_a_law_package_is_confirmed_current_and_an_incident_decided_by_a_named_person(server):
    sv, mid, _rid, browse = server
    governance = browse(G)
    confirmed = governance.decide(
        "POST",
        "/v1/frameworks/gdpr/current",
        {"checked_on": "2026-11-01", "note": "Checked against the consolidated text."},
    )
    assert confirmed.status_code == 204, confirmed.text
    assert sv.checks.law_checked_on("gdpr")[1] == G
    arbitrator = browse(A)
    opened = arbitrator.send(
        "POST",
        f"/v1/matters/{mid}/incidents",
        {
            "category": "wrong_law",
            "detail": "Relied on a repealed provision.",
            "severity": "serious",
        },
    )
    assert opened.status_code == 201, opened.text
    incident = opened.json()["incident_id"]
    decided = arbitrator.decide(
        "POST",
        f"/v1/matters/{mid}/incidents/{incident}/reporting",
        {
            "reportable": True,
            "reason": "Harm to a party's rights is possible.",
            "serious_kind": "general",
            "reported_on": "2026-11-05",
            "reference": "MSA-2026-001",
        },
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["report_reference"] == "MSA-2026-001"
