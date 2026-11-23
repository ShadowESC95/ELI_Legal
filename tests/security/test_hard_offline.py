"""Hard offline: the kernel, not Python, refuses network access.

The kernel tests run in a child process: once applied, the filter cannot be removed, and the
test runner itself must keep its network."""

import json
import platform
import socket
import subprocess
import sys
import textwrap
import time
import urllib.request
from pathlib import Path

import pytest

from eli_legal.adapters.local import network
from eli_legal.adapters.local.network import NetworkGuard
from eli_legal.domain.errors import NetworkDenied, PolicyDenied, StepUpRequired
from eli_legal.security import authn, hard_offline

KERNEL = platform.system() == "Linux" and platform.machine().lower() in (
    "x86_64",
    "amd64",
    "aarch64",
    "arm64",
)
needs_kernel = pytest.mark.skipif(not KERNEL, reason="seccomp is applied on Linux x86-64 and ARM64")

PROBE = textwrap.dedent(
    """
    import ctypes, json, os, socket, subprocess, sys, threading
    libc = ctypes.CDLL(None, use_errno=True)
    def native():
        fd = libc.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        if fd >= 0:
            os.close(fd)
            return "created"
        return "refused"
    out = {"native_before": native()}
    seen, gate = {}, threading.Event()
    worker = threading.Thread(target=lambda: (gate.wait(), seen.update(thread=native())))
    worker.start()
    from eli_legal.security import hard_offline
    state = hard_offline.go_offline()
    gate.set(); worker.join()
    out.update(by=state.enforced_by, verified=state.verified, thread=seen["thread"],
               native_after=native())
    for name, family in (("inet", socket.AF_INET), ("inet6", socket.AF_INET6)):
        try:
            socket.socket(family).close(); out[name] = "created"
        except OSError:
            out[name] = "refused"
    a, b = socket.socketpair(socket.AF_UNIX); a.close(); b.close(); out["unix"] = "works"
    libc.syscall.restype = ctypes.c_long
    params = ctypes.create_string_buffer(120)
    out["io_uring"] = "refused" if libc.syscall(ctypes.c_long(425), ctypes.c_long(4), params) < 0 else "allowed"
    child = subprocess.run([sys.executable, "-c",
        "import socket\\ntry:\\n socket.socket(socket.AF_INET).close(); print('created')\\nexcept OSError: print('refused')"],
        capture_output=True, text=True)
    out["child"] = child.stdout.strip()
    print(json.dumps(out))
    """
)


@needs_kernel
def test_the_kernel_refuses_every_network_socket_whatever_code_asks():
    """What the Python-level guard cannot stop: native code, a thread started earlier, io_uring
    and a child process. Local sockets keep working."""
    done = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["native_before"] == "created", "the probe proves nothing if this was refused"
    assert out["by"].startswith("the Linux kernel") and out["verified"]
    for refused in ("native_after", "thread", "inet", "inet6", "io_uring", "child"):
        assert out[refused] == "refused", (refused, out)
    assert out["unix"] == "works"


SERVER = textwrap.dedent(
    """
    import sys, uvicorn
    from fastapi import FastAPI
    from eli_legal.security import hard_offline
    app = FastAPI()
    @app.get("/health")
    def health():
        import socket
        try:
            socket.create_connection(("1.1.1.1", 443), timeout=2); out = "reached the internet"
        except OSError:
            out = "refused"
        return {"outbound": out, "by": hard_offline.state().enforced_by}
    config = uvicorn.Config(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="error")
    sockets = [config.bind_socket()]
    hard_offline.go_offline()
    print("ready", flush=True)
    uvicorn.Server(config).run(sockets=sockets)
    """
)


