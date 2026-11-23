# API reference

Generated from the server's routes by `scripts/generate_reference_docs.py`. Do not edit by hand.

The server exposes 106 operations under `/v1`, plus `/health` and the browser application at `/`.
It has no other routes: no general assistant, no shell, no device or media control, no plug-ins.

## Conventions

- **Credentials.** Either the session cookie set by `POST /v1/auth/login` (browsers), or
  `Authorization: Bearer <token>` (programs). Nothing else is accepted.
- **Changing anything from a browser session** also needs the header `X-ELI-CSRF`, whose value
  is returned by sign-in and by `GET /v1/auth/session`.
- **Decisions.** Resolving a hold, recording a check, reviewing, restarting, releasing, closing a
  matter, approving a source, changing the model, managing users and recording compliance work
  or a law package's check need the caller's
  passphrase with the request: `X-ELI-Passphrase`, or `X-ELI-Passphrase-B64` (base64 of the
  UTF-8 text) for passphrases with characters a header cannot carry. Sent without it, such a
  request is answered `401` with `"error": "StepUpRequired"`; send it again with the header.
- **Errors** are JSON: `{"error": "<Name>", "detail": "<why, in plain words>"}`.

| Status | `error` | Meaning |
|---|---|---|
| 400 | `UnknownHost`, `BadRequest` | Wrong host name, or a malformed request |
| 401 | `AuthenticationFailed`, `StepUpRequired`, `SecondFactorRequired` | Not signed in; passphrase needed; code needed |
| 403 | `PolicyDenied`, `MatterAccessDenied`, `CrossOrigin`, `Forbidden` | Not permitted for this role, matter or origin |
| 404 | `NotFound` | No such record in a matter you may see |
| 409 | `VerificationGateFailed`, `InvalidState` | A gate or the state of the run forbids it |
| 411 / 413 | `LengthRequired`, `TooLarge` | Body length not declared, or over the limit |
| 422 | `InvalidInput` | A field is missing, malformed or too long |
| 423 | `AccountLocked` | Too many failed attempts |
| 429 | `TooManyRequests` | Rate limit; see `Retry-After` |

Uploading a document: `POST /v1/matters/{id}/documents?filename=<name>` with the file as the
request body (`Content-Type: application/octet-stream`); optional query fields `party_id`,
`doc_type`, `scope`, `custodian`.

## Signing in and your own account

| Method | Path | Sign-in | What it does |
|---|---|---|---|
| `GET` | `/health` | no | Whether the server is up. Says nothing else to someone who has not signed in. |
| `GET` | `/v1/boundaries` | no | What this system will never do, whoever asks. |
| `POST` | `/v1/auth/login` | no | Sign in with a passphrase, and a code if a second factor is set up. Sets the session cookie and returns the CSRF value. |
| `POST` | `/v1/auth/logout` | no | End the session and clear the cookie. |
| `GET` | `/v1/auth/session` | yes | Who is signed in, their roles, and the CSRF value for this session. |
| `POST` | `/v1/auth/passphrase` | yes | Change your own passphrase. Every session of yours ends, including this one. |
| `POST` | `/v1/auth/second-factor/begin` | yes | Start setting up an authenticator. Returns the key to add to the app. A decision: needs the passphrase. |
| `POST` | `/v1/auth/second-factor/confirm` | yes | Confirm the authenticator with a code it shows. From then on a code is needed at every sign-in. |
| `DELETE` | `/v1/auth/second-factor` | yes | Remove your own second factor. A decision: needs the passphrase. Ends your sessions. |
| `POST` | `/v1/auth/tokens` | yes | A token for a program acting as you. Shown once. |

## Users and roles

