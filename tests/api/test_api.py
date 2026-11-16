"""The server as a front end: the same rules as every other, and the whole lifecycle over HTTP."""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from eli_legal.api.app import create_app
from eli_legal.application.matter_service import hash_passphrase
from eli_legal.application.services import build_services
from eli_legal.demo import PARTIES, RELEVANT_DATE, SOURCE_ID, STATED_ISSUES, build_demo_workspace
from eli_legal.demo_run import demo_settings
from eli_legal.security import authn

from .helpers import Browser

A, S, G = "arb.keane", "sec.byrne", "gov.hale"
PHRASE = {
    A: "arbitrator passphrase",
    S: "secretary passphrase",
    G: "governance passphrase",
    "admin": "administrator phrase",
}


@pytest.fixture
def api(held_run):
    """The server runs in its own thread, outside the test harness, so these requests are checked
    exactly as a real client's would be."""
    sv, mid, rid = held_run
    tokens = {}
    admin = sv.ctx.user("admin")
    admin.passphrase_hash = hash_passphrase(PHRASE["admin"])
    sv.ctx.store.put_user(admin)
    for user, phrase in PHRASE.items():
        if user != "admin":
            sv.users.set_passphrase(actor_id="admin", user_id=user, new=phrase)
        tokens[user] = sv.users.issue_token(actor_id="admin", user_id=user)
    app = create_app(sv)
    client = TestClient(app, base_url="http://localhost")
    return client, mid, rid, {u: {"Authorization": f"Bearer {t}"} for u, t in tokens.items()}, app


def test_health_and_boundaries_are_public_and_say_little(api):
    client, mid, _rid, _, _app = api
    assert set(client.get("/health").json()) == {"status", "version"}
    boundaries = client.get("/v1/boundaries").json()
    assert boundaries["renders_verdict_or_award"] is False
    assert "award.issue" in boundaries["prohibited_actions"]
    assert client.get("/v1/matters").status_code == 401
    wrong = client.get(f"/v1/matters/{mid}", headers={"Authorization": "Bearer wrong"})
    assert wrong.status_code == 401 and wrong.json()["error"] == "AuthenticationFailed"


def test_no_route_answers_without_credentials_except_the_few_meant_to(api):
    client, _mid, _rid, _, app = api
    public = {"/health", "/v1/boundaries", "/", "/v1/auth/login", "/v1/auth/logout"}
    checked = 0
    for route in app.routes:
        methods = getattr(route, "methods", None)
        if not methods or route.path in public or route.path.startswith("/assets"):
            continue
        path = route.path.replace("{", "").replace("}", "")
        for method in methods - {"HEAD", "OPTIONS"}:
            answer = client.request(method, path, json={})
            assert answer.status_code == 401, f"{method} {route.path} answered {answer.status_code}"
            checked += 1
    assert checked > 60


def test_the_server_enforces_the_same_rules_as_every_other_front_end(api):
    client, mid, rid, auth, _app = api
    me = client.get("/v1/auth/session", headers=auth[A]).json()
    assert me["user"]["roles"] == ["arbitrator"] and me["csrf"] is None
    assert [m["matter_id"] for m in client.get("/v1/matters", headers=auth[A]).json()] == [mid]
    assert client.get("/v1/matters", headers=auth["admin"]).json() == []
    assert client.get(f"/v1/matters/{mid}", headers=auth["admin"]).status_code == 403
    missing = client.get(f"/v1/matters/{mid}/runs/run_does_not_exist", headers=auth[A])
    assert missing.status_code == 404
    summary = client.get(f"/v1/matters/{mid}/runs/{rid}", headers=auth[A]).json()
    assert summary["status"] == "held" and summary["open_holds"]
    assert "path" not in summary["report"], "where files sit on the server is not disclosed"
    report = client.get(f"/v1/matters/{mid}/runs/{rid}/report", headers=auth[A]).json()
    assert report["release_status"] == "NOT_FOR_RELIANCE" and "DRAFT" in report["text"]
    assert (
        client.get(f"/v1/matters/{mid}/runs/{rid}/report", headers=auth["admin"]).status_code == 403
    )
    users = client.get("/v1/users", headers=auth[A]).json()
    assert all("passphrase_hash" not in u and "second_factor" not in u for u in users)
    assert "locked_until" in client.get("/v1/users", headers=auth["admin"]).json()[0]


