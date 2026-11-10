Governed legal case preparation: it takes the papers in a dispute, establishes what is said and by whom, finds and checks the law, and assembles a source-linked analysis for a named human to review. It renders no verdict.

**A high-risk AI system under the EU AI Act (Article 6(2) and Annex III, point 8(a)). It has not been conformity-assessed or validated on real matters, and it is not legal advice.** Read the [documentation](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/README.md), starting with the legal overview, before using it on a matter.

## Fixed in this release

- **The live EU and UK databases gave law in pieces.** EU articles came as fragments (a point's letter on its own, the title as a passage of its own, "Art. 17 ¶691"); UK subsections lost their numbers' brackets ("10 1 Unless …"), and Schedule paragraphs were taken for sections. Each provision is now one passage, located and headed as printed: "Art. 17(1)" under "Right to erasure", "s.10" under "Stipulations about time.", "Sch. 1 para. 5". Regulations cited as "Regulation (EU) No 1215/2012" or "Council Directive 85/374/EEC" were not found, an act printed with its next article's heading at the end of a paragraph lost that article, and a schedule of plain paragraphs was left out.
- **Common words decided searches.** A question "whether the buyer could keep them" matched every provision that says "them". Words that carry no subject are no longer searched for.

## New in this version

- **Research by meaning.** With an embedding model on this machine (bge-small-en-v1.5 or nomic-embed-text-v1.5 in GGUF form, in a model folder), research finds law by its meaning as well as its words. It decides only which passages are offered and in what order: each is quoted word for word and checked as before, and the report says how research was done.
- **Facts filed under the issues they bear on, by meaning.** Without a language model, facts were linked to issues by shared words, which found one link in ten; a fact linked to no issue is set aside as not material.
- **What a party says of an authority is shown beside the passage closest to it in meaning**, chosen during the run, as a pointer, not a finding.
- **Measured.** `eli-legal evaluate` runs two benchmarks: 70 legal issues over fifteen EU and UK instruments as their official databases publish them, and 50 facts in four disputes. With bge-small, the provisions in point among the first ten results rose from 66% to 76%, the governing provisions put in front of the reviewer from 34% to 60%, and the closest passage in point from 40% to 67%. Linking facts to issues rose from F1 0.17 to 0.44 (0.52 with nomic). The benchmarks were written for this software; they are not real matters.
- **An EU judgment comes with the later judgments citing it**, for the person confirming its standing to read: Google Spain, for one, is cited by 26 later judgments and 35 Advocate General's opinions.
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
- **Research and linking by meaning** were measured on Linux with bge-small-en-v1.5 and nomic-embed-text-v1.5 on an NVIDIA RTX 2060 SUPER; each setting was chosen on half of a benchmark and checked on the other half. The test suite uses a stand-in model.
- **The live EU and UK connectors** were run against the live services on 9 and 10 November 2026 with the network guard on, fetching the benchmark's fifteen instruments; the test suite answers them from recorded responses.

Installation and first steps: [docs/6_manuals/01_installation.md](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/6_manuals/01_installation.md).