| Method | Path | Sign-in | What it does |
|---|---|---|---|
| `GET` | `/v1/users` | yes | Everyone who has an account, with their roles. Administrators also see lock and second-factor state. |
| `GET` | `/v1/roles` | yes | Every role and the actions it permits. |
| `POST` | `/v1/users` | yes | Create a user with roles, and optionally a first passphrase. A decision; administrators only. |
| `POST` | `/v1/users/{user_id}/passphrase` | yes | Set another user's passphrase and end their sessions. A decision; administrators only. |
| `POST` | `/v1/users/{user_id}/deactivate` | yes | Deactivate a user: their sessions and tokens stop working. A decision; administrators only. |
| `POST` | `/v1/users/{user_id}/unlock` | yes | Lift a lock caused by failed sign-ins. A decision; administrators only. |
| `DELETE` | `/v1/users/{user_id}/second-factor` | yes | Remove a user's second factor (lost device). A decision; administrators only. Ends their sessions. |
| `POST` | `/v1/users/{user_id}/tokens` | yes | Issue an API token for another user. Shown once. A decision; administrators only. |

## The installation

| Method | Path | Sign-in | What it does |
|---|---|---|---|
| `GET` | `/v1/system` | yes | What this installation is, for the screens that need to offer choices. |
| `GET` | `/v1/workflow` | yes | The steps as a graph, and each step as an agent with a fixed mandate. |
| `GET` | `/v1/config` | yes | The model in use, the runtime policy and the server's settings. |
| `GET` | `/v1/config/models` | yes | The models that can be chosen: GGUF files found on this machine (by reference, never by path), and those a model server on this machine offers. Only an address on this machine can be asked, so the server cannot be made to call anywhere else. |
| `GET` | `/v1/config/models/{ref}/placement` | yes | How that GGUF model would be placed on this machine if it were loaded now: context, layers on the graphics card, and the reasons. Nothing is loaded or changed. |
| `POST` | `/v1/config/model` | yes | Change the model. A decision, recorded. For GGUF, give the references from the list. |
| `GET` | `/v1/network` | yes | Whether hard offline is on, what enforces it, and whether it is set for every start. |
| `POST` | `/v1/network/offline` | config.manage | Switch hard offline on now: from here until the server stops, the kernel refuses every connection it would open. It keeps answering on its own port. |
| `PUT` | `/v1/network/at-start` | yes | Start hard offline every time, or not. Needs the right to manage the configuration and the passphrase. Switching it off takes effect at the next start. |

## Matters and documents

| Method | Path | Sign-in | What it does |
|---|---|---|---|
| `GET` | `/v1/matters` | yes | The matters you have access to. |
| `POST` | `/v1/matters` | yes | Open a matter under a profile, with its legal system, parties, issues and relevant date. |
| `GET` | `/v1/matters/{matter_id}` | yes | One matter: parties, issues, who has access, the named reviewers, the approved sources. |
| `PATCH` | `/v1/matters/{matter_id}` | yes | Change the relevant date, issues, forum or rules, or add parties. |
| `GET` | `/v1/matters/{matter_id}/members` | yes | Who is on the matter: their role on it, whom they act for, what they may read. |
| `POST` | `/v1/matters/{matter_id}/members/{user_id}` | yes | Give a user access to the matter, optionally in a given role on it and acting for a party. Their account role must fit the matter's profile. |
| `PATCH` | `/v1/matters/{matter_id}/members/{user_id}` | yes | Change a member's role on the matter, the party they act for, or what they read. |
| `DELETE` | `/v1/matters/{matter_id}/members/{user_id}` | yes | Remove a user's access to the matter. |
| `PUT` | `/v1/matters/{matter_id}/reviewers` | yes | Name the people who must approve before anything is relied on. |
| `PUT` | `/v1/matters/{matter_id}/sources` | yes | Choose which approved legal sources this matter may use. |
| `POST` | `/v1/matters/{matter_id}/close` | yes | Close the matter, optionally deleting its documents and extracted text. The audit trail is kept. A decision. |
| `GET` | `/v1/matters/{matter_id}/documents` | yes | The documents filed in the matter, with what was read, what was not, and what was flagged. |
| `POST` | `/v1/matters/{matter_id}/documents` | yes | File a document. The body is the file itself; its name and filing details are in the query. It is stored once, read-only, addressed by its SHA-256, and then read. |
| `GET` | `/v1/matters/{matter_id}/documents/{document_id}/passages` | yes | A document as the located passages every finding points back to. |
| `POST` | `/v1/matters/{matter_id}/chat` | yes | Ask about the matter. The answer is its sources; nothing can be decided here. |
| `GET` | `/v1/matters/{matter_id}/frameworks` | yes | The packages applied to a matter, and exactly what the model is told about them. |
| `PUT` | `/v1/matters/{matter_id}/frameworks` | yes | Choose the packages that apply to a matter, from its next run. |
| `GET` | `/v1/matters/{matter_id}/guide` | yes | Where the matter stands, your role on it, what you read, and what to do next. |

