# Requirements

Each requirement names the control that meets it. Controls are in the control register
(`src/eli_legal/governance/registers/control_register.csv`), which names the code that carries
each one out and the tests that prove it. `eli-legal governance` fails if a named file or test
does not exist, so this table cannot quietly go stale.

Status: **met** means implemented and tested. **Partly** and **not met** say what is missing.

## 1. Functional

| ID | The system shall | Control | Status |
|---|---|---|---|
| FR-01 | Open a matter under exactly one profile, with parties, issues, governing law, relevant date, approved sources and a named reviewer | C-01, C-14 | Met |
| FR-02 | Accept documents as PDF, DOCX, ODT, RTF, HTML, e-mail and text, keeping each original unaltered and addressed by its SHA-256 | C-05 | Met |
| FR-03 | Record for each document who filed it, what it is, who held it and who may see it | C-05 | Met |
| FR-04 | Read each document into passages with locators a person can follow | C-05 | Met |
| FR-05 | Account for every document: read, or the gap accepted by a named person | C-06 | Met |
| FR-06 | Take facts word for word from documents, with date and party | C-05, C-11 | Met |
| FR-07 | Identify issues and attach the facts that bear on them, noting gaps and conflicts | C-11 | Met |
| FR-08 | Search approved sources only, and list every authority a party cites with the sentence citing it | C-03, C-08 | Met |
| FR-09 | Check, separately, that each authority exists, is still good law for the relevant date, and says what it is quoted as saying | C-08, C-09, C-10 | Met; only as reliable as the source's status data |
| FR-10 | Draft arguments only from verified findings, attributed to a party | C-13 | Met; a model can still misattribute, see instructions for use |
| FR-11 | Assemble the report from verified findings, showing held and excluded findings separately with reasons | C-11, C-13 | Met |
| FR-12 | Answer questions about a matter only from its documents, findings and approved sources | C-32 | Met |
| FR-13 | Require a named human to resolve holds, review, approve and release | C-12, C-14, C-20 | Met |
| FR-14 | Export an evidence pack for any run | C-27 | Met |
| FR-15 | Work for any legal system described by a jurisdiction pack | C-26 | Met structurally; **no pack is validated by a qualified lawyer** |
| FR-16 | Read scanned documents and photographs | C-67 | Met where Tesseract (and Poppler, for PDF pages) is installed; otherwise reported unread and held |
| FR-17 | Query a live legal database | C-60 | **Partly met**: the EU (CELLAR, EUR-Lex) and UK (legislation.gov.uk, Find Case Law) are looked up by citation; research searches what has been fetched or loaded, not the databases themselves |

## 2. Governance

| ID | Requirement | Control | Status |
|---|---|---|---|
| GR-01 | Role, matter membership and matter profile are all needed for any matter action | C-01 | Met |
| GR-02 | No record is readable or writable across matters | C-02 | Met |
| GR-03 | Document and source text is data, never instruction | C-07 | Met |
| GR-04 | A finding is verified only when every check its kind requires has passed | C-11 | Met |
| GR-05 | A failed, conflicting, inconclusive or missing check holds the finding and what relies on it | C-11, C-12 | Met |
| GR-06 | A system identity can hold no role: it cannot review, approve, resolve or release | C-14 | Met |
| GR-07 | No reviewer, no run. No approval, no release. No audit key, no run | C-14, C-16, C-20 | Met |
| GR-08 | Approval binds to the exact report reviewed, with every stated limit acknowledged | C-14, C-15 | Met |
| GR-09 | The audit chain and the run's record must both verify before approval | C-16, C-17 | Met |
| GR-10 | Logs carry identifiers and hashes, not content | C-18 | Met |
| GR-11 | A run can be stopped, and restarts only by a named, authorised person with a reason | C-19 | Met |
| GR-12 | A policy file may tighten these rules and cannot switch them off | C-24 | Met |
| GR-13 | No output states a decision; for decision-makers and neutrals, none says who should succeed | C-13 | Met by rule; wording outside the rules' reach is possible |
| GR-14 | Incidents are recorded and closed only with containment and reasons | C-21 | Met |
| GR-15 | Monitoring is computed from control evidence | C-22 | Met |
| GR-16 | Closing a matter ends access and can delete content while keeping the decision record | C-23 | Met |
| GR-17 | The report marks every authority found by research that no party cited | C-42 | Met |

## 3. Identity and access

