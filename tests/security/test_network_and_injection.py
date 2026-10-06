import errno
import socket

import pytest

from eli_legal.adapters.inference.local import OpenAICompatInference
from eli_legal.adapters.local.network import NetworkGuard
from eli_legal.domain.errors import NetworkDenied
from tests.conftest import FakeInference

UNROUTABLE = ("192.0.2.1", 9)  # TEST-NET-1: never a real host


def test_outbound_connections_are_refused_by_default():
    guard = NetworkGuard()
    assert guard.install() is True and guard.install() is False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(NetworkDenied):
            sock.connect(UNROUTABLE)
        assert sock.connect_ex(UNROUTABLE) == errno.ENETUNREACH
    finally:
        sock.close()
    assert guard.blocked_attempts()[-1] == {"host": "192.0.2.1", "outcome": "blocked"}


def test_a_window_opens_for_one_approved_host_only_and_needs_a_reason():
    guard = NetworkGuard(["legal-source.example"])
    guard.install()
    with pytest.raises(NetworkDenied, match="not on the approved list"):
        with guard.allow(host="somewhere-else.example", reason="curiosity"):
            pass
    with pytest.raises(NetworkDenied, match="reason"):
        with guard.allow(host="legal-source.example", reason=" "):
            pass
    with guard.allow(host="legal-source.example", reason="approved source lookup"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(NetworkDenied):  # the window is for that host, not for the network
                sock.connect(UNROUTABLE)
        finally:
            sock.close()


def test_a_model_endpoint_off_this_machine_is_refused_unless_it_goes_through_the_guard():
    OpenAICompatInference(base_url="http://127.0.0.1:11434/v1", model="m")
    with pytest.raises(NetworkDenied):
        OpenAICompatInference(base_url="https://api.example.com/v1", model="m")


def test_a_flagged_file_raises_a_hold_and_an_incident_and_never_reaches_a_model(tmp_path):
    from eli_legal.application.services import build_services
    from eli_legal.demo import build_demo_workspace
    from eli_legal.demo_run import ARBITRATOR, SECRETARY, demo_settings, setup_demo

    model = FakeInference(
        {
            "fact_select": {"selected": []},
            "issue_propose": {"issues": []},
            "fact_issue_link": {"links": []},
            "arguments": {"arguments": []},
        }
    )
    workspace = build_demo_workspace(tmp_path / "demo")
    sv = build_services(
        demo_settings(tmp_path, workspace), inference=model, install_network_guard=False
    )
    mid = setup_demo(sv, workspace)
    run = sv.runs.start(mid, actor_id=SECRETARY)
    summary = sv.runs.summary(mid, run.run_id, actor_id=ARBITRATOR)
    assert "prompt_injection_detected" in {h["reason"] for h in summary["open_holds"]}
    assert [i.category for i in sv.incidents.list(mid, actor_id=ARBITRATOR)] == [
        "prompt_injection_detected"
    ]
    assert model.prompts, "the model was used for the other documents"
    assert not any("ignore all previous instructions" in p.lower() for p in model.prompts)
    assert not any("leaving the depot" in p for p in model.prompts)  # nothing from that file at all
    assert all("[BEGIN UNTRUSTED SOURCE MATERIAL id=" in p for p in model.prompts)
