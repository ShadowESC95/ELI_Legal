"""The command line: status, roles on a matter, compliance and the routine checks, as real
invocations (no harness: every command signs in, and decisions ask for the passphrase)."""

import io
import json

import pytest

from eli_legal import cli
from eli_legal.security import authn

ADMIN_PHRASE = "administrator phrase"


def _cli(monkeypatch, argv, stdin=""):
    authn.remove_harness()
    authn.clear()
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    try:
        return cli.main(["--passphrase-stdin", *argv])
    except SystemExit as exc:
        return exc.code


@pytest.fixture
def signed_in(tmp_path, monkeypatch):
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
    assert (
        _cli(monkeypatch, ["init", "--admin", "admin", "--retention-later"], f"{ADMIN_PHRASE}\n")
        == 0
    )
    assert _cli(monkeypatch, ["login", "admin"], f"{ADMIN_PHRASE}\n") == 0
    return tmp_path


def test_status_compliance_and_checks_from_the_command_line(signed_in, monkeypatch, capsys):
    phrase = f"{ADMIN_PHRASE}\n"
    run = lambda *argv, stdin="": _cli(monkeypatch, list(argv), stdin)  # noqa: E731
    assert (
        run("user", "add", "clerk", "--name", "Clerk", "--role", "tribunal_secretary", stdin=phrase)
        == 0
    )
    capsys.readouterr()
    made = run(
        "matter", "create", "--name", "A v B", "--purpose", "Bench memorandum",
        "--jurisdiction", "XX", "--profile", "adjudicator",
        "--party", "A Ltd:claimant", "--party", "B Ltd:respondent",
        "--member", "clerk:assistant:A Ltd",
    )  # fmt: skip
    assert made == 0
    mid = capsys.readouterr().out.strip().splitlines()[-1]
    assert run("matter", "people", mid) == 0
    people = capsys.readouterr().out
    assert "Lead" in people and "Assistant" in people and "acts for A Ltd" in people
    assert run("matter", "role", mid, "clerk", "--role", "observer", "--no-party") == 0
    assert run("matter", "people", mid) == 0 and "Observer" in capsys.readouterr().out
    assert run("status", mid) == 0
    status = capsys.readouterr().out
    assert "You are lead on this matter" in status and "Name at least one reviewer" in status
    assert "Add the documents" in status
    assert run("compliance", "show") == 0 and "requirements met" in capsys.readouterr().out
    assert run("compliance", "form", "OA-01") == 0
    questions = json.loads(capsys.readouterr().out)
    answers = signed_in / "answers.json"
    answers.write_text(json.dumps({k: "Answered for the test." for k in questions}))
    assert run("compliance", "record", "OA-01", "--answers", str(answers), stdin=phrase) == 0
    assert "completed" in capsys.readouterr().out
    assert run("compliance", "record", "OA-04", stdin="the wrong passphrase\n") == 2
    assert "AuthenticationFailed" in capsys.readouterr().err
    assert (
        run("compliance", "retention", "--audit-days", "30", "--closed-days", "0", stdin=phrase)
        == 2
    )
    assert "six months" in capsys.readouterr().err
    assert run("checks", "run", "--as-system") in (0, 1)
    out = capsys.readouterr().out
    assert "routine checks" in out.lower() or "need" in out
    assert run("checks", "show") in (0, 1) and "Audit trail intact" in capsys.readouterr().out
    assert (
        run("framework", "current", "gdpr", "--note", "Checked against the text.", stdin=phrase)
        == 0
    )
    assert "checked against the official text" in capsys.readouterr().out
