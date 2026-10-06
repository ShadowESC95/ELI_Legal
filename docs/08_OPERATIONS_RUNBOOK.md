# Operations runbook

## Before first use

`eli-legal init --admin <id>` (asks for the administrator's passphrase), or start the desktop
application, which does the same on first run. Back up the audit key separately from the
databases. Sign in (`eli-legal login <id>`), create users and roles, set each user's first
passphrase (`eli-legal passphrase <user>`), register and approve sources, `eli-legal doctor`.
Every step below can be done in the desktop application instead.

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
4. Fix the cause where there is one (re-import a corrected source, re-ingest a converted scan).
5. `eli-legal run resume M R --reason …` by a person authorised to restart.
6. If the same source or component could affect other matters, check them and open an incident.

## Review and release

`eli-legal report M R`; then `eli-legal review M R --decision approve --reasons … --report-hash H
--acknowledge-all` (the limits are printed first). `eli-legal release prepare` and
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
indexes are deleted. Runs, reviews, releases, holds, incidents and the ledger are kept.