def test_a_decision_needs_the_persons_passphrase_as_well_as_their_token(api, held_run):
    client, mid, rid, auth, _app = api
    sv = held_run[0]
    summary = client.get(f"/v1/matters/{mid}/runs/{rid}", headers=auth[A]).json()
    hold_id = summary["open_holds"][0]["hold_id"]
    body = {"action": "exclude", "reason": "Not to be relied on for this hearing."}
    url = f"/v1/matters/{mid}/holds/{hold_id}/resolve"
    asked = client.post(url, json=body, headers=auth[A])
    assert asked.status_code == 401 and asked.json()["error"] == "StepUpRequired"
    wrong = client.post(
        url, json=body, headers={**auth[A], "X-ELI-Passphrase": "a wrong passphrase"}
    )
    assert wrong.status_code == 401 and wrong.json()["error"] == "AuthenticationFailed"
    signed = {**auth[A], "X-ELI-Passphrase": PHRASE[A]}
    too_short = client.post(url, json={"action": "exclude", "reason": "no"}, headers=signed)
    assert too_short.status_code == 422
    secretary = {**auth[S], "X-ELI-Passphrase": PHRASE[S]}
    assert client.post(url, json=body, headers=secretary).status_code == 403, (
        "proving who you are does not grant the role"
    )
    assert client.post(url, json=body, headers=signed).status_code == 200
    review = {
        "decision": "approve",
        "reasons": "Approving while holds are open.",
        "report_hash": summary["report"]["sha256"],
    }
    refused = client.post(f"/v1/matters/{mid}/runs/{rid}/review", json=review, headers=signed)
    assert refused.status_code == 409 and refused.json()["error"] == "VerificationGateFailed"
    resolved = [
        e for e in sv.ctx.audit.events(matter_id=mid) if e["event_type"] == "hold_resolved"
    ][-1]
    assert resolved["actor_id"] == A and resolved["payload"]["auth"] == "api-token+step-up"


def test_documents_can_be_uploaded_and_a_deactivated_user_is_shut_out(api, held_run):
    client, mid, _rid, auth, _app = api
    sv = held_run[0]
    url = f"/v1/matters/{mid}/documents"
    filed = client.post(
        f"{url}?filename=late_exhibit.txt&doc_type=exhibit",
        content=b"On 5 May 2023 the Claimant returned 2 containers.",
        headers=auth[S],
    )
    assert filed.status_code == 201 and filed.json()["status"] == "processed"
    doc = filed.json()["document_id"]
    passages = client.get(f"{url}/{doc}/passages", headers=auth[S]).json()
    assert passages[0]["text"].startswith("On 5 May 2023") and passages[0]["locator"]
    escaped = client.post(f"{url}?filename=../../etc/passwd", content=b"x", headers=auth[S])
    assert escaped.status_code == 201 and escaped.json()["filename"] == "etcpasswd"
    assert (
        client.post(f"{url}?filename=x.txt", content=b"t", headers=auth["admin"]).status_code == 403
    )
    sv.users.deactivate(actor_id="admin", user_id=S)
    assert client.get("/v1/auth/session", headers=auth[S]).status_code in (401, 403)


