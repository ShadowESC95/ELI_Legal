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
