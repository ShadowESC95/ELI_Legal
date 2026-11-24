# ELI Legal

Governed legal case preparation. It takes the papers in a dispute, establishes what is said and by
whom, finds and checks the law, and assembles a source-linked analysis for a named human to
review. It stops before the decision: it renders no verdict, award, recommendation on the merits
or settlement terms.

It is its own product with its own desktop application, command line and API. It can also be
loaded by **ELI v3** as a separate edition (an add-on that can be licensed on its own or bundled).

**Status: working software, not an assured product.** Everything described below runs and is
tested, and a full synthetic dispute goes from ingestion to approved release (`eli-legal demo`).
What has *not* been done is listed under [What this is not](#what-this-is-not): no conformity
assessment, no validation on real matters, no jurisdiction pack validated by a qualified lawyer,
and no connector to a live legal database.

## What it does

```
documents ─▶ ingest ─▶ coverage ─▶ facts ─▶ issues ─▶ evidence map ─┐
                                              │                      ├─▶ gate ─▶ analysis ─▶ report ─▶ final validation
                              legal research ─┴▶ citation ─▶ current law ─▶ proposition ─┘
                                                                                              │
                 named human:  resolve holds · verify · review · approve · release ◀──────────┘
```

| Step | What happens | What can stop it |
|---|---|---|
| Ingest | PDF, DOCX, ODT, RTF, HTML, e-mail and text are read into paragraphs with page/paragraph locators. Originals are stored once, read-only, addressed by SHA-256. | A file that cannot be read is reported, never guessed at. |
| Coverage | Every document is accounted for. | An unread document holds the run until a named person describes it by hand from the original, files a readable copy, or accepts the gap. |
| Facts | Factual statements are taken **word for word** from the documents, with date, party and locator. | — |
| Issues | Issues stated at intake, lifted from the papers, or proposed by a model (labelled as proposed). Facts are filed under the issues they bear on by their words and, with an embedding model, their meaning. | — |
| Legal research | Approved sources only, searched by the words of each issue and, with an embedding model on this machine, by meaning. Also lists every authority the parties cite, with the sentence citing it. | An unapproved source cannot be reached. |
| Citation check | Does the authority exist in an approved source? | Not found in a source that is complete for that kind of citation: fails. |
| Current-law check | Is it still good law, for the matter's relevant date, as confirmed recently enough? | Overruled, repealed, wrong version, or stale status: held. |
| Proposition check | Does the source say what it is quoted as saying? | Anything reworded goes to a person; two models agreeing is not verification. |
| Gate | A finding is verified only when **every** check its kind requires has passed. | A held finding holds everything relying on it. |
| Analysis | With a model: arguments open to each party, from verified findings only, attributed by the system. | An argument stating an outcome, or a figure or citation not in its basis, is discarded. |
| Report | Rendered from verified findings; held and excluded findings are shown separately with reasons. | — |
| Human review | A named reviewer approves the exact report version, acknowledging every stated limit. Nobody approves a run they started: another named reviewer decides. | No reviewer, open hold, changed findings or altered file: no approval. |
| Release | Staged in an outbox for entitled recipients confirmed by a named person. Nothing is sent. | A recipient who is not entitled blocks the release. |

Every step, hold, decision and release is written to a tamper-evident audit ledger. No audit key,
no run.

## Who it is for

A matter is opened under one **profile**, which fixes who may work on it and what the output may
say:

| Profile | Users | Output | May it say who should win? |
|---|---|---|---|
| `adjudicator` | judge, tribunal member, arbitrator, tribunal secretary | bench memorandum | No |
| `neutral_facilitator` | mediator, conciliator | mediation brief (with a shared version that omits anything given in confidence by one party) | No |
| `party_representative` | solicitor, barrister, in-house counsel, paralegal | privileged case-preparation memorandum | A merits assessment is permitted; decision wording never is |

A party's lawyer joins a tribunal's matter only as one party's representative (below), never as
one of the tribunal's team, and a technical administrator has no access to any matter.

Each person on a matter also has a **role on it** (lead, decision-maker, case worker, assistant,
observer or auditor) that can only narrow what their account allows, and a **clearance** for its
material. Anything they are not cleared for (the neutral's own notes, what one party gave in
confidence, privileged work) is withheld from them everywhere it could appear, with the reason,
never the content; someone who acts for one party never sees what another gave in confidence.

Everyone in a case signs in with their own account. On a court's, tribunal's or neutral's matter
the parties' people (prosecution, defence, a claimant's or respondent's lawyers, a party acting for
themselves) join as **one party's representative**: from their own screen on the server they file
their side's papers, read what is served on all parties, and answer holds on their own filings
when they are told an answer is wanted. The tribunal reads the answer and decides; its analysis
is never shown to a party.
Observers and auditors see contact, bank, card and identity numbers masked.

