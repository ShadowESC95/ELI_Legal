Governed legal case preparation: it takes the papers in a dispute, establishes what is said and by whom, finds and checks the law, and assembles a source-linked analysis for a named human to review. It renders no verdict.

**A high-risk AI system under the EU AI Act (Article 6(2) and Annex III, point 8(a)). It has not been conformity-assessed or validated on real matters, and it is not legal advice.** Read the [documentation](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/README.md), starting with the legal overview, before using it on a matter.

## New in this version

- **Reports released to you, in the application and the browser.** When a report is released, every recipient with an account is told and finds it on the new **Released to me** page. They read it there, or save it as **PDF**, **Word** or **Markdown**. Each copy is made as it is taken and stamped with who took it, when, the release and the approved report's SHA-256; every reading and copy is in the audit trail. Collection is refused, and the refusal recorded, unless the person is a confirmed recipient still on the matter, the report is not suspended from reliance, and its file still matches the approved version. Nothing is kept in per-person folders or databases, so retention, legal holds and erasure still reach the one report (control C-82). A release's state now reads "Ready to collect".
- **Start the server from the desktop application.** Settings, System, Server: an administrator or a judge (or a tribunal member or an arbitrator) starts it for *this computer only* or for *other computers on the network*, with their passphrase again, and the panel shows the address to give everyone. For other computers it is always TLS (a self-signed certificate is made, and its fingerprint shown, if there is none) with an authenticator code for every account. It runs inside the application, on the same data and audit trail, and stops when the window closes. Starting and stopping, from the application or the command line, are in the audit trail (control C-81).
- **Access proven by attack.** A new test signs in as every kind of person (the tribunal, a legal administrator, each party's people, an auditor, a governance officer and a judge not on the case, a technical administrator) and calls every one of the server's routes. It fails if anyone is shown a paper they are not cleared for, if anyone can change what their role does not allow, or if an evidence pack carries content its exporter may not read; new routes are swept automatically (control C-80). It found and this version fixes: anyone signed in, a party included, could switch the whole server to hard offline (now only someone who manages the configuration); a wrong value for a fixed choice gave a server error instead of a plain refusal; and a case with an unknown legal system was saved before being refused.
- **Mapped to the law and the standard.** The new controls, and the parties' access from 0.8.9, are tied in the registers to the AI Act (Arts. 12, 14, 15, 26), ISO/IEC 42001 (A.6.2, A.6.2.8, A.8, A.9.4), GDPR (Arts. 5, 25, 32) and the Cyber Resilience Act, and `eli-legal governance` checks each against its code and tests.

0.8.10 was built but not published: a test of its own called the real hard-offline switch and stopped a later test from opening its port. The test now keeps everything it does inside its own folder; the software is as 0.8.10 was, with the above.

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
