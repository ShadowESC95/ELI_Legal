"""What stands between the network and the application."""

import argparse
import ssl
import time

import pytest
from fastapi.testclient import TestClient

from eli_legal.api import serve, tls
from eli_legal.api.app import create_app
from eli_legal.api.config import ServerConfig
from eli_legal.api.security import RateLimiter
from eli_legal.application.matter_service import hash_passphrase
from eli_legal.security import totp

from .helpers import Browser

A, S = "arb.keane", "sec.byrne"
PHRASE = {A: "arbitrator passphrase", S: "secretary passphrase", "admin": "administrator phrase"}
LOCAL = "http://localhost"


@pytest.fixture
def served(held_run):
    sv, mid, rid = held_run
    admin = sv.ctx.user("admin")
    admin.passphrase_hash = hash_passphrase(PHRASE["admin"])
    sv.ctx.store.put_user(admin)
    for user in (A, S):
        sv.users.set_passphrase(actor_id="admin", user_id=user, new=PHRASE[user])

    def app(**config):
        return create_app(sv, ServerConfig(**config))

    return sv, mid, rid, app


def test_signing_in_gives_a_cookie_scripts_cannot_read_and_a_csrf_value(served):
    sv, mid, _rid, app = served
    application = app()
    anonymous = TestClient(application, base_url=LOCAL)
    wrong = anonymous.post(
        "/v1/auth/login", json={"user_id": A, "passphrase": "not the passphrase"}
    )
    assert wrong.status_code == 401 and "set-cookie" not in wrong.headers
    nobody = anonymous.post(
        "/v1/auth/login", json={"user_id": "no.such.user", "passphrase": "x" * 12}
    )
    assert nobody.json() == wrong.json(), "an unknown user looks the same as a wrong passphrase"
    browser = Browser(application, A, PHRASE[A])
    cookie = browser.login.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    assert browser.get("/v1/matters").json()[0]["matter_id"] == mid
    session = browser.get("/v1/auth/session").json()
    assert session["csrf"] == browser.csrf and session["user"]["user_id"] == A
    body = {"question": "When was the notice received?"}
    forged = browser.client.post(f"/v1/matters/{mid}/chat", json=body)
    assert forged.status_code == 403 and "CSRF" in forged.json()["detail"]
    guessed = browser.client.post(
        f"/v1/matters/{mid}/chat", json=body, headers={"X-ELI-CSRF": "0" * 64}
    )
    assert guessed.status_code == 403
    assert browser.send("POST", f"/v1/matters/{mid}/chat", body).status_code == 200
    assert browser.send("POST", "/v1/auth/logout").status_code == 204
    assert browser.get("/v1/matters").status_code == 401
    events = [
        e["outcome"] for e in sv.ctx.audit.events(matter_id="-") if e["event_type"] == "sign_in"
    ]
    assert events[-4:] == ["sign_in_refused", "sign_in_refused", "signed_in", "signed_out"]


def test_a_session_from_another_front_end_is_not_a_web_session(served):
    sv, _mid, _rid, app = served
    client = TestClient(app(), base_url=LOCAL)
    token = sv.users.login(A, PHRASE[A], method="cli-session")
    client.cookies.set("eli_legal_session", token)
    assert client.get("/v1/matters").status_code == 401


def test_an_idle_session_ends(served):
    _sv, _mid, _rid, app = served
    browser = Browser(app(idle_minutes=0.002), A, PHRASE[A])
    assert browser.get("/v1/matters").status_code == 200
    time.sleep(0.25)
    assert browser.get("/v1/matters").status_code == 401


def test_every_response_carries_the_browser_protections(served):
    _sv, _mid, _rid, app = served
    plain = TestClient(app(), base_url=LOCAL)
    for path in ("/", "/health", "/v1/matters", "/assets/app.js", "/no-such-page"):
        headers = plain.get(path).headers
        csp = headers["content-security-policy"]
        assert (
            "default-src 'none'" in csp
            and "script-src 'self'" in csp
            and "frame-ancestors 'none'" in csp
        )
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
        assert (
            headers["x-content-type-options"] == "nosniff" and headers["x-frame-options"] == "DENY"
        )
        assert headers["referrer-policy"] == "no-referrer"
        assert headers["cross-origin-resource-policy"] == "same-origin"
        assert "server" not in headers and "access-control-allow-origin" not in headers
        assert "strict-transport-security" not in headers, "only meaningful over TLS"
    assert plain.get("/v1/matters").headers["cache-control"] == "no-store"
    secure = app(tls=True)
    over_tls = TestClient(secure, base_url="https://localhost")
    assert "max-age=31536000" in over_tls.get("/health").headers["strict-transport-security"]
    cookie = Browser(secure, A, PHRASE[A], base="https://localhost").login.headers["set-cookie"]
    assert cookie.startswith("__Host-eli_legal_session=") and "Secure" in cookie


