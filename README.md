# ELI Legal

Governed legal case preparation. It takes the papers in a dispute, establishes what is said and by
whom, finds and checks the law, and assembles a source-linked analysis for a named human to
review. It stops before the decision: it renders no verdict, award, recommendation on the merits
or settlement terms.

It runs on its own, and it is also built to be loaded by **ELI v3** as a separate edition (an
add-on that can be licensed on its own or bundled).

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
cites authority and how a later decision or amendment affects an earlier one. Packs ship for
Ireland, England and Wales, the EU, US federal law, Germany, France, international arbitration
instruments, and a generic fallback. They hold structure and citation grammar only, contain no
rules of law, and are marked unvalidated until a lawyer qualified in that jurisdiction signs them
off. The law itself always comes from an approved source. See
[docs/17_JURISDICTION_PACKS.md](docs/17_JURISDICTION_PACKS.md).

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
eli-legal demo                      # a synthetic dispute, start to finish, narrated
```

To work a real matter:

```bash
eli-legal init --admin admin
export ELI_LEGAL_ACTOR=admin
eli-legal user add j.murphy --name "Judge Murphy" --role judge
eli-legal source add my-corpus --name "Firm library" --jurisdiction IE --owner "…" \
    --licence "…" --terms-reviewed --status-semantics "…"
eli-legal source approve my-corpus && eli-legal source import my-corpus ./corpus

export ELI_LEGAL_ACTOR=j.murphy
M=$(eli-legal matter create --name "A v B" --purpose "Bench memorandum" --jurisdiction IE \
      --profile adjudicator --party "A Ltd:claimant" --party "B Ltd:respondent" \
      --issue "Whether …" --relevant-date 2023-04-28)
eli-legal matter reviewers $M j.murphy && eli-legal matter sources $M my-corpus
eli-legal ingest $M ./bundle --party "A Ltd"
eli-legal run start $M              # then: holds, tasks, verify, hold, run resume, review, release
```

`eli-legal --help` lists every command. A model is optional: without one, facts are selected by
rule and no arguments are drafted. To use a local model, set `ELI_LEGAL_INFERENCE=openai_compat`,
`ELI_LEGAL_INFERENCE_URL` (any OpenAI-compatible endpoint on this machine, such as Ollama or
llama.cpp) and `ELI_LEGAL_INFERENCE_MODEL`.

The HTTP API exposes the same services: `uvicorn --factory eli_legal.api.app:create_app`.

## Loading it into ELI v3

ELI Legal is a separate package that presents itself in the shape ELI v3's edition registry
defines: a manifest, three policy hooks and its capabilities, advertised through the
`eli.editions` entry point. While it is active, every other host action except conversation and
status is refused, no decision can be taken through the assistant, and capability output carries
no matter content. See [docs/04_ELI_V3_INTEGRATION.md](docs/04_ELI_V3_INTEGRATION.md).

```bash
eli-legal edition verify --eli-root /path/to/ELI_v3.0     # read-only check against a checkout
```

## What this is not

- **Not legal advice and not a decision-maker.** It prepares; a named, qualified person decides.
- **Not conformity-assessed.** Used by or for a court or tribunal, or similarly in ADR, a system
  like this is listed as high-risk in EU AI Act Annex III point 8(a). The registers under
  `governance/` map requirements to controls and say plainly which duties are organisational and
  remain undone. They are aids, to be checked against the official texts, not legal advice.
- **Not validated on real matters.** The evaluation matter is synthetic. Accuracy thresholds on
  representative real matters must be set and met before anyone relies on it.
- **No live legal database.** The one working connector reads a corpus you load yourself. Whether
  a case is still good law is only as reliable as the status data in that corpus.
- **No encryption at rest and no OCR.** Use an encrypted volume; convert scans before ingestion.

## Layout

| Path | Contents |
|---|---|
| `src/eli_legal/domain` | models, profiles, policy |
| `src/eli_legal/legal` | citations, facts, issues, research, verifiers, analysis, report |
| `src/eli_legal/governance` | gates, holds, audit completeness, evidence pack, register check |
| `src/eli_legal/workflows` | the workflow runner and the case-preparation steps |
| `src/eli_legal/application` | services: the only thing a front end calls |
| `src/eli_legal/adapters` | parsers, vault, ledger, network guard, sources, inference, ELI v3 |
| `src/eli_legal/edition` | the ELI v3 edition pack |
| `src/eli_legal/config` | default policy, workflow and jurisdiction packs |
| `governance/` | control, risk and requirement registers, checked against the code in CI |
| `docs/` | architecture, standards, runbook, instructions for use |
| `tests/` | unit, security, integration, evaluation, edition contract, API |
