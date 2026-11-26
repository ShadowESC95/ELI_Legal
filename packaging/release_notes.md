Governed legal case preparation: it takes the papers in a dispute, establishes what is said and by whom, finds and checks the law, and assembles a source-linked analysis for a named human to review. It renders no verdict.

**A high-risk AI system under the EU AI Act (Article 6(2) and Annex III, point 8(a)). It has not been conformity-assessed or validated on real matters, and it is not legal advice.** Read the [documentation](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/README.md), starting with the legal overview, before using it on a matter.

## New in this version

- **One status for a practice review, everywhere.** On a practice matter (demonstration, training or testing) the approved report's banner said "Practice review complete — not for reliance", but its summary box at the top said "Status: Approved for reliance" and "May be relied on". The summary now says what the banner says: **"Practice review complete … Not for reliance: a practice matter"**, and lists what passed its checks as practice. An approved practice run is shown as **Practice review complete** on every screen (desktop, browser, command line, the demonstration) and in its step record, never as "Approved for reliance". A real matter's approved report and screens are unchanged. Decision D-32.
- **Case details say which kind of case it is.** In the desktop and the browser, the case details now begin with **Kind**: a practice matter (nothing in it is for reliance, reviewed or not) or a real matter (a report may be relied on once a named reviewer approves it, under a signed deployment authorisation).
- Everything from 0.8.18: deciding a hold on the evidence (HO-01.13), describing an unreadable document by hand or filing a readable copy (DG-01.45), who can decide a report (HO-01.14), one set of live data (DG-01.46), editing a case's details (RM-01.12), and guides for every system.

## Still to know

- Benchmarks measure retrieval and linking against answers fixed in advance on public legislation. They are not a measure of accuracy on real matters, which has not been done. Before a real matter is relied on, an authorisation needs that evaluation as evidence, and a lawyer's validation of the legal-system packs.
- Case law's later treatment (overruled, distinguished) needs a licensed citator source; the open databases ELI Legal reads do not supply it, so a case's standing goes to a person.
- Tesseract and Poppler are not included in the installers: install Tesseract for photographs and scans to be read, and Poppler as well for scanned PDF pages.
- The keys are kept in the secrets folder on the same machine: they protect a copy of the data folder, a backup or a disk image made without it, not the machine itself. Keep the machine on an encrypted disk (BitLocker, FileVault, LUKS) and back up the secrets folder with the data folder, stored apart: a lost key is lost data.
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
- **New in this version:** a practice matter's approved report, its run's state on each screen and its step record say "practice review complete", never "approved for reliance"; the same report on a real matter says "approved for reliance" once; the case details name the kind of case. Still tested from 0.8.18: a hold decided from its window, a document described by hand or replaced by a readable copy, who can decide a report, edited case details, and a developer checkout refusing to serve its test data beside an installed copy.

Installation and first steps: [docs/6_manuals/01_installation.md](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/6_manuals/01_installation.md).
