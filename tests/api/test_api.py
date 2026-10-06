import pytest
from fastapi.testclient import TestClient

from eli_legal.api.app import create_app

A, S = "arb.keane", "sec.byrne"
PHRASE = {A: "arbitrator passphrase", S: "secretary passphrase", "admin": "administrator phrase"}


@pytest.fixture
def api(held_run):
    """The API runs in its own thread, outside the test harness, so these requests are checked
    exactly as a real client's would be."""
    sv, mid, rid = held_run
    tokens = {}
    for user, phrase in PHRASE.items():
        sv.users.set_passphrase(
            actor_id="admin", user_id=user, new=phrase
        ) if user != "admin" else None
        tokens[user] = sv.users.issue_token(actor_id="admin", user_id=user)
    admin = sv.ctx.user("admin")
    from eli_legal.application.matter_service import hash_passphrase

    admin.passphrase_hash = hash_passphrase(PHRASE["admin"])
    sv.ctx.store.put_user(admin)
    client = TestClient(create_app(sv))
    return client, mid, rid, {u: {"Authorization": f"Bearer {t}"} for u, t in tokens.items()}


def test_health_and_boundaries_are_public_and_everything_else_needs_a_token(api):
    client, mid, _rid, _ = api
    assert client.get("/health").json()["network_default"] == "deny"
    boundaries = client.get("/boundaries").json()
    assert (
        boundaries["renders_verdict_or_award"] is False
        and "award.issue" in boundaries["prohibited_actions"]
    )
    assert client.get("/matters").status_code == 401
    assert (
        client.get(f"/matters/{mid}", headers={"Authorization": "Bearer wrong"}).status_code == 401
    )


def test_the_api_enforces_the_same_rules_as_every_other_front_end(api):
    client, mid, rid, auth = api
    assert client.get("/me", headers=auth[A]).json()["roles"] == ["arbitrator"]
    assert [m["matter_id"] for m in client.get("/matters", headers=auth[A]).json()] == [mid]
    assert client.get("/matters", headers=auth["admin"]).json() == []
    assert client.get(f"/matters/{mid}", headers=auth["admin"]).status_code == 403
    assert client.get(f"/matters/{mid}/runs/run_does_not_exist", headers=auth[A]).status_code == 404
    summary = client.get(f"/matters/{mid}/runs/{rid}", headers=auth[A]).json()
    assert summary["status"] == "held" and summary["open_holds"]
    report = client.get(f"/matters/{mid}/runs/{rid}/report", headers=auth[A])
    assert report.status_code == 200 and report.headers["X-Release-Status"] == "NOT_FOR_RELIANCE"
    assert client.get(f"/matters/{mid}/runs/{rid}/report", headers=auth["admin"]).status_code == 403


def test_a_decision_through_the_api_needs_the_persons_passphrase_as_well_as_their_token(
    api, held_run
):
    client, mid, rid, auth = api
    sv = held_run[0]
    hold_id = client.get(f"/matters/{mid}/runs/{rid}", headers=auth[A]).json()["open_holds"][0][
        "hold_id"
    ]
    body = {"action": "exclude", "reason": "Not to be relied on for this hearing."}
    url = f"/matters/{mid}/holds/{hold_id}/resolve"
    no_phrase = client.post(url, json=body, headers=auth[A])
    assert no_phrase.status_code == 401 and "X-ELI-Passphrase" in no_phrase.json()["detail"]
    assert (
        client.post(
            url, json=body, headers={**auth[A], "X-ELI-Passphrase": "a wrong passphrase"}
        ).status_code
        == 401
    )
    signed = {**auth[A], "X-ELI-Passphrase": PHRASE[A]}
    assert (
        client.post(url, json={"action": "exclude", "reason": "no"}, headers=signed).status_code
        == 422
    )
    secretary = {**auth[S], "X-ELI-Passphrase": PHRASE[S]}
    assert client.post(url, json=body, headers=secretary).status_code == 403, (
        "proving who you are does not grant the role"
    )
    assert client.post(url, json=body, headers=signed).status_code == 200
    summary = client.get(f"/matters/{mid}/runs/{rid}", headers=auth[A]).json()
    review = {
        "decision": "approve",
        "reasons": "Approving while holds are open.",
        "report_hash": summary["report"]["sha256"],
    }
    refused = client.post(f"/matters/{mid}/runs/{rid}/review", json=review, headers=signed)
    assert refused.status_code == 409 and refused.json()["error"] == "VerificationGateFailed"
    resolved = [
        e for e in sv.ctx.audit.events(matter_id=mid) if e["event_type"] == "hold_resolved"
    ][-1]
    assert resolved["actor_id"] == A and resolved["payload"]["auth"] == "api-token+step-up"


def test_documents_can_be_uploaded_and_a_revoked_token_stops_working(api, held_run):
    client, mid, _rid, auth = api
    sv = held_run[0]
    put = client.put(
        f"/matters/{mid}/documents/late_exhibit.txt?doc_type=exhibit",
        content=b"On 5 May 2023 the Claimant returned 2 containers.",
        headers=auth[S],
    )
    assert put.status_code == 201 and put.json()["status"] == "processed"
    assert (
        client.put(
            f"/matters/{mid}/documents/x.txt", content=b"text", headers=auth["admin"]
        ).status_code
        == 403
    )
    sv.users.deactivate(actor_id="admin", user_id=S)
    assert client.get("/me", headers=auth[S]).status_code == 401
