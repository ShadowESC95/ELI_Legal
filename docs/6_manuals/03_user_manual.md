# User manual

For the people who do the legal work. It applies equally to the desktop application and the
browser application: the screens are the same. Read the
[Instructions for use](08_instructions_for_use.md) first; they say what the system is for and
what you must not rely on it for.

## The idea in one paragraph

You file the papers. The system reads them into numbered passages, pulls out what is said word
for word, finds the law in sources your organisation has approved, and checks each authority
three ways. Anything it cannot stand behind, it holds and shows you. You deal with the holds,
read the report, and approve it or send it back. Until you approve, nothing may be relied on.
After you approve, your name is on it.

## Signing in

Sign in with your own user and passphrase, and the code from your authenticator if you have set
one up. Never share them. What is done in your session is recorded as done by you. A decision
asks for your passphrase again at the moment you make it. Five wrong attempts lock the account;
an administrator unlocks it. Sign out when you leave the machine.

## The screens

| Screen | You use it to |
|---|---|
| Start a new case | Walk through every part of a new case, in order, and see which are done |
| How to use | Learn the steps of a case and what any word means |
| Home | See where the open matter stands, your role on it, what to do next (with a button that takes you there, or who can do it if you cannot), what is waiting for you on your other matters, and the routine checks |
| Case details | Open a case; see parties, issues, relevant date; decide who has access, who reviews, which sources apply |
| Documents | File documents; read any document as numbered passages; see what was not read and what was flagged |
| Ask about the case | Ask about the case and get its own passages back, with where each comes from |
| Progress | Start, stop or restart a run; see what each step did |
| Who does each step | See what each step is allowed to read, write and never do |
| Findings | See every finding with its source passage and checks |
| Review and approve | Deal with holds and checks; read the report; decide; release |
| Record of actions | See everything that happened, verify it, export it |
| Compliance, Legal sources, Laws and standards, Settings | Oversight and administration |

Everything can be made larger with Ctrl and + (Ctrl and − smaller, Ctrl and 0 normal size), and
resting the pointer on a heading or a field explains it.

## Step by step

### 1. Open the matter

**Open a matter…** asks six short questions, one page each; nothing is created until you press
Finish on the last, which shows everything you chose.

Choose **who it is for**. This cannot be changed later, and it fixes who can be given access and
what the report may say.

| Choose | If you are | The report |
|---|---|---|
| Court, tribunal or arbitral tribunal | Deciding the dispute, or assisting the person who is | Gives no view on who should succeed |
| Mediator or conciliator | A neutral helping the parties settle | Gives no view on outcome; has a shared version without one-party confidences |
| Party representative | Acting for one side | May assess your own client's case |

Set the **relevant date**: the date as at which the law is to be checked. For most disputes
that is the date of the events, not today.

State the **issues** as you understand them. The system will also lift issues from the papers.

Choose **the team**: tick who else works on the matter and each person's **role on it**. You lead
it. A colleague can decide (resolve holds, approve, release), work the case (add documents, run,
record checks), assist (add documents, run), observe (read what is before all parties) or audit
(read the audit trail only). A role on the matter only ever narrows what someone's account
allows. Say whom each person **acts for**, where that matters: they will never see what another
party gave in confidence.

On a court's, tribunal's or neutral's matter, the parties' own people (prosecution, defence, a
claimant's or respondent's lawyers, a party acting for themselves) can be added too, each as
**one party's representative**. They file their side's papers and answer holds on them from their
own screen on the server; they see what is served on all parties and their own side's papers, and
none of your analysis. When a hold is about a paper a party filed (it cannot be read, or it carries
instructions aimed at an AI), that party is asked for its answer; you are told when the answer is
in, read it beside the hold, and decide the hold yourself.

Name the **reviewer**: tick "I review and approve the report myself", or "Reviews" beside a
colleague whose account can approve. Without a reviewer, no run will start.

Tick the **legal sources** and the **law and standards** that apply; those recommended for this
kind of matter and legal system are ticked for you.

Afterwards, the Home page always says what to do next.

### 2. File the documents

Choose the files (Add files…, or Add a folder…). A list then shows each one, and for each you
say what it is, who filed it, who may see it and where it came from; hover over a choice of who
may see it for what that means. Scope matters most in mediation and for privileged material: a
document filed "in confidence" by one party never appears in anything shared, and is withheld
from anyone on the matter who acts for another party. When they are in, you are told in plain
words what was read, what could not be read and why, and what was flagged.

Then check the list. A file marked **not read** (a scan, a photograph, a damaged file) will hold
the run until you either supply a readable version or accept the gap. A file marked **flagged**
contains text addressed to an AI system; it is treated as evidence of that fact and never as an
instruction, and it too is held for you to decide.

A scan or a photograph (a PDF page that is only an image, or a PNG, JPEG or TIFF filed on its
own) is read by OCR on this machine where Tesseract is installed. Its passages are marked (OCR)
with the confidence of the reading; a reading below 80% holds the run until a person checks it
against the original. Without OCR it is reported unread, never guessed.

