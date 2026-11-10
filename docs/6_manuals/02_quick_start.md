# Quick start

Fifteen minutes, on the synthetic dispute that ships with the software. Nothing in it is real:
the parties, the documents and the law of "Examplia" are invented so that the system's checks
have something to catch.

## 1. Watch the whole thing once

```
eli-legal demo
```

This runs the dispute from filing to an approved, released report in a temporary folder and
narrates each step. Look for the six holds it raises: a file carrying a hidden instruction to an
AI system, a photograph it could not read, an overruled case cited by one side, a case that does
not exist, and a case whose status it could not confirm recently enough. Then watch a named
person deal with each one. Add `--model <name>` to see it with a model running on your machine.

## 2. Do it yourself in the application

Start the desktop application (`eli-legal-gui`) or the server (`eli-legal serve`, then open
`http://localhost:8443/`). The screens are the same.

1. **Create the administrator** when asked, then **sign in**.
2. **Settings, Users and roles.** Add yourself a second account with a legal role, for example
   `arbitrator`, and give it a first passphrase. The administrator account cannot see matters; that
   is deliberate. Sign out and sign in as the new user.
3. **Sources.** As the administrator: register a source, record who publishes it, its licence
   and how it reports status, approve it, and load a corpus. For a first try,
   `eli-legal demo --dir ./demo` leaves the synthetic corpus in `./demo/demo/corpus` and the
   synthetic documents in `./demo/demo/documents`. That corpus is for the invented legal system
   `XX`, whose pack is in `./demo/demo/jurisdictions`; copy it into `config/jurisdictions` in
   your data folder to try it.
4. **Matter.** Open a matter: choose who it is for, the legal system, the parties, the issues and
   the relevant date. Name yourself as reviewer. Choose the source.
5. **Evidence.** File the documents. Say who filed each and who may see it.
6. **DAG.** Start a run and watch each step turn green, or amber where it holds.
7. **Review.** Work through the holds and the checks for you. Each decision asks for your
   passphrase and your reasons.
8. **DAG.** Restart the run. It now reaches "awaiting human review".
9. **Review.** Read the report. Tick each stated limit, give your reasons, approve.
10. **Review, Release.** Name a recipient, confirm them, release. The report is staged in the
    outbox; nothing is sent.
11. **Record of actions.** Verify the chain. Every step you took is there, with how you proved who you
    were.

## 3. What to notice

- The report shows nothing it could not tie to a source passage.
- It distinguishes an authority that is cited, one that exists, one that is still good law, and
  one that says what it is quoted as saying.
- It tells you which authorities it found that no party cited.
- It says what it did not check.
- It will not tell you who should win.

Next: the [User manual](03_user_manual.md) for your role, and the
[Instructions for use](08_instructions_for_use.md) before any real matter.