def test_the_page_loads_nothing_from_anywhere_else_and_has_no_inline_script(served):
    _sv, _mid, _rid, app = served
    client = TestClient(app(), base_url=LOCAL)
    page = client.get("/").text
    assert '<script src="/assets/app.js" defer></script>' in page and page.count("<script") == 1
    assert "http://" not in page and "https://" not in page and "style=" not in page
    script = client.get("/assets/app.js").text
    assert "innerHTML" not in script and "eval(" not in script and "localStorage" not in script
    assert "https://" not in script.replace("http://www.w3.org/2000/svg", "")
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404
    assert TestClient(app(api_docs=True), base_url=LOCAL).get("/openapi.json").status_code == 200


def test_a_request_under_another_host_name_is_refused(served):
    _sv, _mid, _rid, app = served
    application = app(allowed_hosts=("localhost", "legal.chambers.example"))
    assert (
        TestClient(application, base_url="http://attacker.example").get("/health").status_code
        == 400
    )
    assert TestClient(application, base_url="http://127.0.0.1").get("/health").status_code == 400
    assert (
        TestClient(application, base_url="http://legal.chambers.example:8443")
        .get("/health")
        .status_code
        == 200
    )


def test_a_request_from_another_site_cannot_change_anything(served):
    _sv, mid, _rid, app = served
    browser = Browser(app(), A, PHRASE[A])
    body = {"question": "When was the notice received?"}
    url = f"/v1/matters/{mid}/chat"
    for hostile in (
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
    ):
        refused = browser.send("POST", url, body, headers=hostile)
        assert refused.status_code == 403 and refused.json()["error"] == "CrossOrigin", hostile
    own = {"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"}
    assert browser.send("POST", url, body, headers=own).status_code == 200


def test_bodies_are_bounded_before_they_are_read(served):
    _sv, mid, _rid, app = served
    browser = Browser(app(max_json_bytes=2000, max_upload_bytes=5000), S, PHRASE[S])
    big = browser.send("POST", f"/v1/matters/{mid}/chat", {"question": "x" * 3000})
    assert big.status_code == 413
    upload = f"/v1/matters/{mid}/documents?filename=a.txt"
    assert browser.send("POST", upload, content=b"y" * 4000).status_code == 201, (
        "uploads have their own limit"
    )
    assert browser.send("POST", upload, content=b"y" * 6000).status_code == 413

    def chunks():
        yield b"y" * 10

    unbounded = browser.send("POST", upload, content=chunks())
    assert unbounded.status_code == 411, "a body of undeclared length is refused"


def test_sign_in_attempts_are_rate_limited_per_client(served):
    _sv, _mid, _rid, app = served
    client = TestClient(app(login_attempts_per_minute=4), base_url=LOCAL)
    codes = [
        client.post(
            "/v1/auth/login", json={"user_id": f"nobody{i}", "passphrase": "x" * 12}
        ).status_code
        for i in range(6)
    ]
    assert codes == [401, 401, 401, 401, 429, 429]
    limited = client.post("/v1/auth/login", json={"user_id": A, "passphrase": PHRASE[A]})
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0
    assert client.get("/health").status_code == 200, "only sign-in is slowed"
    limiter = RateLimiter()
    assert [limiter.allow("b", "c", 2, now=t) > 0 for t in (0, 1, 2, 61, 62)] == [
        False,
        False,
        True,
        False,
        False,
    ]


def test_repeated_wrong_passphrases_lock_the_account_until_an_administrator_unlocks_it(served):
    sv, _mid, _rid, app = served
    application = app()
    client = TestClient(application, base_url=LOCAL)
    attempt = {"user_id": S, "passphrase": "definitely not it"}
    assert [client.post("/v1/auth/login", json=attempt).status_code for _ in range(5)] == [401] * 5
    locked = client.post("/v1/auth/login", json={"user_id": S, "passphrase": PHRASE[S]})
    assert locked.status_code == 423 and locked.json()["error"] == "AccountLocked"
    outcomes = [
        e["outcome"] for e in sv.ctx.audit.events(matter_id="-") if e["event_type"] == "sign_in"
    ]
    assert "account_locked" in outcomes and outcomes[-1] == "refused_locked"
    admin = Browser(application, "admin", PHRASE["admin"])
    listed = {u["user_id"]: u for u in admin.get("/v1/users").json()}
    assert listed[S]["locked_until"] and not listed[A]["locked_until"]
    assert admin.decide("POST", f"/v1/users/{S}/unlock").status_code == 204
    assert Browser(application, S, PHRASE[S]).get("/v1/matters").status_code == 200
    assert (
        Browser(application, A, PHRASE[A]).decide("POST", f"/v1/users/{S}/unlock").status_code
        == 403
    )


