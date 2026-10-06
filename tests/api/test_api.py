import pytest
from fastapi.testclient import TestClient

from eli_legal.api.app import create_app

A, S = "arb.keane", "sec.byrne"


@pytest.fixture
def api(held_run):
    sv, mid, rid = held_run
    tokens = {u: sv.users.issue_token(actor_id="admin", user_id=u) for u in (A, S, "admin")}
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
    hold_id = summary["open_holds"][0]["hold_id"]
    body = {"action": "exclude", "reason": "Not to be relied on for this hearing."}
    assert (
        client.post(
            f"/matters/{mid}/holds/{hold_id}/resolve", json=body, headers=auth[S]
        ).status_code
        == 403
    )
    review = {
        "decision": "approve",
        "reasons": "Approving while holds are open.",
        "report_hash": summary["report"]["sha256"],
    }
    refused = client.post(f"/matters/{mid}/runs/{rid}/review", json=review, headers=auth[A])
    assert refused.status_code == 409 and refused.json()["error"] == "VerificationGateFailed"
    short = client.post(
        f"/matters/{mid}/holds/{hold_id}/resolve",
        json={"action": "exclude", "reason": "no"},
        headers=auth[A],
    )
    assert short.status_code == 422
    report = client.get(f"/matters/{mid}/runs/{rid}/report", headers=auth[A])
    assert report.status_code == 200 and report.headers["X-Release-Status"] == "NOT_FOR_RELIANCE"
    assert client.get(f"/matters/{mid}/runs/{rid}/report", headers=auth["admin"]).status_code == 403


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
