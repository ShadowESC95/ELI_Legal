# Administrator manual

For whoever installs and looks after ELI Legal. An administrator manages users, sources, the
model and the installation. **An administrator has no access to any matter**, and cannot give
themselves any: that separation is deliberate.

## 1. After installing

1. Create the first administrator: start the desktop application, or `eli-legal init --admin <id>`.
2. `eli-legal doctor` checks the installation and says what is wrong in plain words.
3. Copy `secrets/audit_hmac.key` from the [data folder](01_installation.md#where-your-data-is) to
   somewhere safe and separate. Without it the ledger cannot be verified and nothing will run.
4. Put the data folder on an encrypted disk. The software does not encrypt it.
5. Set up a second factor for yourself: Settings, You, Second factor; or
   `eli-legal second-factor setup`.

## 2. Users and roles

Every person has their own account. Never share one: the audit trail is only as good as that.

| Do this | Desktop or browser | Command line |
|---|---|---|
| Add a user | Settings, Users and roles, Add a user | `eli-legal user add <id> --name "<name>" --role <role>` |
| Set a first or replacement passphrase | Passphrase… | `eli-legal passphrase <id>` |
| Unlock after failed sign-ins | Unlock | `eli-legal unlock <id>` |
| Remove a lost second factor | Reset second factor | `eli-legal second-factor remove <id>` |
| Deactivate a leaver | Deactivate | `eli-legal user deactivate <id>` |
| Issue a token for a program | Create an API token | `eli-legal user token <id>` |

A new user cannot sign in until an administrator sets their first passphrase. Tell them to change
it at once. Setting someone's passphrase or removing their second factor ends their sessions.
Deactivating a user stops their sessions and tokens; their past actions stay in the ledger.

### Roles

| For | Roles | Can work on |
|---|---|---|
| Decision-makers | `judge`, `tribunal_member`, `arbitrator`, `tribunal_secretary` | Adjudicator matters |
| Neutrals | `mediator`, `conciliator` | Neutral-facilitator matters |
| Party representatives | `supervising_solicitor`, `solicitor`, `barrister`, `in_house_counsel`, `paralegal` | Party-representative matters |
| Oversight | `legal_admin`, `governance_officer`, `auditor`, `reviewer`, `read_only` | Any matter they are added to, within their role |
| System | `system_admin` | No matter. Users, configuration, audit verification |

A role alone gives nothing on a matter: the person must also be added to it by its lead, and
their role must fit the matter's profile. A party's lawyer cannot be added to a tribunal's matter.
Settings, "What each role can do" shows exactly what each role may do, in plain words.

### Roles on a matter, and what each person may read

Three things decide what someone may do on a matter, and all three must agree:

1. their **account role** (above): what they may do anywhere;
2. their **role on the matter**, chosen when they are added: it can only narrow the account role;
3. their **clearance**: which of the matter's material they may read.

| Role on a matter | Does | Reads |
|---|---|---|
| Lead | Everything, including choosing the team, sources and laws. The person who opened the matter always leads it. | Everything |
| Decision-maker | Resolves holds, reviews, approves, releases, stops the work | Everything |
| Case worker | Adds documents, runs the analysis, records checks; approves nothing | All but the neutral's own notes |
| Assistant | Adds documents, starts the analysis | Material before all parties, and privileged work |
| Observer | Reads | Material before all parties, with contact, bank, card and identity numbers masked |
| Auditor | Reads and verifies the matter's audit trail; exports its evidence pack | No document content or findings |
| One party's representative | Files papers for the party they act for; answers holds on that party's filings | What is served on all parties, and their own side's papers; none of the tribunal's analysis |

**Everyone in a case signs in with their own account.** On a court's, tribunal's or neutral's
matter, the people of each party (a prosecutor, the defence, a claimant's or respondent's
solicitor or barrister, in-house counsel, a paralegal, or a party acting for themselves, account
role *Party acting for themselves*) join as **one party's representative**, always acting for a
named party. Give them an account (`eli-legal user add pat --name "Pat Byrne" --role prosecutor`,
then `eli-legal passphrase pat`), then add them to the matter:
`eli-legal matter grant M pat --acts-for "The People"` (the role on the matter is *party* by
itself), or **Grant access…** on Case details, which asks which party they act for. They sign in
to the server from their own machine and see only their side's pages (see the
[Web application and server](06_web_application_and_server.md#everyone-in-the-case)). They are
never a named reviewer and decide nothing.

Someone who **acts for a party** never sees what another party gave in confidence. The lead may
widen or narrow anyone's clearance (`eli-legal matter role M USER --reads …`, or the Case details page).
Whatever a person is not cleared for is withheld everywhere it could appear (lists, passages,
findings, chat, the report, warnings, the evidence pack), with the reason, never the content, and
every attempt to read it is recorded. A named reviewer must hold a role on the matter that can
approve. People added before roles on a matter existed keep exactly what their account allowed.

Oversight roles (legal administrator, governance officer, auditor) see a list of every matter in
Governance, "All matters"; a matter they are not on shows no name, party or content.

## 3. Legal sources

Nothing can be searched that is not on the approved-source register.

1. **Register** the source: who publishes it, the licence and whether it permits this use, that
   you have read the terms, how it reports whether an authority is still good law, how often it
   is updated, and which citation forms it is complete for.
2. **Approve** it. This is a decision in your name. It is refused if the owner, licence or status
   semantics are missing. **Do not record that terms were reviewed unless they were**: most
   commercial databases forbid this use. See
   [Liability, IP and licensing](../5_legal_and_compliance/05_liability_ip_and_licensing.md).
3. **Load** a corpus. On the server, put the files in a folder inside `imports/` in the data
   folder and name that folder. The format is in the
   [Source connector standard](../3_architecture/04_source_connector_standard.md).
4. Each matter then chooses which approved sources it uses.

**Live official databases.** `eli-legal source add-live eu_cellar --terms-reviewed` (the EU's
Publications Office and EUR-Lex) or `uk_open` (legislation.gov.uk and Find Case Law) registers
one with its publisher, licence and hosts already declared; approve it as above. It looks up
each authority a matter relies on when first needed, judges legislation on the version in force
on the matter's relevant date, and keeps what it fetched for 24 hours. It reaches only its own
hosts, and nothing under hard offline. No open database records whether a judgment was later
overruled: that goes to a person. Find Case Law's licence needs a further licence from the
National Archives for computational analysis; obtain it before approving `uk_open` for that use.

"Complete for" matters: if a source is recorded as complete for a citation form and a citation in
that form is not found, the system treats the authority as possibly non-existent and holds it. If
you over-state completeness you will get false alarms; if you under-state it, missing cases pass
as merely "not found here".

Status goes stale. Each legal system's pack sets how old a status confirmation may be (thirty
days by default). Refresh the corpus at least that often, or users will see every authority held.

## 4. The model

Optional. Without one the system does everything except draft arguments and summarise chat
answers.

- It must run on the same machine and speak the OpenAI-compatible API (Ollama and llama.cpp do).
  A model on any other machine is refused.
- Set it in Settings, Model, or with `ELI_LEGAL_INFERENCE=openai_compat`,
  `ELI_LEGAL_INFERENCE_URL` and `ELI_LEGAL_INFERENCE_MODEL` in `.env` in the data folder.
- A second, different model can be named as verifier. The same model cannot check itself.
- Changing the model is a recorded decision. Monitoring then flags the change: complete a change
  assessment and re-run your evaluation before relying on the new one.
- Read the model's licence. Some restrict professional or commercial use.

## 4a. Searching by meaning

Research finds passages by the words of each issue and, with an embedding model, also by their
meaning; facts are linked to the issues they bear on the same way. It runs on this machine. It
decides only which passages are offered and which facts are filed under an issue: everything is
quoted word for word and checked as before.

- **Setting it up.** Put an embedding model in GGUF form in a model folder (bge-small-en-v1.5
  and nomic-embed-text-v1.5 were measured). `ELI_LEGAL_EMBEDDING_MODEL` is `auto` by default
  (the first one found), a file path, or `none`.
- **Embedding a corpus.** Passages are embedded when a run first needs them, at most
  `ELI_LEGAL_EMBEDDING_BUDGET` (20,000) in one run; the report says when part of a source was
  not yet covered. `eli-legal source index <source>` embeds a source ahead of any run.
- **What a run records.** The model and its file's fingerprint are the run's retrieval and
  linking tools. Changing the model is a change monitoring flags between runs: assess it and
  re-run the benchmarks before relying on it.
- **Measuring it.** `eli-legal evaluate` runs the research benchmark (70 issues over fifteen EU
  and UK instruments) and the linking benchmark (50 facts in four disputes) with the model
  configured, or another with `--embedding <file>`. As measured for 0.8:

  | Research | recall at 10 | MRR | nDCG at 10 | governing provisions offered | closest passage in point |
  |---|---|---|---|---|---|
  | By words (0.7) | 0.66 | 0.54 | 0.51 | 34% | 40% |
  | By words (0.8) | 0.66 | 0.60 | 0.54 | 44% | 40% |
  | By words and meaning, bge-small | 0.76 | 0.70 | 0.64 | 60% | 67% |
  | By words and meaning, nomic | 0.74 | 0.68 | 0.62 | 52% | 54% |

  "Closest passage" is the passage shown beside what a party says of an authority: whether,
  in each instrument that governs an issue, the passage closest to it is in point.

  | Linking facts to issues | precision | recall | F1 |
  |---|---|---|---|
  | By words | 0.62 | 0.10 | 0.17 |
  | By words and meaning, bge-small | 0.58 | 0.36 | 0.44 |
  | By words and meaning, nomic | 0.65 | 0.44 | 0.52 |

  The benchmarks are written for this software and are not real matters. Measure on your own
  annotated matters before relying on a figure.

## 5. The server

See [Web application and server](06_web_application_and_server.md) and
[Server security](../4_security/04_server_security.md). In short: one machine needs nothing; a
team needs TLS and gets a second factor required by default.

## 6. Settings

Settings are environment variables beginning `ELI_LEGAL_`, or lines in `.env` in the data folder.
`.env.example` in the source tree lists them. The ones most often changed:

| Setting | Default | Meaning |
|---|---|---|
| `ELI_LEGAL_HOME` | per-user data folder | Where everything is kept |
| `ELI_LEGAL_DEFAULT_JURISDICTION` | `EU` | Offered first when opening a matter |
| `ELI_LEGAL_SESSION_HOURS` | 8 | Command-line session length |
| `ELI_LEGAL_LOCKOUT_THRESHOLD`, `ELI_LEGAL_LOCKOUT_MINUTES` | 5, 15 | Failed attempts before a lock, and its length |
| `ELI_LEGAL_SERVER_PORT` | 8443 | |
| `ELI_LEGAL_SERVER_IDLE_MINUTES`, `ELI_LEGAL_SERVER_SESSION_HOURS` | 30, 8 | Browser session limits |
| `ELI_LEGAL_SERVER_REQUIRE_SECOND_FACTOR` | `auto` | `auto` requires it when other machines can connect |
| `ELI_LEGAL_SERVER_MAX_UPLOAD_MB` | 250 | Largest file |

A policy file can tighten what roles may do. It cannot switch off human release, the fail-closed
audit or matter isolation: the program refuses to start with such a file.

## 6a. Hard offline

Hard offline makes the computer's kernel refuse every network connection ELI Legal makes: from
Python code, from native code such as llama.cpp, through io_uring, and from any program it
starts. It is stronger than the network guard, which only intercepts Python's own sockets, and
than a switch inside the program: nothing running in ELI Legal can undo it.

| Do this | Desktop or browser | Command line |
|---|---|---|
| Go hard offline now, until ELI Legal closes | Settings, System, "Go hard offline now" (someone who manages the configuration: it cuts every legal source for everyone) | `eli-legal network offline` |
| Start or stop the server for everyone on a case | Settings, System, Server (an administrator, a judge, a tribunal member or an arbitrator; passphrase again) | `eli-legal serve` |
| Start hard offline every time | Settings, System, "Start hard offline every time" (needs the right to manage the configuration and your passphrase) | `eli-legal network at-start on` |
| See what enforces it | The header, and Settings, System | `eli-legal network status` |

| System | Enforced by | Notes |
|---|---|---|
| Linux (x86-64, ARM64) | A seccomp filter on every thread | Applied at once; lasts until the program exits; every child process inherits it |
| macOS | The kernel sandbox | Applied when the program starts: switched on mid-session it is the program's own guard until the next start, and the header says so |
| Windows | An outbound Windows Defender Firewall rule for the program | Needs an administrator once; removed when it is switched off |

While it is on: local GGUF models keep working; live legal sources and a model server (even
one on this machine) do not. The server binds its port first, so it keeps answering on it.
Switching "every time" off takes effect at the next start.

## 7. Backups

Back up, together and while the program is stopped or idle:

- `data/` (both databases and the document vault),
- `secrets/` (the audit key),
- `artifacts/` (reports, evidence packs),
- `.env` and `config/` if you have them.

Keep one copy of the audit key separately from the databases. Someone who holds both the ledger
and the key can rewrite history; someone who holds neither cannot run the system.

**Checkpoints.** Record of actions, Download a checkpoint (or `eli-legal audit checkpoint --out <file>`)
writes a signed statement of where the ledger stands. Keep it off the machine. Verifying against
it later (`eli-legal audit verify --against <file>`) detects a restore from an older backup, which
the chain alone cannot. Take one at least weekly and after every approval.

**Restoring.** Stop the program, restore all four together, start, and verify the chain against
your latest checkpoint. If it does not verify, treat it as an incident.

## 8. Routine checks

The system checks itself every day (the setting `ELI_LEGAL_CHECKS_EVERY_HOURS`, default 24; 0
switches the schedule off). The desktop application runs them soon after sign-in when they are
due; the server runs them on a thread of its own while it is up. Where neither is running all
day, run them from cron or a systemd timer as the account that owns the data:

```bash
eli-legal checks run --as-system      # exit status 1 when anything needs attention
```

| Check | What it looks at | What it does on its own |
|---|---|---|
| Audit trail intact | Every signature and link of the ledger | — |
| Governance registers consistent | Controls, tests, risks, requirements and organisation actions link up | — |
| Authorities still good law | Every authority relied on in each open matter's latest run, judged exactly as a run would judge it today; a person's recent confirmation stands | For an **approved** report, opens one incident per authority |
| Law and standards up to date | When each package in use was last checked against its official text (180 days by default, `ELI_LEGAL_LAW_REVIEW_DAYS`), and dates in the law calendar coming into application | — |
| Legal sources current | How old each source's status information is | — |
| Stored documents unaltered | Every stored original against the hash it was filed with | Opens a **serious** incident |
| Organisation's compliance work | Organisation actions not recorded or due for review | — |
| People and sign-in | Missing passphrases, locked accounts, reviewers without training or a second factor | — |
| Retention | Closed matters past their retention period | **Deletes** their documents, text and indexes, once, keeping the record |
| Holds and incidents | Holds open more than 14 days; serious incidents and their Art. 73 deadline | — |

Results are on the Home page and in Governance, "Routine checks"; `eli-legal checks show` prints
them. Someone not on a matter is told only that a matter they are not on needs attention.

Still for a person:

| How often | Do |
|---|---|
| Weekly | Take an audit checkpoint and keep it off this machine; confirm the backup restores |
| When the checks say a law package is due | Check it against the official text and record it (Laws & Standards, "Confirm checked against the official text", or `eli-legal framework current`) |
| Monthly | Import a current copy of each legal source; remove leavers; review who is on which matter |
| On any change of model, version or policy | The change assessment (organisation action OA-22); run the evaluation (OA-07) |
| On upgrade | Back up first; `eli-legal doctor` and `eli-legal governance` afterwards |

## 9. Closing matters and retention

Closing a matter ends access to it. With "also delete the documents", the documents, extracted
text and search indexes are removed at once; the decision record and the ledger are kept.

Set the retention periods in Governance, "Organisation actions", OA-09 (or `eli-legal compliance
retention --audit-days N --closed-days N`). The audit trail must be kept at least six months
(EU AI Act Art. 19(1) and 26(6)) and is never shortened by the software: the ledger is permanent
by design and holds identifiers, hashes and user identities, not document text. A closed matter's
documents are deleted by the routine checks when its period ends.

## 9a. The organisation's compliance work

Governance, "Requirements" shows every requirement of the instruments that apply and where it
stands: **met by the software**, **met** (the software's part and your organisation's recorded
part), **waiting for your organisation**, or **review due**. What the software cannot do is a list
of **organisation actions** (Governance, "Organisation actions"; `eli-legal compliance actions`):
classifying the deployment, the impact assessment, training, the risk review, the technical
documentation (drafted for you from the system's records), the instructions for use, the accuracy
evaluation (run for you on a matter with known defects), retention, oversight, the conformity
assessment, the declaration (drafted for you), registration, and the rest. Each is recorded in a
named person's name, with their passphrase, and falls due for review on its own date. Recording
needs the governance officer or legal administrator role. See
[Compliance and routine checks](13_compliance_and_routine_checks.md).

## 10. If something goes wrong

Follow the [Operations runbook](09_operations_runbook.md). The short version: if the audit chain
does not verify, stop everything, preserve both databases and the key as they are, and
investigate before anyone works on a matter again.
