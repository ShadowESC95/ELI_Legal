Governed legal case preparation: it takes the papers in a dispute, establishes what is said and by whom, finds and checks the law, and assembles a source-linked analysis for a named human to review. It renders no verdict.

**A high-risk AI system under the EU AI Act (Article 6(2) and Annex III, point 8(a)). It has not been conformity-assessed or validated on real matters, and it is not legal advice.** Read the [documentation](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/README.md), starting with the legal overview, before using it on a matter.

## New in this version

- **Nobody checks their own work.** By default the person who started a run can no longer approve, return or reject its report: another named reviewer decides, and the matter's lead is told when one is needed. The desktop disables the decision for the person who ran it and says why. An organisation's policy file may allow it (a sole practitioner); every run records which policy applied. The person who proposes a deployment authorisation can no longer sign it: two other people sign. Policy version 0.5.0.
- **How long the record is kept is chosen at set-up.** The first-run window and `eli-legal init` ask how long to keep the audit trail (at least six months), a closed matter's documents, and how long an open matter may sit idle before it is reported; unattended, `init` takes `--audit-days`, `--closed-matter-days` and `--inactive-matter-days`, or `--retention-later` on purpose. A matter can keep its content for its own period (the new-matter wizard, `--retention-days`). The routine checks delete on time and report idle matters, and `eli-legal checks timer --install` runs them daily from the operating system's scheduler, so a period ends on time even when ELI Legal is closed.
- **Deleted means gone from the files.** Deleted database rows are overwritten; after a matter's content is deleted the database is rebuilt and its log emptied, and files ELI Legal deletes are overwritten first. The deletion receipt says so.
- **Case files are private on disk.** Folders 0700, databases 0600, originals read-only; what an earlier version left readable by others is tightened when ELI Legal starts.
- **Security policy and an audited release.** [SECURITY.md](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/SECURITY.md) says how to report a weakness privately and what happens next; `eli-legal doctor` shows where. Each release now carries a CycloneDX bill of materials (`ELI_Legal-…-sbom.cdx.json`) and is built only if a known-vulnerability audit of what it ships passes, any exception recorded with its reason. pypdf is now at least 6.21.4.

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
