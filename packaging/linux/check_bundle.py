#!/usr/bin/env python3
"""Refuse a frozen bundle that splits a library from its own other half.

A frozen build carries some shared libraries and takes the rest from the machine it runs on. That
is safe when the two sides only meet through a stable interface. It is not when a library from the
host needs one the bundle carries and both come from the same source package: they are released
together and use each other's internals. 0.4.0 bundled libxkbcommon from the build machine (1.4,
Ubuntu 22.04) but not libxkbcommon-x11, so the host's libxkbcommon-x11 (1.13 on Ubuntu 26.04)
loaded against it, and the window crashed on the first key press.

    check_bundle.py DIR     exit 1 when such a split exists, naming the package to install on the
                            build machine so both halves are bundled

Reads package ownership with dpkg, so it judges on Debian and Ubuntu build machines; elsewhere it
says it cannot and exits 0.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys


def _needed(path: str) -> list[str]:
    out = subprocess.run(["readelf", "-d", path], capture_output=True, text=True).stdout
    return re.findall(r"\(NEEDED\).*\[(.+?)\]", out)


def _host_libraries() -> dict[str, str]:
    """soname -> path of the host's copy, from the dynamic linker's cache."""
    found: dict[str, str] = {}
    out = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        m = re.match(r"\s*(\S+) \((.+?)\) => (\S+)", line)
        if m and ("x86-64" in m.group(2) or "AArch64" in m.group(2) or "64bit" in m.group(2)):
            found.setdefault(m.group(1), m.group(3))
    return found


def _source_package(path: str) -> tuple[str, str] | None:
    """(binary package, source package) that installed this file, or None."""
    real = os.path.realpath(path)
    for candidate in (path, real):
        out = subprocess.run(["dpkg", "-S", candidate], capture_output=True, text=True)
        if out.returncode == 0 and ": " in out.stdout:
            # "libxkbcommon-x11-0:amd64: /usr/lib/..." -- keep the architecture for the query
            qualified = out.stdout.splitlines()[0].rsplit(": ", 1)[0].strip()
            source = subprocess.run(["dpkg-query", "-W", "-f=${source:Package}\n", qualified],
                                    capture_output=True, text=True).stdout.split("\n")[0].strip()
            package = qualified.split(":")[0]
            return package, source or package
    return None


def splits(root: str) -> list[str]:
    bundled: dict[str, str] = {}
    elves: list[str] = []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(folder, name)
            bundled.setdefault(name, path)
            if os.path.islink(path):
                continue
            try:
                with open(path, "rb") as handle:
                    if handle.read(4) == b"\x7fELF":
                        elves.append(path)
            except OSError:
                continue
    host = _host_libraries()
    problems: dict[tuple[str, str], str] = {}
    for elf in elves:
        for soname in _needed(elf):
            if soname in bundled or soname not in host:
                continue
            for dep in _needed(host[soname]):
                if dep not in bundled or (soname, dep) in problems:
                    continue
                host_pkg = _source_package(host[soname])
                dep_pkg = _source_package(host.get(dep, "")) if dep in host else None
                if host_pkg and dep_pkg and host_pkg[1] == dep_pkg[1]:
                    problems[(soname, dep)] = (
                        f"{soname} would come from the user's system and needs {dep}, which the "
                        f"bundle carries; both are built from {host_pkg[1]}. Install {host_pkg[0]} "
                        f"on the build machine so the bundle carries both.")
    return sorted(problems.values())


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    for tool in ("readelf", "ldconfig"):
        if not shutil.which(tool):
            print(f"check_bundle: {tool} not found, cannot check", file=sys.stderr)
            return 2
    if not shutil.which("dpkg"):
        print("check_bundle: no dpkg on this build machine, library pairs not checked")
        return 0
    found = splits(argv[0])
    for line in found:
        print(f"check_bundle: {line}", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
