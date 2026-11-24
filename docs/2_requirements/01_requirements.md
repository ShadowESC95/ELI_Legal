# Requirements

Each requirement names the control that meets it. Controls are in the control register
(`src/eli_legal/governance/registers/control_register.csv`), which names the code that carries
each one out and the tests that prove it. `eli-legal governance` fails if a named file or test
does not exist, so this table cannot quietly go stale.

Status: **met** means implemented and tested. **Partly** and **not met** say what is missing.

## 1. Functional

| ID | The system shall | Control | Status |
|---|---|---|---|
| FR-01 | Open a matter under exactly one profile, with parties, issues, governing law, relevant date, approved sources and a named reviewer | DG-01.1, HO-01.2 | Met |
| FR-02 | Accept documents as PDF, DOCX, ODT, RTF, HTML, e-mail and text, keeping each original unaltered and addressed by its SHA-256 | DG-01.5 | Met |
| FR-03 | Record for each document who filed it, what it is, who held it and who may see it | DG-01.5 | Met |
| FR-04 | Read each document into passages with locators a person can follow | DG-01.5 | Met |
| FR-05 | Account for every document: read, or the gap accepted by a named person | DG-01.6 | Met |
| FR-06 | Take facts word for word from documents, with date and party | DG-01.5, DG-01.11 | Met |
| FR-07 | Identify issues and attach the facts that bear on them, noting gaps and conflicts | DG-01.11 | Met |
| FR-08 | Search approved sources only, and list every authority a party cites with the sentence citing it | DG-01.3, DG-01.8 | Met |
| FR-09 | Check, separately, that each authority exists, is still good law for the relevant date, and says what it is quoted as saying | DG-01.8, DG-01.9, DG-01.10 | Met; only as reliable as the source's status data |
| FR-10 | Draft arguments only from verified findings, attributed to a party | HO-01.1 | Met; a model can still misattribute, see instructions for use |
| FR-11 | Assemble the report from verified findings, showing held and excluded findings separately with reasons | DG-01.11, HO-01.1 | Met |
| FR-12 | Answer questions about a matter only from its documents, findings and approved sources | TR-01.3 | Met |
| FR-13 | Require a named human to resolve holds, review, approve and release | RM-01.1, HO-01.2, HO-01.4 | Met |
| FR-14 | Export an evidence pack for any run | TR-01.2 | Met |
| FR-15 | Work for any legal system described by a jurisdiction pack | TR-01.1 | Met structurally; **no pack is validated by a qualified lawyer** |
| FR-16 | Read scanned documents and photographs | DG-01.35 | Met where Tesseract (and Poppler, for PDF pages) is installed; otherwise reported unread and held |
| FR-17 | Query a live legal database | DG-01.32 | **Partly met**: the EU (CELLAR, EUR-Lex) and UK (legislation.gov.uk, Find Case Law) are looked up by citation; research searches what has been fetched or loaded, not the databases themselves |

## 2. Governance

| ID | Requirement | Control | Status |
|---|---|---|---|
| GR-01 | Role, matter membership and matter profile are all needed for any matter action | DG-01.1 | Met |
| GR-02 | No record is readable or writable across matters | DG-01.2 | Met |
| GR-03 | Document and source text is data, never instruction | DG-01.7 | Met |
| GR-04 | A finding is verified only when every check its kind requires has passed | DG-01.11 | Met |
| GR-05 | A failed, conflicting, inconclusive or missing check holds the finding and what relies on it | DG-01.11, RM-01.1 | Met |
| GR-06 | A system identity can hold no role: it cannot review, approve, resolve or release | HO-01.2 | Met |
| GR-07 | No reviewer, no run. No approval, no release. No audit key, no run | HO-01.2, MO-01.1, HO-01.4 | Met |
| GR-08 | Approval binds to the exact report reviewed, with every stated limit acknowledged | HO-01.2, HO-01.3 | Met |
| GR-09 | The audit chain and the run's record must both verify before approval | MO-01.1, MO-01.2 | Met |
| GR-10 | Logs carry identifiers and hashes, not content | DG-01.12 | Met |
| GR-11 | A run can be stopped, and restarts only by a named, authorised person with a reason | RM-01.2 | Met |
| GR-12 | A policy file may tighten these rules and cannot switch them off | RM-01.4 | Met |
| GR-13 | No output states a decision; for decision-makers and neutrals, none says who should succeed | HO-01.1 | Met by rule; wording outside the rules' reach is possible |
| GR-14 | Incidents are recorded and closed only with containment and reasons | RM-01.3 | Met |
| GR-15 | Monitoring is computed from control evidence | MO-01.3 | Met |
| GR-16 | Closing a matter ends access and can delete content while keeping the decision record | DG-01.13 | Met |
| GR-17 | The report marks every authority found by research that no party cited | TR-01.5 | Met |

