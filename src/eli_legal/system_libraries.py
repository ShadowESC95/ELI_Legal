"""System libraries the desktop toolkit needs and cannot carry.

Qt comes with the application. A few libraries it loads belong to the operating system: OpenGL
and EGL, pieces of X11 and Wayland, fonts. A desktop has them; a server or a minimal system does
not, and Python then names only the first one missing ("libEGL.so.1: cannot open shared object
file") under a message about PySide6, which is installed. Here all of them are found at once
and the command that installs them on this system is given.

As in ELI (``eli.utils.platform_compat``). Linux only: Windows and macOS ship what Qt needs.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

_MISSING = re.compile(
    r"(lib[\w.+-]+?\.so(?:\.\d+)*)(?=: cannot open shared object file| => not found)"
)
# Debian names a package after its library (libGL.so.1 -> libgl1); these are the exceptions.
_APT_ODD = {
    "libglib-2.0.so.0": "libglib2.0-0",
    "libgthread-2.0.so.0": "libglib2.0-0",
    "libbrotlidec.so.1": "libbrotli1",
    "libbrotlicommon.so.1": "libbrotli1",
    "libharfbuzz.so.0": "libharfbuzz0b",
    "libwayland-egl.so.1": "libwayland-egl1",
}
# Arch: library name starts with -> package
_PACMAN = (
    ("libGL.so", "libglvnd"),
    ("libEGL.so", "libglvnd"),
    ("libGLX.so", "libglvnd"),
    ("libOpenGL.so", "libglvnd"),
    ("libglib-2.0", "glib2"),
    ("libgthread-2.0", "glib2"),
    ("libxcb-cursor", "xcb-util-cursor"),
    ("libxcb-icccm", "xcb-util-wm"),
    ("libxcb-image", "xcb-util-image"),
    ("libxcb-keysyms", "xcb-util-keysyms"),
    ("libxcb-render-util", "xcb-util-renderutil"),
    ("libxcb-util", "xcb-util"),
    ("libxcb", "libxcb"),
    ("libxkbcommon-x11", "libxkbcommon-x11"),
    ("libxkbcommon", "libxkbcommon"),
    ("libX11", "libx11"),
    ("libfontconfig", "fontconfig"),
    ("libfreetype", "freetype2"),
    ("libdbus-1", "dbus"),
    ("libwayland-", "wayland"),
    ("libbrotli", "brotli"),
    ("libgssapi_krb5", "krb5"),
)


def missing() -> list[str]:
    """Every system library the installed Qt asks for and this system does not have. An import
    stops at the first; this lists them all, so they are installed in one go."""
    if not sys.platform.startswith("linux") or not shutil.which("ldd"):
        return []
    try:
        spec = importlib.util.find_spec("PySide6")
    except (ImportError, ValueError):
        spec = None
    if spec is None or not spec.submodule_search_locations:
        return []
    home = Path(next(iter(spec.submodule_search_locations)))
    files = [
        home / "Qt" / "lib" / name
        for name in (
            "libQt6Core.so.6",
            "libQt6Gui.so.6",
            "libQt6Widgets.so.6",
            "libQt6DBus.so.6",
            "libQt6XcbQpa.so.6",
            "libQt6WaylandClient.so.6",
        )
    ]
    files.append(home / "Qt" / "plugins" / "platforms" / "libqxcb.so")
    found: list[str] = []
    for path in files:
        if not path.exists():
            continue
        try:
            out = subprocess.run(
                ["ldd", str(path)], capture_output=True, text=True, timeout=60
            ).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        for library in _MISSING.findall(out):
            if library not in found and not library.startswith("libQt6"):
                found.append(library)
    return found


def _debian_package(library: str) -> str | None:
    """Debian's name for the package holding a library, checked against apt's own list."""
    name = _APT_ODD.get(library)
    if not name:
        stem, _, version = library.partition(".so")
        stem = stem.lower().replace("_", "-")
        name = stem + ("-" if stem[-1:].isdigit() else "") + version.lstrip(".").split(".")[0]
    if shutil.which("apt-cache"):
        try:
            known = subprocess.run(["apt-cache", "show", name], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        if known.returncode != 0:
            return None
    return name


def install_command(libraries: list[str]) -> tuple[str | None, list[str]]:
    """(the command that installs these libraries on this system, the ones it does not cover)."""
    libraries = list(dict.fromkeys(libraries))
    wanted: list[str] = []
    unknown: list[str] = []

    def add(package: str | None, library: str) -> None:
        if not package:
            unknown.append(library)
        elif package not in wanted:
            wanted.append(package)

    if shutil.which("apt-get"):
        command = "sudo apt-get install -y"
        for library in libraries:
            add(_debian_package(library), library)
    elif shutil.which("dnf") or shutil.which("zypper"):
        command = "sudo dnf install -y" if shutil.which("dnf") else "sudo zypper install"
        wanted = [f"'{library}()(64bit)'" for library in libraries]
    elif shutil.which("pacman"):
        command = "sudo pacman -S --needed"
        for library in libraries:
            add(next((pkg for start, pkg in _PACMAN if library.startswith(start)), None), library)
    elif shutil.which("apk"):
        command = "sudo apk add"
        wanted = ["so:" + library for library in libraries]
    else:
        return None, libraries
    return (command + " " + " ".join(wanted)) if wanted else None, unknown


def explain(libraries: list[str]) -> str | None:
    """A sentence naming the missing system libraries and the command that installs them."""
    libraries = list(dict.fromkeys(libraries))
    if not libraries:
        return None
    command, unknown = install_command(libraries)
    one = len(libraries) == 1
    say = (
        f"This system has no {', '.join(libraries)}, "
        f"{'a system library' if one else 'system libraries'} the desktop application needs "
        "and cannot carry itself."
    )
    if command:
        say += f" Install {'it' if one else 'them'} with:  {command}"
    if unknown or not command:
        rest = unknown or libraries
        say += (
            (f" For {', '.join(rest)}, install" if command else " Install")
            + f" the package that provides {'it' if len(rest) == 1 else 'them'} with your "
            "system's package manager."
        )
    return say


def window_cannot_start(error: BaseException) -> str:
    """Why the desktop application's toolkit did not load, in one sentence, with what to do."""
    if isinstance(error, ModuleNotFoundError) and (error.name or "").split(".")[0] == "PySide6":
        return "Its toolkit is not installed: pip install 'eli-legal[gui]'"
    named = _MISSING.search(str(error))
    return (
        explain(missing())
        or (explain([named.group(1)]) if named else None)
        or f"PySide6 is installed but did not load: {error}"
    )
