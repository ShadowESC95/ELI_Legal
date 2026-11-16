Governed legal case preparation: it takes the papers in a dispute, establishes what is said and by whom, finds and checks the law, and assembles a source-linked analysis for a named human to review. It renders no verdict.

**A high-risk AI system under the EU AI Act (Article 6(2) and Annex III, point 8(a)). It has not been conformity-assessed or validated on real matters, and it is not legal advice.** Read the [documentation](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/README.md), starting with the legal overview, before using it on a matter.

0.8.4 was built but not published: a review found that its fix for scanned pages did not reach documents read by earlier versions, and that practice reports carried two contradicting statuses. 0.8.5 carries everything 0.8.4 did, with those corrected.

## Fixed in this release

- **A page of a PDF that is only an image was left out without a word.** A witness statement with a scanned exhibit page was marked processed while the exhibit was silently skipped. Every page is now accounted for: an image page is read by OCR on this machine where Tesseract and Poppler are installed, its text marked "(OCR)" with the page's confidence; a page that cannot be read, or is read with less than 80% confidence, holds the run until a person adds a readable copy or, having checked the original, accepts it with reasons. The report lists every page read by OCR, every page not read, and pages with images beside their text. Without Tesseract and Poppler nothing is guessed: the page is reported unread.
- **Documents read by earlier versions are read again.** Each document now records the version of the reader that read it. A PDF read before every page was accounted for is read again from its stored original before the next run, so a page missing since then is found and held; a report approved before then is flagged by the daily checks for a new run and review. Any document can be read again from its original (Documents page, *Re-read from the original*), for example once OCR is installed.
- **A report returned for correction could not be approved after a restart.** A restart began at the verification gate and never read the correction; and after a restart from the first step, approval refused the corrected report. A returned report now restarts from the beginning by default, a restart that would not read a document added since is refused, and the corrected report can be approved.
- **The Review page offered decisions it would refuse.** Approve, Return and Reject are available only on a report awaiting review; the page says what each state needs (a returned report: correct it, then *Restart to make the corrections*), and what you ticked is kept when the page refreshes.

## New in this version

- **An approved report is suspended from release once a status problem is detected.** The daily checks look at every approved report, not only the latest run. When they find that an authority one relies on is no longer confirmed as good law, reliance on the report is suspended and an incident opened, naming who already received it; from then on, preparing or sending a release is refused by every route. It takes effect when the check runs, not before; copies already sent cannot be recalled, and their recipients are named to be told. Closing the incident does not end the suspension: a named reviewer does, on a written basis, once the law is confirmed again or a later approved run replaces the report.
- **Preservation holds.** A legal hold keeps a matter's content, or named documents, from deletion at closure or when retention ends; only the legal or data-protection owner releases it, with reasons. Every deletion leaves a receipt of the documents deleted and kept. (`eli-legal preserve`; the desktop screen follows.) The receipt covers the matter's documents; reports, outbox copies and evidence packs are not yet included.
- **A serious incident's reporting deadline counts from when someone became aware** (Art. 73), not from when it was entered; an incident has an owner and a stand-in, who is told once half the time to report is gone undecided. (`eli-legal incident aware|assign`.)
- **Practice and real matters.** A practice matter's report carries one status: *Practice matter — draft, not for reliance*, then *Practice review complete — not for reliance*; never "approved for reliance". Real matters will need a signed, current deployment authorisation; opening them comes in a later version, so every matter is practice for now.

## Still to know

- Benchmarks measure retrieval and linking against answers fixed in advance on public legislation. They are not a measure of accuracy on real matters, which has not been done.
- Tesseract and Poppler are not included in the installers; install them for scanned pages to be read.
- An image beside text on a page (an exhibit pasted under a caption) is listed in the report for a person to look at, but is not yet read.
- A report you download keeps the status it was approved with; whether it has since been suspended is shown on the Release tab.
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
- **The desktop application:** the Review page's states, the restart it offers and the ticks it keeps are tested; a scanned exhibit page is read by OCR (tested on Linux with Tesseract installed) and, without OCR, reported unread and held (tested everywhere).

Installation and first steps: [docs/6_manuals/01_installation.md](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/6_manuals/01_installation.md).
