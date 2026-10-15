#!/usr/bin/env bash
# Build the macOS disk image: PyInstaller makes "ELI Legal.app", hdiutil wraps it in a .dmg.
#
#   packaging/macos/build.sh
#
# Run on the oldest macOS you intend to support, once per architecture (Apple silicon, Intel).
# An unsigned application is blocked by Gatekeeper. To sign and notarise, set:
#   ELI_LEGAL_CODESIGN_IDENTITY   "Developer ID Application: Your Name (TEAMID)"
#   ELI_LEGAL_NOTARY_PROFILE      a keychain profile created with `xcrun notarytool store-credentials`
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
if [ -n "${PYTHON:-}" ]; then PY="$PYTHON"; elif [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
"$PY" -m pip install --quiet -e ".[all,build]"
VERSION="$("$PY" -c 'import eli_legal; print(eli_legal.__version__)')"
ARCH="$(uname -m)"
OUT="dist/installers"
DMG="$OUT/ELI_Legal-$VERSION-macos-$ARCH.dmg"

"$PY" scripts/third_party_notices.py
"$PY" -m PyInstaller packaging/pyinstaller/eli_legal.spec --noconfirm --distpath build/dist --workpath build/work --log-level WARN
APP="build/dist/ELI Legal.app"
[ -d "$APP" ] || { echo "PyInstaller did not produce $APP" >&2; exit 1; }
"$APP/Contents/MacOS/eli-legal" --help >/dev/null

if [ -n "${ELI_LEGAL_CODESIGN_IDENTITY:-}" ]; then
  codesign --force --deep --options runtime --timestamp --sign "$ELI_LEGAL_CODESIGN_IDENTITY" "$APP"
  codesign --verify --deep --strict "$APP"
else
  echo "NOTE: not signed. Gatekeeper will refuse to open it until the user allows it explicitly." >&2
fi

mkdir -p "$OUT" build/dmg
rm -rf build/dmg/* "$DMG"
cp -R "$APP" build/dmg/
cp LICENSE packaging/INSTALL_NOTICE.txt THIRD_PARTY_NOTICES.md build/dmg/
ln -s /Applications build/dmg/Applications
hdiutil create -volname "ELI Legal $VERSION" -srcfolder build/dmg -ov -format UDZO "$DMG" >/dev/null

if [ -n "${ELI_LEGAL_CODESIGN_IDENTITY:-}" ] && [ -n "${ELI_LEGAL_NOTARY_PROFILE:-}" ]; then
  xcrun notarytool submit "$DMG" --keychain-profile "$ELI_LEGAL_NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"
fi
(cd "$OUT" && shasum -a 256 "$(basename "$DMG")" > "SHA256SUMS-macos-$ARCH")
echo "Built $DMG"