| ID | Requirement | Control | Status |
|---|---|---|---|
| IA-01 | No action on a name alone: identity is established by a credential on every front end | C-29 | Met |
| IA-02 | A decision needs the person's passphrase again | C-30 | Met |
| IA-03 | Every audit event records how identity was proved | C-31 | Met |
| IA-04 | Repeated wrong passphrases or codes lock the account; only an administrator unlocks | C-38 | Met |
| IA-05 | A second factor is available to every user and required where the server is reachable from other machines | C-39 | Met (one-time codes; no hardware keys) |
| IA-06 | Passphrases and tokens are stored only as salted hashes or hashes | C-29 | Met |
| IA-07 | Single sign-on with an organisation's identity provider | — | **Not met** |

## 4. Server

| ID | Requirement | Control | Status |
|---|---|---|---|
| SV-01 | Serve only legal and governance functions; no route answers without credentials except health, boundaries, the page and sign-in | C-28, C-40 | Met |
| SV-02 | Listen on this machine only unless told otherwise; never beyond it without TLS | C-35 | Met |
| SV-03 | TLS 1.2 or later | C-35 | Met |
| SV-04 | Browser sessions in an HttpOnly, SameSite=Strict cookie; changes need a CSRF value; idle and absolute time-outs | C-36 | Met |
| SV-05 | Refuse unknown host names, cross-site changes, undeclared or oversized bodies, and excessive request rates | C-37 | Met |
| SV-06 | Send a strict content-security policy and related protections on every response; allow no other origin to read a response | C-37 | Met |
| SV-07 | Show all matter content in the browser as text, and load nothing from any other site | C-40 | Met |
| SV-08 | Disclose no server path; give no way to read outside the import area or to call another machine | C-40 | Met |
| SV-09 | Carry the whole lifecycle, with runs executing in the background as the person who started them | C-41 | Met |
| SV-10 | More than one server process, or high availability | — | **Not met**: one process, one database |

## 5. Security and privacy

| ID | Requirement | Control | Status |
|---|---|---|---|
| SP-01 | Outbound network refused by default | C-04 | Met |
| SP-02 | A model runs on this machine only, and changing it is a governed decision | C-33 | Met |
| SP-03 | Legal sources are reachable only if registered and approved | C-03 | Met |
| SP-04 | Text addressed to a model is flagged, held and kept out of every prompt | C-07 | Met for known patterns |
| SP-05 | Edits, removals and truncation of the audit ledger are detected | C-16 | Met |
| SP-06 | Encryption at rest | — | **Not met**: use an encrypted volume |
| SP-07 | Malware scanning of uploads | — | **Not met**: files are parsed, never executed; scan them before filing |

## 6. Installation and operation

| ID | Requirement | Status |
|---|---|---|
| IN-01 | An installer that needs nothing else installed | Met: Linux (AppImage, `.run`, `.deb`), Windows (setup program), macOS (disk image), built and smoke-tested by the release workflow. Windows and macOS have not been used by a person |
| IN-02 | Program and data kept apart; uninstalling never removes data | Met |
| IN-03 | An installer whose integrity can be checked before it runs | Met (`--verify`, `SHA256SUMS`); builds are **not signed** |
| IN-04 | Nothing starts by itself: no service, port or network call | Met |
| IN-05 | Installable from source wherever Python 3.10 runs | Met on Linux; scripted and untested on Windows |
| IN-06 | Runs with no ELI installed, and loads into ELI v3 as an edition | Met (C-25); the v3 loader change is proposed, not applied |

## 7. Quality

| ID | Requirement | Status |
|---|---|---|
| QA-01 | Re-running a matter reproduces the same findings and keeps human decisions | Met (C-19) |
| QA-02 | Every control is tied to code and to tests, checked automatically | Met |
| QA-03 | Declared accuracy on representative real matters | **Not met**: see the [evaluation plan](04_evaluation_plan.md) |
| QA-04 | Accessibility to WCAG 2.1 AA | **Not assessed**: keyboard operation and labels are present; no audit has been done |
| QA-05 | Languages other than English in the interface | **Not met** |

## 8. Prohibited

The system shall not: issue an award or decision; recommend an outcome to a decision-maker or
neutral; contact parties; alter evidence; use unapproved sources, the web or tools; offer a
general shell, desktop control, device control or a personal assistant; remember across matters;
act on its own initiative; or modify itself. These are refused by policy (C-24) and absent from
every front end (C-34, C-40).
