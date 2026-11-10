# Desktop application

`eli-legal gui` (or `./eli_legal.sh`, or `python -m eli_legal`) opens the desktop application. It
needs the `gui` extra: `pip install 'eli-legal[gui]'`. It is a front end over the same services
as the command line and the API, so access control, gates, holds and audit behave identically.
It looks and behaves like the ELI desktop applications, and contains only legal and governance
functions: there is no general assistant, no shell, no screen or desktop control, no web access.

## Signing in

On first start it creates the audit key and asks you to create the first administrator. After
that, everyone signs in with their own passphrase. An administrator sets a new user's first
passphrase; the user then changes it. Everything you do is recorded under your name together
with how you proved who you are. **A decision asks for your passphrase again** at the moment you
make it.

## The header

Always visible: the open matter and who it is for; the result of the latest routine checks;
whether the audit chain verifies and how many events it holds; that the network is denied by
default; which model is in use, if any; and who is signed in, with their roles.

## Pages

The pages are listed down the left in plain words, each in a box of its own with a line saying
what it is for, in four groups: **start here** (Start a new case, How to use, Home), **this case** (Case details to Review and approve),
**checking and records** (Record of actions, Compliance) and **set-up** (Legal sources, Laws and
standards, Settings). Ctrl+1 to Ctrl+9 open the first nine; F1 opens How to use.

**Reading it comfortably.** Ctrl and + makes everything larger, Ctrl and − smaller, Ctrl and 0
returns to normal size; holding Ctrl and turning the mouse wheel does the same, anywhere in the
application. The size is remembered. Rest the pointer on a column heading, a field, a button or a
page in the sidebar and a yellow box explains it; How to use lists every word the application
uses, with its meaning.

| Page | What it is for |
|---|---|
| 🧭 Start a new case | How a case is built: its eleven parts as a map, from who the work is for to its release. Choose a part to see what it is, every question asked with what it means and an example, tips, and who does it, with a button that does it now. With a case open, each part already done is ticked. |
| How to use | A case from start to finish, step by step, with who does each step and a button to the page for it; and every word the application uses, explained, with a search. |
| 🏠 Home | Where the open matter stands (six stages: set up, documents, analysis, holds and checks, review, release), your role on it and what you may read, the next things to do with a button to each, the work waiting for you on every matter you are on, the routine checks, and where compliance stands. |
| 📁 Case details | Open a matter with the six-page wizard; parties, issues, relevant date; the team, each person's role on the matter, whom they act for and what they read; change a role; the named reviewers; the approved sources; close a matter. |
| 📄 Documents | Take documents in, saying for each file what it is, who filed it, who may see it and where it came from; read any document as located passages; see what was not read and what was flagged. Anything you are not cleared to read is listed as withheld, with the reason. |
| 💬 Ask about the case | Ask about the matter. Answers come from its documents, the run's findings and the approved sources, each with its locator and whether it may be relied on. With a model, a short summary whose every sentence is tied to its sources. It will not say who should win, and nothing can be decided from chat. |
| 🕸 Progress | The analysis steps as a map, coloured by what happened to each step. Start, stop or restart a run (a stop ends the step at work at its next model answer, document or issue); select a step to see what it did. Runs execute in the background. |
| 🤖 Who does each step | Each step as an agent with a fixed mandate: what it reads, what it writes, what it may never do, which controls it carries out, and what it did in the selected run. Three are model-assisted (marked ✦); four are people. |
| 🔎 Findings | Every finding of the run with its source passage, its checks and who decided them. Record a check by hand, or take a held finding out of reliance. |
| ⚖ Review and approve | Holds; checks waiting for a person; the report; the decision (tick each stated limit, give reasons, approve / return / reject); release to confirmed recipients. |
| 🧾 Record of actions | The ledger for the matter, including how each actor's identity was proved; verify the chain; reconcile a run's record; export a checkpoint or the evidence pack. |
| 🛡 Compliance | Every requirement and where it stands (met, waiting for your organisation, review due), with what your organisation still has to record for each and a button that takes you there; the organisation's actions, recorded here with your passphrase (forms, statements, training, retention, the accuracy evaluation, the drafted Annex IV documentation and declaration, registration); the routine checks and what they found; every matter on the system, for oversight; the control and risk registers; who is responsible for what, in words (does it, answers for it, is asked first, is kept informed); monitoring; incidents, with each serious incident's reporting deadline and the decision on it. |
| 📚 Legal sources | Where the law comes from: add an official EU or UK database by reading its licence, or your own collection with a form that explains each field; approve or revoke a source; load texts into your own collection; read what a source holds and each authority's status history. |
| 📜 Laws and standards | The law, regulation and standards packages: the library, when each was last checked against its official text, your organisation's own, and which apply to the open matter; record that you checked one. See [Laws & Standards](11_laws_and_standards.md). |
| ⚙ Settings | Your passphrase; users and roles, each role described; what every account role and every role on a matter may do; the model; the legal systems installed; the policy; this installation. |

## What it will not let you do

Whatever your role does not permit. Refusals are shown in the system's own words and, where they
concern a matter, are written to the audit trail. The application cannot be used to approve as
someone else: a decision needs the signed-in person's own passphrase.

## Limits

A passphrase proves knowledge of a secret, not presence. Set up a second factor (Settings, You)
so that a code from your phone is needed as well. Five wrong attempts lock an account until an
administrator unlocks it. The
application shows matter content on screen: use it on a machine and in a place appropriate to
that content.
