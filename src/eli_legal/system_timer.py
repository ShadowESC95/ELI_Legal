"""The routine checks, and the deletions they make on time, run from the system's own scheduler.

The desktop application runs them while it is open and the server while it runs. If neither runs
for a while, a retention period could end with nothing to act on it. A daily timer in the
operating system closes that gap: systemd on Linux (a user timer that catches up after the machine
was off), launchd on macOS, Task Scheduler on Windows. It runs ``eli-legal checks run --as-system``
as the same operating-system user, against the same data.

``eli-legal checks timer`` shows what would be installed; ``--install`` installs it for this user
and ``--remove`` takes it away. Nothing needs administrator rights.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

NAME = "eli-legal-checks"
WINDOWS_TASK = "ELI Legal routine checks"
LAUNCHD_LABEL = "eu.eli.legal.checks"
AT_HOUR, AT_MINUTE = 3, 30


def command() -> list[str]:
    """How this installation runs itself: the frozen program, or Python with the package."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "checks", "run", "--as-system"]
    return [sys.executable, "-m", "eli_legal.cli", "checks", "run", "--as-system"]


def _environment() -> dict[str, str]:
    """Where the data is, when it is not in the default place."""
    return {k: v for k, v in os.environ.items() if k == "ELI_LEGAL_HOME" and v}


def _workdir() -> str | None:
    """A copy run from its source folder keeps its data beside the code: run the checks there."""
    if getattr(sys, "frozen", False) or _environment():
        return None
    return str(Path.cwd())


@dataclass(frozen=True, slots=True)
class Plan:
    system: str
    files: dict[Path, str]
    install: list[list[str]]
    remove: list[list[str]]

    def describe(self) -> str:
        lines = [f"Daily at {AT_HOUR:02d}:{AT_MINUTE:02d} ({self.system}): {shlex.join(command())}"]
        for path, text in self.files.items():
            lines += ["", f"# {path}", text.rstrip()]
        if self.install:
            lines += ["", "Then:"] + [f"  {shlex.join(c)}" for c in self.install]
        return "\n".join(lines)


def systemd_units() -> tuple[str, str]:
    env = "".join(f"Environment={k}={v}\n" for k, v in _environment().items())
    service = (
        "[Unit]\n"
        "Description=ELI Legal routine checks (audit chain, current law, retention)\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"{env}"
        + (f"WorkingDirectory={_workdir()}\n" if _workdir() else "")
        + f"ExecStart={shlex.join(command())}\n"
        # A check that finds something to attend to exits 1; that is a finding, not a failure.
        "SuccessExitStatus=1\n"
    )
    timer = (
        "[Unit]\n"
        "Description=Run the ELI Legal routine checks every day\n\n"
        "[Timer]\n"
        f"OnCalendar=*-*-* {AT_HOUR:02d}:{AT_MINUTE:02d}:00\n"
        "Persistent=true\n"
        "RandomizedDelaySec=10min\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
    return service, timer


def launchd_plist() -> str:
    args = "".join(f"    <string>{escape(a)}</string>\n" for a in command())
    env = "".join(
        f"    <key>{escape(k)}</key><string>{escape(v)}</string>\n"
        for k, v in _environment().items()
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n'
        f"  <key>Label</key><string>{LAUNCHD_LABEL}</string>\n"
        f"  <key>ProgramArguments</key>\n  <array>\n{args}  </array>\n"
        + (f"  <key>EnvironmentVariables</key>\n  <dict>\n{env}  </dict>\n" if env else "")
        + (
            f"  <key>WorkingDirectory</key><string>{escape(_workdir() or '')}</string>\n"
            if _workdir()
            else ""
        )
        + "  <key>StartCalendarInterval</key>\n"
        f"  <dict><key>Hour</key><integer>{AT_HOUR}</integer>"
        f"<key>Minute</key><integer>{AT_MINUTE}</integer></dict>\n"
        "</dict>\n</plist>\n"
    )


def plan(system: str | None = None) -> Plan:
    system = system or ("windows" if os.name == "nt" else sys.platform)
    if system.startswith("linux"):
        folder = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        units = folder / "systemd" / "user"
        service, timer = systemd_units()
        return Plan(
            "systemd user timer",
            {units / f"{NAME}.service": service, units / f"{NAME}.timer": timer},
            [["systemctl", "--user", "daemon-reload"],
             ["systemctl", "--user", "enable", "--now", f"{NAME}.timer"]],
            [["systemctl", "--user", "disable", "--now", f"{NAME}.timer"]],
        )  # fmt: skip
    if system == "darwin":
        path = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
        return Plan(
            "launchd agent",
            {path: launchd_plist()},
            [["launchctl", "load", "-w", str(path)]],
            [["launchctl", "unload", "-w", str(path)]],
        )
    run = subprocess.list2cmdline(command())
    return Plan(
        "Task Scheduler",
        {},
        [["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", f"{AT_HOUR:02d}:{AT_MINUTE:02d}",
          "/TN", WINDOWS_TASK, "/TR", run]],
        [["schtasks", "/Delete", "/F", "/TN", WINDOWS_TASK]],
    )  # fmt: skip


def install(p: Plan) -> None:
    for path, text in p.files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for step in p.install:
        if shutil.which(step[0]) is None:
            raise RuntimeError(f"{step[0]} is not available here; install the timer by hand")
        subprocess.run(step, check=True)  # noqa: S603 - fixed programs, no shell


def remove(p: Plan) -> None:
    for step in p.remove:
        if shutil.which(step[0]) is not None:
            subprocess.run(step, check=False)  # noqa: S603 - fixed programs, no shell
    for path in p.files:
        path.unlink(missing_ok=True)
