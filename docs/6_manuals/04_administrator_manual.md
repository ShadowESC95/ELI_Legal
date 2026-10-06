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

A role alone gives nothing on a matter: the person must also be added to it by someone on it,
and their role must fit the matter's profile. A party's lawyer cannot be added to a tribunal's
matter. `eli-legal show-policy` and Settings show exactly what each role may do.

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

## 7. Backups

Back up, together and while the program is stopped or idle:

- `data/` (both databases and the document vault),
- `secrets/` (the audit key),
- `artifacts/` (reports, evidence packs),
- `.env` and `config/` if you have them.

Keep one copy of the audit key separately from the databases. Someone who holds both the ledger
and the key can rewrite history; someone who holds neither cannot run the system.

**Checkpoints.** Audit Trail, Download a checkpoint (or `eli-legal audit checkpoint --out <file>`)
writes a signed statement of where the ledger stands. Keep it off the machine. Verifying against
it later (`eli-legal audit verify --against <file>`) detects a restore from an older backup, which
the chain alone cannot. Take one at least weekly and after every approval.

**Restoring.** Stop the program, restore all four together, start, and verify the chain against
your latest checkpoint. If it does not verify, treat it as an incident.

## 8. Routine checks

| How often | Check |
|---|---|
| Daily, on a busy system | Governance, Monitoring: any alert |
| Weekly | Verify the audit chain; take a checkpoint; confirm the backup restored somewhere |
| Monthly | Refresh legal-source status; review users and remove leavers; review who is on which matter |
| On any change of model, version or policy | Change assessment; re-run the evaluation |
| On upgrade | Back up first; `eli-legal doctor` and `eli-legal governance` afterwards |

## 9. Closing matters and retention

Closing a matter ends access to it. With "also delete the documents", the documents, extracted
text and search indexes are removed; the decision record and the ledger are kept. Set a retention
period for closed matters and apply it. The ledger is permanent by design and holds identifiers,
hashes and user identities, not document text.

## 10. If something goes wrong

Follow the [Operations runbook](09_operations_runbook.md). The short version: if the audit chain
does not verify, stop everything, preserve both databases and the key as they are, and
investigate before anyone works on a matter again.
