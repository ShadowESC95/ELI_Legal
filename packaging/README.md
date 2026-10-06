# Packaging

| Target | Build with | Produces (in `dist/installers`) | Built and tested |
|---|---|---|---|
| Linux | `packaging/linux/build.sh` | `ELI_Legal-<v>-linux-<arch>.run` (installer), `eli-legal_<v>_<arch>.deb`, `.tar.gz` | Yes, on the development machine |
| Windows | `packaging\windows\build.ps1` | `ELI_Legal-<v>-windows-x64-setup.exe` (Inno Setup) | **No.** Written, not yet run |
| macOS | `packaging/macos/build.sh` | `ELI_Legal-<v>-macos-<arch>.dmg` | **No.** Written, not yet run |
| Any, from source | `./install.sh` or `install.ps1` | a private Python environment and launchers | `install.sh` on Linux; `install.ps1` not yet run |

`.github/workflows/release.yml` builds all of them on a version tag and attaches them to a
draft release. Until that workflow has run green, treat the Windows and macOS builds as untested.

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

## Things a release still needs

- **Build on the oldest system you support.** A frozen Linux build needs the C library of the
  machine it was built on, or newer. The release workflow uses Ubuntu 22.04 for that reason.
- **Signing.** None of the builds is signed. Windows SmartScreen and macOS Gatekeeper will warn
  or block. Signing needs the publisher's own certificates: see the variables named at the top of
  `windows/build.ps1` and `macos/build.sh`.
- **A licence.** There is no `LICENSE` file in this repository. The installers include one
  automatically when it exists; until then they state that all rights are reserved.
- **Third-party licences.** `scripts/third_party_notices.py` regenerates
  `THIRD_PARTY_NOTICES.md` from the build environment at every build. Qt and PySide6 are LGPL-3.0:
  they are shipped as separate, replaceable library files and must stay that way.
