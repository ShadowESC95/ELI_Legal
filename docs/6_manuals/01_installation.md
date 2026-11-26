# Installation

How to download ELI Legal, check it, install it and start it on Windows, macOS and Linux
(Ubuntu, Debian, Fedora, Arch and others), where it keeps your data, and how to upgrade and
remove it. The examples use version 0.8.19; use the version you downloaded.

## Which file

All files are on the [latest release](https://github.com/ShadowESC95/ELI_Legal/releases/latest).

| Your system | File | Built and tested |
|---|---|---|
| Windows 10 or 11 (64-bit) | `ELI_Legal-0.8.19-windows-x64-setup.exe` | By the release workflow (install, start, uninstall); the tests run on Windows for every release |
| macOS, Apple silicon | `ELI_Legal-0.8.19-macos-arm64.dmg` | By the release workflow; the tests run on macOS for every release |
| macOS, Intel | `ELI_Legal-0.8.19-macos-x86_64.dmg` | As above |
| Ubuntu, Debian | `eli-legal_0.8.19_amd64.deb` | Built and tested |
| Any Linux (x86-64), nothing installed | `ELI_Legal-0.8.19-linux-x86_64.AppImage`: one file, run it | Built and tested |
| Any Linux (x86-64), installed for you | `ELI_Legal-0.8.19-linux-x86_64.run` | Built and tested |
| Any Linux (x86-64), unpack and run | `ELI_Legal-0.8.19-linux-x86_64.tar.gz` | Built and tested |
| Anything with Python 3.10 or newer | `install.sh` or `install.ps1` from the source tree | Run on Linux, macOS and Windows by the tests on every change |

Every file includes the desktop application, the server with its browser application, and the
command line; Python and the graphical toolkit are inside. `SHA256SUMS` lists every file's
fingerprint and `ELI_Legal-0.8.19-sbom.cdx.json` is the bill of materials (what the build
contains).

**The builds are not signed.** Windows SmartScreen and macOS Gatekeeper will warn. Check a
download against `SHA256SUMS` before running it:

| System | Check |
|---|---|
| Linux | `sha256sum -c SHA256SUMS --ignore-missing` (in the folder holding both) |
| macOS | `shasum -a 256 -c SHA256SUMS --ignore-missing`, or `shasum -a 256 <file>` and compare |
| Windows (PowerShell) | `Get-FileHash .\ELI_Legal-0.8.19-windows-x64-setup.exe -Algorithm SHA256`, and compare with its line in `SHA256SUMS` |

**A licence, or the seven-day trial.** An installed copy runs for seven days from its first use
without a key. The trial covers **practice matters only**: opening a real matter needs a paid
licence (and, as always, a signed deployment authorisation). A key can be entered at any time,
during the trial or after it: **Help → Licence…** in the desktop application (**Buy a
licence…** opens the store; **Enter a key…** takes an ELI Legal key, or an ELI v3 key that
includes ELI Legal), or from the command line `eli-legal licence activate <key>`;
`eli-legal licence buy` opens the store and waits for the key; `eli-legal licence` shows the
state, including the days left. A key activated in ELI v3 counts here too. Deleting the trial's
record, moving the data folder or setting the clock back does not start a new trial.

## Windows

1. Run `ELI_Legal-0.8.19-windows-x64-setup.exe`. If SmartScreen stops it, choose **More info**,
   then **Run anyway** (after checking the fingerprint).
2. It installs for you, with no administrator rights. Tick *Add the eli-legal command to PATH* if
   you want to type `eli-legal` in any terminal.
3. Start **ELI Legal** from the Start menu (or the desktop shortcut). The first time it asks for
   the licence key and then for the first administrator.

The Start menu also has **ELI Legal command line**: a Command Prompt opened in the program's
folder, where `eli-legal <command>` works (see [the command line on each system](#the-command-line-on-each-system)).

Remove it from Settings → Apps → Installed apps. Your data is kept.

## macOS

1. Open the `.dmg` (Apple silicon: `macos-arm64`; Intel: `macos-x86_64`) and drag **ELI Legal** to
   Applications.
2. The first time, right-click ELI Legal in Applications and choose **Open**, then **Open** again:
   Gatekeeper warns because the build is unsigned. If it still refuses, in Terminal:
   `xattr -dr com.apple.quarantine "/Applications/ELI Legal.app"`.
3. It asks for the licence key and then for the first administrator.

The command line is inside the application: `"/Applications/ELI Legal.app/Contents/MacOS/eli-legal"`.

Remove it by dragging ELI Legal from Applications to the Bin. Your data is kept.

## Linux

Any of the three Linux files works on any x86-64 distribution made since 2022: they are built on
Ubuntu 22.04 and need its C library (glibc 2.35) or newer. A graphics pack, to run a model on the
graphics card, needs glibc 2.38 or newer (Ubuntu 24.04, Debian 13, Fedora 39, a current Arch);
on an older system a model runs on the processor.

### Ubuntu and Debian: the package

```
sudo apt install ./eli-legal_0.8.19_amd64.deb
```

It installs the program to `/opt/eli-legal/app`, the commands `eli-legal` and `eli-legal-gui` to
`/usr/bin`, and ELI Legal in your applications menu, and pulls in the libraries the desktop
application needs. Remove it with `sudo apt remove eli-legal`. Your data is kept.

### Any Linux: the installer

```
sh ELI_Legal-0.8.19-linux-x86_64.run --verify     # check the file is intact; installs nothing
sh ELI_Legal-0.8.19-linux-x86_64.run              # install for you
```

It installs the program to `~/.local/opt/eli-legal`, adds the commands `eli-legal` and
`eli-legal-gui` to `~/.local/bin`, and adds ELI Legal to your applications menu. It needs no
administrator rights. If `~/.local/bin` is not on your `PATH`, it tells you: add
`export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc` (or your shell's file).

| Option | Effect |
|---|---|
| `--system` | Install for everyone, to `/opt/eli-legal` and `/usr/local/bin`. Run as root |
| `--prefix DIR` | Install the program somewhere else |
| `--bin-dir DIR` | Put the two commands somewhere else |
| `--no-desktop` | Do not add a menu entry |
| `--verify` | Check the file's integrity and stop |
| `--uninstall` | Remove the program. Your data is kept |

### Any Linux: the AppImage

One file. Nothing is installed.

```
chmod +x ELI_Legal-0.8.19-linux-x86_64.AppImage
./ELI_Legal-0.8.19-linux-x86_64.AppImage                 # the desktop application
./ELI_Legal-0.8.19-linux-x86_64.AppImage serve           # the server
./ELI_Legal-0.8.19-linux-x86_64.AppImage doctor          # any command-line command
```

With no arguments it opens the desktop application; with arguments it is the command line and
the server. It uses the same data folder as any other installed copy, so you can move between
them. To remove it, delete the file.

The AppImage needs FUSE 2. Most desktops have it; if it says it cannot mount, install it
(Arch: `sudo pacman -S fuse2`; Fedora: `sudo dnf install fuse`; Debian and Ubuntu:
`sudo apt install libfuse2`, or `libfuse2t64` on Ubuntu 24.04), or start it without FUSE by
adding `--appimage-extract-and-run` as the first argument.

### Any Linux: the archive

```
tar -xzf ELI_Legal-0.8.19-linux-x86_64.tar.gz
./eli-legal/eli-legal-gui                # the desktop application
./eli-legal/eli-legal <command>          # the command line and the server
```

Nothing is installed and no menu entry is made. To remove it, delete the folder.

### Fedora

Use the `.run` installer (or the AppImage). If the desktop application does not open on a minimal
system, install the libraries Qt needs:
`sudo dnf install mesa-libEGL mesa-libGL libxkbcommon fontconfig dbus-libs xcb-util-cursor`.

### Arch Linux

There is no Arch package; the AppImage, the `.run` installer and the archive all work.

```
sudo pacman -S --needed fuse2                       # for the AppImage
chmod +x ELI_Legal-0.8.19-linux-x86_64.AppImage
./ELI_Legal-0.8.19-linux-x86_64.AppImage            # the desktop application
```

or `sh ELI_Legal-0.8.19-linux-x86_64.run` to install it with `eli-legal` and `eli-legal-gui` in
`~/.local/bin` and a menu entry. On a minimal system the desktop application needs
`sudo pacman -S --needed libglvnd libxkbcommon fontconfig dbus xcb-util-cursor`. The `.deb` is for
Debian and Ubuntu only.

### What the desktop application needs on Linux

A graphical session and, on a minimal system, a few libraries (Ubuntu and Debian:
`sudo apt install libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3 libxcb-cursor0`; the
`.deb` pulls them in itself; Fedora and Arch above). The command line and the server need none of
them.

### Scanned pages and photographs (all systems)

A PDF page that is only an image (a scan, a photographed exhibit), and an image file filed on its
own (PNG, JPEG, TIFF, BMP, GIF or WebP), is read by OCR on this machine: images need Tesseract,
PDF pages Tesseract and Poppler. The installers do not include them:

| System | Install |
|---|---|
| Ubuntu, Debian | `sudo apt install tesseract-ocr poppler-utils` |
| Fedora | `sudo dnf install tesseract poppler-utils` |
| Arch | `sudo pacman -S tesseract tesseract-data-eng poppler` |
| macOS | `brew install tesseract poppler` |
| Windows | the Tesseract installer and Poppler for Windows, both on the `PATH` |

Without them such a page is never skipped: it is reported unread and holds the run until a person
describes it by hand from the original, files a readable copy, or accepts the gap. A damaged image
is reported as damaged ("could not be opened"). Text read by OCR is marked "(OCR)" with its
confidence, and a page read with less than 80% confidence holds the run until it is checked
(`ELI_LEGAL_OCR`, `ELI_LEGAL_OCR_MIN_CONFIDENCE` change this).

## The command line on each system

The command line and the server are the same program, `eli-legal`. How you reach it depends on
how you installed ELI Legal:

| Installed with | Open a terminal | Then type |
|---|---|---|
| Windows setup | Start menu → **ELI Legal command line** (or any Command Prompt or PowerShell if you ticked *Add to PATH*) | `eli-legal --help` |
| macOS `.dmg` | Applications → Utilities → **Terminal** | `"/Applications/ELI Legal.app/Contents/MacOS/eli-legal" --help` |
| `.deb` (Ubuntu, Debian) | your desktop's **Terminal** (Ctrl+Alt+T on Ubuntu) | `eli-legal --help` |
| `.run` installer (any Linux) | Terminal | `eli-legal --help` (in `~/.local/bin`) |
| AppImage (any Linux, Arch) | Terminal, in the folder holding the file | `./ELI_Legal-0.8.19-linux-x86_64.AppImage --help` |
| Archive (`.tar.gz`) | Terminal, in the folder you unpacked it in | `./eli-legal/eli-legal --help` |

To type less on macOS, add `alias eli-legal='"/Applications/ELI Legal.app/Contents/MacOS/eli-legal"'`
to `~/.zshrc`; with the AppImage, `alias eli-legal="$HOME/Downloads/ELI_Legal-0.8.19-linux-x86_64.AppImage"`
to `~/.bashrc`. Every installed form uses your installed data folder, so the command line, the
desktop application and the server all see the same cases.

What to do with it is in [Using the command line](14_command_line_guide.md); every command is in
the [command-line reference](07_command_line_reference.md).

## From source

```
git clone https://github.com/ShadowESC95/ELI_Legal.git && cd ELI_Legal
./install.sh                                              # Linux, macOS
powershell -ExecutionPolicy Bypass -File install.ps1      # Windows
```

This makes a private Python environment and launchers. `./install.sh --no-gui` installs the
command line and server only. `--uninstall` removes it and keeps your data.

ELI Legal needs eli-sdk 1.2.1, which is not published. A licensee installing from source gets
its wheel with their licence and points pip at its folder first:
`PIP_FIND_LINKS=/path/to/folder ./install.sh` (on Windows, set `$env:PIP_FIND_LINKS` before
running `install.ps1`). The ready-made installers above include it, and SQLCipher, which encrypts
the databases.

The installer also adds llama.cpp, which runs GGUF model files in process, at the version the
graphics packs are built at. Where there is no ready-made build for the machine it is compiled,
which takes some minutes and needs a C and C++ compiler. If that fails the installation still
completes, and the installer says what is missing and the one command to run afterwards. A
graphics pack (`eli-legal gpu install FILE`) is a complete llama.cpp and needs no compiler, and
a model server on the machine works without either. `--no-models` (`-NoModels` on Windows)
leaves llama.cpp out.

For development instead: `python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev,all]'`.
**A development checkout keeps its own data beside the code**, in `./data` and `./secrets` of the
folder you run it from: not your installed copy's data, and with its own accounts. Its
`eli-legal serve` refuses to serve that test data while an installed copy's data exists on the
machine, says where your installed data is, and serves the test data only with `--dev-data`.

## Where your data is

The program and your data are kept apart. Removing or upgrading the program never touches data.

| System | Data folder |
|---|---|
| Linux | `~/.local/share/eli-legal` (or `$XDG_DATA_HOME/eli-legal`) |
| Windows | `%LOCALAPPDATA%\ELI Legal` |
| macOS | `~/Library/Application Support/ELI Legal` |

Inside it:

| Folder | Holds |
|---|---|
| `data/` | The working database and the audit ledger (both encrypted with SQLCipher), `archive.sqlite3` (closed cases' archives), and each case's original documents (sealed) |
| `secrets/` | `audit_hmac.key` (signs the ledger), `database.key` (opens the databases), `file_keys/` (each case's file keys), `archive_keys/` (each closed case's archive keys), and the server's certificate if it made one |
| `artifacts/` | Reports, evidence packs and the outbox (sealed), and deletion receipts |
| `imports/` | Corpora to load |
| `.env`, `config/` | Optional settings, and your own policy, workflow or jurisdiction packs |

To keep the data somewhere else, set the environment variable `ELI_LEGAL_HOME` to that folder
before starting the program. Everything that should share one set of cases (the desktop
application, the server, the command line) must use the same folder.

**Back up `data/` and `secrets/` together, and store the two copies apart.** Without
`secrets/database.key` the databases cannot be opened; without `secrets/audit_hmac.key` the ledger
cannot be verified and the system will not run. Save the database key once, off the machine:

```
eli-legal database-key --out eli-legal-database-key.txt
```

It writes the key as one line of text to a new file. Put that file in a password manager or a safe,
apart from your backups, then delete the copy. Anyone holding it and your data can read every
case. To restore, put it back as `secrets/database.key`. On Windows the key in `secrets/` is also
tied to the Windows account, so restore under that account or from the saved copy.

## First run

Start the desktop application. It asks for the licence key, creates the keys, and asks you to
create the first administrator (a passphrase of at least ten characters) and how long each kind
of record is kept. Or, from the command line:

```
eli-legal init --admin <your-id>
eli-legal doctor
```

The administrator manages people and settings but cannot see any case. Create an account with a
legal role for yourself (Settings → Users and roles), and a second one for whoever reviews:
nobody approves a run they started. Then follow the [Quick start](02_quick_start.md).

## Upgrading

**Close ELI Legal and its server first**, then install the new version over the old one. The
program folder is replaced; the data folder is untouched, and the databases are brought up to date
on first start. Starting 0.8.16 or later the first time encrypts databases an earlier version left
plain and seals its files: it checks every row before it replaces anything, and it needs the files
to itself. Back up first. To go back to an older version you must restore the backup: a newer
database is not read by an older program.

## Removing

Use the installer's `--uninstall`, the package manager, Installed apps, or delete the AppImage or
the folder. To remove your data as well, delete the data folder yourself. That cannot be undone,
and it destroys the audit trail.