def test_the_whole_lifecycle_works_over_https_sessions_alone(tmp_path):
    """From an empty installation to an approved, released report and its evidence pack, with
    every step taken through the server by a signed-in person."""
    workspace = build_demo_workspace(tmp_path / "demo")
    settings = demo_settings(tmp_path, workspace, import_root=workspace.root)
    sv = build_services(settings, install_network_guard=False)
    sv.users.bootstrap_admin("admin", "System administrator", passphrase=PHRASE["admin"])
    authn.remove_harness()  # nothing below is vouched for: only what the server checks counts
    authn.clear()
    app = create_app(sv)

    admin = Browser(app, "admin", PHRASE["admin"])
    people = (
        (A, "Aoife Keane", "arbitrator"),
        (S, "Tom Byrne", "tribunal_secretary"),
        (G, "Ruth Hale", "governance_officer"),
    )
    for user, name, role in people:
        made = admin.decide(
            "POST",
            "/v1/users",
            {"user_id": user, "display_name": name, "roles": [role], "passphrase": PHRASE[user]},
        )
        assert made.status_code == 201, made.text
    source = {
        "source_id": SOURCE_ID,
        "name": "Examplia Law Reports (fictional)",
        "jurisdictions": ["XX"],
        "source_types": ["case", "legislation"],
        "authority_owner": "Examplia Council of Law Reporting (fictional)",
        "licence": "Synthetic data created for demonstration",
        "freshness": "Status is as last confirmed on the date recorded for each authority",
        "inspection": "Each record is a file in the demo corpus directory",
        "terms_reviewed": True,
        "treatment_semantics": "Editorial treatment table",
        "authoritative_for": ["xx_neutral"],
    }
    assert admin.decide("POST", "/v1/sources", source).status_code == 201
    incomplete = admin.decide(
        "POST", "/v1/sources", {**source, "source_id": "no-owner", "authority_owner": ""}
    )
    assert incomplete.status_code == 201
    refused = admin.decide("POST", "/v1/sources/no-owner/approve")
    assert refused.status_code == 403 and "authority owner" in refused.json()["detail"]
    approved = admin.decide("POST", f"/v1/sources/{SOURCE_ID}/approve")
    assert approved.status_code == 204, approved.text
    folder = str(workspace.corpus.relative_to(workspace.root))
    loaded = admin.decide("POST", f"/v1/sources/{SOURCE_ID}/import", {"directory": folder})
    assert loaded.status_code == 200 and loaded.json()["imported"] >= 5

    judge, clerk = Browser(app, A, PHRASE[A]), Browser(app, S, PHRASE[S])
    matter = judge.decide(
        "POST",
        "/v1/matters",
        {
            "name": "Harbour Freight Ltd v Northwind Logistics Ltd",
            "purpose": "Case analysis for the sole arbitrator ahead of the hearing",
            "jurisdiction": "XX",
            "profile": "adjudicator",
            "relevant_date": RELEVANT_DATE.isoformat(),
            "parties": [{"name": n, "role": r} for n, r in PARTIES],
            "stated_issues": list(STATED_ISSUES),
        },
    )
    assert matter.status_code == 201, matter.text
    mid = matter.json()["matter_id"]
    m = f"/v1/matters/{mid}"
    assert judge.decide("POST", f"{m}/members/{S}").status_code == 204
    assert judge.decide("PUT", f"{m}/reviewers", {"ids": [A]}).status_code == 204
    assert judge.decide("PUT", f"{m}/sources", {"ids": [SOURCE_ID]}).status_code == 204
    party = {p["role"]: p["party_id"] for p in matter.json()["parties"]}
    for name, (role, doc_type) in workspace.filing.items():
        query = {
            "filename": name,
            **({"party_id": party[role]} if role else {}),
            **({"doc_type": doc_type} if doc_type else {}),
        }
        filed = clerk.send(
            "POST",
            f"{m}/documents",
            params=query,
            content=(workspace.documents / name).read_bytes(),
        )
        assert filed.status_code == 201, filed.text

    started = clerk.decide("POST", f"{m}/runs")
    assert started.status_code == 202
    rid = started.json()["run_id"]
    assert app.state.jobs.wait()
    r = f"{m}/runs/{rid}"
    assert judge.get(r).json()["status"] == "held"

    claims = {c["claim_id"]: c for c in judge.get(f"{r}/claims").json()}
    for hold in judge.get(f"{r}/holds").json():
        if hold["hold_id"] not in {h["hold_id"] for h in judge.get(f"{r}/holds").json()}:
            continue
        if hold["reason_code"] == "verification_inconclusive":
            body = {
                "check": "current_law",
                "result": "verified",
                "reason": "Checked the treatment table today.",
            }
            done = judge.decide(
                "POST", f"{m}/claims/{claims[hold['subject_id']]['claim_id']}/verifications", body
            )
            assert done.status_code == 201, done.text
            continue
        action = "waive" if hold["reason_code"] == "coverage_gap" else "exclude"
        done = judge.decide(
            "POST",
            f"{m}/holds/{hold['hold_id']}/resolve",
            {"action": action, "reason": "Decided on the papers for this test."},
        )
        assert done.status_code == 200, done.text
    assert judge.get(f"{r}/holds").json() == []

    not_yours = clerk.decide("POST", f"{r}/resume", {"reason": "Holds have been dealt with"})
    assert not_yours.status_code == 403
    assert (
        judge.decide(
            "POST", f"{r}/resume", {"reason": "All holds resolved; rebuild the report."}
        ).status_code
        == 202
    )
    assert app.state.jobs.wait()
    assert judge.get(r).json()["status"] == "awaiting_human_review"

    report = judge.get(f"{r}/report").json()
    decision = {
        "decision": "approve",
        "reasons": "Reviewed against the papers.",
        "report_hash": report["sha256"],
    }
    unacknowledged = judge.decide("POST", f"{r}/review", decision)
    assert unacknowledged.status_code == 409, "every stated limit must be acknowledged"
    decision["acknowledged"] = [w.split(": ", 1)[0] for w in report["warnings"]]
    assert judge.decide("POST", f"{r}/review", decision).status_code == 201
    assert judge.get(r).json()["status"] == "approved_for_reliance"

    pack = judge.decide(
        "POST",
        f"{r}/releases",
        {
            "recipients": [
                {
                    "recipient_id": A,
                    "display_name": "Aoife Keane",
                    "address": "a.keane@tribunal.example",
                }
            ]
        },
    )
    assert pack.status_code == 201 and pack.json()["recipients"][0]["entitled"] is True
    sent = judge.decide(
        "POST", f"{m}/releases/{pack.json()['release_id']}/send", {"confirmed_recipient_ids": [A]}
    )
    assert sent.status_code == 200 and sent.json()[0]["recipient_id"] == A

    assert judge.decide("POST", f"{r}/evidence-pack").status_code == 403, (
        "not the arbitrator's to export"
    )
    assert judge.decide("POST", f"{m}/members/{G}").status_code == 204
    governance = Browser(app, G, PHRASE[G])
    archive = governance.decide("POST", f"{r}/evidence-pack")
    assert archive.status_code == 200 and archive.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(archive.content)).namelist()
    assert any(n.endswith("manifest.json") for n in names) or len(names) > 5
    assert governance.get(f"{r}/record").json()["ok"] is True
    assert admin.get("/v1/audit/verify").json()["ok"] is True

    proofs = {
        e["payload"].get("auth") for e in judge.get(f"/v1/audit/events?matter_id={mid}").json()
    }
    assert proofs <= {"web-session", "web-session+step-up", "system"}, proofs
    asked = judge.decide("POST", f"{m}/chat", {"question": "Who should win this case?"}).json()
    assert any("do not say who should succeed" in n for n in asked["notes"])


