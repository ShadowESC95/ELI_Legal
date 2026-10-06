# Overview

## What it is

**A high-risk AI system under the EU AI Act (Annex III, point 8(a)), built to that standard.**

ELI Legal is case-preparation software for people who decide, mediate or argue disputes. It takes
the papers in a matter, establishes what is said and by whom, finds the law and checks it, and
assembles a source-linked analysis for a named human to review and approve. Then it stops.

It renders no verdict, award, order or settlement terms. It does not recommend an outcome to a
decision-maker or a neutral. It contacts no one. It is a tool for preparation; the judgment
remains with the person whose judgment it is.

It is its own product, with a desktop application, a browser application served by its own
server, and a command line. It can also be loaded into ELI v3 as a separately licensed edition.

## Who it is for

| User | Matter profile | What they get |
|---|---|---|
| Judge, tribunal member, adjudicator, arbitrator, and their secretary or assistant | `adjudicator` | A bench memorandum: facts, issues, each party's authorities checked, arguments open to each side. No view on who should succeed. |
| Mediator, conciliator | `neutral_facilitator` | A mediation brief, with a shared version that leaves out anything one party gave in confidence. No view on who should succeed. |
| Solicitor, barrister, in-house counsel, paralegal | `party_representative` | A privileged case-preparation memorandum. An assessment of the client's own case is permitted; wording that decides the matter never is. |
| Governance officer, auditor, administrator | any, through oversight roles | Registers, monitoring, the audit trail, the evidence pack. An administrator has no access to any matter. |

## What it does, in order

1. **Intake.** A matter is opened under one profile, with its legal system, parties, issues, the
   date as at which the law is to be checked, the approved legal sources and a named reviewer.
2. **Evidence.** Documents are filed (PDF, DOCX, ODT, RTF, HTML, e-mail, text). Each original is
   stored once, read-only, under its SHA-256. Each is read into numbered passages. A file that
   cannot be read is reported, and holds the run until a named person accepts the gap.
3. **Facts.** Factual statements are taken word for word from the documents, with date, party and
   passage.
4. **Issues.** The issues stated at intake, those lifted from the papers, and any a model
   proposes (labelled as proposed).
5. **Research.** Approved sources only. Every authority a party cites is listed with the
   sentence citing it.
6. **Three checks on every authority.** Does it exist? Is it still good law for the relevant
   date, as confirmed recently enough? Does it say what it is quoted as saying?
7. **Gate.** A finding is verified only when every check its kind requires has passed. Anything
   else is held, with what relies on it.
8. **Analysis.** With a local model, arguments open to each party, built only from verified
   findings and attributed by the system. Without a model, this step is skipped.
9. **Report.** Rendered from verified findings. Held and excluded findings are shown separately,
   with reasons. Every limit is stated.
10. **Review.** A named reviewer resolves holds, answers checks only a person can make, and
    approves the exact version of the report, acknowledging each stated limit.
11. **Release.** The approved report is staged for entitled recipients the reviewer confirms one
    by one. The system sends nothing itself.
12. **Record.** Every step, hold, decision and release is in a tamper-evident ledger, with how
    each person's identity was proved. An evidence pack can be exported for any run.

## What makes it different from a general legal assistant

- **Findings are the product; prose is rendered from them.** Nothing appears in a report that is
  not a located, checked finding.
- **It distinguishes "cited" from "exists" from "still good law" from "says that".** These are
  four separate questions and it asks each one.
- **A model is optional and never trusted.** Without one, facts are selected by rule. With one,
  the model may propose; rules decide what is kept. Two models agreeing is not verification.
- **Nothing leaves the machine.** The network is denied by default. A model must run locally.
- **Named human approval is provable.** Identity is established by passphrase (and a second
  factor where configured); a decision needs the passphrase again; the ledger records both.
- **It says what it has not done.** Unvalidated jurisdiction packs, stale status data, unread
  documents and excluded findings are all stated in the report itself.

## The parts

| Part | What it is | Start it with |
|---|---|---|
| Desktop application | Eleven tabs: Matter, Evidence, Chat, DAG, Agents, Findings, Review, Audit Trail, Governance, Sources, Settings | `eli-legal-gui` |
| Server and browser application | The same eleven screens in a browser, over HTTPS, for a chambers, firm or tribunal | `eli-legal serve` |
| Command line | Every operation, for scripted and administrative use | `eli-legal` |
| ELI v3 edition | The same services, presented to ELI v3 as a separately licensed edition | see [ELI v3 integration](../3_architecture/03_eli_v3_integration.md) |

All four call the same application services, so roles, gates, holds and the audit ledger behave
identically whichever is used.

## Legal systems

A legal system is described as data, in a jurisdiction pack: its courts, how it cites authority,
and how a later decision or amendment affects an earlier one. The default is the European Union
pack, which recognises Union law and the decisions of any member state by their European Case
Law Identifier. National packs ship for Ireland, Germany and France; others for England and
Wales, United States federal law, international arbitration instruments, and a generic fallback. A pack contains no rules of law. The law comes from a source
you approve and load. Every pack is marked unvalidated until a lawyer qualified in that system
signs it off, and every report says so.

## Status

| Area | State |
|---|---|
| Whole lifecycle, three profiles, eight packs | Built and tested |
| Desktop application, server, browser application, command line | Built and tested on Linux |
| Installers | Published on the GitHub releases page for Linux (AppImage, `.run`, `.deb`), Windows and macOS. Unsigned; Windows and macOS not yet used by a person |
| Identity: passphrase, lock-out, second factor, step-up for decisions | Built and tested |
| Accuracy on real matters | **Not measured.** Only a synthetic matter has been evaluated |
| Live legal database connector | **None.** One connector reads a corpus you load yourself |
| Jurisdiction packs validated by a qualified lawyer | **None** |
| Conformity assessment under the EU AI Act | **Not done** |
| Encryption at rest, optical character recognition | **Not included** |
| A licence for the software | **Not yet chosen** |

See [Roadmap](04_roadmap.md) for what remains and [Legal overview](../5_legal_and_compliance/01_legal_overview.md)
for what must be settled before use on a real matter.