## Which legal systems

Legal systems are data, not code: a **jurisdiction pack** describes a system's courts, how it
cites authority and how a later decision or amendment affects an earlier one. The default is the
**European Union** pack, which recognises Union law and the decisions of any member state by
their European Case Law Identifier. National packs ship for Ireland, Germany and France, and
others for England and Wales, US federal law, international arbitration instruments, and a
generic fallback. They hold structure and citation grammar only, contain no
rules of law, and are marked unvalidated until a lawyer qualified in that jurisdiction signs them
off. The law itself always comes from an approved source. See
[docs/3_architecture/05_jurisdiction_packs.md](docs/3_architecture/05_jurisdiction_packs.md).

## Run on your system

Download from the [latest release](https://github.com/ShadowESC95/ELI_Legal/releases/latest) and
check the file against `SHA256SUMS` first: the builds are not signed. An installed copy asks for a
licence key the first time it starts (an ELI Legal key, or an ELI v3 key that includes it). The
full guide is [Installation](docs/6_manuals/01_installation.md); the command line is explained in
[Using the command line](docs/6_manuals/14_command_line_guide.md).

| | Download | Install | Open the desktop app | Start the server (browser app) | The command line |
|---|---|---|---|---|---|
| **Windows 10/11** | `ELI_Legal-<v>-windows-x64-setup.exe` | Run it (SmartScreen: *More info* → *Run anyway*) | Start menu → **ELI Legal** | In the app: Settings → System → Server; or `eli-legal serve` | Start menu → **ELI Legal command line**, then `eli-legal <command>` |
| **macOS** (Apple silicon / Intel) | `ELI_Legal-<v>-macos-arm64.dmg` / `-x86_64.dmg` | Drag to Applications; first time right-click → **Open** | Applications → **ELI Legal** | In the app: Settings → System → Server; or the command below with `serve` | `"/Applications/ELI Legal.app/Contents/MacOS/eli-legal" <command>` |
| **Ubuntu, Debian** | `eli-legal_<v>_amd64.deb` (or the AppImage) | `sudo apt install ./eli-legal_<v>_amd64.deb` | Applications menu, or `eli-legal-gui` | In the app, or `eli-legal serve` | `eli-legal <command>` |
| **Fedora and other Linux** | `ELI_Legal-<v>-linux-x86_64.run` (or the AppImage) | `sh ELI_Legal-<v>-linux-x86_64.run` | Applications menu, or `eli-legal-gui` | In the app, or `eli-legal serve` | `eli-legal <command>` (in `~/.local/bin`) |
| **Arch Linux** | `ELI_Legal-<v>-linux-x86_64.AppImage` (or the `.run`) | `sudo pacman -S fuse2`, then `chmod +x` the file | `./ELI_Legal-<v>-linux-x86_64.AppImage` | `./ELI_Legal-<v>-linux-x86_64.AppImage serve` | `./ELI_Legal-<v>-linux-x86_64.AppImage <command>` |

The server listens on this machine only (`http://localhost:8443/`) until it is started for the
network with TLS. **Run ELI Legal on one machine that holds the cases and does the work, and let
everyone else use a browser**: the desktop application and a server started from it, or with the
installed program's `serve`, share the same live data. See
[Web application and server](docs/6_manuals/06_web_application_and_server.md).

From a source checkout (developers):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev,all]'
eli-legal demo                      # a synthetic dispute, start to finish, narrated
./eli_legal.sh                      # the desktop application
```

A source checkout keeps its own test data in `./data` of the folder it is run from, not your
installed copy's data; `eli-legal serve` there refuses to serve it while an installed copy's data
exists, unless you pass `--dev-data`.

## Three ways to use it

| | Start with | For |
|---|---|---|
| Desktop application | the ELI Legal menu entry, or `eli-legal-gui` | The machine that holds the cases, and one person at it |
| Server and browser application | Settings → System → Server in the desktop app, or `eli-legal serve` | Everyone else in a chambers, firm, court or tribunal, from a browser, over HTTPS on the network |
| Command line | `eli-legal` | Administration and scripted use |

All three show the same screens or commands over the same services: **Start a new case · How to
use · Home · Case details · Documents · Ask about the case · Progress · Who does each step · Findings · Review and
approve · Record of actions · Compliance · Released to me · Legal sources · Laws and standards ·
Settings**. What anyone does on a case shows on everyone else's open page within about five
seconds, in the desktop application and in the browser. Every
word is explained when the pointer rests on it, and everything can be made larger with Ctrl and +. Home says where the open matter stands, what to do next and who can do it; a new
matter is opened step by step, with its team, reviewers, sources and laws; everything a person
reads is in plain words. There is no general assistant, no shell and no web access in any of them.

## Law and standards

Each matter applies packages of law, regulation and standards: the EU AI Act (Annex III 8(a)),
GDPR, the Council of Europe convention, fair-trial and arbitration due process, national packages,
ISO/IEC 42001, professional guidance, and your organisation's own (imported from JSON, CSV or a
document, approved before use). The model is told their rules, the system enforces what it can,
the reviewer confirms the rest, and the report lists every requirement. See
[docs/6_manuals/11_laws_and_standards.md](docs/6_manuals/11_laws_and_standards.md).

## Compliance and routine checks

Every requirement of the instruments that apply is shown as met by the software, met, waiting for
your organisation, or due for review. What only an organisation can do (classifying the
deployment, the impact assessment, training, the conformity assessment, registration and the
rest) is a list of actions recorded in the application in a named person's name and reviewed on
time; the system drafts the Annex IV documentation and the declaration of conformity from its own
records and runs its own accuracy evaluation. Every day it checks that each authority relied on is
still good law, that each law package was checked against its official text recently, that stored
originals are unaltered, and more, opening an incident where someone may already have relied on
something that changed. See
[docs/6_manuals/13_compliance_and_routine_checks.md](docs/6_manuals/13_compliance_and_routine_checks.md).

## Models

GGUF files run in process with llama.cpp, as in ELI v2 and v3, and are found in ELI's model
folders; or a model server on this machine; or ELI v3's model when opened from ELI v3.

A GGUF model is placed on the machine by measurement: the graphics and system memory free when it
loads, and the model's own costs read from its file, decide its context and how many layers go on
the graphics card (NVIDIA, AMD, Intel, Apple). What loaded is shown and recorded. The model writes
literally: no manner of its own, no opinion, only what the sources state. See
[docs/6_manuals/12_models.md](docs/6_manuals/12_models.md).

## Hard offline

A switch (desktop, browser and command line) makes the operating system's kernel refuse every
network connection ELI Legal makes, from Python code, native code such as llama.cpp, or any
program it starts. On Linux it is a seccomp filter that nothing in the program can remove until it
exits; on macOS the kernel sandbox; on Windows a firewall rule. A server keeps answering on its
own port. See the [administrator manual](docs/6_manuals/04_administrator_manual.md#6a-hard-offline).

## Identity

Roles and matter membership decide what someone may do; that is worthless if anyone can claim to
be them. No front end acts on a typed name:

| Front end | You prove who you are with | A decision also needs |
|---|---|---|
| Desktop application | your passphrase, and a code if you have set up a second factor | your passphrase again |
| Browser | the same; a second factor is required when the server is reachable from other machines | your passphrase again |
| Command line | `eli-legal login` (a session that expires) | your passphrase again |
| API | a bearer token issued to a named user | that user's passphrase with the request |

Five wrong attempts lock an account. Every audit event records how the actor's identity was
established.

## The server

`eli-legal serve` listens on this machine only. To let others connect it must have TLS
(`--tls-cert`/`--tls-key`, or `--self-signed`), and it refuses to start otherwise. It prints the
data folder it serves, and after signing in the browser's header shows which machine and
installation it serves (administrators also see the folder; developer test data is shown in red),
so a server started on the wrong data is plain at once. It checks the
host name, origin, size and rate of every request before any route runs; uses a cookie scripts
cannot read plus a CSRF value; sends a strict content-security policy; shows all matter content
as text; and cannot be made to read the machine or call out. See
[Server security](docs/4_security/04_server_security.md).

## The command line

```bash
eli-legal init --admin admin                    # asks for the passphrase and how long records are kept
eli-legal login admin
eli-legal user add j.murphy --name "Judge Murphy" --role judge
eli-legal passphrase j.murphy                   # the administrator sets the first passphrase
eli-legal source add my-corpus --name "Firm library" --jurisdiction IE --owner "…" \
    --licence "…" --terms-reviewed --status-semantics "…"
