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


def test_the_command_line_will_not_run_unlicensed(issuer, monkeypatch, capsys):
    monkeypatch.setenv("ELI_LEGAL_REQUIRE_LICENCE", "1")
    monkeypatch.setattr(cli, "cmd_matter", lambda args: 0)
    assert cli.main(["matter", "list"]) == 3
    assert "eli-legal licence activate" in capsys.readouterr().err
    assert cli.main(["licence", "activate", issuer.key(product="legal")]) == 0
    assert cli.main(["matter", "list"]) == 0


def test_the_licence_commands_work_without_one(issuer, monkeypatch, capsys):
    monkeypatch.setenv("ELI_LEGAL_REQUIRE_LICENCE", "1")
    assert cli.main(["licence"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["licensed"] is False and shown["required"] is True
    assert cli.main(["licence", "activate", "ELIV3-not.akey"]) == 2
