#!/usr/bin/env python3
"""requirements.lock.txt: the exact version of every package ELI Legal is built, tested and
installed with, on every system and Python it supports.

pyproject.toml says what ELI Legal can work with (ranges). The lock says what it is built
with: CI, the release build and the source installers all install under it (pip's -c), so a new
release of numpy, PySide6, llama-cpp-python or anything they pull in changes nothing until the
lock is made again on purpose and tested. ELI Creation Station's 0.3.0 showed why: PySide6 6.12.0,
released the day it was built, broke the type check and aborted the tests on Python 3.10.

    python scripts/lock_dependencies.py            make the lock again (needs uv, and eli-sdk's
                                                   wheel: ELI_SDK_WHEELS names its folder)
    python scripts/lock_dependencies.py --check    every dependency in pyproject.toml is pinned
                                                   (exit 1 if not); standard library only

One file for every system and Python (uv's universal resolution): where a version differs by
Python (PySide6 6.11 below 3.12, 6.12 from it) the lock says so with a marker.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements.lock.txt"
PYPROJECT = ROOT / "pyproject.toml"
EXTRAS = ("all", "gui", "server", "gguf", "packs", "build", "dev")
OLDEST_PYTHON = "3.10"
HEADER = """\
# The exact versions ELI Legal is built, tested and installed with, on every system and
# Python it supports. Made by: python scripts/lock_dependencies.py (never by hand).
# CI, the release build and the source installers install under it: pip install -c requirements.lock.txt
"""
_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
INTEL_MAC = "sys_platform == 'darwin' and platform_machine == 'x86_64'"
# Held below what the newest would be, each with its reason.
HOLD = (
    # From 49 there is no wheel for Intel Macs; built from source it links the build machine's
    # OpenSSL, the bundle's libssl lacks SSL_get0_group_name, and the licence check fails.
    f"cryptography<49 ; {INTEL_MAC}",
)
# Kept at or above a version everywhere it can be, each with its reason.
# llama.cpp for Python at the version the graphics packs are built at (packaging/gpu_packs.json):
# two versions' libraries in one process crash.
PACKS = json.loads((ROOT / "packaging" / "gpu_packs.json").read_text(encoding="utf-8"))[
    "llama_cpp_python"
]
FLOOR = (
    f"llama-cpp-python=={PACKS}",
    # 49 and 50 fix PYSEC-2026-3552, -3553 and -3554; without this floor the one version that
    # suits Intel Macs too (48) would be chosen for every system, and the release audit refuses it.
    "cryptography>=50 ; sys_platform != 'darwin' or platform_machine != 'x86_64'",
)


def key(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def declared() -> set[str]:
    """Every package pyproject.toml asks for, in its dependencies and its extras."""
    text = PYPROJECT.read_text(encoding="utf-8")
    try:
        import tomllib
    except (
        ModuleNotFoundError
    ):  # Python 3.10: the arrays read by hand, from [project] and its extras
        wanted = []
        section = ""
        inside = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if line.startswith("[") and not inside:
                section = line.strip("[]")
                continue
            if (
                not inside
                and section in ("project", "project.optional-dependencies")
                and line.endswith("= [")
            ):
                inside = section == "project.optional-dependencies" or line.startswith(
                    "dependencies"
                )
                continue
            if inside:
                if line.startswith("]"):
                    inside = False
                    continue
                wanted += re.findall(r'"([^"]+)"', line)
    else:
        project = tomllib.loads(text)["project"]
        wanted = list(project.get("dependencies", []))
        for extra in project.get("optional-dependencies", {}).values():
            wanted += extra
    return {key(m.group(1)) for line in wanted if (m := _NAME.match(line))}


def pinned() -> dict[str, list[str]]:
    """{name: [the pins, each with its marker]} from the lock."""
    out: dict[str, list[str]] = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        text = line.split(" #", 1)[0].strip()
        m = _NAME.match(text)
        if not text or text.startswith("#") or not m:
            continue
        if "==" not in text:
            raise SystemExit(f"{LOCK.name}: {text!r} is not an exact pin")
        out.setdefault(key(m.group(1)), []).append(text)
    return out


def check() -> int:
    if not LOCK.is_file():
        print(f"{LOCK.name} is missing: python scripts/lock_dependencies.py", file=sys.stderr)
        return 1
    missing = sorted(declared() - set(pinned()))
    if missing:
        print(
            f"{LOCK.name} does not pin {', '.join(missing)}: python scripts/lock_dependencies.py",
            file=sys.stderr,
        )
        return 1
    print(f"{LOCK.name}: every dependency pinned ({len(pinned())} packages)")
    return 0


def make() -> int:
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit(
            "needs uv (https://docs.astral.sh/uv/) to resolve for every system and Python"
        )
    wheels = os.environ.get("ELI_SDK_WHEELS") or str(Path.home() / "Desktop" / "eli-sdk" / "dist")
    if not Path(wheels).is_dir():
        raise SystemExit(
            f"eli-sdk is private: set ELI_SDK_WHEELS to the folder with its wheel ({wheels} is not one)"
        )
    cmd = [
        uv,
        "pip",
        "compile",
        "--universal",
        "--python-version",
        OLDEST_PYTHON,
        "--no-header",
        "--quiet",
        "--find-links",
        wheels,
        str(PYPROJECT),
    ]
    for extra in EXTRAS:
        cmd += ["--extra", extra]
    import tempfile

    with tempfile.TemporaryDirectory(prefix="lock-") as tmp:
        holds, floors = Path(tmp) / "holds.txt", Path(tmp) / "floors.txt"
        holds.write_text("\n".join(HOLD) + "\n", encoding="utf-8")
        floors.write_text("\n".join(FLOOR) + "\n", encoding="utf-8")
        # both as requirements: uv's universal resolution forks a package on its requirements' markers
        done = subprocess.run(
            cmd + [str(floors), str(holds)], capture_output=True, text=True, cwd=ROOT
        )
        # the lock names where a version came from; the holds and floors live here, not in a
        # temporary file
        out = done.stdout.replace(str(holds), "scripts/lock_dependencies.py (HOLD)")
        out = out.replace(str(floors), "scripts/lock_dependencies.py (FLOOR)").replace(
            str(PYPROJECT), "pyproject.toml"
        )
    if done.returncode != 0:
        print(done.stderr, file=sys.stderr)
        return done.returncode
    body = "\n".join(
        line for line in out.splitlines() if not line.startswith(("--find-links", "-f "))
    )
    if str(Path.home()) in body or "/tmp" in body:
        raise SystemExit("the lock would name a folder on this machine; not written")
    LOCK.write_text(HEADER + body.strip() + "\n", encoding="utf-8")
    return check()


if __name__ == "__main__":
    sys.exit(check() if "--check" in sys.argv[1:] else make())