def test_suspensions_of_approved_reports_are_listed_and_ending_one_is_a_decision(api):
    """EL-001 parity: what the desktop and command line do with a suspension, the API does,
    and ending one needs the person's passphrase like every decision."""
    client, mid, _rid, _headers, app = api
    judge = Browser(app, A, PHRASE[A])
    listed = judge.get(f"/v1/matters/{mid}/reliance-blocks")
    assert listed.status_code == 200 and listed.json() == []
    path = f"/v1/matters/{mid}/reliance-blocks/blk_missing/resolve"
    body = {"basis": "The source withdrew the overruling; the authority stands as cited."}
    unconfirmed = judge.send("POST", path, body)
    assert unconfirmed.status_code == 401 and unconfirmed.json()["error"] == "StepUpRequired"
    assert judge.decide("POST", path, body).status_code == 404
    assert Browser(app, S, PHRASE[S]).decide("POST", path, body).status_code == 403


def test_preservation_holds_are_placed_and_released_through_the_api_as_decisions(api):
    """EL-004 parity: a hold is placed and released over the API like everywhere else."""
    client, mid, _rid, _headers, app = api
    judge, governance = Browser(app, A, PHRASE[A]), Browser(app, G, PHRASE[G])
    path = f"/v1/matters/{mid}/preservation-holds"
    body = {"legal_basis": "Notice of a negligence claim received on 12 November 2026.",
            "authority": "Tribunal chair"}  # fmt: skip
    assert judge.send("POST", path, body).status_code == 401, "a decision needs the passphrase"
    placed = judge.decide("POST", path, body)
    assert placed.status_code == 201 and placed.json()["scope"] == "matter"
    assert [h["status"] for h in judge.get(path).json()] == ["active"]
    release = f"{path}/{placed.json()['hold_id']}/release"
    reason = {"reason": "The claim was settled by deed; preservation is no longer required."}
    assert judge.decide("POST", release, reason).status_code == 403, "not the owner's to end"
    assert governance.decide("POST", release, reason).json()["status"] == "released"
