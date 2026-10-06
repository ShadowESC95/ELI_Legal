#!/usr/bin/env bash
# Install ELI Legal from this source tree, for the current user, on Linux or macOS.
# It needs Python 3.10 or newer. Use this when there is no packaged installer for your system.
#
#   ./install.sh                 install (or upgrade) into ~/.local/opt/eli-legal-src
#   ./install.sh --prefix DIR    install somewhere else
#   ./install.sh --no-gui        command line and server only (no desktop application)
#   ./install.sh --uninstall     remove the program; your data is kept
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${HOME}/.local/opt/eli-legal-src"
BIN="${HOME}/.local/bin"
EXTRAS="all"
MODE="install"
MARK=".eli-legal-program-folder"
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --bin-dir) BIN="$2"; shift 2 ;;
    --no-gui) EXTRAS="server"; shift ;;
    --uninstall) MODE="uninstall"; shift ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
if [ "$(uname -s)" = "Darwin" ]; then DATA="$HOME/Library/Application Support/ELI Legal"; else DATA="${XDG_DATA_HOME:-$HOME/.local/share}/eli-legal"; fi
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

if [ "$MODE" = "uninstall" ]; then
  if [ -e "$PREFIX" ]; then
    [ -f "$PREFIX/$MARK" ] || { echo "$PREFIX was not created by this installer; not touching it" >&2; exit 1; }
    rm -rf "$PREFIX"
  fi
  for name in eli-legal eli-legal-gui; do
    if [ -f "$BIN/$name" ] && grep -q "ELI Legal launcher" "$BIN/$name" 2>/dev/null; then rm -f "$BIN/$name"; fi
  done
  rm -f "$APPS/eli-legal.desktop"
  echo "ELI Legal has been removed. Your data was NOT removed: $DATA"
  exit 0
fi

PY="${PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null \
  || { echo "Python 3.10 or newer is needed (found: $("$PY" --version 2>&1 || echo none)). Set PYTHON=/path/to/python." >&2; exit 1; }
if [ -e "$PREFIX" ] && [ ! -f "$PREFIX/$MARK" ]; then echo "$PREFIX exists and was not created by this installer; choose another --prefix" >&2; exit 1; fi
mkdir -p "$PREFIX" "$BIN" "$DATA"
: > "$PREFIX/$MARK"
echo "Creating a private Python environment in $PREFIX ..."
"$PY" -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/python" -m pip install --quiet --upgrade pip
echo "Installing ELI Legal and what it needs ..."
"$PREFIX/venv/bin/python" -m pip install --quiet "$ROOT[$EXTRAS]"

launcher() {  # name, module arguments
  printf '#!/bin/sh\n# ELI Legal launcher (created by install.sh)\nELI_LEGAL_HOME="${ELI_LEGAL_HOME:-%s}"\nexport ELI_LEGAL_HOME\nexec "%s/venv/bin/python" -m %s "$@"\n' "$DATA" "$PREFIX" "$2" > "$BIN/$1"
  chmod 755 "$BIN/$1"
}
launcher eli-legal eli_legal.cli
if [ "$EXTRAS" = "all" ]; then
  launcher eli-legal-gui eli_legal.gui.app
  if [ "$(uname -s)" != "Darwin" ]; then
    mkdir -p "$APPS"
    ICON="$("$PREFIX/venv/bin/python" -c 'import eli_legal, pathlib; print(pathlib.Path(eli_legal.__file__).parent / "gui" / "assets" / "eli_legal_256.png")')"
    printf '[Desktop Entry]\nType=Application\nName=ELI Legal\nGenericName=Governed legal case preparation\nExec=%s/eli-legal-gui\nIcon=%s\nTerminal=false\nCategories=Office;\nStartupWMClass=ELI Legal\n' "$BIN" "$ICON" > "$APPS/eli-legal.desktop"
  fi
fi
"$BIN/eli-legal" --version
echo
echo "Installed. Your data will be kept in: $DATA"
echo "  First run        : eli-legal init --admin <your-id>     (or just start the desktop application)"
[ "$EXTRAS" = "all" ] && echo "  Desktop          : eli-legal-gui"
echo "  Server           : eli-legal serve --help"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "  Note: add $BIN to your PATH, or run $BIN/eli-legal directly." ;; esac
