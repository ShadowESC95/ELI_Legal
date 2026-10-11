Governed legal case preparation: it takes the papers in a dispute, establishes what is said and by whom, finds and checks the law, and assembles a source-linked analysis for a named human to review. It renders no verdict.

**A high-risk AI system under the EU AI Act (Article 6(2) and Annex III, point 8(a)). It has not been conformity-assessed or validated on real matters, and it is not legal advice.** Read the [documentation](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/README.md), starting with the legal overview, before using it on a matter.

## Fixed in this release

- **No model ran on a graphics card.** The llama.cpp inside every 0.5.0 installer was a processor-only build, so the "layers on the graphics card" setting did nothing and a model of ordinary size was too slow to use.
- **A model could not be chosen from Settings, Model.** With no model set, Apply failed with "no GGUF model file at (none)": the empty verifier box was read as a file name.
- A model no longer chosen stayed loaded until the program closed.

## New in this version

- **The graphics card is used.** NVIDIA (CUDA or Vulkan), AMD and Intel (Vulkan), Apple (Metal). The llama.cpp that uses the card is switched on only after it has shown, in a process of its own, that it can use this machine's card. It comes from the installer (Vulkan, Linux and Windows), from ELI v2 or v3 if either is installed, or from a file an administrator installs. Nothing is downloaded.
- **A model is placed by measurement.** The memory free on the card and in the machine when the model loads, and the model's own costs read from its file, decide the context and the layers on the card; there is no fixed size for any model or machine. Context and layers are "automatic" by default. What loaded is shown, and recorded in the audit trail as llama.cpp reported it.
- **Each step fits its material to the model's context** and says what it left out. A reply cut off mid-answer is refused, not used; a failed summary says why.
- **The model writes literally.** No manner of its own, no opinion, no figure of speech: only what the sources state. Recorded on each run as system prompt version 2.
- Settings, Model shows the machine, the llama.cpp in use and how the selected model would be placed. On the command line: `eli-legal gpu status`, `eli-legal gpu install <file>`, `eli-legal model plan <file>`.
- Opened from ELI v3, the model is held to JSON, and a prompt that would not fit ELI v3's context is refused where ELI v3 would have shortened it without saying so.

If you chose a GGUF model in 0.5.0, its settings were saved as 8192 tokens and 0 layers: open Settings, Model, set both to automatic and Apply.

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
- **No licence accompanies this release.** All rights are reserved by the author.
- The Linux builds are made on Ubuntu 22.04 and run there and on anything newer.

## What was tested

- **Linux:** the installer was installed, run through the synthetic dispute from filing to an approved, released report, and uninstalled; the AppImage ran the same dispute, and its desktop window was opened on a virtual display and typed into.
- **Windows:** the program ran the synthetic dispute; the setup program was installed silently, started and uninstalled. The desktop application was not opened by a person.
- **macOS:** the program ran the synthetic dispute. The disk image was not opened by a person.
- The test suite (desktop application, server, browser application, security, the whole lifecycle) passes on Linux, Windows and macOS.
- **The graphics card:** on Linux with an NVIDIA RTX 2060 SUPER (8 GB), through ELI v3's CUDA pack and through the Vulkan pack the installer ships. A 7-billion-parameter model was placed wholly on the card, ran the synthetic dispute to an approved report and answered in the matter chat. AMD, Intel and Apple cards, and any card on Windows or macOS, were not run on real hardware: there the same code runs, checked by its tests only.

Installation and first steps: [docs/6_manuals/01_installation.md](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/6_manuals/01_installation.md).
