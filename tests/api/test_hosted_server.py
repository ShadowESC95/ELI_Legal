"""The server started from the desktop application: only an administrator or a judge may start
or stop it, with the passphrase again; it is the same hardened server; it carries no identity
from the desktop into a request; and each start and stop is in the audit trail."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request

import pytest

from eli_legal.api.hosting import HostedServer
from eli_legal.api.serve import build_config
from eli_legal.domain.errors import AuthenticationFailed, PolicyDenied
from eli_legal.security import authn

ARB, SEC = "arb.keane", "sec.byrne"


def _get(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:  # noqa: S310 - a local test server
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_only_an_administrator_or_a_judge_starts_the_server(demo):
    sv, _mid = demo
    for uid, roles in (
        ("sol.x", ["solicitor"]),
        ("gov.x", ["governance_officer"]),
        ("aud.x", ["auditor"]),
        ("pip.x", ["self_represented"]),
    ):
        sv.users.add_user(actor_id="admin", user_id=uid, display_name=uid, roles=roles)
        with pytest.raises(PolicyDenied):
            HostedServer(sv).start(actor_id=uid, port=0)
    with pytest.raises(PolicyDenied):
        HostedServer(sv).start(actor_id=SEC, port=0)  # the registrar runs tasks, not the server
    denied = [e for e in sv.ctx.audit.events() if e["event_type"] == "access_denied"]
    assert {e["actor_id"] for e in denied} >= {"sol.x", "gov.x", "aud.x", "pip.x", SEC}


def test_starting_and_stopping_need_the_passphrase_again():
    authn.remove_harness()
    try:
        with authn.established(ARB, "gui-passphrase"):
            with pytest.raises(AuthenticationFailed):
                authn.require_step_up(ARB, "start the server")
    finally:
        authn.install_harness("test-harness")


def test_a_judge_starts_it_it_answers_and_it_stops_and_both_are_recorded(demo):
    sv, _mid = demo
    host = HostedServer(sv)
    state = host.start(actor_id=ARB, port=0)
    try:
        assert state["running"] and not state["exposed"] and state["url"].startswith("http://")
        status, body = _get(state["url"] + "health")
        assert status == 200 and body["status"] == "ok"
        status, body = _get(state["url"] + "v1/matters")
        assert status == 401, "a request carries no identity from the desktop"
        with pytest.raises(Exception, match="already running"):
            host.start(actor_id=ARB, port=0)
    finally:
        host.stop(actor_id=ARB)
    assert not host.running
    with pytest.raises(OSError):
        urllib.request.urlopen(state["url"] + "health", timeout=2)  # noqa: S310
    told = [e for e in sv.ctx.audit.events() if e["object_type"] == "server"]
    assert [(e["event_type"], e["actor_id"]) for e in told] == [
        ("server_started", ARB),
        ("server_stopped", ARB),
    ]
    assert {k: told[0]["payload"][k] for k in ("port", "exposed", "tls", "second_factor")} == {
        "port": state["port"],
        "exposed": False,
        "tls": False,
        "second_factor": False,
    }
    assert sv.ctx.audit.report().ok


def test_for_other_computers_it_is_always_tls_with_a_second_factor(demo, tmp_path):
    sv, _mid = demo
    args = argparse.Namespace(
        host=None,
        port=0,
        lan=True,
        tls_cert=None,
        tls_key=None,
        self_signed=True,
        behind_proxy=False,
        trusted_proxy=[],
        allowed_host=[],
        require_second_factor=None,
        api_docs=False,
    )
    config, cert, key = build_config(args, sv.ctx.settings)
    assert config.exposed and config.tls and config.require_second_factor
    assert cert is not None and cert.exists() and key is not None and key.exists()
    assert config.problems() == []


def test_closing_the_window_stops_a_server_it_started(demo):
    sv, _mid = demo
    host = HostedServer(sv)
    state = host.start(actor_id="admin", port=0)  # the first administrator
    host.stop(actor_id="system")
    assert not host.running
    stopped = [e for e in sv.ctx.audit.events() if e["event_type"] == "server_stopped"]
    assert stopped[-1]["actor_id"] == "system" and stopped[-1]["payload"]["port"] == state["port"]
