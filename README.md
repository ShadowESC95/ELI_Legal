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
| Coverage | Every document is accounted for. | An unread document holds the run until a named person accepts the gap. |
| Facts | Factual statements are taken **word for word** from the documents, with date, party and locator. | — |
| Issues | Issues stated at intake, lifted from the papers, or proposed by a model (labelled as proposed). | — |
| Legal research | Approved sources only. Also lists every authority the parties cite, with the sentence citing it. | An unapproved source cannot be reached. |
| Citation check | Does the authority exist in an approved source? | Not found in a source that is complete for that kind of citation: fails. |
| Current-law check | Is it still good law, for the matter's relevant date, as confirmed recently enough? | Overruled, repealed, wrong version, or stale status: held. |
| Proposition check | Does the source say what it is quoted as saying? | Anything reworded goes to a person; two models agreeing is not verification. |
| Gate | A finding is verified only when **every** check its kind requires has passed. | A held finding holds everything relying on it. |
| Analysis | With a model: arguments open to each party, from verified findings only, attributed by the system. | An argument stating an outcome, or a figure or citation not in its basis, is discarded. |
| Report | Rendered from verified findings; held and excluded findings are shown separately with reasons. | — |
| Human review | A named reviewer approves the exact report version, acknowledging every stated limit. | No reviewer, open hold, changed findings or altered file: no approval. |
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

A party's lawyer cannot be added to a tribunal's matter, and a technical administrator has no
access to any matter.

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

## Install and try it

Installers for Linux (AppImage, `.run`, `.deb`), Windows and macOS are on the
[releases page](https://github.com/ShadowESC95/ELI_Legal/releases); see
[Installation](docs/6_manuals/01_installation.md). From a source checkout:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev,all]'
eli-legal demo                      # a synthetic dispute, start to finish, narrated
./eli_legal.sh                      # the desktop application
eli-legal serve                     # the server and browser application, on this machine
```

## Three ways to use it

| | Start with | For |
|---|---|---|
| Desktop application | `eli-legal-gui` | One person at their own machine |
| Server and browser application | `eli-legal serve` | A chambers, firm or tribunal, over HTTPS |
| Command line | `eli-legal` | Administration and scripted use |

All three show the same screens or commands over the same services: **Matter · Evidence · Chat ·
DAG · Agents · Findings · Review · Audit Trail · Governance · Sources · Laws & Standards ·
Settings**. There
is no general assistant, no shell and no web access in any of them.

## Law and standards

Each matter applies packages of law, regulation and standards: the EU AI Act (Annex III 8(a)),
GDPR, the Council of Europe convention, fair-trial and arbitration due process, national packages,
ISO/IEC 42001, professional guidance, and your organisation's own (imported from JSON, CSV or a
document, approved before use). The model is told their rules, the system enforces what it can,
the reviewer confirms the rest, and the report lists every requirement. See
[docs/6_manuals/11_laws_and_standards.md](docs/6_manuals/11_laws_and_standards.md).

## Models

GGUF files run in process with llama.cpp, as in ELI v2 and v3, and are found in ELI's model
folders; or a model server on this machine; or ELI v3's model when opened from ELI v3.

A GGUF model is placed on the machine by measurement: the graphics and system memory free when it
loads, and the model's own costs read from its file, decide its context and how many layers go on
the graphics card (NVIDIA, AMD, Intel, Apple). What loaded is shown and recorded. The model writes
literally: no manner of its own, no opinion, only what the sources state. See
[docs/6_manuals/12_models.md](docs/6_manuals/12_models.md).

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
(`--tls-cert`/`--tls-key`, or `--self-signed`), and it refuses to start otherwise. It checks the
host name, origin, size and rate of every request before any route runs; uses a cookie scripts
cannot read plus a CSRF value; sends a strict content-security policy; shows all matter content
as text; and cannot be made to read the machine or call out. See
[Server security](docs/4_security/04_server_security.md).

## The command line

```bash
eli-legal init --admin admin                    # asks for the administrator's passphrase
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
```

Every command is in the [command-line reference](docs/6_manuals/07_command_line_reference.md).
A model is optional: without one, facts are selected by rule and no arguments are drafted.

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
  `src/eli_legal/governance/registers` map requirements to controls and say plainly which duties are organisational and
  remain undone. They are aids, to be checked against the official texts, not legal advice.
- **Not validated on real matters.** The evaluation matter is synthetic. Accuracy thresholds on
  representative real matters must be set and met before anyone relies on it.
- **No live legal database.** The one working connector reads a corpus you load yourself. Whether
  a case is still good law is only as reliable as the status data in that corpus.
- **No encryption at rest and no OCR.** Use an encrypted volume; convert scans before ingestion.
- **No licence yet.** The repository has no licence file; all rights are reserved until one is chosen.
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