**Work waiting for you.** When a run stops for a person, everyone on the matter who can act on it
is told: the desktop header shows "🔔 N waiting for you" and the status bar names the newest; in
the browser a bell and a notice with an **Open** button. That covers holds to clear, a restart
once every hold is cleared, a report ready for review or returned, and an approved report
suspended. You are only told what you are allowed to do. Each notice goes once the work is done,
and each is recorded in the audit trail. Nothing is ever sent outside ELI Legal.

### 3. Start a run

On the DAG screen. It takes seconds without a model and minutes with one. You can keep working.

### 4. Read what it held, and why

Review, Holds. Each hold says what is held and why.

| You see | It means | What to do |
|---|---|---|
| Document was not read | The file could not be turned into text | Supply a readable copy, or accept the gap with reasons |
| Prompt injection detected | A file contains instructions aimed at an AI system | Read it. Usually take it out of reliance and consider why it is there |
| Citation not found | An authority a party cites is not in a source that should contain it | Check the citation yourself. It may be mistyped, or may not exist |
| Overruled, reversed, repealed | The source records that the authority is no longer good law | Take it out of reliance, unless you have reason to think the source is wrong |
| Status last confirmed too long ago | The source's information is older than the limit for this legal system | Check current status yourself and record the result |
| Proposition not confirmed | Words attributed to an authority are not its own words | Read the passage and record whether it supports the proposition |

Two ways to close a hold, both needing your passphrase and reasons:

- **Take out of reliance.** The item stays on the record, marked excluded, and is listed in the
  report under "not to be relied on".
- **Accept the gap.** The run continues without it, and the report says so.

Or answer the check yourself (Review, Checks for you): say what you checked it against and what
you found. That is recorded as your verification, in your name.

### 5. Restart, and read the report

Restart the run from the DAG screen. When every hold is closed the report is built and the run
waits for review.

Read the report against the sources. For each finding you care about, open the passage it
points to (Findings, or Evidence). The report's sections:

1. The matter. 2. Documents considered, including any not read. 3. Chronology. 4. Each issue:
the evidence, the authorities located, and (with a model) arguments open to each party.
5. Authorities the parties rely on, with status. 6. Findings not to be relied on, with reasons.
7. What was verified, and by whom. 8. The limits of the document. 9. The run record.

### 6. Decide

Review, Decision. Tick each stated limit to acknowledge it, give your reasons, and choose:

- **Approve for reliance.** Binds to this exact version. If anything changes, approval lapses.
- **Return for correction.** Say what is wrong.
- **Reject.**

Approving without reading defeats the purpose. The system counts approvals that follow no
challenge at all and raises it with whoever is responsible for oversight.

### 7. Release

Name each recipient. The system says who is entitled to the matter and blocks anyone who is not.
Confirm each one yourself. The report is staged in the outbox for you to send by your usual
means. The system sends nothing.

## For decision-makers in particular

- The report is not a draft decision and offers no view on outcome. The reasoning is yours.
- **Authorities no party cited.** Under each issue the table of authorities has a column, "Cited
  by a party". Where it says no, the authority is new to the dispute. Put it to the parties
  before you rely on it.
- Read both sides' passages, not only the extracts.
- Decide, with your court or institution, whether the parties are told the tool is in use, and
  whether the report forms part of the file.

## For mediators

- File each side's private material as "one party in confidence".
- Share only the shared brief.
- The brief evaluates nothing and proposes no terms.

## For solicitors and barristers

- "Verified" means matched to an approved source. **It is not your verification.** Before
  anything goes to a court, open each authority and check it yourself. Courts require it.
- Know what your court requires about disclosing AI use. The Record of actions and the evidence pack
  record exactly what the tool did, which is what an accurate disclosure needs.
- Do not use any AI tool to produce the substance of an affidavit or witness statement.
- The memorandum is privileged. Keep it within the team.

## Using Chat

Ask a factual question about the matter. The answer is the passages themselves, each labelled
with where it comes from and whether it may be relied on. With a model you can ask for a short
summary; every sentence is tied to its sources and any sentence that cannot be is dropped.
Questions about who should win are declined. Nothing can be decided from Chat, and the
conversation is not kept.

## When something looks wrong

- A finding looks wrong: open its source passage. If the document is wrong, that is evidence; if
  the system misread it, take the finding out of reliance and tell your administrator.
- An argument is attributed to the wrong party: possible with a model. Check each one.
- The audit chain will not verify: stop. Do not continue the matter. Tell your administrator.
- You think the system has caused or nearly caused harm: open an incident (Governance).

## If something is marked withheld

Your role on a matter decides which of its material you may read. Anything outside it is shown
as **[withheld]** with the reason ("given in confidence by Northwind Logistics Ltd", "for the
neutral only", "privileged"), wherever it would appear: in the document list, a passage, a
finding, chat, the report. You are told that it exists, never what it says. If you need it, ask
the matter's lead to change your role or clearance; the request and the change are recorded.