## Audit and governance

| Method | Path | Sign-in | What it does |
|---|---|---|---|
| `GET` | `/v1/audit/events` | yes | The ledger for a matter, or (with the right) the events that belong to none: sign-ins, users, sources, configuration. Identifiers and hashes only; never document text. |
| `GET` | `/v1/audit/verify` | yes | Verify every signature and link of the audit chain. |
| `POST` | `/v1/audit/checkpoint` | yes | A signed statement of where the chain stands now, to keep somewhere else. |
| `GET` | `/v1/governance/registers` | yes | The names of the governance registers. |
| `GET` | `/v1/governance/registers/{name}` | yes | One register as rows: requirements, controls, risks or responsibilities. |
| `GET` | `/v1/monitoring` | yes | Monitoring figures computed from control evidence, with any alerts. |

## Approved legal sources

| Method | Path | Sign-in | What it does |
|---|---|---|---|
| `GET` | `/v1/sources` | yes | The approved-source register. |
| `POST` | `/v1/sources` | yes | Register a legal source. It cannot be used until approved. |
| `POST` | `/v1/sources/{source_id}/approve` | yes | Approve a source for use. Refused unless its owner, licence and status semantics are recorded. A decision. |
| `POST` | `/v1/sources/{source_id}/revoke` | yes | Withdraw a source's approval. |
| `POST` | `/v1/sources/{source_id}/import` | yes | Load a corpus from a folder on the server. Only folders inside the import area can be named, so this cannot be used to read anything else on the machine. |
| `GET` | `/v1/sources/{source_id}/authorities` | yes | What a source holds: each authority with its citation and current status. |
| `GET` | `/v1/authorities/{authority_id}` | yes | The text of one authority as located passages. |

## Law and standards packages

| Method | Path | Sign-in | What it does |
|---|---|---|---|
| `GET` | `/v1/frameworks` | yes | Every law and standards package, with its standing: usable or not, and why. |
| `GET` | `/v1/frameworks/recommended` | yes | The packages recommended for a kind of matter in a legal system. |
| `GET` | `/v1/frameworks/{pack_id}` | yes | One package in full: every requirement and how the system meets it. |
| `GET` | `/v1/frameworks/{pack_id}/export` | yes | The package as JSON, to edit and import again as the organisation's own. |
| `POST` | `/v1/frameworks/upload` | yes | Import a package: JSON, a CSV requirements register, or a document of the organisation's rules. The body is the file. It cannot be used until approved. |
| `POST` | `/v1/frameworks/{pack_id}/approve` | yes | Approve an organisation's package for use. A decision. |
| `POST` | `/v1/frameworks/{pack_id}/validate` | yes | Record that a qualified lawyer checked this exact version against its source. A decision. |
| `POST` | `/v1/frameworks/{pack_id}/withdraw` | yes | Stop a package being applied to any matter from the next run. |
| `POST` | `/v1/frameworks/{pack_id}/reinstate` | yes | Allow a withdrawn package again. A decision. |
| `DELETE` | `/v1/frameworks/{pack_id}` | yes | Delete an organisation's package. |
| `POST` | `/v1/frameworks/{pack_id}/current` | yes | Record that you checked a law package against its official text. A decision. |

