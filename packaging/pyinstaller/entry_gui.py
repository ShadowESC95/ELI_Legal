"""Frozen entry point without a console window: the desktop application."""

import os
import sys

if sys.platform.startswith("linux"):
    # The bundle carries Qt and no GTK (packaging/linux/check_bundle.py says why). File dialogs
    # are the desktop's own, asked for through its portal; where there is none Qt shows its own.
    # A style the session names for the system's Qt is not in the bundle.
    os.environ["QT_QPA_PLATFORMTHEME"] = "xdgdesktopportal"
    os.environ.pop("QT_STYLE_OVERRIDE", None)

from eli_legal.gui.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