## 3. Identity and access

| ID | Requirement | Control | Status |
|---|---|---|---|
| IA-01 | No action on a name alone: identity is established by a credential on every front end | DG-01.16 | Met |
| IA-02 | A decision needs the person's passphrase again | HO-01.5 | Met |
| IA-03 | Every audit event records how identity was proved | MO-01.4 | Met |
| IA-04 | Repeated wrong passphrases or codes lock the account; only an administrator unlocks | DG-01.20 | Met |
| IA-05 | A second factor is available to every user and required where the server is reachable from other machines | DG-01.21 | Met (one-time codes; no hardware keys) |
| IA-06 | Passphrases and tokens are stored only as salted hashes or hashes | DG-01.16 | Met |
| IA-07 | Single sign-on with an organisation's identity provider | — | **Not met** |

## 4. Server

| ID | Requirement | Control | Status |
|---|---|---|---|
| SV-01 | Serve only legal and governance functions; no route answers without credentials except health, boundaries, the page and sign-in | DG-01.15, DG-01.22 | Met |
| SV-02 | Listen on this machine only unless told otherwise; never beyond it without TLS | DG-01.17 | Met |
| SV-03 | TLS 1.2 or later | DG-01.17 | Met |
| SV-04 | Browser sessions in an HttpOnly, SameSite=Strict cookie; changes need a CSRF value; idle and absolute time-outs | DG-01.18 | Met |
| SV-05 | Refuse unknown host names, cross-site changes, undeclared or oversized bodies, and excessive request rates | DG-01.19 | Met |
| SV-06 | Send a strict content-security policy and related protections on every response; allow no other origin to read a response | DG-01.19 | Met |
| SV-07 | Show all matter content in the browser as text, and load nothing from any other site | DG-01.22 | Met |
| SV-08 | Disclose no server path; give no way to read outside the import area or to call another machine | DG-01.22 | Met |
| SV-09 | Carry the whole lifecycle, with runs executing in the background as the person who started them | HO-01.6 | Met |
| SV-10 | More than one server process, or high availability | — | **Not met**: one process, one database |

## 5. Security and privacy

| ID | Requirement | Control | Status |
|---|---|---|---|
| SP-01 | Outbound network refused by default | DG-01.4 | Met |
| SP-02 | A model runs on this machine only, and changing it is a governed decision | RM-01.5 | Met |
| SP-03 | Legal sources are reachable only if registered and approved | DG-01.3 | Met |
| SP-04 | Text addressed to a model is flagged, held and kept out of every prompt | DG-01.7 | Met for known patterns |
| SP-05 | Edits, removals and truncation of the audit ledger are detected | MO-01.1 | Met |
| SP-06 | Encryption at rest | DG-01.42; DG-01.44 | Met for the databases (SQLCipher) and case files (AES-256-GCM); the keys are on the same machine, so full-disk encryption is still needed |
| SP-07 | Malware scanning of uploads | — | **Not met**: files are parsed, never executed; scan them before filing |

## 6. Installation and operation

| ID | Requirement | Status |
|---|---|---|
| IN-01 | An installer that needs nothing else installed | Met: Linux (AppImage, `.run`, `.deb`), Windows (setup program), macOS (disk image), built and smoke-tested by the release workflow. Windows and macOS have not been used by a person |
| IN-02 | Program and data kept apart; uninstalling never removes data | Met |
| IN-03 | An installer whose integrity can be checked before it runs | Met (`--verify`, `SHA256SUMS`); builds are **not signed** |
| IN-04 | Nothing starts by itself: no service, port or network call | Met |
| IN-05 | Installable from source wherever Python 3.10 runs | Met on Linux; scripted and untested on Windows |
| IN-06 | Runs with no ELI installed, and loads into ELI v3 as an edition | Met (DG-01.14); the v3 loader change is proposed, not applied |

## 7. Quality

| ID | Requirement | Status |
|---|---|---|
| QA-01 | Re-running a matter reproduces the same findings and keeps human decisions | Met (RM-01.2) |
| QA-02 | Every control is tied to code and to tests, checked automatically | Met |
| QA-03 | Declared accuracy on representative real matters | **Not met**: see the [evaluation plan](04_evaluation_plan.md) |
| QA-04 | Accessibility to WCAG 2.1 AA | **Not assessed**: keyboard operation and labels are present; no audit has been done |
| QA-05 | Languages other than English in the interface | **Not met** |

## 8. Prohibited

The system shall not: issue an award or decision; recommend an outcome to a decision-maker or
neutral; contact parties; alter evidence; use unapproved sources, the web or tools; offer a
general shell, desktop control, device control or a personal assistant; remember across matters;
act on its own initiative; or modify itself. These are refused by policy (RM-01.4) and absent from
every front end (TR-01.4, DG-01.22).
