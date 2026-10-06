#!/bin/sh
# ELI Legal @VERSION@ - installer for Linux (@ARCH@).
#
#   sh ELI_Legal-@VERSION@-linux-@ARCH@.run              install for the current user
#   sh ELI_Legal-@VERSION@-linux-@ARCH@.run --system     install for everyone (as root)
#   sh ELI_Legal-@VERSION@-linux-@ARCH@.run --uninstall  remove the program (never your data)
#   sh ELI_Legal-@VERSION@-linux-@ARCH@.run --verify     check this file is intact, install nothing
#
# The program is everything after the line __PAYLOAD_BELOW__. Its SHA-256 is recorded here and
# checked before anything is unpacked.
set -eu

VERSION="@VERSION@"
SHA256="@SHA256@"
MARK=".eli-legal-program-folder"
PREFIX="${HOME}/.local/opt/eli-legal"
BIN="${HOME}/.local/bin"
SHARE="${XDG_DATA_HOME:-$HOME/.local/share}"
MODE="install"
DESKTOP=1

say() { printf '%s\n' "$*"; }
fail() { printf 'eli-legal installer: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) [ $# -ge 2 ] || fail "--prefix needs a folder"; PREFIX="$2"; shift 2 ;;
    --bin-dir) [ $# -ge 2 ] || fail "--bin-dir needs a folder"; BIN="$2"; shift 2 ;;
    --system) PREFIX="/opt/eli-legal"; BIN="/usr/local/bin"; SHARE="/usr/share"; shift ;;
    --no-desktop) DESKTOP=0; shift ;;
    --uninstall) MODE="uninstall"; shift ;;
    --verify) MODE="verify"; shift ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) fail "unknown option: $1 (try --help)" ;;
  esac
done

APP="$PREFIX/app"
ENTRY="$SHARE/applications/eli-legal.desktop"
ICON="$SHARE/icons/hicolor/256x256/apps/eli-legal.png"

remove_program() {
  # Only ever delete a folder this installer created.
  if [ -e "$APP" ]; then
    [ -f "$APP/$MARK" ] || fail "$APP exists but was not created by this installer; not touching it"
    rm -rf "$APP"
  fi
}

if [ "$MODE" = "uninstall" ]; then
  remove_program
  for name in eli-legal eli-legal-gui; do
    if [ -f "$BIN/$name" ] && grep -q "ELI Legal launcher" "$BIN/$name" 2>/dev/null; then rm -f "$BIN/$name"; fi
  done
  rm -f "$ENTRY" "$ICON"
  rmdir "$PREFIX" 2>/dev/null || true
  say "ELI Legal has been removed."
  say "Your matters, audit ledger and key were NOT removed. They are in:"
  say "  ${XDG_DATA_HOME:-$HOME/.local/share}/eli-legal"
  exit 0
fi

LINE=$(awk '/^__PAYLOAD_BELOW__$/ { print NR + 1; exit 0 }' "$0")
[ -n "$LINE" ] || fail "this file is incomplete"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is needed to check this file"
FOUND=$(tail -n +"$LINE" "$0" | sha256sum | cut -d' ' -f1)
[ "$FOUND" = "$SHA256" ] || fail "this file is damaged or has been altered (checksum mismatch); download it again"
if [ "$MODE" = "verify" ]; then say "ELI Legal $VERSION: this installer is intact ($SHA256)."; exit 0; fi

case "$(uname -m)" in @ARCH@) ;; *) fail "this installer is for @ARCH@ machines; this one is $(uname -m)" ;; esac
mkdir -p "$PREFIX" "$BIN" || fail "cannot write to $PREFIX or $BIN (for a system-wide install use --system as root)"

NEW="$PREFIX/app.new.$$"
rm -rf "$NEW"; mkdir -p "$NEW"
trap 'rm -rf "$NEW"' EXIT
say "Unpacking ELI Legal $VERSION to $APP ..."
tail -n +"$LINE" "$0" | tar -xzf - -C "$NEW"
[ -x "$NEW/eli-legal/eli-legal" ] || fail "the program did not unpack correctly"
"$NEW/eli-legal/eli-legal" --help >/dev/null 2>&1 || fail "the program does not run on this system (it needs glibc @GLIBC@ or newer)"
remove_program
mv "$NEW/eli-legal" "$APP"
: > "$APP/$MARK"

for name in eli-legal eli-legal-gui; do
  printf '#!/bin/sh\n# ELI Legal launcher (created by the installer)\nexec "%s/%s" "$@"\n' "$APP" "$name" > "$BIN/$name"
  chmod 755 "$BIN/$name"
done

if [ "$DESKTOP" = 1 ]; then
  mkdir -p "$(dirname "$ENTRY")" "$(dirname "$ICON")"
  cp "$APP/_internal/eli_legal/gui/assets/eli_legal_256.png" "$ICON"
  cat > "$ENTRY" <<DESKTOP
[Desktop Entry]
Type=Application
Name=ELI Legal
GenericName=Governed legal case preparation
Comment=Prepare a dispute for a named human decision-maker: evidence, issues, checked authorities, audit trail
Exec=$APP/eli-legal-gui
Icon=$ICON
Terminal=false
Categories=Office;
StartupWMClass=ELI Legal
DESKTOP
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$(dirname "$ENTRY")" >/dev/null 2>&1 || true
fi

say ""
say "ELI Legal $VERSION is installed."
say "  Desktop application : eli-legal-gui   (also in your applications menu)"
say "  Command line        : eli-legal --help"
say "  Server              : eli-legal serve --help"
say "  Your data           : ${XDG_DATA_HOME:-$HOME/.local/share}/eli-legal  (kept if you uninstall)"
say "  Documentation       : $APP/_internal/README.md"
case ":$PATH:" in *":$BIN:"*) ;; *) say "  Note: $BIN is not on your PATH; add it, or run $BIN/eli-legal directly." ;; esac
say "To remove it later:  sh $(basename "$0") --uninstall"
exit 0
__PAYLOAD_BELOW__
