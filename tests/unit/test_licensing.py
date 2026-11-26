"""An installed copy of ELI Legal runs with a licence: a key of its own, or an ELI v3 key that
includes it, from the folder every ELI product shares."""

from __future__ import annotations

import base64
import json
import sys

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from eli_sdk import InvalidKey

from eli_legal import cli, licensing


class _Issuer:
    def __init__(self) -> None:
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )

    def key(self, **fields) -> str:
        body = {
            "version": 1 if fields.get("product", "eli") == "eli" else 2,
            "license_id": "t",
            "tier": "pro",
            "seats": 1,
            "issued_at": "2026-10-15T00:00:00+00:00",
        }
        body.update(fields)
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        enc = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")  # noqa: E731
        return f"ELIV3-{enc(raw)}.{enc(self.private.sign(raw))}"


@pytest.fixture()
def issuer(tmp_path, monkeypatch) -> _Issuer:
    made = _Issuer()
    monkeypatch.setattr(licensing, "_public_key", made.public)
    monkeypatch.setattr(licensing, "_hosted", False)
    monkeypatch.setenv("ELI_KEYS_DIR", str(tmp_path / "keys"))
    monkeypatch.delenv("ELI_LEGAL_REQUIRE_LICENCE", raising=False)
    return made


def test_an_installed_copy_needs_a_licence_and_a_checkout_does_not(issuer, monkeypatch):
    assert licensing.required() is False
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert licensing.required() is True
    licensing.hosted_by_eli()
    assert licensing.required() is False, "ELI v3 checked the licence before opening it"


def test_its_own_key_licenses_it(issuer):
    lic = licensing.activate(issuer.key(product="legal"))
    assert lic.product == "legal" and licensing.status().granted


def test_an_eli_v3_key_that_includes_it_licenses_it(issuer):
    licensing.activate(issuer.key(includes={"legal": 1}))
    got = licensing.status()
    assert got.granted and got.included


def test_an_eli_v3_key_without_it_is_kept_for_eli_but_refused_here(issuer):
    with pytest.raises(InvalidKey, match="no ELI Legal licence"):
        licensing.activate(issuer.key())
    assert (licensing.store().directory / "eli.key").is_file()


def test_a_key_for_another_line_does_not_open_this_one(issuer, monkeypatch):
    monkeypatch.setattr(licensing, "__version__", "2.0.0")
    with pytest.raises(InvalidKey, match="needs an upgrade"):
        licensing.activate(issuer.key(product="legal", major_version=1))


def test_removing_it(issuer):
    licensing.activate(issuer.key(product="legal"))
    assert licensing.remove() and not licensing.status().granted


def test_the_command_line_will_not_run_unlicensed_once_the_trial_is_spent(
    issuer, monkeypatch, capsys
):
    monkeypatch.setenv("ELI_LEGAL_REQUIRE_LICENCE", "1")
    monkeypatch.setattr(cli, "cmd_matter", lambda args: 0)
    monkeypatch.setattr(licensing, "_used_before", lambda: True)  # used here, trial record gone
    assert cli.main(["matter", "list"]) == 3
    err = capsys.readouterr().err
    assert "eli-legal licence activate" in err and "eli-legal licence buy" in err
    assert "used on this machine before" in err
    assert cli.main(["licence", "activate", issuer.key(product="legal")]) == 0
    assert cli.main(["matter", "list"]) == 0


# ── the trial ────────────────────────────────────────────────────────────────


def test_an_installed_copy_runs_a_seven_day_trial_and_takes_a_key_any_time(issuer, monkeypatch):
    monkeypatch.setenv("ELI_LEGAL_REQUIRE_LICENCE", "1")
    assert licensing.standing().granted is False, "nothing is started by looking"
    assert licensing.allowed(), "first use starts the trial"
    st = licensing.standing()
    assert st.on_trial and st.days_left == 7 and not st.real_matters
    assert "practice matters only" in st.describe()
    assert licensing.covers_real_matters() is False
    licensing.activate(issuer.key(product="legal"))  # during the trial
    st = licensing.standing()
    assert st.granted and not st.on_trial and st.real_matters


def test_deleting_the_trial_record_does_not_restart_it(issuer, monkeypatch, tmp_path):
    monkeypatch.setenv("ELI_LEGAL_REQUIRE_LICENCE", "1")
    assert licensing.allowed()
    data = tmp_path / "home" / "data" / "eli-legal" / "data"
    data.mkdir(parents=True)
    (data / "eli_legal.sqlite3").write_bytes(b"cases")  # ELI Legal was used
    for path in licensing.trial().paths():
        path.unlink()
    monkeypatch.setenv(
        "ELI_LEGAL_HOME", str(tmp_path / "somewhere-new")
    )  # nor does moving its data
    assert not licensing.allowed()
    assert "used on this machine before" in licensing.standing().reason


def test_a_trial_key_that_ended_starts_no_second_trial(issuer, monkeypatch):
    monkeypatch.setenv("ELI_LEGAL_REQUIRE_LICENCE", "1")
    keys = licensing.store().directory
    keys.mkdir(parents=True, exist_ok=True)
    (keys / "legal.key").write_text(
        issuer.key(product="legal", tier="trial", expires_at="2026-01-01T00:00:00+00:00")
    )
    assert not licensing.allowed()
    assert "trial has expired" in licensing.standing().reason


def test_a_trial_covers_practice_matters_only(issuer, monkeypatch, demo):
    from eli_legal.application.deployment_service import why_not
    from eli_legal.domain.enums import Profile
    from eli_legal.domain.errors import PolicyDenied

    sv, mid = demo
    monkeypatch.setenv("ELI_LEGAL_REQUIRE_LICENCE", "1")
    assert licensing.allowed() and licensing.standing().on_trial
    with pytest.raises(PolicyDenied, match="practice matters only"):
        sv.matters.create(
            actor_id="arb.keane", name="Real v Matter", purpose="Bench memorandum",
            jurisdiction="XX", profile=Profile.ADJUDICATOR, real=True,
        )  # fmt: skip
    practice = sv.matters.create(
        actor_id="arb.keane", name="Practice v Matter", purpose="Training",
        jurisdiction="XX", profile=Profile.ADJUDICATOR,
    )  # fmt: skip
    assert not practice.real
    matter = sv.matters.get(mid, "arb.keane")
    matter.real = True  # a real matter already on this machine: its work stops on a trial
    assert "practice matters only" in why_not(sv.ctx, matter)[0]


def test_buying_from_the_command_line_activates_the_key_by_itself(issuer, monkeypatch, capsys):
    import webbrowser

    from eli_sdk import store as eli_store

    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", opened.append)
    key = issuer.key(product="legal", license_id="bought")
    monkeypatch.setattr(eli_store, "collect", lambda claim, store=None: [key])
    assert cli.main(["licence", "buy"]) == 0
    assert opened and "/?product=legal&claim=" in opened[0]
    assert "activated: ELI Legal " in capsys.readouterr().out
    assert licensing.status().license.license_id == "bought"


def test_the_licence_commands_work_without_one(issuer, monkeypatch, capsys):
    monkeypatch.setenv("ELI_LEGAL_REQUIRE_LICENCE", "1")
    assert cli.main(["licence"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["licensed"] is False and shown["required"] is True
    assert cli.main(["licence", "activate", "ELIV3-not.akey"]) == 2
