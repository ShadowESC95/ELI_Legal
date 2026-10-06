"""Identity. These tests remove the harness the rest of the suite runs under, so the services
are called the way a front end would call them: with no identity unless one was established."""

import io
import os
from datetime import timedelta

import pytest

from eli_legal import cli
from eli_legal.domain.enums import ReviewDecision
from eli_legal.domain.errors import AuthenticationFailed
from eli_legal.domain.models import utcnow
from eli_legal.security import authn

A, S = "arb.keane", "sec.byrne"


@pytest.fixture
def strict(held_run):
    sv, mid, rid = held_run
    sv.users.set_passphrase(actor_id="admin", user_id=A, new="arbitrator passphrase")
    sv.users.set_passphrase(actor_id="admin", user_id=S, new="secretary passphrase")
    authn.remove_harness()
    authn.clear()
    return sv, mid, rid


def test_a_name_alone_is_refused_everywhere_and_the_attempt_is_recorded(strict):
    sv, mid, rid = strict
    calls = [
        lambda: sv.matters.get(mid, A),
        lambda: sv.matters.list_for(A),
        lambda: sv.runs.start(mid, actor_id=S),
        lambda: sv.runs.summary(mid, rid, actor_id=A),
        lambda: sv.verification.claims(mid, rid, actor_id=A),
        lambda: sv.chat.ask(mid, actor_id=A, question="/status"),
        lambda: sv.evidence_pack(mid, rid, actor_id=A),
        lambda: sv.monitoring.snapshot(actor_id="gov.hale"),
        lambda: sv.sources.import_corpus("examplia-law-reports", ".", actor_id="admin"),
    ]
    for call in calls:
        with pytest.raises(AuthenticationFailed, match="no identity has been established"):
            call()
    denied = [
        e
        for e in sv.ctx.audit.events()
        if e["event_type"] == "access_denied"
        and e["payload"]["reason"] == "identity_not_established"
    ]
    assert len(denied) >= len(calls) - 1
    assert all(e["payload"]["auth"] == "unauthenticated" for e in denied)


def test_a_signed_in_person_cannot_act_as_someone_else(strict):
    sv, mid, rid = strict
    with authn.established(S, "cli-session"):
        assert sv.matters.get(mid, S).matter_id == mid
        with pytest.raises(
            AuthenticationFailed, match="belongs to 'sec.byrne'; it cannot act as 'arb.keane'"
        ):
            sv.matters.get(mid, A)
        with pytest.raises(AuthenticationFailed):
            sv.runs.resume(mid, rid, actor_id=A, reason="restarting as the arbitrator")


def test_a_decision_needs_the_passphrase_again_even_when_signed_in(strict):
    sv, mid, rid = strict
    hold = None
    with authn.established(A, "cli-session"):
        hold = sv.holds.list(mid, rid, actor_id=A)[0]
        report = sv.runs.summary(mid, rid, actor_id=A)["report"]
        decisions = [
            lambda: sv.holds.resolve(
                mid, hold.hold_id, actor_id=A, action="exclude", reason="Not to be relied on."
            ),
            lambda: sv.verification.record_human_result(
                mid,
                hold.subject_id,
                actor_id=A,
                verification_type="current_law",
                status=__import__(
                    "eli_legal.domain.enums", fromlist=["x"]
                ).VerificationStatus.VERIFIED,
                reason="Checked the treatment table.",
            ),
            lambda: sv.reviews.decide(
                mid,
                rid,
                actor_id=A,
                decision=ReviewDecision.REJECT,
                reasons="Rejecting this draft.",
                report_hash=report["sha256"],
            ),
            lambda: sv.runs.resume(mid, rid, actor_id=A, reason="Restart after corrections."),
            lambda: sv.matters.close(
                mid, actor_id=A, purge_content=False, reason="Closing the matter."
            ),
        ]
        for decide in decisions:
            with pytest.raises(AuthenticationFailed, match="confirm your passphrase"):
                decide()
        with authn.stepped_up():
            sv.holds.resolve(
                mid, hold.hold_id, actor_id=A, action="exclude", reason="Not to be relied on."
            )
    event = [e for e in sv.ctx.audit.events(matter_id=mid) if e["event_type"] == "hold_resolved"][
        -1
    ]
    assert event["payload"]["auth"] == "cli-session+step-up"
    assert sv.runs.stop.__name__ == "stop"  # stopping is deliberately not behind step-up


def test_every_audit_event_says_how_identity_was_established(lifecycle):
    from eli_legal.application.services import build_services
    from eli_legal.demo import build_demo_workspace
    from eli_legal.demo_run import demo_settings

    sv = build_services(
        demo_settings(lifecycle.root, build_demo_workspace(lifecycle.root / "demo")),
        install_network_guard=False,
    )
    events = list(sv.ctx.audit.events())
    assert events and all("auth" in e["payload"] for e in events)
    methods = {e["payload"]["auth"] for e in events}
    assert "demo-harness+step-up" in methods
    # another test may since have used this workspace under the test harness; neither harness
    # can ever be recorded as a person who proved who they were
    assert methods <= {"demo-harness+step-up", "test-harness+step-up", "system"}
    assert not any(m.startswith(("cli-", "gui-", "api-", "eli-host")) for m in methods)


