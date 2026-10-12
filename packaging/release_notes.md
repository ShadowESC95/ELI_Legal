Governed legal case preparation: it takes the papers in a dispute, establishes what is said and by whom, finds and checks the law, and assembles a source-linked analysis for a named human to review. It renders no verdict.

**A high-risk AI system under the EU AI Act (Article 6(2) and Annex III, point 8(a)). It has not been conformity-assessed or validated on real matters, and it is not legal advice.** Read the [documentation](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/README.md), starting with the legal overview, before using it on a matter.

## Fixed in this release

- **Chat and every model step failed with some models.** "The model did not return a usable answer (… 'str object' has no attribute 'text')": the model's own chat template reads each message as a list of parts and failed on plain text (Mistral Small 3.1 among them). The conversation is now given in the form the model's template takes: plain text, parts, or, for a template with no system message, the instructions at the head of the question. Which form was used is on the model's report.
- **Errors in the terminal on Linux**, on every start, on a system newer than the build machine: "undefined symbol: g_task_set_static_name … Failed to load module", "Loading IM context type 'ibus' failed". The installers carried GTK and GLib's I/O library, which loaded the system's newer plug-ins. The Linux builds now carry neither; file dialogs are the desktop's own, through its portal.
- **"TypeError: 'NoneType' object is not callable" on closing** after a model had been used. Models are closed before Python shuts down.

## New in this version

- **Installing from source installs the model runtime.** `install.sh` and `install.ps1` add llama.cpp at the version the graphics packs are built at, and what a graphics pack needs, so a pack runs where llama.cpp cannot be compiled. If it cannot be built the installation still completes and says what is missing.
- **Missing system libraries are named.** On a system without the libraries Qt needs (a server, a minimal install) the desktop application said PySide6 was missing. It now lists every missing library and the command that installs them; `install.sh` adds them itself where that needs no password.

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
- The Linux builds are made on Ubuntu 22.04 and run there and on anything newer. The graphics card is used on Ubuntu 24.04, Debian 13, Fedora 39 or newer (C library 2.38), which the graphics packs need; on an older system a model runs on the processor.

## What was tested

- **Linux:** the installer was installed, run through the synthetic dispute from filing to an approved, released report, and uninstalled; the AppImage ran the same dispute, and its desktop window was opened on a virtual display and typed into.
- **Windows:** the program ran the synthetic dispute; the setup program was installed silently, started and uninstalled. The desktop application was not opened by a person.
- **macOS:** the program ran the synthetic dispute. The disk image was not opened by a person.
- The test suite (desktop application, server, browser application, security, the whole lifecycle) passes on Linux, Windows and macOS.
- **Installing from source:** `install.sh` on Linux and macOS and `install.ps1` on Windows were run on clean machines; each built llama.cpp, started the program and the window toolkit, and uninstalled.
- **The chat template fix:** checked against the template inside the Mistral Small 3.1 file that failed, filled in by llama.cpp's own code. That 24-billion-parameter model was not run to an answer here.
- **The graphics card:** on Linux with an NVIDIA RTX 2060 SUPER (8 GB), through ELI v3's CUDA pack and through the Vulkan pack the installer ships, in the installed program as built here. A model was placed wholly on the card and ran the synthetic dispute to an approved report (a 7-billion-parameter model in 0.6.0, a small one in this build). AMD, Intel and Apple cards, and any card on Windows or macOS, were not run on real hardware: there the same code runs, checked by its tests only.

Installation and first steps: [docs/6_manuals/01_installation.md](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/6_manuals/01_installation.md).
