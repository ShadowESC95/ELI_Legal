"""``python -m eli_legal`` opens the desktop application; with arguments it is the command line."""

import sys

from eli_legal.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["gui"]))
