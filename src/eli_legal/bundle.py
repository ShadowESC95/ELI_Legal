"""ELI Legal as an ELI v3 bundle: a separate application ELI v3 can open in place of its own
window, on ELI v3's core.

The contract (``eli.bundles`` in ELI v3) asks a bundle for a description and a launch function.
Installed in ELI v3's Python environment, ELI Legal is found through the ``eli.bundles`` entry
point and runs inside ELI v3's process, using ELI v3's loaded model unless another is chosen.
Installed on its own (an AppImage, an installer), ``eli-legal bundle register`` tells ELI v3
where it is, and ELI v3 starts it as its own program.

This module imports nothing heavy at load: ELI v3 reads the description without starting
anything.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from eli_legal import __version__

CONTRACT = 1
_ICON = Path(__file__).resolve().parent / "gui" / "assets" / "eli_legal_256.png"


def describe() -> dict[str, Any]:
    return {
        "contract": CONTRACT,
        "id": "legal",
        "title": "ELI Legal",
        "summary": "Governed case preparation for courts, tribunals, arbitrators, mediators and lawyers. Decision support only.",
        "version": __version__,
        "edition": "legal",
        "icon": str(_ICON) if _ICON.is_file() else "",
        "launch": "eli_legal.bundle:launch",
        "requires_core": ">=3.0",
    }


def launch(argv: list[str] | None = None, *, host: dict[str, Any] | None = None) -> int:
    """Open ELI Legal's window, hosted by ELI v3.

    Its data goes where an installed copy keeps it, never into ELI v3's folders, so the same
    matters are there whichever way ELI Legal is opened. Unless a model has been chosen in ELI
    Legal's own settings, it uses the model ELI v3 has loaded.
    """
    from eli_legal import licensing

    licensing.hosted_by_eli()
    os.environ.setdefault("ELI_LEGAL_HOME", str(_data_home()))
    os.environ["ELI_LEGAL_MODE"] = "eli_v3"
    if host:
        os.environ["ELI_LEGAL_HOST"] = (
            f"{host.get('name', 'ELI v3')} {host.get('version', '')}".strip()
        )
    from eli_legal.settings import Settings  # read only now, after the folder is decided

    if Settings().inference == "none":
        os.environ.setdefault("ELI_LEGAL_INFERENCE", "eli_v3")
        os.environ.setdefault("ELI_LEGAL_INFERENCE_MODEL", "eli_v3")
    if argv and argv[0] not in ("gui",):
        from eli_legal.cli import main as cli_main

        return int(cli_main(argv))
    from eli_legal.gui.app import main as gui_main

    return int(gui_main([]))


def _data_home() -> Path:
    from eli_legal.paths import user_data_dir

    return user_data_dir()


# ── registering a separately installed copy with ELI v3 ───────────────────────
def own_command() -> list[str]:
    """How to start this copy of ELI Legal's window from outside."""
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        return [appimage]
    if getattr(sys, "frozen", False):
        gui = Path(sys.executable).with_name("eli-legal-gui" + (".exe" if os.name == "nt" else ""))
        return [str(gui if gui.exists() else sys.executable)]
    return [sys.executable, "-m", "eli_legal", "gui"]


def v3_bundle_dirs() -> list[Path]:
    """The folders ELI v3 looks in for separately installed bundles."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    out = [base / "ELI_v3" / "bundles"]
    if os.environ.get("ELI_DATA_DIR"):
        out.append(Path(os.environ["ELI_DATA_DIR"]) / "bundles")
    return out


def register(target: Path | None = None) -> Path:
    """Tell ELI v3 where this copy is, so it can offer to open it. Writes one small file."""
    folder = target or v3_bundle_dirs()[0]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "legal.json"
    record = {**describe(), "command": own_command(), "launch": ""}
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path


def _version_key(text: str) -> tuple[int, ...]:
    m = re.match(r"\s*(\d+(?:\.\d+)*)", str(text or ""))
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def installed_copy() -> bool:
    """An AppImage or an installed, packaged program; not a source checkout."""
    return bool(os.environ.get("APPIMAGE")) or bool(getattr(sys, "frozen", False))


def refresh_registration(target: Path | None = None) -> Path | None:
    """Keep ELI v3's record of ELI Legal pointing at the newest copy on this machine.

    Called when an installed copy starts. It registers this copy if ELI v3 is on this machine
    and its record names no copy, a copy that has since been removed, or an older version;
    a copy of the same version leaves the record alone, so two copies never take turns. A
    source checkout registers only when told to. Never raises: ELI Legal starts regardless.
    """
    if target is None and (not installed_copy() or os.environ.get("ELI_LEGAL_MODE") == "eli_v3"):
        return None  # a source checkout, or ELI v3's own process hosting ELI Legal
    try:
        folder = target or v3_bundle_dirs()[0]
        if target is None and not folder.parent.is_dir():
            return None  # ELI v3 is not on this machine
        path = folder / "legal.json"
        if path.is_file():
            held = json.loads(path.read_text(encoding="utf-8"))
            command = held.get("command") or []
            present = bool(command) and Path(str(command[0])).exists()
            if present and _version_key(held.get("version", "")) >= _version_key(__version__):
                return None
        return register(folder)
    except (OSError, ValueError, TypeError):
        return None


def eli_v3_present() -> bool:
    return v3_bundle_dirs()[0].parent.is_dir()


def _names_this_copy(path: Path) -> bool:
    try:
        command = json.loads(path.read_text(encoding="utf-8")).get("command") or []
        return bool(command) and Path(str(command[0])).resolve() == Path(own_command()[0]).resolve()
    except (OSError, ValueError, TypeError):
        return False


def unregister(target: Path | None = None, *, this_copy: bool = False) -> list[Path]:
    """Take ELI Legal off ELI v3's list; with ``this_copy``, only where the record names this
    copy (an uninstaller must not remove the record of another copy)."""
    removed = []
    for folder in [target] if target else v3_bundle_dirs():
        path = folder / "legal.json"
        if path.is_file() and (not this_copy or _names_this_copy(path)):
            path.unlink()
            removed.append(path)
    return removed
