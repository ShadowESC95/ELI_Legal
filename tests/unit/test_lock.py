"""requirements.lock.txt: every dependency at an exact version, on every system and Python, naming
no folder of any machine, so a new upstream release changes nothing until the lock is made again."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "requirements.lock.txt"


def test_every_dependency_in_pyproject_is_pinned_in_the_lock():
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "lock_dependencies.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr


def test_the_lock_pins_exactly_and_names_no_folder():
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        text = line.split(" #", 1)[0].strip()
        if not text or text.startswith("#"):
            assert not re.search(r"(/home/|/Users/|[A-Za-z]:\\\\|/tmp/|file://)", line), line
            continue
        assert re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*==[^\s;]+( ; .+)?$", text), (
            f"not an exact pin: {text!r}"
        )


def test_every_install_in_the_builds_and_installers_keeps_to_the_lock():
    for name in (
        ".github/workflows/ci.yml",
        ".github/workflows/release.yml",
        "install.sh",
        "install.ps1",
        "packaging/macos/build.sh",
        "packaging/windows/build.ps1",
    ):
        for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
            command = re.search(r"(-m pip|/pip\"?|\bpip) install\b", line)
            if (
                command
                and "throw" not in line
                and not line.lstrip().startswith(("#", "echo", "Write-Host"))
            ):
                if "--upgrade pip" in line or "cyclonedx" in line or "pip-audit" in line:
                    continue  # pip itself, and the audit's own tools in their own environment
                assert "requirements.lock.txt" in line, f"{name}: {line.strip()}"