## What to do next, compliance and the routine checks

| Method | Path | Sign-in | What it does |
|---|---|---|---|
| `GET` | `/v1/words` | yes | The words the system uses for its states, checks, holds, roles and scopes, so every screen says the same thing the same way. |
| `GET` | `/v1/home` | yes | What is waiting for you on every matter you are on, the latest routine checks as you may see them, and where compliance stands. |
| `GET` | `/v1/compliance` | yes | Every requirement and where it stands; every organisation action, its form and its latest record. |
| `POST` | `/v1/compliance/actions/{action_id}` | yes | Record an organisation action as done (a form, a statement, a registration number), or as not applying, with reasons. A decision: send your passphrase. |
| `POST` | `/v1/compliance/retention` | yes | Set how long the audit trail and a closed matter's documents are kept. |
| `GET` | `/v1/compliance/training` | yes | Training records, and who works on matters without a current one. |
| `POST` | `/v1/compliance/training` | yes | Record training a person has completed. |
| `POST` | `/v1/compliance/evaluation` | yes | Run the accuracy evaluation on the planted-defect matter, against the thresholds. |
| `POST` | `/v1/compliance/documents/{kind}` | yes | Draft the Annex IV documentation (annex_iv) or the declaration (declaration). |
| `POST` | `/v1/compliance/actions/{action_id}/sign-off` | yes | Sign off a drafted document by its SHA-256, once completed and reviewed. |
| `GET` | `/v1/checks` | yes | The latest routine checks as you may see them, and when the earlier ones ran. |
| `POST` | `/v1/checks/run` | yes | Run the routine checks now. |
| `GET` | `/v1/oversight/matters` | yes | Every matter, for those who oversee the system; content withheld where you are not on the matter. |
| `GET` | `/v1/notifications` | yes | Your notifications still waiting on you, unseen first, with the count unseen: holds to clear, a restart, a report to review, returned or suspended. |
| `POST` | `/v1/matters/{matter_id}/notifications/{notification_id}/read` | yes | Mark one of your own notifications as seen; it stays until the work is done. |
| `POST` | `/v1/notifications/read` | yes | Mark all your notifications as seen. |

### Reports released to you

| Method | Path | Sign-in | What it does |
|---|---|---|---|
| `GET` | `/v1/released` | yes | The reports released to you, newest first, and whether each can be opened now and why not. |
| `GET` | `/v1/matters/{matter_id}/released/{release_id}?format=md\|docx\|pdf` | yes | A copy of a report released to you, stamped with your name; refused unless you are a confirmed recipient still on the matter, the report is not suspended, and its file still matches the approved SHA-256. Recorded. |

### A party's own pages

For someone on a matter as one party's representative (prosecution, defence, a party's lawyers, a
party acting for themselves). Every other matter route refuses them.

| Method | Path | Sign-in | What it does |
|---|---|---|---|
| `GET` | `/v1/party/cases` | yes | The cases on which you act for a party, and how many of your side's filings wait for your answer. |
| `GET` | `/v1/party/cases/{matter_id}` | yes | One case as your side sees it: the parties, the papers you may read, and holds on your side's filings with any answers. |
| `POST` | `/v1/party/cases/{matter_id}/filings?filename=…&doc_type=…&title=…&confidential=…` | yes | File a paper (the body is the file) for the party you act for; served on all parties, or with `confidential=true` for the tribunal only. |
| `GET` | `/v1/party/cases/{matter_id}/filings/{document_id}/passages` | yes | A paper's text, passage by passage, if you may read it. |
| `POST` | `/v1/party/cases/{matter_id}/holds/{hold_id}/answer` | passphrase | Answer a hold on your side's filing: `kind` `refiled` (with `replacement_document_id`), `withdraw` or `explain`, and `reasons`. The tribunal decides the hold. |

