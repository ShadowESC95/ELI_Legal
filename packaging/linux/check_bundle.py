#!/usr/bin/env python3
"""Refuse a frozen bundle that splits a library from its own other half.

A frozen build carries some shared libraries and takes the rest from the machine it runs on. That
is safe when the two sides only meet through a stable interface. It is not when a library from the
host needs one the bundle carries and both come from the same source package: they are released
together and use each other's internals. 0.4.0 bundled libxkbcommon from the build machine (1.4,
Ubuntu 22.04) but not libxkbcommon-x11, so the host's libxkbcommon-x11 (1.13 on Ubuntu 26.04)
loaded against it, and the window crashed on the first key press.

    check_bundle.py DIR     exit 1 when such a split exists, naming the package to install on the
                            build machine so both halves are bundled; and when the bundle carries
                            the C++ runtime, which must be the user's system's own, or GTK or
                            GLib's I/O library, which load the user's system's plug-ins
    check_bundle.py --trim DIR
                            first remove the Qt plug-ins that bring GTK and GLib's I/O library
                            in, and the libraries nothing else in the bundle needs

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


# Libraries every system has, that a process can hold one copy of, and that are only ever newer
# on the user's machine than on the build machine. A bundled copy is the old one, and it is then
# the one the machine's graphics drivers and a graphics pack are given. 0.6.0's first build
# carried them and no graphics pack could start: "GLIBCXX_3.4.32 not found".
MACHINES_OWN = ("libstdc++.so.6", "libgcc_s.so.1")


# Qt plug-ins that bring GTK and GLib's I/O library into the process. Each of those then loads
# its own plug-ins from the user's system (input methods, gvfs, dconf), which are built for the
# system's GLib and not for the older one a bundle carries. On a system newer than the build
# machine every one failed ("undefined symbol: g_task_set_static_name"), the ibus input method
# among them. ELI Legal needs neither: it draws its own widgets, and file dialogs are the
# desktop's own through its portal (packaging/pyinstaller/entry_gui.py asks for that).
LOADS_THE_SYSTEMS_PLUGINS = ("platformthemes/libqgtk3.so", "networkinformation/libqglib.so")
THEIR_LIBRARIES = ("libgtk-3.so.0", "libgdk-3.so.0", "libgio-2.0.so.0")


def only_needed_by(gone: set[str], needs: dict[str, list[str]]) -> set[str]:
    """`gone` and every file that only files in it need, by NEEDED entry, to the end of the
    chain. `needs` maps each file to the library names it needs; a library nothing names (one
    opened by name at run time) is never added."""
    gone = set(gone)
    while True:
        users: dict[str, set[str]] = {}
        for path, sonames in needs.items():
            for soname in sonames:
                users.setdefault(soname, set()).add(path)
        more = {path for path in needs
                if path not in gone and users.get(os.path.basename(path))
                and users[os.path.basename(path)] <= gone}
        if not more:
            return gone
        gone |= more


def trim(root: str) -> list[str]:
    """Remove those plug-ins and what only they needed. Returns what was removed."""
    needs: dict[str, list[str]] = {}
    for folder, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(folder, name)
            if not os.path.islink(path) and (".so" in name or os.access(path, os.X_OK)):
                needs[os.path.relpath(path, root)] = _needed(path)
    start = {path for path in needs if path.replace(os.sep, "/").endswith(LOADS_THE_SYSTEMS_PLUGINS)}
    names = {os.path.basename(path) for path in only_needed_by(start, needs)}
    removed = []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if name in names:                      # the file, and any link to it by the same name
                os.remove(os.path.join(folder, name))
                removed.append(os.path.relpath(os.path.join(folder, name), root))
    return sorted(removed)


def carried(root: str) -> list[str]:
    found = sorted({name for _f, _d, files in os.walk(root) for name in files if name in MACHINES_OWN})
    problems = [f"the bundle carries {name}; it must come from the user's system (see the spec)"
                for name in found]
    for folder, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(folder, name).replace(os.sep, "/")
            if path.endswith(LOADS_THE_SYSTEMS_PLUGINS) or name in THEIR_LIBRARIES:
                problems.append(f"the bundle carries {name}, which loads the user's system's "
                                f"plug-ins into the bundle's older GLib; build with --trim")
    return sorted(problems)


def main(argv: list[str]) -> int:
    if argv[:1] == ["--trim"] and len(argv) == 2:
        if not shutil.which("readelf"):
            print("check_bundle: readelf not found, cannot trim", file=sys.stderr)
            return 2
        removed = trim(argv[1])
        print(f"check_bundle: removed {len(removed)} files that only the GTK and GLib I/O "
              f"plug-ins needed" + (": " + ", ".join(removed) if removed else ""))
        return 0
    if not argv:
        print(__doc__)
        return 2
    for tool in ("readelf", "ldconfig"):
        if not shutil.which(tool):
            print(f"check_bundle: {tool} not found, cannot check", file=sys.stderr)
            return 2
    found = carried(argv[0])
    if shutil.which("dpkg"):
        found += splits(argv[0])
    else:
        print("check_bundle: no dpkg on this build machine, library pairs not checked")
    for line in found:
        print(f"check_bundle: {line}", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
