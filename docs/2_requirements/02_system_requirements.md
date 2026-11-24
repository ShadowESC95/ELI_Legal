# System requirements

## Where it has been run

| System | Packaged installer | From source |
|---|---|---|
| Linux x86-64 (developed and tested on a current Ubuntu) | Built and tested | Tested |
| Windows 10 / 11, x64 | Built by the release workflow, which installs, starts and uninstalls it; **not yet used by a person** | The test suite passes; not otherwise tried |
| macOS, Intel and Apple silicon | Built by the release workflow, which runs the synthetic dispute with it; **not yet used by a person** | The test suite passes; not otherwise tried |

A packaged Linux build runs on the system it was built on and newer ones, not older. Release
builds are made on Ubuntu 22.04 so that they run there and on anything later.

## Hardware

| | Without a model | With a local model |
|---|---|---|
| Processor | Any 64-bit processor from the last ten years | As the model requires; a recent multi-core processor at least |
| Memory | 4 GB | 16 GB or more; 32 GB for larger models |
| Graphics | Not needed | A graphics card makes a model usable; without one it is slow. NVIDIA (CUDA or Vulkan), AMD and Intel (Vulkan) and Apple (Metal) are used. The model is sized to the graphics memory free when it loads, so any amount helps: what does not fit the card runs on the processor |
| Disk | 500 MB for the program, plus about twice the size of the documents you file | Add the model's size (commonly 5 to 20 GB) |

Without a model the system does everything except draft arguments and summarise chat answers.

## Software

| Need | Detail |
|---|---|
| Packaged installer | Nothing else. Python and Qt are included |
| From source | Python 3.10 or newer |
| Desktop application on Linux | A graphical session, and the libraries `libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3 libxcb-cursor0` |
| A model (optional) | Any server on the same machine that speaks the OpenAI-compatible API, such as Ollama or llama.cpp |
| Browser, for the web application | A current Chrome, Edge, Firefox or Safari. JavaScript on. Nothing is loaded from any other site |

## Network

| Use | Network |
|---|---|
| Desktop application or command line | None. The system denies outbound connections by default |
| A model | The loopback interface only. A model on another machine is refused |
| Server, one machine | The loopback interface |
| Server, for a team | One TCP port (8443 by default) on your internal network, over TLS. Do not expose it to the internet |

## What the deploying organisation must supply

The software does not do these, and a deployment that handles real matters needs them:

- **Encryption at rest**: the databases (SQLCipher) and case files (AES-256-GCM) are encrypted by
  the software; their keys are on the same machine, so use an encrypted disk or volume as well, and
  keep a copy of the keys apart from the backups.
- **Backups**, including a separate copy of the audit key.
- **A certificate** from your own authority for the server, or a checked self-signed one.
- **A firewall** limiting who can reach the server.
- **Patching** of the operating system and browsers.
- **Tesseract** (and Poppler, for scanned PDF pages) for scans and photographs to be read by OCR; the installers do not include them.
- **A legal source** you are licensed to use, in a form that carries status information.

## Sizing

Storage is a single-file database per installation and one process per server. That suits a
chambers, a tribunal panel or a firm's team. It has not been tested with many simultaneous users
or very large matters; measure before relying on it at scale.

| Limit | Default | Where it is set |
|---|---|---|
| Largest single upload | 250 MB | `ELI_LEGAL_SERVER_MAX_UPLOAD_MB` |
| Session idle time-out | 30 minutes | `ELI_LEGAL_SERVER_IDLE_MINUTES` |
| Session length | 8 hours | `ELI_LEGAL_SERVER_SESSION_HOURS` |
| Failed sign-ins before a lock | 5, then 15 minutes | `ELI_LEGAL_LOCKOUT_THRESHOLD`, `ELI_LEGAL_LOCKOUT_MINUTES` |
