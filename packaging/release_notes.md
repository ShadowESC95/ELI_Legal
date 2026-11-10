Governed legal case preparation: it takes the papers in a dispute, establishes what is said and by whom, finds and checks the law, and assembles a source-linked analysis for a named human to review. It renders no verdict.

**A high-risk AI system under the EU AI Act (Article 6(2) and Annex III, point 8(a)). It has not been conformity-assessed or validated on real matters, and it is not legal advice.** Read the [documentation](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/README.md), starting with the legal overview, before using it on a matter.

## Fixed in this release

- **The window became slow while a run was under way (0.8.1).** Zooming listened for the mouse wheel on every part of the window, so every redraw passed through it. It now listens only where the wheel arrives.
- **Stop waited for the step at work to finish**, which with a model can take minutes, and the program could not be closed until then. The step at work now ends at its next model answer, document or issue, no later step starts, and the page says at once that the run is stopping.
- **A stop could be undone** by a step saving the run at the same moment. A stop now stands, whatever a step saves.
- **Ctrl+C in the terminal did not close the program**; each press printed an error. It now closes it.
- **Run from source on Python 3.10 or 3.11, the desktop application could end itself** ("Fatal Python error: none_dealloc"), through a fault in PySide6 6.12 that ELI Legal now steers clear of. The installers carry Python 3.12 and were not affected.

## New in this version

- **Start a new case**, first in the sidebar: how a case is built, as a map of its eleven parts from who the work is for to its release. Choose a part to see what it is, every question you will be asked with what it means and an example, tips, and who does it, with a button that does it now. With a case open, each part already done is ticked. The browser application has it too.
- **Each page in the sidebar has a box of its own**, with the groups spaced apart and Start a new case picked out.

## Which file

| Your system | Download |
|---|---|
| Linux, nothing to install | `ELI_Legal-…-linux-x86_64.AppImage`: `chmod +x` it and run it |
| Linux, installed for your user | `ELI_Legal-…-linux-x86_64.run`: `sh <file>` (and `--uninstall` to remove) |
| Debian, Ubuntu | `eli-legal_…_amd64.deb`: `sudo apt install ./<file>` |
| Windows 10 or 11, 64-bit | `ELI_Legal-…-windows-x64-setup.exe` |
| macOS, Apple silicon | `ELI_Legal-…-macos-arm64.dmg` |
| macOS, Intel | `ELI_Legal-…-macos-x86_64.dmg` |

Every one of them includes the desktop application, the server with its browser application (`eli-legal serve`), and the command line. Your matters, the audit ledger and its key are kept in your user data folder, apart from the program; removing the program never removes them.

## Before you run it

- **These builds are not signed.** Windows SmartScreen and macOS Gatekeeper will warn. Check your download against `SHA256SUMS` first: `sha256sum -c SHA256SUMS --ignore-missing`.
- **An installed copy needs a licence key:** one for ELI Legal, or an ELI v3 key that includes it. The terms are in `LICENSE`, shipped with every build.
- The Linux builds are made on Ubuntu 22.04 and run there and on anything newer. The graphics card is used on Ubuntu 24.04, Debian 13, Fedora 39 or newer (C library 2.38), which the graphics packs need; on an older system a model runs on the processor.

## What was tested

- **Linux:** the installer was installed, run through the synthetic dispute from filing to an approved, released report, and uninstalled; the AppImage ran the same dispute, and its desktop window was opened on a virtual display and typed into.
- **Windows:** the program ran the synthetic dispute; the setup program was installed silently, started and uninstalled. The desktop application was not opened by a person.
- **macOS (Intel and Apple silicon):** the program ran the synthetic dispute. The disk images were not opened by a person.
- The test suite (desktop application, server, browser application, security, the whole lifecycle, the benchmarks) passes on Linux, Windows and macOS.
- **The desktop application** was looked at from screenshots taken on Linux: the boxed sidebar, and Start a new case with and without a case open. A stop during a step, a step saving the run after a stop, and a model asked after a stop are each tested.

Installation and first steps: [docs/6_manuals/01_installation.md](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/6_manuals/01_installation.md).
