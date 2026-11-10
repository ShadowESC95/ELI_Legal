Governed legal case preparation: it takes the papers in a dispute, establishes what is said and by whom, finds and checks the law, and assembles a source-linked analysis for a named human to review. It renders no verdict.

**A high-risk AI system under the EU AI Act (Article 6(2) and Annex III, point 8(a)). It has not been conformity-assessed or validated on real matters, and it is not legal advice.** Read the [documentation](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/README.md), starting with the legal overview, before using it on a matter.

## Fixed in this release

- **A run would not start, and nothing said why.** Only an account that decides that kind of matter may approve its report: for a court or tribunal a judge, tribunal member or arbitrator; for a mediator a mediator or conciliator; for a party's lawyers a solicitor, supervising solicitor, barrister or in-house counsel. When no one on the matter had such an account, Named reviewers was simply empty and the run held with "missing_reviewer". Now Named reviewers says which accounts may approve, lists each person who cannot and why, marks anyone who has no passphrase yet and so cannot sign in to approve, and, when nobody can, offers to change an account there. A run held for want of a reviewer says the same in words.
- **The Reviews boxes on Open a matter could not be ticked, and the page did not say why.** The team page now says who can approve this kind of matter; where someone cannot, it says so in words instead of showing a box that does nothing, and explains why. Ticking Reviews also puts the person on the matter as decision-maker, which approving needs. What you chose is kept when you go back and forth.
- **Running the test suite changed the size you chose to read at** (it was kept in your own settings). The tests now keep their own.
- **The Product Liability Directive's date.** Directive (EU) 2024/2853 applies to products placed on the market or put into service after 8 December 2026, as Article 2(1) was corrected in the Official Journal on 7 May 2026 (OJ L 2026/90364); the register and the documentation said after 9 December. Corrected throughout, with a test that keeps it so.
- **The Reviewer account's description said it approves reports;** on its own it cannot. It now says what it does.

## New in this version

- **People and accounts from the team page.** On Open a matter, an administrator can press **Add a person…**, **Change their account…** or **Change my account…** without leaving the page. The account roles that may approve that kind of matter are starred and listed first; a new person can be given a passphrase there and then, and is put on the team. Each change asks for your passphrase and is recorded in the audit trail. Anyone else is told to ask an administrator.
- **The legal documentation covers more:** the Cyber Resilience Act, whose reporting duty already applies to the provider; NIS2, which does not reach the courts; who supervises legal AI systems under the AI Act (Article 74(8): the data protection authority or one as independent); Ireland's Regulation of Artificial Intelligence Act 2026; and the UK's new rules on automated decisions (Articles 22A to 22D UK GDPR, from 5 February 2026).

## Still to know

- Benchmarks measure retrieval and linking against answers fixed in advance on public legislation. They are not a measure of accuracy on real matters, which has not been done.
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
- **The desktop application** was looked at from screenshots taken on Linux: the team page of Open a matter. Adding a person, changing an account, naming reviewers when nobody could approve, and the reason a run gives when held for want of a reviewer are each tested.

Installation and first steps: [docs/6_manuals/01_installation.md](https://github.com/ShadowESC95/ELI_Legal/blob/@TAG@/docs/6_manuals/01_installation.md).