def test_sessions_expire_are_revocable_and_end_when_the_passphrase_changes(strict):
    sv, _mid, _rid = strict
    token = sv.users.login(A, "arbitrator passphrase", method="cli-session", hours=8)
    assert sv.users.session_user(token).user_id == A
    with pytest.raises(AuthenticationFailed):
        sv.users.login(A, "not the passphrase", method="cli-session")
    with pytest.raises(AuthenticationFailed):
        sv.users.session_user("els_not_a_real_token")
    expired = "els_expired_token"
    sv.ctx.store.add_session(expired, A, "cli-session", utcnow() - timedelta(minutes=1))
    with pytest.raises(AuthenticationFailed, match="session has ended"):
        sv.users.session_user(expired)
    sv.users.logout(token)
    with pytest.raises(AuthenticationFailed):
        sv.users.session_user(token)
    second = sv.users.login(A, "arbitrator passphrase", method="cli-session")
    with authn.established(A, "cli-session"):
        sv.users.set_passphrase(
            actor_id=A, user_id=A, new="a brand new passphrase", current="arbitrator passphrase"
        )
    with pytest.raises(AuthenticationFailed):
        sv.users.session_user(second)
    stored = sv.ctx.store._all("SELECT token_hash FROM sessions")
    assert all(len(row[0]) == 64 and not row[0].startswith("els_") for row in stored), (
        "only hashes are stored"
    )


# ── the command line ─────────────────────────────────────────────────────────
def _cli(monkeypatch, tmp_path, argv, stdin=""):
    """Run the CLI as a real invocation: fresh process state, no harness, no inherited identity."""
    authn.remove_harness()
    authn.clear()
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    try:
        return cli.main(["--passphrase-stdin", *argv])
    except SystemExit as exc:
        return exc.code


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    from eli_legal.demo import build_demo_workspace

    ws = build_demo_workspace(tmp_path / "demo")
    for name, value in {
        "DB_PATH": tmp_path / "data/eli.sqlite3",
        "AUDIT_DB_PATH": tmp_path / "data/audit.sqlite3",
        "AUDIT_KEY_FILE": tmp_path / "secrets/audit_hmac.key",
        "DATA_DIR": tmp_path / "data/matters",
        "ARTIFACTS_DIR": tmp_path / "artifacts",
        "JURISDICTIONS_DIR": ws.jurisdictions,
    }.items():
        monkeypatch.setenv(f"ELI_LEGAL_{name}", str(value))
    return tmp_path


def test_the_command_line_does_nothing_in_anyones_name_without_a_sign_in(
    workspace, monkeypatch, capsys
):
    assert _cli(monkeypatch, workspace, ["init", "--admin", "admin"], "administrator phrase\n") == 0
    assert (
        _cli(monkeypatch, workspace, ["matter", "list"])
        == "not signed in: run  eli-legal login USER"
    )
    assert _cli(monkeypatch, workspace, ["whoami"]) == "not signed in: run  eli-legal login USER"
    assert _cli(monkeypatch, workspace, ["login", "admin"], "the wrong phrase\n") == 2
    assert "AuthenticationFailed" in capsys.readouterr().err
    assert _cli(monkeypatch, workspace, ["login", "admin"], "administrator phrase\n") == 0
    session = next((workspace / "secrets").glob(".session_*"))
    if os.name != "nt":
        assert oct(session.stat().st_mode & 0o777) == "0o600"
    assert _cli(monkeypatch, workspace, ["whoami"]) == 0
    assert "admin" in capsys.readouterr().out
    # an environment variable no longer makes you anyone
    monkeypatch.setenv("ELI_LEGAL_ACTOR", "j.okoro")
    assert _cli(monkeypatch, workspace, ["whoami"]) == 0 and "admin" in capsys.readouterr().out
    assert _cli(monkeypatch, workspace, ["logout"]) == 0
    assert (
        _cli(monkeypatch, workspace, ["matter", "list"])
        == "not signed in: run  eli-legal login USER"
    )


def test_a_decision_at_the_command_line_asks_for_the_passphrase_again(
    workspace, monkeypatch, capsys
):
    _cli(monkeypatch, workspace, ["init", "--admin", "admin"], "administrator phrase\n")
    _cli(monkeypatch, workspace, ["login", "admin"], "administrator phrase\n")
    add = ["user", "add", "j.okoro", "--name", "Judge Okoro", "--role", "judge"]
    assert _cli(monkeypatch, workspace, add, "not my passphrase\n") == 2
    assert "AuthenticationFailed" in capsys.readouterr().err
    assert _cli(monkeypatch, workspace, add, "administrator phrase\n") == 0
    assert "set their first passphrase" in capsys.readouterr().out
    # the judge cannot sign in until an administrator has set a first passphrase
    assert _cli(monkeypatch, workspace, ["login", "j.okoro"], "anything at all\n") == 2
    assert (
        _cli(
            monkeypatch,
            workspace,
            ["passphrase", "j.okoro"],
            "administrator phrase\njudge first phrase\n",
        )
        == 0
    )
    assert _cli(monkeypatch, workspace, ["login", "j.okoro"], "judge first phrase\n") == 0
    capsys.readouterr()
    assert _cli(monkeypatch, workspace, ["whoami"]) == 0 and "j.okoro" in capsys.readouterr().out
    # signed in as the judge: no user administration, whatever passphrase is typed
    assert (
        _cli(
            monkeypatch,
            workspace,
            ["user", "add", "x.y", "--role", "judge"],
            "judge first phrase\n",
        )
        == 2
    )
    assert "PolicyDenied" in capsys.readouterr().err