eli-legal source approve my-corpus && eli-legal source import my-corpus ./corpus

eli-legal login j.murphy
M=$(eli-legal matter create --name "A v B" --purpose "Bench memorandum" --jurisdiction IE \
      --profile adjudicator --party "A Ltd:claimant" --party "B Ltd:respondent" \
      --issue "Whether …" --relevant-date 2023-04-28)
eli-legal matter reviewers $M j.murphy && eli-legal matter sources $M my-corpus
eli-legal ingest $M ./bundle --party "A Ltd"
eli-legal run start $M              # then: holds, tasks, verify, hold, run resume, review, release
eli-legal status $M                 # where it stands, and what to do next
eli-legal checks show                # the latest routine checks
```

`eli-legal` is the command as the `.deb` and `.run` installers and Windows' *ELI Legal command
line* name it; on macOS it is `"/Applications/ELI Legal.app/Contents/MacOS/eli-legal"`, and with
the AppImage it is the AppImage file itself. See [Using the command line](docs/6_manuals/14_command_line_guide.md);
every command is in the [command-line reference](docs/6_manuals/07_command_line_reference.md).
A model is optional: without one, facts are selected by rule and no arguments are drafted.

## Keeping and protecting the record

Each kind of information is kept for its own period, set at set-up and in Compliance (OA-09): the
audit trail at least six months (six years suggested), and from a case's closing its papers (six
years suggested), its analysis and reports (as long as the papers unless set otherwise), its
evidence packs and its decision record (ten years suggested). A closed case leaves the case list
(File → Closed cases) and each kind of its content is archived under its own key, restored if the
case is reopened, and destroyed for good (its key destroyed) when its period ends, unless a
preservation hold keeps it. Save the databases' key once with `eli-legal database-key --out <file>`
and keep it off the machine. See [the administrator manual](docs/6_manuals/04_administrator_manual.md#9-closing-matters-and-retention).

## Loading it into ELI v3

ELI Legal is a separate package that presents itself in the shape ELI v3's edition registry
defines: a manifest, three policy hooks and its capabilities, advertised through the
`eli.editions` entry point. While it is active, every other host action except conversation and
status is refused, no decision can be taken through the assistant, and capability output carries
no matter content. See [docs/3_architecture/03_eli_v3_integration.md](docs/3_architecture/03_eli_v3_integration.md).

```bash
eli-legal edition verify --eli-root /path/to/ELI_v3.0     # read-only check against a checkout
eli-legal bundle register                                 # let ELI v3 open this copy
```

ELI v3 can open ELI Legal in place of its own window (`eli --bundle legal`, or its start-up
question and Bundles menu).

## What this is not

- **Not legal advice and not a decision-maker.** It prepares; a named, qualified person decides.
- **Not conformity-assessed.** ELI Legal is a high-risk AI system under the EU AI Act (Article
  6(2) and Annex III, point 8(a)); the Chapter III duties apply to it from 2 December 2027 in
  every member state. See [docs/5_legal_and_compliance/02_eu_ai_act.md](docs/5_legal_and_compliance/02_eu_ai_act.md). The registers under
  `src/eli_legal/governance/registers` map requirements to controls, and each duty that is an organisation's is
  an action to record in the application; until it is recorded it shows as waiting. They are aids, to be checked against the official texts, not legal advice.
- **Not validated on real matters.** The evaluation matter is synthetic, and so are the
  benchmarks (`eli-legal evaluate`): 70 issues over fifteen real EU and UK instruments for legal
  research, 50 facts in four disputes for linking facts to issues. On them research by words and
  meaning finds 76% of the provisions in point among the first ten (by words alone 66%), and
  linking reaches F1 0.44 to 0.52. Accuracy thresholds on representative real matters must be
  set and met before anyone relies on it.
- **Live databases for the EU and the UK only, and no case-law citator.** Live connectors reach
  the EU's Publications Office (CELLAR and EUR-Lex) and the UK's legislation.gov.uk and Find Case
  Law, once their licence is read and they are approved. They tell whether legislation is in force,
  from and until when, and what repealed it, on the matter's relevant date. No open database records
  whether a judgment was later overruled, so a judgment's standing goes to a person unless a licensed
  citator is connected; for an EU judgment the person is told which later judgments cite it. Other legal systems use a corpus you load.
- **Keys kept on the same machine.** The databases (SQLCipher) and every case file ELI Legal
  keeps (AES-256-GCM) are encrypted at rest, but their keys are in the `secrets/` folder of the
  same machine (on Windows also tied to the account): they protect copies and backups made without
  that folder, not the machine itself. Use full-disk encryption, and back up `secrets/` apart from
  `data/`. OCR of scans and photographs needs Tesseract installed (and Poppler for PDF pages); the
  installers do not include them.
- **Unsigned installers.** The Windows and macOS builds are made and smoke-tested by the release workflow but have not been used by a person.
- **No single sign-on or hardware keys.** Passphrase, lock-out and one-time codes only.
- **Not penetration-tested.** Keep the server on an internal network.

## Layout

| Path | Contents |
|---|---|
| `src/eli_legal/domain` | models, profiles, policy |
| `src/eli_legal/legal` | citations, facts, issues, research, verifiers, analysis, report |
| `src/eli_legal/governance` | gates, holds, audit completeness, evidence pack, register check |
| `src/eli_legal/workflows` | the workflow runner and the case-preparation steps |
| `src/eli_legal/application` | services: the only thing a front end calls |
| `src/eli_legal/adapters` | parsers, vault, ledger, network guard, sources, inference, ELI v3 |
| `src/eli_legal/gui` | the desktop application |
| `src/eli_legal/api` | the server: security layer, sign-in, routes |
| `src/eli_legal/web` | the browser application |
| `src/eli_legal/edition` | the ELI v3 edition pack |
| `src/eli_legal/config` | default policy, workflow and jurisdiction packs |
| `src/eli_legal/governance/registers` | control, risk and requirement registers, checked against the code in CI |
| `docs/` | [the documentation](docs/README.md): project, requirements, architecture, security, legal and compliance, manuals |
| `packaging/`, `install.sh`, `install.ps1` | installers |
| `tests/` | unit, security, integration, evaluation, edition contract, server, browser, desktop |

## Licence

ELI Legal is proprietary commercial software, © 2026 Jason Fitzgibbon Bridgeman, all rights
reserved. It is licensed only under the ELI End User Licence Agreement and the ELI Legal Product
Schedule, set out in full in [LICENSE](LICENSE) and shipped with every build: a licence to ELI Legal
bought on its own, or an ELI v3 licence that includes it. Third-party components keep their own
licences ([THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)).
