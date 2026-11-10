Governed legal case preparation: it takes the papers in a dispute, establishes what is said and by whom, finds and checks the law, and assembles a source-linked analysis for a named human to review. It renders no verdict.

**A high-risk AI system under the EU AI Act (Article 6(2) and Annex III, point 8(a)). It has not been conformity-assessed or validated on real matters, and it is not legal advice.** Read the [documentation](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/README.md), starting with the legal overview, before using it on a matter.

This release follows 0.6.1. Version 0.7.0 was tagged but never released; everything in it is here.

## Fixed in this release

- **The last four steps of a run stayed "pending"** after the report was approved and released: review, release preparation, recipient approval and delivery were never recorded. Each is recorded now, with who did it, and the step panel says what it is waiting for, with the decision, release and hold buttons.
- **Nobody could put the work on hold at the human stages.** Anyone working on a matter can now hold a run while it waits for review, or suspend reliance on an approved report and stop its release; only a decision-maker can lift the hold.
- **A mediation brief's shared version could carry a drafted argument built on one party's confidential material.** An argument is now never shown more widely than what it rests on.
- **Common words decided searches.** A question "whether the buyer could keep them" matched every provision that says "them". Words that carry no subject are no longer searched for.

## New in this version

- **Home: what to do next.** Where the open matter stands (set up, documents, analysis, holds, review, release), your role on it, the next things to do with a button to each (or who can do them if you cannot), and what is waiting for you on every matter. Pages are grouped down the left.
- **Opening a matter step by step,** with its team, each person's role on it, the reviewers, sources and laws; and documents taken in file by file, with a plain account of what was read and what was not.
- **Roles on each matter and redaction.** Lead, decision-maker, case worker, assistant, observer or auditor: a role on a matter only narrows what someone's account allows. Material a person is not cleared for (the neutral's own notes, what one party gave in confidence, privileged work) is withheld everywhere with the reason, never the content. Observers and auditors see contact, bank, card and identity numbers masked.
- **Every legal requirement reads as met, waiting for your organisation, or due for review**, not "partial". What only an organisation can do is a list of actions recorded in the application in a named person's name: the classification, the impact assessment, training, retention, the accuracy evaluation the system runs itself, the Annex IV documentation and the declaration of conformity it drafts from its own records, registration and the rest. The register now covers EU AI Act Articles 8, 18, 20 to 24 and 47 to 49 as well.
- **Routine checks, every day:** whether each authority relied on is still good law, when each law package was last checked against its official text, the age of source data, stored originals against their hashes, compliance, accounts and training, retention, old holds and serious-incident reporting deadlines. A change of law in an approved report, or an altered original, opens an incident.
- **Hard offline,** enforced by the operating system's kernel rather than inside Python: on Linux a filter on every thread that nothing in the program can remove until it exits, also stopping native code such as llama.cpp and any program it starts; on macOS the kernel sandbox; on Windows a firewall rule. Settings, System, or `eli-legal network`.
- **Live EU and UK law.** Once their licence is read and they are approved: the EU's Publications Office and EUR-Lex (whether legislation is in force, from and until when, and what repealed it) and the UK's legislation.gov.uk (the version in force on the matter's relevant date) and Find Case Law. No open database records whether a judgment was later overruled: that still goes to a person. Each act and judgment is divided into provisions as it is printed ("Art. 17(1)" under "Right to erasure", "s.10" under "Stipulations about time."), and an EU judgment comes with the later judgments that cite it, for the person confirming its standing to read.
- **Plain words everywhere.** Reports open with "At a glance" and group their limits; holds say what they mean and what can be done; chat, the audit trail and the command line say states as a person would. `eli-legal status` says what to do next.
- **Research by meaning.** With an embedding model on this machine (bge-small-en-v1.5 or nomic-embed-text-v1.5 in GGUF form, in a model folder), research finds law by its meaning as well as its words. It decides only which passages are offered and in what order: each is quoted word for word and checked as before, and the report says how research was done.
- **Facts filed under the issues they bear on, by meaning.** Without a language model, facts were linked to issues by shared words, which found one link in ten; a fact linked to no issue is set aside as not material.
- **What a party says of an authority is shown beside the passage closest to it in meaning**, chosen during the run, as a pointer, not a finding.
- **Measured.** `eli-legal evaluate` runs two benchmarks: 70 legal issues over fifteen EU and UK instruments as their official databases publish them, and 50 facts in four disputes. With bge-small, the provisions in point among the first ten results rose from 66% to 76%, the governing provisions put in front of the reviewer from 34% to 60%, and the closest passage in point from 40% to 67%. Linking facts to issues rose from F1 0.17 to 0.44 (0.52 with nomic). The benchmarks were written for this software; they are not real matters.
- **ELI v3 opens the newest copy.** An installed copy keeps ELI v3's record of ELI Legal current when it starts, and the Linux and Windows installers register and unregister their own copy.
- `eli-legal source index` embeds a source ahead of any run.

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
- The test suite (desktop application, server, browser application, security, the whole lifecycle, the benchmarks) passes on Linux, Windows and macOS.
- **Hard offline** was proved on Linux: after it was switched on the kernel refused Python, native code, an earlier thread, io_uring and a child process, and a server kept answering on its port. On macOS and Windows its code is tested but it has not been run on those systems.
- **Installing from source:** `install.sh` and `install.ps1` are installed, started and removed on Linux, macOS and Windows by the tests on every change.
- **Research and linking by meaning** were measured on Linux with bge-small-en-v1.5 and nomic-embed-text-v1.5 on an NVIDIA RTX 2060 SUPER; each setting was chosen on half of a benchmark and checked on the other half. The test suite uses a stand-in model.
- **The live EU and UK connectors** were run against the live services on 9 and 10 November 2026 with the network guard on, fetching the benchmark's fifteen instruments; the test suite answers them from recorded responses.

Installation and first steps: [docs/6_manuals/01_installation.md](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/6_manuals/01_installation.md).
