Governed legal case preparation: it takes the papers in a dispute, establishes what is said and by whom, finds and checks the law, and assembles a source-linked analysis for a named human to review. It renders no verdict.

**A high-risk AI system under the EU AI Act (Article 6(2) and Annex III, point 8(a)). It has not been conformity-assessed or validated on real matters, and it is not legal advice.** Read the [documentation](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/README.md), starting with the legal overview, before using it on a matter.

## New in this version

- **No crash on Windows as a window closes.** On Windows, closing the application could occasionally crash it, as the part that makes everything larger or smaller with Ctrl and the wheel looked over widgets that were already being taken apart. It now leaves any such widget alone, and the case's stage bar keeps its buttons instead of rebuilding them each time it refreshes. Nothing was ever lost: every record is written before a window can close.
- Everything new in 0.8.13 is here too: controls identified by the RAIMS control map (RM-01, HO-01, TR-01, MO-01, DG-01) with their lifecycle stages and each run's minimum evidence, the case from A to Z on every page, and dropping files and folders on the Documents page. See the 0.8.13 notes.

## Still to know

- Benchmarks measure retrieval and linking against answers fixed in advance on public legislation. They are not a measure of accuracy on real matters, which has not been done. Before a real matter is relied on, an authorisation needs that evaluation as evidence, and a lawyer's validation of the legal-system packs.
- Case law's later treatment (overruled, distinguished) needs a licensed citator source; the open databases ELI Legal reads do not supply it, so a case's standing goes to a person.
- Tesseract and Poppler are not included in the installers: install Tesseract for photographs and scans to be read, and Poppler as well for scanned PDF pages.
- Nothing is encrypted at rest: keep the data folder on an encrypted disk.
- A repeal of part of a subsection, or of words within it, is not detected; a consolidated EU text is documentation, not the authentic text.

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
- **New in this version:** images read by OCR (and an image read with too little confidence, or not at all, held), notifications reaching only those who can act and going when the work is done, two people signed in to the server each seeing their own, and the resized desktop window are tested.

Installation and first steps: [docs/6_manuals/01_installation.md](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/6_manuals/01_installation.md).