def test_a_wrong_passphrase_at_a_decision_also_counts_toward_the_lock(served):
    _sv, mid, rid, app = served
    browser = Browser(app(), A, PHRASE[A])
    hold = browser.get(f"/v1/matters/{mid}/runs/{rid}/holds").json()[0]["hold_id"]
    url, body = (
        f"/v1/matters/{mid}/holds/{hold}/resolve",
        {"action": "exclude", "reason": "Guessing at the passphrase."},
    )
    guesses = [
        browser.send(
            "POST", url, body, headers={"X-ELI-Passphrase": f"guess number {i}"}
        ).status_code
        for i in range(6)
    ]
    assert guesses == [401, 401, 401, 401, 401, 423]
    assert len(browser.get(f"/v1/matters/{mid}/runs/{rid}/holds").json()) == 6, (
        "nothing was decided"
    )


def test_a_second_factor_can_be_set_up_and_is_then_needed_at_every_sign_in(served):
    sv, _mid, _rid, app = served
    application = app()
    browser = Browser(application, A, PHRASE[A])
    assert browser.send("POST", "/v1/auth/second-factor/begin").json()["error"] == "StepUpRequired"
    begun = browser.decide("POST", "/v1/auth/second-factor/begin").json()
    assert begun["uri"].startswith(
        "otpauth://totp/ELI%20Legal%3Aarb.keane?secret=" + begun["secret"]
    )
    wrong = browser.send("POST", "/v1/auth/second-factor/confirm", {"code": "000000"})
    assert wrong.status_code == 401 and not sv.users.has_second_factor(A)
    code = totp.code_at(begun["secret"], totp.step_at())
    assert browser.send("POST", "/v1/auth/second-factor/confirm", {"code": code}).status_code == 204
    client = TestClient(application, base_url=LOCAL)
    without = client.post("/v1/auth/login", json={"user_id": A, "passphrase": PHRASE[A]})
    assert without.status_code == 401 and without.json()["error"] == "SecondFactorRequired"
    replayed = client.post(
        "/v1/auth/login", json={"user_id": A, "passphrase": PHRASE[A], "code": code}
    )
    assert replayed.status_code == 401, "a code that has been used once is not accepted again"
    fresh = totp.code_at(begun["secret"], totp.step_at() + 1)
    again = Browser(application, A, PHRASE[A], code=fresh)
    assert again.get("/v1/auth/session").json()["user"]["second_factor"] is True
    outcomes = [e["outcome"] for e in sv.ctx.audit.events(matter_id="-")]
    assert "second_factor_enabled" in outcomes and "signed_in_two_factor" in outcomes
    admin = Browser(application, "admin", PHRASE["admin"])
    assert admin.decide("DELETE", f"/v1/users/{A}/second-factor").status_code == 204
    assert again.get("/v1/matters").status_code == 401, (
        "removing a factor ends that person's sessions"
    )
    assert Browser(application, A, PHRASE[A]).get("/v1/matters").status_code == 200