## Runs, findings, review and release

| Method | Path | Sign-in | What it does |
|---|---|---|---|
| `POST` | `/v1/matters/{matter_id}/runs` | yes | Start a run. It executes on the server; ask for the run to watch it progress. |
| `GET` | `/v1/matters/{matter_id}/runs` | yes | The runs of a matter. |
| `GET` | `/v1/matters/{matter_id}/runs/{run_id}` | yes | One run: every step and its outcome, findings by status, open holds, open checks, the report. |
| `POST` | `/v1/matters/{matter_id}/runs/{run_id}/resume` | yes | Restart a held or stopped run, with reasons. A decision. Continues on the server. |
| `POST` | `/v1/matters/{matter_id}/runs/{run_id}/stop` | yes | Stop a run, with reasons. |
| `GET` | `/v1/matters/{matter_id}/runs/{run_id}/record` | yes | Does the audit ledger account for everything the store says happened in this run? |
| `GET` | `/v1/matters/{matter_id}/runs/{run_id}/claims` | yes | Every finding of the run, with its source passages and status. |
| `GET` | `/v1/matters/{matter_id}/runs/{run_id}/issues` | yes | The issues in the run: stated at intake, lifted from the papers, or proposed. |
| `GET` | `/v1/matters/{matter_id}/claims/{claim_id}/verifications` | yes | Every check made on a finding, by rule, model or person. |
| `POST` | `/v1/matters/{matter_id}/claims/{claim_id}/verifications` | yes | Record a check made by hand, with what it was checked against. A decision. |
| `GET` | `/v1/matters/{matter_id}/runs/{run_id}/holds` | yes | The holds on the run. Nothing reaches review while one is open. |
| `POST` | `/v1/matters/{matter_id}/runs/{run_id}/hold` | yes | Put a run on hold while it waits for review or once approved (suspending reliance and its release), with reasons. A decision; lifting it needs someone who may resolve holds. |
| `POST` | `/v1/matters/{matter_id}/holds/{hold_id}/resolve` | yes | Close a hold by a named decision, `exclude` or `waive` (or `lift`, for a run a person put on hold), with reasons. A decision. |
| `GET` | `/v1/matters/{matter_id}/runs/{run_id}/tasks` | yes | Checks waiting for a person. |
| `GET` | `/v1/matters/{matter_id}/runs/{run_id}/report` | yes | The report text, its SHA-256, its release state and the limits a reviewer must acknowledge. |
| `GET` | `/v1/matters/{matter_id}/runs/{run_id}/report.md` | yes | The report as a Markdown file. |
| `POST` | `/v1/matters/{matter_id}/runs/{run_id}/review` | yes | The named reviewer's decision on this exact version of the report. |
| `POST` | `/v1/matters/{matter_id}/runs/{run_id}/releases` | yes | Stage an approved report for named recipients; says which are entitled to this matter. |
| `POST` | `/v1/matters/{matter_id}/releases/{release_id}/send` | yes | Stage the approved report for the confirmed recipients. Nothing leaves this system. |
| `POST` | `/v1/matters/{matter_id}/runs/{run_id}/evidence-pack` | yes | The run's evidence pack as one archive: identifiers, hashes, versions, decisions. |

## Incidents

| Method | Path | Sign-in | What it does |
|---|---|---|---|
| `GET` | `/v1/matters/{matter_id}/incidents` | yes | Incidents recorded for the matter. |
| `POST` | `/v1/matters/{matter_id}/incidents` | yes | Open an incident. |
| `POST` | `/v1/matters/{matter_id}/incidents/{incident_id}/close` | yes | Close an incident, recording what contained it and why it can be closed. |
| `POST` | `/v1/matters/{matter_id}/incidents/{incident_id}/reporting` | yes | Decide whether a serious incident must be reported (EU AI Act Art. 73), and record the report. A decision: send your passphrase. |
