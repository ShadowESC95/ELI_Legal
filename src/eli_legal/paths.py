"""Where things live, decided without reading any setting, so it can be used before settings load."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def user_data_dir() -> Path:
    """The per-user folder an installed copy keeps its data in."""
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(root) / "ELI Legal"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ELI Legal"
    root = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(root) / "eli-legal"


def data_roots(app: str) -> list[Path]:
    """Where another application of that name keeps its per-user data on this system."""
    home = Path.home()
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        return [local / app, local / app.lower()]
    if sys.platform == "darwin":
        return [home / "Library" / "Application Support" / app]
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    return [data / app, data / app.lower()]


def home_dir() -> Path | None:
    """Where an installed copy keeps its databases, key and settings.

    ``ELI_LEGAL_HOME`` wins. An installed (frozen) build uses the per-user application data
    directory of the operating system. A source checkout returns None and keeps using the
    working directory, so a developer's data stays beside the code.
    """
    explicit = os.environ.get("ELI_LEGAL_HOME", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    if getattr(sys, "frozen", False):
        return user_data_dir()
    return None


def runtime_dir() -> Path:
    """What this machine taught the program: measured model sizes, the graphics runtime in use.
    Nothing here is a record of a matter."""
    return (home_dir() or Path(".")) / "runtime"
