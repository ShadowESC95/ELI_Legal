# Packaging

| Target | Build with | Produces (in `dist/installers`) | Built and tested |
|---|---|---|---|
| Linux | `packaging/linux/build.sh` | `ELI_Legal-<v>-linux-<arch>.AppImage`, `.run` (installer), `eli-legal_<v>_<arch>.deb`, `.tar.gz` | Yes, by the release workflow (built on Ubuntu 22.04: runs on Ubuntu, Debian, Fedora, Arch and others with glibc 2.35 or newer) |
| Windows | `packaging\windows\build.ps1` | `ELI_Legal-<v>-windows-x64-setup.exe` (Inno Setup) | By the release workflow: silent install, start, uninstall. Not used by a person |
| macOS | `packaging/macos/build.sh` | `ELI_Legal-<v>-macos-<arch>.dmg` | By the release workflow: the program runs the synthetic dispute. Not used by a person |
| Any, from source | `./install.sh` or `install.ps1` | a private Python environment and launchers | Both, by the tests on every change: Linux, macOS and Windows, installed, started and removed |

`.github/workflows/release.yml` builds and tests all of them. Run by hand it publishes nothing;
on a version tag (`git tag -a v1.2.3 -m ... && git push origin v1.2.3`) it attaches them, with
checksums and notes from `packaging/release_notes.md`, to a draft release for a person to
publish.

All packaged builds use `packaging/pyinstaller/eli_legal.spec`: one folder holding two programs,
`eli-legal` (command line and server) and `eli-legal-gui` (desktop application).

## Rules every installer follows

- **Program and data are separate.** The program goes where the installer puts it; matters, the
  audit ledger and its key go in the user's data folder. Uninstalling never removes data.
- **Nothing starts by itself.** No service, no open port, no network call.
- **It only deletes what it created.** The Linux installers mark their folder and refuse to
  remove one without the mark.
- **It can be verified.** `sh <installer>.run --verify` checks the embedded SHA-256 and installs
  nothing; every build writes `SHA256SUMS`.

The AppImage is made with `appimagetool`, taken from `$APPIMAGETOOL`, the `PATH` or
`build/tools`. If it is nowhere, the build downloads it from the AppImage project; set
`NO_DOWNLOAD=1` to forbid that and skip the AppImage. With no arguments the AppImage opens the
desktop application; with arguments it is the command line and server.

## Things a release still needs

- **Build on the oldest system you support.** A frozen Linux build needs the C library of the
  machine it was built on, or newer. The release workflow uses Ubuntu 22.04 for that reason.
- **Signing.** None of the builds is signed. Windows SmartScreen and macOS Gatekeeper will warn
  or block. Signing needs the publisher's own certificates: see the variables named at the top of
  `windows/build.ps1` and `macos/build.sh`.
- **A licence.** `LICENSE` (the ELI End User Licence Agreement and the ELI Legal Product Schedule)
  is included in every build. An installed copy asks for a licence key on first start.
- **Third-party licences.** `scripts/third_party_notices.py` regenerates
  `THIRD_PARTY_NOTICES.md` from the build environment at every build. Qt and PySide6 are LGPL-3.0:
  they are shipped as separate, replaceable library files and must stay that way.
