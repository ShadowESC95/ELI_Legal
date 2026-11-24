Governed legal case preparation: it takes the papers in a dispute, establishes what is said and by whom, finds and checks the law, and assembles a source-linked analysis for a named human to review. It renders no verdict.

**A high-risk AI system under the EU AI Act (Article 6(2) and Annex III, point 8(a)). It has not been conformity-assessed or validated on real matters, and it is not legal advice.** Read the [documentation](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/README.md), starting with the legal overview, before using it on a matter.

## New in this version

- **Decide a hold on the evidence.** In Review and approve, double-click a hold (or select it and press **Open…**): its window shows what the hold means, the document (reference, who filed it, when, how it was read, its fingerprint) and the **exact words that caused it, highlighted in the document's full text**, each match named in plain words and listed to jump to; or **the original itself**, an image or a PDF shown inside the application without writing it anywhere (a damaged file is said to be damaged). The filing party's answer is there, and only the actions that fit the hold: accept the words as ordinary evidence, take the document out of the analysis, record a check by hand, take a finding out of reliance, lift a hold, save a copy of the original (a recorded hand-over). Control HO-01.13.
- **An unreadable document can be dealt with, not only accepted as a gap.** **Describe it by hand…**: look at the original and type what it shows or says; the words become its text, marked as yours, the hold closes as corrected, and the analysis uses them once restarted. **File a readable copy…**: a clearer scan, the native file or a written description, filed for the same party; the original's hold closes, naming the copy, once the copy is read. Control DG-01.45.
- **A damaged image is called damaged.** An image file that cannot be opened is now reported as damaged (or not what its name says), not as "a picture with no text"; one with no writing is reported as needing a person to look at it.
- **Never stuck at a greyed-out decision.** When a report awaits review and you may not decide it (you started the run, and nobody approves their own run; or you are not a named reviewer), the Decision tab says why and names **who can decide it**, with **Switch person…** (sign in as them on this machine) and, if nobody else can, **Name another reviewer…**; they can also decide in the browser when the server is running. The Progress page names only the people who can. Control HO-01.14.
- **One set of live data, kept current everywhere.** Whatever anyone does on a case, in the desktop or a browser, shows on everyone else's open page **within about five seconds** without pressing F5 (never over a form being typed or an open dialog), and nothing of any other case is named. The server prints the data folder it serves, and the browser's header names the machine and installation (administrators also see the folder; a developer checkout's test data is shown in red). A **developer checkout now refuses to serve its own test data** while your installed copy's data exists (the mix-up that put the browser and the desktop on different data), unless given `--dev-data`. Control DG-01.46.
- **A changed law or standards package says what works.** A run prepared under a package that has since changed must be started again, or restarted from its first step; the message now says so instead of "restart the run".
- **Documentation for every system.** The README and manuals show how to download, check, install and run ELI Legal on Windows, macOS and Linux (Ubuntu and Debian, Fedora, **Arch Linux**), how to run the local server, and how to use the command line on each (new: the command-line guide).
- **Edit a case's details.** Case details → **Edit details…** corrects the name, purpose, forum, rules, the date the law is assessed at, the parties (renamed, added, or removed if nothing depends on them) and the **issues to decide**, one per line; every change is recorded. **Next: State the issues** now opens it at the issues. Control RM-01.12.

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
- **New in this version:** images read by OCR (and an image read with too little confidence, or not at all, held), notifications reaching only those who can act and going when the work is done, two people signed in to the server each seeing their own, and the resized desktop window are tested.

Installation and first steps: [docs/6_manuals/01_installation.md](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/6_manuals/01_installation.md).
