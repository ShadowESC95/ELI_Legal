Governed legal case preparation: it takes the papers in a dispute, establishes what is said and by whom, finds and checks the law, and assembles a source-linked analysis for a named human to review. It renders no verdict.

**A high-risk AI system under the EU AI Act (Article 6(2) and Annex III, point 8(a)). It has not been conformity-assessed or validated on real matters, and it is not legal advice.** Read the [documentation](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/README.md), starting with the legal overview, before using it on a matter.

## New in this version

- **A seven-day trial, for practice matters.** An installed copy now runs for seven days from its first use without a key, instead of asking for one at once. The trial covers **practice matters only**: opening a real matter, or doing any work on one, needs a paid licence, as it needs a signed deployment authorisation. Deleting the trial's record, moving the data folder, pointing environment variables elsewhere or setting the clock back does not start another trial. Control RM-01.13.
- **Licence window.** **Help → Licence…** shows where the licence stands (the trial's days left, the licence's tier and seats) with **Buy a licence…**, which opens the store (the key is emailed when payment completes, and is activated here by itself where the store can tell this program), and **Enter a key…**, at any time during the trial or after it. The status bar shows the days left. From the command line: `eli-legal licence buy` and `eli-legal licence` (status). With hard offline on, nothing is sent.
- **Keys from the licence store, and withdrawn keys.** ELI Legal reads keys signed by the store's certified issuer, keys bound to one machine, and ELI's signed revocation lists (a refunded or leaked key stops working), with eli-sdk 1.2. An ELI v3 key that includes a bundle released later still opens ELI Legal.
- Your personal email address is no longer shown in the licence prompt.

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
- **New in this version:** the trial starting on first use and covering practice matters only (a real matter refused on a trial, in the services and the deployment gate); the trial not restarted by deleting its record or moving the data folder; an ended trial key starting no second trial; a key entered during the trial; the licence window entering a key and activating a purchase by itself, letting the store through the network guard for that request alone, and sending nothing with hard offline on; `eli-legal licence buy`.

Installation and first steps: [docs/6_manuals/01_installation.md](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/6_manuals/01_installation.md).
