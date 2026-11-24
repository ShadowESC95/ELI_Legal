# Desktop application

Start it from your applications menu or Start menu (**ELI Legal**), from Applications on macOS,
by running the AppImage with no arguments, or with `eli-legal-gui` (see
[Installation](01_installation.md)). From a source checkout, `eli-legal gui`, `./eli_legal.sh` or
`python -m eli_legal` (with the `gui` extra: `pip install 'eli-legal[gui]'`). It is a front end over the same services
as the command line and the API, so access control, gates, holds and audit behave identically.
It looks and behaves like the ELI desktop applications, and contains only legal and governance
functions: there is no general assistant, no shell, no screen or desktop control, no web access.

## Signing in

On first start an installed copy asks for the licence key, creates the keys, and asks you to
create the first administrator and how long each kind of record is kept. After that, everyone
signs in with their own passphrase. **File → Sign out** returns to the sign-in window, so a
second person can sign in on the same machine (for example the reviewer, when you started the
run). An administrator sets a new user's first
passphrase; the user then changes it. Everything you do is recorded under your name together
with how you proved who you are. **A decision asks for your passphrase again** at the moment you
make it.

## The header

Always visible: the open matter and who it is for; the result of the latest routine checks;
whether the audit chain verifies and how many events it holds; that the network is denied by
default; which model is in use, if any; what is waiting for you; and who is signed in, with
their roles.

**Waiting for you.** "🔔 N waiting for you" counts the work on your matters that only a person
can do and that you are allowed to do: holds to clear, a restart once every hold is cleared, a
report to review, a report returned or suspended. It is checked every few seconds; a new one is
named in the status bar. Click it to see them and open one at the page where it is done.

**What others do shows here.** When someone else acts on the case you have open (in a browser, or
on another machine using the same data), the stage bar, the header and the page in front of you
update within about five seconds without pressing F5, if it is a page that only shows the case
(Home, Progress, Who does each step, Findings, Review and approve, Record of actions, Released to
me, Documents). Never while a dialog is open or work is running, so nothing you are typing is
lost. The status bar says "Updated: someone else has worked on this case."

**The status bar** (bottom right) shows how busy this machine is and how much of it ELI Legal
uses: processor, memory (unified memory where the processor and graphics share it) and each
graphics processor. View → Show or hide.

**The stage bar** under the header shows where the open case is, from 1. Set up to 8. Close, and
**Next: …**, the next step if it is yours (**Next: State the issues** opens Case details at the
issues).

**Window size.** The window opens to fit your screen. A page larger than the window scrolls; rows
of buttons wrap. Drag the edge between the sidebar and the page, and the dividers inside pages,
to give room where you need it; the window remembers its size and where you left them. Ctrl and
the mouse wheel, or Ctrl and + / −, make everything larger or smaller.

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
| 📁 Case details | Open a matter with the six-page wizard; **Edit details…** corrects its name, purpose, forum, rules, the date the law is assessed at, the parties (rename or add; remove only one nothing depends on) and the issues to decide (one per line), each change recorded; the team, each person's role on the matter, whom they act for and what they read; change a role; the named reviewers; the approved sources; preservation holds; close a matter (archive its content encrypted, keep it, or delete it). |
| 📄 Documents | Take documents in, saying for each file what it is, who filed it, who may see it and where it came from; read any document as located passages; see what was not read and what was flagged. Anything you are not cleared to read is listed as withheld, with the reason. |
| 💬 Ask about the case | Ask about the matter. Answers come from its documents, the run's findings and the approved sources, each with its locator and whether it may be relied on. With a model, a short summary whose every sentence is tied to its sources. It will not say who should win, and nothing can be decided from chat. |
| 🕸 Progress | The analysis steps as a map, coloured by what happened to each step. Start, stop or restart a run (a stop ends the step at work at its next model answer, document or issue); select a step to see what it did. Runs execute in the background. A run prepared under a law or standards package that has changed since must be restarted from the beginning or started again; the step's message says so. |
| 🤖 Who does each step | Each step as an agent with a fixed mandate: what it reads, what it writes, what it may never do, which controls it carries out, and what it did in the selected run. Three are model-assisted (marked ✦); four are people. |
| 🔎 Findings | Every finding of the run with its source passage, its checks and who decided them. Record a check by hand, or take a held finding out of reliance. |
| ⚖ Review and approve | **Holds**: double-click one (or select it and press **Open…**) for its window: what it means, the document (reference, who filed it, when, how it was read, its SHA-256), the exact words that caused it highlighted in the full text with each match named and listed, or the original image or PDF shown on screen (a damaged file is said to be damaged), the filing party's answer, and only the actions that fit: accept it as ordinary evidence, take the document out of the analysis, **describe it by hand** (type what the original shows; it becomes its text, marked as yours), **file a readable copy**, accept the gap, save a copy of the original (a recorded hand-over), record a check by hand, take a finding out of reliance, lift a hold. Checks waiting for a person; the report; the **decision** (tick each stated limit, give reasons, approve / return / reject: if you cannot decide it, because you started the run or are not a named reviewer, a box says who can and offers **Switch person…** and **Name another reviewer…**); release to confirmed recipients. |
| 🧾 Record of actions | The ledger for the matter, including how each actor's identity was proved; verify the chain; reconcile a run's record; export a checkpoint or the evidence pack. |
| 🛡 Compliance | Every requirement and where it stands (met, waiting for your organisation, review due), with what your organisation still has to record for each and a button that takes you there; the organisation's actions, recorded here with your passphrase (forms, statements, training, retention, the accuracy evaluation, the drafted Annex IV documentation and declaration, registration); the routine checks and what they found; every matter on the system, for oversight; the control and risk registers; who is responsible for what, in words (does it, answers for it, is asked first, is kept informed); monitoring; incidents, with each serious incident's reporting deadline and the decision on it. |
| 📚 Legal sources | Where the law comes from: add an official EU or UK database by reading its licence, or your own collection with a form that explains each field; approve or revoke a source; load texts into your own collection; read what a source holds and each authority's status history. |
| 📜 Laws and standards | The law, regulation and standards packages: the library, when each was last checked against its official text, your organisation's own, and which apply to the open matter; record that you checked one. See [Laws & Standards](11_laws_and_standards.md). |
| 📥 Released to me | Approved reports released to you: read them, or save them as PDF, Word or Markdown, each copy stamped with your name. |
| ⚙ Settings | Your passphrase; users and roles, each role described; what every account role and every role on a matter may do; the model; the legal systems installed; the policy; this installation; **System → Server** to start the server for everyone on a case (administrators, judges, tribunal members and arbitrators), with the address to give them. |

**File → Closed cases** lists closed cases (they leave the case list): where each kind of their
content is and until when it is kept; view one, reopen it, archive it, or delete its content.

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
