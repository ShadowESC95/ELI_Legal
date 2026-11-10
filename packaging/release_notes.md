Governed legal case preparation: it takes the papers in a dispute, establishes what is said and by whom, finds and checks the law, and assembles a source-linked analysis for a named human to review. It renders no verdict.

**A high-risk AI system under the EU AI Act (Article 6(2) and Annex III, point 8(a)). It has not been conformity-assessed or validated on real matters, and it is not legal advice.** Read the [documentation](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/README.md), starting with the legal overview, before using it on a matter.

This release makes ELI Legal easier to read and to use for people who do not work in IT.

## Fixed in this release

- **Compliance said "Waiting for your organisation" without saying for what.** Each requirement now names what your organisation still has to record, the page explains what waiting means, and a button takes you to the record it needs. The panel below the requirements is never empty.
- **Who is responsible for what was shown as R, I, C and A.** It now says *does it*, *answers for it*, *is asked first* and *is kept informed*, with a key saying who the provider and the deployer are; its last column is no longer cut off.
- **Adding a legal source asked technical questions most people cannot answer.** The official EU and UK databases are now added by choosing one and reading its licence; your own collection has a form in plain words, with an example under every field.

## New in this version

- **Pages named in plain words**, each with a line saying what it is for, in a larger sidebar: Case details, Documents, Ask about the case, Progress, Who does each step, Review and approve, Record of actions, Compliance, Legal sources, Laws and standards.
- **How to use**: a case from start to finish, step by step, with who does each step and a button to the page for it, and every word the application uses explained, with a search. F1 opens it.
- **Explanations on hover.** Rest the pointer on a column heading, a field, a button, a page in the sidebar or a status at the top, and a yellow box explains it.
- **Make everything larger or smaller**: Ctrl and + or −, Ctrl and 0 for normal size, or Ctrl and the mouse wheel, on every page, table and dialog. The size is remembered.
- **The browser application** has the same page names, the How to use page and explanations on its column headings.

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
- **The desktop application** was looked at, at normal size and at 150%, from screenshots taken on Linux: the sidebar, How to use, Compliance, Who is responsible and the source forms. Zooming takes about a tenth of a second a step on a full window.

Installation and first steps: [docs/6_manuals/01_installation.md](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/6_manuals/01_installation.md).
