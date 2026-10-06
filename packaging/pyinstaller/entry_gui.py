"""Frozen entry point without a console window: the desktop application."""

import sys

from eli_legal.gui.app import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