@needs_kernel
def test_a_server_listening_before_lockdown_keeps_answering_but_cannot_reach_out():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = subprocess.Popen(
        [sys.executable, "-c", SERVER, str(port)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        assert server.stdout is not None and server.stdout.readline().strip() == b"ready"
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                    answer = json.loads(r.read())
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("the server did not answer after locking down")
        assert answer == {"outbound": "refused", "by": answer["by"]}
        assert answer["by"].startswith("the Linux kernel")
    finally:
        server.terminate()
        server.wait(10)


@pytest.fixture
def pretend_kernel(monkeypatch):
    """The services, without applying a filter that would outlive the test."""

    def fake():
        network.set_hard_offline(True)
        return hard_offline.OfflineState(True, "the Linux kernel (test)", "test", True)

    monkeypatch.setattr(hard_offline, "go_offline", fake)
    monkeypatch.setattr(hard_offline, "state", lambda: fake())
    yield
    NetworkGuard().uninstall()


def test_only_someone_who_manages_the_configuration_goes_hard_offline_and_it_is_recorded(
    demo, pretend_kernel
):
    """It cuts every approved legal source for everyone on the server, so a registrar, a
    reviewer or a party may not pull it; someone who manages the configuration may."""
    sv, _mid = demo
    with pytest.raises(PolicyDenied):
        sv.network.go_offline(actor_id="sec.byrne")
    status = sv.network.go_offline(actor_id="admin")
    assert status["hard_offline"] and status["verified"]
    event = [e for e in sv.ctx.audit.events(matter_id="-") if e["event_type"] == "network_mode"][-1]
    assert event["actor_id"] == "admin" and event["outcome"] == "on"
    with pytest.raises(NetworkDenied, match="hard offline is on"):
        with sv.ctx.guard.allow(host="www.legislation.gov.uk", reason="a lookup"):
            pass


def test_starting_hard_offline_every_time_needs_the_right_and_the_passphrase(
    demo, pretend_kernel, tmp_path
):
    sv, _mid = demo
    env = tmp_path / ".env"
    env.write_text("ELI_LEGAL_ENV=production\n", encoding="utf-8")
    with pytest.raises(PolicyDenied):
        sv.network.set_at_every_start(actor_id="arb.keane", on=True, persist_to=env)
    with authn.harness("test-harness", step_up=False), pytest.raises(StepUpRequired):
        sv.network.set_at_every_start(actor_id="admin", on=True, persist_to=env)
    status = sv.network.set_at_every_start(actor_id="admin", on=True, persist_to=env)
    assert status["at_every_start"] and status["hard_offline"]
    assert env.read_text(encoding="utf-8").splitlines() == [
        "ELI_LEGAL_ENV=production",
        "ELI_LEGAL_HARD_OFFLINE=true",
    ]
    sv.network.set_at_every_start(actor_id="admin", on=False, persist_to=env)
    assert "ELI_LEGAL_HARD_OFFLINE=false" in env.read_text(encoding="utf-8")
    outcomes = [
        e["outcome"]
        for e in sv.ctx.audit.events(matter_id="-")
        if e["event_type"] == "network_mode" and e["subject_id"] == "hard_offline_at_start"
    ]
    assert outcomes == ["on", "off"]


def test_the_seccomp_program_denies_only_what_it_should():
    """The filter as data: a non-native architecture, x32, io_uring and every socket family
    except Unix domain and netlink are refused; the rest is allowed."""
    program = hard_offline._filter("x86_64")
    assert len(program) == 11 and all(len(i) == 8 for i in program)
    assert program[-2].endswith((0x7FFF0000).to_bytes(4, "little"))
    assert program[-1].endswith((0x0005000D).to_bytes(4, "little"))


def test_the_windows_rule_blocks_only_this_program_and_can_be_removed():
    add = hard_offline.windows_rule_command(r"C:\Program Files\ELI Legal\eli-legal.exe")
    assert add[:5] == ["netsh", "advfirewall", "firewall", "add", "rule"]
    assert "dir=out" in add and "action=block" in add
    assert r"program=C:\Program Files\ELI Legal\eli-legal.exe" in add
    assert "delete" in hard_offline.windows_rule_command("", remove=True)


def test_the_macos_profile_denies_ip_and_keeps_local_sockets():
    assert "(deny network-outbound (remote ip" in hard_offline.MACOS_PROFILE
    assert "unix" not in hard_offline.MACOS_PROFILE  # local sockets are not denied
    assert Path(hard_offline.__file__).read_text(encoding="utf-8").count("os.execv") == 1
