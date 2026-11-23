Governed legal case preparation: it takes the papers in a dispute, establishes what is said and by whom, finds and checks the law, and assembles a source-linked analysis for a named human to review. It renders no verdict.

**A high-risk AI system under the EU AI Act (Article 6(2) and Annex III, point 8(a)). It has not been conformity-assessed or validated on real matters, and it is not legal advice.** Read the [documentation](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/README.md), starting with the legal overview, before using it on a matter.

## New in this version

- **Photographs and scans filed as images are read.** A PNG, JPEG, TIFF (every page), BMP, GIF or WebP filed on its own is read by OCR on this machine, known by its contents whatever its name, and each passage is marked (OCR) with the confidence of the reading. A reading below 80%, or one that finds no text, holds the run until a person checks it against the original; nothing is guessed. An image left unread by an earlier version is read again before the next run. On the server a filed document is read on a worker thread, so a long scan holds up no one else.
- **The people who must act are told.** When a run stops for a person (holds to clear, a restart once every hold is cleared, a report ready for review, a report returned, an approved report suspended), everyone on the matter who is allowed to act on it is told, wherever they are signed in: "🔔 N waiting for you" in the desktop header, and a bell with a notice and an **Open** button in the browser, within about ten seconds. Nobody is asked to do what they may not do; each notice goes once the work is done and is written to the audit trail. Nothing is sent outside ELI Legal.
- **The desktop window fits the screen.** It opens to the size of your screen; a page bigger than the window scrolls; rows of buttons and the header wrap rather than widen it. The edge between the sidebar and the page, and the dividers on Home and Review, can be dragged, and the window remembers its size and where you left them.
- **Smaller things.** Ctrl+C stops `eli-legal serve` without a traceback; the first-administrator hint gives a real example; a law package shipped with ELI Legal no longer offers *Approve* (it is used as shipped and needs a lawyer's validation recorded instead), and the desktop says so before asking for a passphrase. The manuals no longer say there is no OCR or rate limiting, and the server manual lists what the browser does not do yet.

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
