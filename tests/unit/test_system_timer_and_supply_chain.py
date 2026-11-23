"""The routine checks run from the system's own scheduler, and a release is audited.

The daily timer runs ``eli-legal checks run --as-system`` against the same data even when neither
the desktop application nor the server is open, and catches up after the machine was off. A
release ships a bill of materials and is built only if the audit of what it ships finds nothing
outstanding; an exception must say why it does not affect ELI Legal.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from eli_legal import system_timer as timer
from eli_legal.security import supply_chain

ROOT = Path(__file__).resolve().parents[2]


def test_the_daily_checks_are_put_in_the_systems_own_scheduler(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("ELI_LEGAL_HOME", str(tmp_path / "home"))
    linux = timer.plan("linux")
    (service_path, service), (timer_path, unit) = linux.files.items()
    assert service_path.parent == timer_path.parent == tmp_path / "systemd" / "user"
    assert "checks run --as-system" in service and "Type=oneshot" in service
    assert "SuccessExitStatus=1" in service, "a finding is not a failure"
    assert f"Environment=ELI_LEGAL_HOME={tmp_path / 'home'}" in service
    assert "Persistent=true" in unit and "OnCalendar=*-*-* 03:30:00" in unit
    assert linux.install[-1] == ["systemctl", "--user", "enable", "--now", "eli-legal-checks.timer"]
    (plist,) = timer.plan("darwin").files.values()
    assert "<string>eu.eli.legal.checks</string>" in plist and "--as-system" in plist
    assert "<key>ELI_LEGAL_HOME</key>" in plist
    windows = timer.plan("windows")
    assert windows.files == {} and windows.install[0][:2] == ["schtasks", "/Create"]
    assert "DAILY" in windows.install[0] and "ELI Legal routine checks" in windows.install[0]

    ran: list[list[str]] = []
    monkeypatch.setattr(timer.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(timer.subprocess, "run", lambda step, check: ran.append(step))
    timer.install(linux)
    assert all(p.is_file() for p in linux.files) and ran == linux.install
    timer.remove(linux)
    assert not any(p.exists() for p in linux.files) and ran[-1] == linux.remove[0]


def test_a_release_is_audited_and_an_exception_must_say_why(tmp_path, monkeypatch, capsys):
    shipped = ROOT / "packaging" / "audit_exceptions.txt"
    listed = supply_chain.read_exceptions(shipped)
    assert listed and all(len(e.reason) >= supply_chain.MIN_REASON for e in listed)
    bad = tmp_path / "exceptions.txt"
    bad.write_text("# a comment\nPYSEC-2026-1  \n")
    with pytest.raises(ValueError, match="needs its reason"):
        supply_chain.read_exceptions(bad)
    bad.write_text("not-an-id because it is fine, honestly, nothing to see here at all\n")
    with pytest.raises(ValueError, match="not a vulnerability id"):
        supply_chain.read_exceptions(bad)
    assert supply_chain.main(["ignore-args", str(shipped)]) == 0
    assert capsys.readouterr().out.split() == [
        part for e in listed for part in ("--ignore-vuln", e.vulnerability_id)
    ]
    assert supply_chain.main(["ignore-args", str(bad)]) == 1, "the release stops"
    monkeypatch.setattr(
        "sys.stdin", io.StringIO("pip==25.0\nPySide6==6.10.1\npyinstaller==6.16\n-e x\n")
    )
    assert supply_chain.main(["shipped"]) == 0
    assert capsys.readouterr().out.split() == ["PySide6==6.10.1"]
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert 'cyclonedx-py" environment' in workflow and "sbom.cdx.json" in workflow
    assert "eli_legal.security.supply_chain ignore-args" in workflow and "pip-audit" in workflow
    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert supply_chain.REPORT_URL in policy and "Art. 14" in policy and "24 hours" in policy
