"""Frozen entry point with a console: the command line and the server.
With no arguments it opens the desktop application, like ``python -m eli_legal``."""

import sys

from eli_legal.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["gui"]))
