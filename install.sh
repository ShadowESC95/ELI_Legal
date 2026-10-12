#!/usr/bin/env bash
# Install ELI Legal from this source tree, for the current user, on Linux or macOS.
# It needs Python 3.10 or newer. Use this when there is no packaged installer for your system.
#
#   ./install.sh                 install (or upgrade) into ~/.local/opt/eli-legal-src
#   ./install.sh --prefix DIR    install somewhere else
#   ./install.sh --no-gui        command line and server only (no desktop application)
#   ./install.sh --no-models     leave out llama.cpp, which runs GGUF model files in process
#   ./install.sh --uninstall     remove the program; your data is kept
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${HOME}/.local/opt/eli-legal-src"
BIN="${HOME}/.local/bin"
EXTRAS="all"
MODELS=1
MODE="install"
MARK=".eli-legal-program-folder"
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --bin-dir) BIN="$2"; shift 2 ;;
    --no-gui) EXTRAS="server"; shift ;;
    --no-models) MODELS=0; shift ;;
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
"$PREFIX/venv/bin/python" -m pip install --quiet "$ROOT[$EXTRAS,packs]"

# Qt needs a few libraries that belong to the system (OpenGL, X11 and Wayland pieces). A desktop
# has them; a minimal system does not, and the desktop application would not start. All of them
# are found at once and added when that takes no password; otherwise the command is given.
if [ "$EXTRAS" = "all" ] && [ "$(uname -s)" = "Linux" ]; then
  libraries() { "$PREFIX/venv/bin/python" -c "from eli_legal import system_libraries as s; $1" 2>/dev/null || true; }
  NEEDS="$(libraries 'print(s.install_command(s.missing())[0] or "")')"
  if [ -n "$NEEDS" ]; then
    if [ "$(id -u)" -eq 0 ]; then AS_ROOT="${NEEDS#sudo }"; elif sudo -n true 2>/dev/null; then AS_ROOT="$NEEDS"; else AS_ROOT=""; fi
    if [ -n "$AS_ROOT" ]; then
      echo "Adding the system libraries the desktop application needs:  $NEEDS"
      DEBIAN_FRONTEND=noninteractive sh -c "$AS_ROOT" >/dev/null 2>&1 || true
    fi
  fi
  LEFT="$(libraries 'print(s.explain(s.missing()) or "")')"
  if [ -n "$LEFT" ]; then
    echo
    echo "The desktop application cannot start on this system yet. $LEFT"
    echo "The command line and the server do not need them."
    echo
  fi
fi

# llama.cpp runs GGUF model files in process. At the version the graphics packs are built at:
# two versions' libraries cannot share a process. It is compiled on this machine when there is
# no ready-made build for it, and the program is complete without it (a model server works).
if [ "$MODELS" = 1 ]; then
  LLAMA="llama-cpp-python==$("$PREFIX/venv/bin/python" "$ROOT/scripts/fetch_gpu_pack.py" --version)"
  echo "Adding llama.cpp to run GGUF model files (compiled here when there is no ready-made build; that takes some minutes) ..."
  if "$PREFIX/venv/bin/python" -m pip install --quiet --log "$PREFIX/llama-build.log" "$LLAMA"; then
    rm -f "$PREFIX/llama-build.log"
  else
    case "$(uname -s)" in
      Darwin) NEEDS="xcode-select --install" ;;
      *) if command -v apt-get >/dev/null 2>&1; then NEEDS="sudo apt-get install build-essential"
         elif command -v dnf >/dev/null 2>&1; then NEEDS="sudo dnf install gcc-c++ make"
         elif command -v pacman >/dev/null 2>&1; then NEEDS="sudo pacman -S base-devel"
         elif command -v zypper >/dev/null 2>&1; then NEEDS="sudo zypper install gcc-c++ make"
         else NEEDS="install a C and C++ compiler"; fi ;;
    esac
    echo
    echo "llama.cpp could not be built here, so GGUF model files will not run in process yet."
    echo "  It needs a C and C++ compiler:  $NEEDS"
    echo "  Then:                           \"$PREFIX/venv/bin/python\" -m pip install '$LLAMA'"
    echo "  What the build said:            $PREFIX/llama-build.log"
    echo "  Without it: a graphics pack (eli-legal gpu install FILE) is a complete llama.cpp and"
    echo "  needs no compiler, and a model server on this machine works as it is."
    echo
  fi
fi

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
