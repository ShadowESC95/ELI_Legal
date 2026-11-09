Governed legal case preparation: it takes the papers in a dispute, establishes what is said and by whom, finds and checks the law, and assembles a source-linked analysis for a named human to review. It renders no verdict.

**A high-risk AI system under the EU AI Act (Article 6(2) and Annex III, point 8(a)). It has not been conformity-assessed or validated on real matters, and it is not legal advice.** Read the [documentation](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/README.md), starting with the legal overview, before using it on a matter.

## Fixed in this release

- **The last four steps of a run stayed "pending"** after the report was approved and released: review, release preparation, recipient approval and delivery were never recorded. Each is recorded now, with who did it, and the step panel says what it is waiting for, with the decision, release and hold buttons.
- **Nobody could put the work on hold at the human stages.** Anyone working on a matter can now hold a run while it waits for review, or suspend reliance on an approved report and stop its release; only a decision-maker can lift the hold.
- **A mediation brief's shared version could carry a drafted argument built on one party's confidential material.** An argument is now never shown more widely than what it rests on.

## New in this version

- **Home: what to do next.** Where the open matter stands (set up, documents, analysis, holds, review, release), your role on it, the next things to do with a button to each (or who can do them if you cannot), and what is waiting for you on every matter. Pages are grouped down the left.
- **Opening a matter step by step,** with its team, each person's role on it, the reviewers, sources and laws; and documents taken in file by file, with a plain account of what was read and what was not.
- **Roles on each matter and redaction.** Lead, decision-maker, case worker, assistant, observer or auditor: a role on a matter only narrows what someone's account allows. Material a person is not cleared for (the neutral's own notes, what one party gave in confidence, privileged work) is withheld everywhere with the reason, never the content. Observers and auditors see contact, bank, card and identity numbers masked.
- **Every legal requirement reads as met, waiting for your organisation, or due for review**, not "partial". What only an organisation can do is a list of actions recorded in the application in a named person's name: the classification, the impact assessment, training, retention, the accuracy evaluation the system runs itself, the Annex IV documentation and the declaration of conformity it drafts from its own records, registration and the rest. The register now covers EU AI Act Articles 8, 18, 20 to 24 and 47 to 49 as well.
- **Routine checks, every day:** whether each authority relied on is still good law, when each law package was last checked against its official text, the age of source data, stored originals against their hashes, compliance, accounts and training, retention, old holds and serious-incident reporting deadlines. A change of law in an approved report, or an altered original, opens an incident.
- **Hard offline,** enforced by the operating system's kernel rather than inside Python: on Linux a filter on every thread that nothing in the program can remove until it exits, also stopping native code such as llama.cpp and any program it starts; on macOS the kernel sandbox; on Windows a firewall rule. Settings, System, or `eli-legal network`.
- **Live EU and UK law.** Once their licence is read and they are approved: the EU's Publications Office and EUR-Lex (whether legislation is in force, from and until when, and what repealed it) and the UK's legislation.gov.uk (the version in force on the matter's relevant date) and Find Case Law. No open database records whether a judgment was later overruled: that still goes to a person.
- **Plain words everywhere.** Reports open with "At a glance" and group their limits; holds say what they mean and what can be done; chat, the audit trail and the command line say states as a person would. `eli-legal status` says what to do next.

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
- **macOS:** the program ran the synthetic dispute. The disk image was not opened by a person.
- The test suite (desktop application, server, browser application, security, the whole lifecycle) passes on Linux, Windows and macOS.
- **Hard offline** was proved on Linux: after it was switched on the kernel refused Python, native code, an earlier thread, io_uring and a child process, and a server kept answering on its port. On macOS and Windows its code is tested but it has not been run on those systems.
- **The live EU and UK connectors** were run against the live services on 9 November 2026 with the network guard on; the test suite answers them from recorded responses.
- **Installing from source:** `install.sh` on Linux and macOS and `install.ps1` on Windows were run on clean machines; each built llama.cpp, started the program and the window toolkit, and uninstalled.
- **The chat template fix:** checked against the template inside the Mistral Small 3.1 file that failed, filled in by llama.cpp's own code. That 24-billion-parameter model was not run to an answer here.
- **The graphics card:** on Linux with an NVIDIA RTX 2060 SUPER (8 GB), through ELI v3's CUDA pack and through the Vulkan pack the installer ships, in the installed program as built here. A model was placed wholly on the card and ran the synthetic dispute to an approved report (a 7-billion-parameter model in 0.6.0, a small one in this build). AMD, Intel and Apple cards, and any card on Windows or macOS, were not run on real hardware: there the same code runs, checked by its tests only.

Installation and first steps: [docs/6_manuals/01_installation.md](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/6_manuals/01_installation.md).
