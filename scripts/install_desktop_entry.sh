#!/usr/bin/env bash
# Adds ELI Legal to the applications menu for the current user (Linux).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$TARGET"
sed "s|@INSTALL_DIR@|$ROOT|g" "$ROOT/packaging/eli-legal.desktop" > "$TARGET/eli-legal.desktop"
echo "Installed $TARGET/eli-legal.desktop"
