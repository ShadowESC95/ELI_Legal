# Operations runbook

## Before first use

`eli-legal init --admin <id>` (asks for the administrator's passphrase and how long the record
is kept), or start the desktop application, which does the same on first run. Then
`eli-legal checks timer --install`, so the routine checks run daily even with nothing open. Save
the keys apart from the databases: `eli-legal database-key --out FILE` (the databases' key, as one
line of text) and a copy of `secrets/audit_hmac.key`, both off the machine. Sign in (`eli-legal login <id>`), create users and roles, set each user's first
passphrase (`eli-legal passphrase <user>`), register and approve sources, `eli-legal doctor`.
Every step below can be done in the desktop application or the browser application instead.
For users, sources, the model, backups and the server, see the
[Administrator manual](04_administrator_manual.md).

## Before a run

Confirm the matter's profile, parties, relevant date, approved sources and named reviewer
(`eli-legal matter show`). Ingest the documents and check `eli-legal docs`.

## A held run

1. `eli-legal run status M R` and `eli-legal holds M R` — what is held and why.
2. `eli-legal tasks M R` — checks waiting for a person.
3. For each hold, a named person decides, with reasons:
   - verify by hand: `eli-legal verify M CLAIM --check current_law --result verified --reason …`
   - take the finding out of reliance: `eli-legal hold M HOLD --action exclude --reason …`
   - accept an unread document or a flagged file: `eli-legal hold M HOLD --action waive --reason …`
   - in the desktop application (Review and approve, Holds, double-click the hold), see the exact
     words or the original that caused it, and for an unread document **describe it by hand** or
     **file a readable copy** instead of accepting the gap.
4. Fix the cause where there is one (re-import a corrected source, re-ingest a converted scan).
   A run prepared under a law or standards package that has changed since cannot continue:
   restart it from its first step (`--from` the first step) or start a new run.
5. `eli-legal run resume M R --reason …` by a person authorised to restart.
6. If the same source or component could affect other matters, check them and open an incident.

## Review and release

`eli-legal report M R`; then `eli-legal review M R --decision approve --reasons … --report-hash H
--acknowledge-all` (the limits are printed first), by a named reviewer who did not start the run. `eli-legal release prepare` and
`eli-legal release send` stage the approved report in the outbox; nothing is transmitted.

## Audit

`eli-legal audit verify` routinely; `eli-legal audit checkpoint --out FILE` and store the file off
the machine; later `eli-legal audit verify --against FILE` detects a rollback. If verification
fails: stop, preserve both database files and the anchor, open an incident, and do not restart
until the cause is known.

## Change

A change of model, prompt, tool, source, workflow or policy shows in `eli-legal monitor`. Complete
`governance/templates/change_assessment.md` and re-run the evaluation before further use.

## Matter close

`eli-legal matter close M --reason … [--purge]`. Access ends; with `--purge`, documents, text and
indexes are deleted. Runs, reviews, releases, holds, incidents and the ledger are kept. The desktop
application (Case details, Close this matter…) also offers to archive the content encrypted, each
kind under its own key; File → Closed cases lists closed cases, reopens them, and shows when each
kind of their content goes. The routine checks retire each kind when its retention period ends.

## The server

Run it on the machine that holds the cases, from the installed program (Settings → System →
Server, or its `serve`), so that the desktop application and every browser share the same live
data. At start it prints the data folder it serves; check it is the installed one. If browser
users see different cases or accounts from the desktop, it is serving other data: stop it and
start the right one. See [Web application and server](06_web_application_and_server.md).