def test_one_time_codes_follow_the_standard(served):
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # RFC 6238 test secret "12345678901234567890"
    assert (
        totp.code_at(secret, 59 // 30) == "287082"
        and totp.code_at(secret, 1111111109 // 30) == "081804"
    )
    assert totp.verify(secret, "287082", at=59) == 1 and totp.verify(secret, "287 082", at=80) == 1
    assert totp.verify(secret, "287082", at=59, last_step=1) is None
    assert (
        totp.verify(secret, "287082", at=200) is None
        and totp.verify(secret, "28708", at=59) is None
    )


def test_where_a_second_factor_is_required_nothing_else_is_reachable_without_one(served):
    _sv, mid, _rid, app = served
    browser = Browser(app(require_second_factor=True), A, PHRASE[A])
    assert browser.login.json()["second_factor_required"] is True
    blocked = browser.get("/v1/matters")
    assert blocked.status_code == 403 and "second factor" in blocked.json()["detail"]
    assert browser.get(f"/v1/matters/{mid}").status_code == 403
    assert browser.get("/v1/auth/session").status_code == 200
    begun = browser.decide("POST", "/v1/auth/second-factor/begin").json()
    code = totp.code_at(begun["secret"], totp.step_at())
    assert browser.send("POST", "/v1/auth/second-factor/confirm", {"code": code}).status_code == 204
    assert browser.get("/v1/matters").status_code == 200


def test_a_refusal_never_repeats_what_was_sent(served):
    _sv, _mid, _rid, app = served
    client = TestClient(app(), base_url=LOCAL)
    secret = "correct horse battery staple " * 60
    answer = client.post(
        "/v1/auth/login", json={"user_id": A, "passphrase": secret, "extra": "field"}
    )
    assert answer.status_code == 422 and answer.json()["error"] == "InvalidInput"
    assert "correct horse" not in answer.text and "passphrase" in answer.json()["detail"]


def test_the_server_cannot_be_used_to_read_the_machine_or_call_out(served):
    sv, _mid, _rid, app = served
    admin = Browser(app(), "admin", PHRASE["admin"])
    for folder in ("../..", "/etc", "..\\..", "missing"):
        escaped = admin.decide(
            "POST", "/v1/sources/examplia-law-reports/import", {"directory": folder}
        )
        assert escaped.status_code == 422 and "import area" in escaped.json()["detail"], folder
    for url in (
        "http://example.com/v1",
        "http://169.254.169.254/latest",
        "http://10.0.0.5:11434/v1",
    ):
        called = admin.get(f"/v1/config/models?url={url}")
        assert called.status_code == 422 and "this machine" in called.json()["detail"], url
    remote = {
        "backend": "openai_compat",
        "url": "https://api.example.com/v1",
        "model": "some-model",
    }
    refused = admin.decide("POST", "/v1/config/model", remote)
    assert refused.status_code in (400, 403, 422) and "api.example.com" in refused.json()["detail"]
    assert sv.config.current()["backend"] == "none"
    assert Browser(app(), A, PHRASE[A]).get("/v1/config/models").status_code == 403


def test_a_run_started_through_the_server_executes_in_the_background_as_that_person(served):
    sv, mid, _rid, app = served
    application = app()
    browser = Browser(application, S, PHRASE[S])
    started = browser.decide("POST", f"/v1/matters/{mid}/runs")
    assert started.status_code == 202
    assert application.state.jobs.wait()
    run = browser.get(f"/v1/matters/{mid}/runs/{started.json()['run_id']}").json()
    assert run["status"] == "held" and run["started_by"] == S
    begun = [
        e for e in sv.ctx.audit.events(matter_id=mid, run_id=run["run_id"]) if e["actor_id"] == S
    ]
    assert begun and {e["payload"]["auth"] for e in begun} <= {"web-session", "web-session+step-up"}


def test_the_server_will_not_listen_beyond_this_machine_without_tls(tmp_path, monkeypatch):
    from eli_legal.settings import Settings

    settings = Settings(_env_file=None, audit_key_file=tmp_path / "secrets" / "audit.key")
    parser = argparse.ArgumentParser()
    serve.add_arguments(parser)
    local, _, _ = serve.build_config(parser.parse_args([]), settings)
    assert not local.exposed and not local.problems() and local.require_second_factor is False
    assert local.cookie_name == "eli_legal_session"
    exposed, cert, key = serve.build_config(parser.parse_args(["--lan"]), settings)
    assert exposed.exposed and cert is None and "without TLS" in exposed.problems()[0]
    proxied, _, _ = serve.build_config(parser.parse_args(["--lan", "--behind-proxy"]), settings)
    assert "--trusted-proxy" in proxied.problems()[0]
    signed, cert, key = serve.build_config(
        parser.parse_args(["--lan", "--self-signed", "--allowed-host", "Legal.Chambers.Example"]),
        settings,
    )
    assert not signed.problems() and signed.tls and signed.require_second_factor is True
    assert signed.cookie_name == "__Host-eli_legal_session"
    assert "legal.chambers.example" in signed.allowed_hosts and "localhost" in signed.allowed_hosts
    assert cert.is_file() and key.is_file() and oct(key.stat().st_mode & 0o777) == "0o600"
    assert len(tls.fingerprint(cert).split(":")) == 32
    running = serve.hardened(lambda *a: None, signed, cert, key)
    running.load()  # loads the pair exactly as the server will
    assert running.ssl.minimum_version == ssl.TLSVersion.TLSv1_2
    options = serve.uvicorn_options(signed, cert, key)
    assert (
        options["server_header"] is False
        and options["workers"] == 1
        and options["proxy_headers"] is False
    )
    assert "certificate SHA-256 fingerprint" in serve.banner(signed, cert)
    opted_out, _, _ = serve.build_config(
        parser.parse_args(["--lan", "--self-signed", "--require-second-factor", "no"]), settings
    )
    assert opted_out.require_second_factor is False
