Governed legal case preparation: it takes the papers in a dispute, establishes what is said and by whom, finds and checks the law, and assembles a source-linked analysis for a named human to review. It renders no verdict.

**A high-risk AI system under the EU AI Act (Article 6(2) and Annex III, point 8(a)). It has not been conformity-assessed or validated on real matters, and it is not legal advice.** Read the [documentation](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/README.md), starting with the legal overview, before using it on a matter.

## Fixed in this release

- **An exhibit pasted beside text on a page was not read.** An invoice image under a searchable caption was listed as an unchecked image, but its words were not read and nothing held. With OCR installed, such a page is now read whole and what its text layer lacks is added from the image, marked "(OCR, image)" with the page's confidence; a logo or a signature adds nothing. Without OCR, on a real matter, the page is a review task that holds the run. PDFs read by 0.8.5 are read again once, from their originals, at the next run.
- **Deleting a matter's content left its reports, outbox copies and evidence packs on disk.** A deletion now takes everything the application made from the matter in its own folders, each file recorded in the receipt by its SHA-256, unless a preservation hold is in force, which keeps them. Evidence packs exported to another folder are named in the receipt as beyond the application's control.
- **A downloaded report did not say it had been suspended.** Wherever a report is read or downloaded, its standing now is shown with it: approved, suspended since when, superseded, or practice, with when the law was last checked by the routine checks and from which sources. A downloaded copy carries this above the approved text, which is otherwise exactly the file that was hashed.

## New in this version

- **A deployment authorisation binds to its evidence and to everything it approves.** Each piece of evidence is the document itself, copied and recorded by its SHA-256, and checked unchanged when signed. The authorisation is pinned to the software version, policy, model, embedding model, workflow, legal-system packs and approved legal sources: a change to any voids it until approved again. (Opening real matters comes in a later version.)

## Still to know

- Benchmarks measure retrieval and linking against answers fixed in advance on public legislation. They are not a measure of accuracy on real matters, which has not been done.
- Tesseract and Poppler are not included in the installers; install them for scanned pages and pasted exhibits to be read.
- A suspension takes effect when the daily check detects the status problem. An authority's status is its source's as last retrieved; refreshing live sources before a real report is staged comes with real matters.
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
- **The desktop application:** the Report tab's standing line and the Documents page's re-read are tested; a pasted exhibit is read by OCR (tested on Linux with Tesseract installed) and, without OCR on a real matter, held for review (tested everywhere).

Installation and first steps: [docs/6_manuals/01_installation.md](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/6_manuals/01_installation.md).
