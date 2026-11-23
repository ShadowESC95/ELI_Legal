# Installation

## Which installer

| Your system | Use | State |
|---|---|---|
| Linux (x86-64), nothing to install | `ELI_Legal-<version>-linux-x86_64.AppImage`: one file, run it | Built and tested |
| Linux (Ubuntu, Debian and others, x86-64) | `ELI_Legal-<version>-linux-x86_64.run`, or the `.deb` on Debian and Ubuntu | Built and tested |
| Windows 10 or 11 (64-bit) | `ELI_Legal-<version>-windows-x64-setup.exe` | Built and smoke-tested by the release workflow; not yet opened by a person |
| macOS, Apple silicon or Intel | `ELI_Legal-<version>-macos-arm64.dmg` or `-x86_64.dmg` | Built and smoke-tested by the release workflow; not yet opened by a person |
| Anything with Python 3.10 or newer | `install.sh` or `install.ps1` from the source tree | Both are run on Linux, macOS and Windows by the tests on every change: installed, started and removed |

Download them from the [releases page](https://github.com/ShadowESC95/ELI_Legal/releases). They
need nothing else: Python and the graphical toolkit are included. To build them yourself, see
`packaging/README.md`.

**The builds are not signed.** Windows SmartScreen and macOS Gatekeeper will warn. Always check a
download against the published `SHA256SUMS` before running it.

## Linux

### The AppImage

One file. Nothing is installed and nothing else is needed.

```
chmod +x ELI_Legal-0.8.15-linux-x86_64.AppImage
./ELI_Legal-0.8.15-linux-x86_64.AppImage                 # the desktop application
./ELI_Legal-0.8.15-linux-x86_64.AppImage serve --help    # the server
./ELI_Legal-0.8.15-linux-x86_64.AppImage doctor          # any command-line command
```

With no arguments it opens the desktop application; with arguments it is the command line and
the server. Your data goes to the same folder as with any other installer (see below), so you
can move between the AppImage and an installed copy. To remove it, delete the file. If your
system has no FUSE, add `--appimage-extract-and-run` as the first argument.

### The installer

```
sh ELI_Legal-0.8.15-linux-x86_64.run --verify     # check the file is intact; installs nothing
sh ELI_Legal-0.8.15-linux-x86_64.run              # install for you
```

It installs the program to `~/.local/opt/eli-legal`, adds the commands `eli-legal` and
`eli-legal-gui` to `~/.local/bin`, and adds ELI Legal to your applications menu. It needs no
administrator rights. If `~/.local/bin` is not on your `PATH`, it tells you.

| Option | Effect |
|---|---|
| `--system` | Install for everyone, to `/opt/eli-legal` and `/usr/local/bin`. Run as root |
| `--prefix DIR` | Install the program somewhere else |
| `--no-desktop` | Do not add a menu entry |
| `--verify` | Check the file's integrity and stop |
| `--uninstall` | Remove the program. Your data is kept |

### The Debian package

```
sudo apt install ./eli-legal_0.8.15_amd64.deb
```

Remove it with `sudo apt remove eli-legal`. Your data is kept.

### What the desktop application needs

A graphical session and, on a minimal system, these libraries:
`sudo apt install libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3 libxcb-cursor0`.
The `.deb` pulls them in itself.

## Windows

Run the setup program. It installs for the current user by default, with no administrator
rights, and can add a desktop shortcut and put `eli-legal` on your `PATH`. Remove it from
"Installed apps". Your data is kept.

## macOS

Open the disk image and drag ELI Legal to Applications. Because the build is unsigned, the first
time you must right-click the application and choose Open. The command line is inside the
application: `/Applications/ELI Legal.app/Contents/MacOS/eli-legal`.

## From source

```
git clone <the repository> && cd ELI_Legal
./install.sh                 # Linux, macOS
powershell -ExecutionPolicy Bypass -File install.ps1     # Windows
```

This makes a private Python environment and launchers. `./install.sh --no-gui` installs the
command line and server only. `--uninstall` removes it and keeps your data.

**Scanned pages and photographs.** A PDF page that is only an image (a scan, a photographed
exhibit), and an image file filed on its own (PNG, JPEG, TIFF, BMP, GIF or WebP), is read by
OCR on this machine: images need Tesseract, PDF pages need Tesseract and Poppler (`sudo apt install tesseract-ocr
poppler-utils`; on macOS `brew install tesseract poppler`; on Windows the Tesseract installer
and Poppler for Windows, both on the PATH). Without them such a page is never skipped: it is
reported unread and the run holds until a person supplies its text or, having checked the
original, accepts the gap. Text read by OCR is marked "(OCR)" with its confidence, and a page
read with less than 80% confidence holds the run until it is checked (`ELI_LEGAL_OCR`,
`ELI_LEGAL_OCR_MIN_CONFIDENCE` change this).

ELI Legal needs eli-sdk 1.1.0, which is not published. A licensee installing from source gets
its wheel with their licence and points pip at its folder first:
`PIP_FIND_LINKS=/path/to/folder ./install.sh` (on Windows, set `$env:PIP_FIND_LINKS` before
running `install.ps1`). The ready-made installers above include it.

The installer also adds llama.cpp, which runs GGUF model files in process, at the version the
graphics packs are built at. Where there is no ready-made build for the machine it is compiled,
which takes some minutes and needs a C and C++ compiler. If that fails the installation still
completes, and the installer says what is missing and the one command to run afterwards. A
graphics pack (`eli-legal gpu install FILE`) is a complete llama.cpp and needs no compiler, and
a model server on the machine works without either. `--no-models` (`-NoModels` on Windows)
leaves llama.cpp out.

For development instead: `python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev,all]'`.
A development checkout keeps its data beside the code, in `./data` and `./secrets`.

## Where your data is

The program and your data are kept apart. Removing or upgrading the program never touches data.

| System | Data folder |
|---|---|
| Linux | `~/.local/share/eli-legal` |
| Windows | `%LOCALAPPDATA%\ELI Legal` |
| macOS | `~/Library/Application Support/ELI Legal` |

Inside it: `data/` (the databases and the document vault), `secrets/` (the audit key, and the
server's certificate if it made one), `artifacts/` (reports, evidence packs, the outbox),
`imports/` (corpora to load) and optionally `.env` (settings) and `config/` (your own policy,
workflow or jurisdiction packs).

To keep the data somewhere else, for example on an encrypted volume, set the environment variable
`ELI_LEGAL_HOME` to that folder before starting the program.

**Back up the data folder, and keep a second copy of `secrets/audit_hmac.key` somewhere else.**
Without the key the audit ledger cannot be verified, and the system will not run.

## First run

Start the desktop application. It creates the audit key and asks you to create the first
administrator, with a passphrase of at least ten characters. Or, from the command line:

```
eli-legal init --admin <your-id>
eli-legal doctor
```

Then follow the [Quick start](02_quick_start.md).

## Upgrading

Install the new version over the old one. The program folder is replaced; the data folder is
untouched and the databases are brought up to date on first start. Back up first. To go back to
an older version you must restore the backup: a newer database is not read by an older program.

## Removing

Use the installer's `--uninstall`, the package manager, or "Installed apps". To remove your data
as well, delete the data folder yourself. That cannot be undone, and it destroys the audit trail.
