# Decision log

**D-01 Separate product, loadable by ELI v3 as an edition.** No dependency on ELI to run.

**D-02 Holds are state, not prose.** A failure creates a hold record the workflow consumes.

**D-03 Audit fails closed.** No key, no run; no downgrade to an unkeyed chain.

**D-04 Status checking is separate from generation.** A generator agreeing with itself is not
verification, and neither is a second model agreeing with the first.

**D-05 Findings are verbatim.** Facts and passages are the source's own words. This gives up
fluent summary for something a reader can check against the page.

**D-06 The system does not vouch for what a party says an authority decides.** It reports the
reliance, checks existence and status, and shows the closest passage for a person to compare.

**D-07 Orchestration stays in ELI Legal.** A host scheduler is not used, because the guarantees
(stop downstream on failure, log every outcome, stop if the log cannot be written) must hold
identically standalone and hosted.

**D-08 ELI Legal's own parser, not the host's.** Locators are needed for every finding.

**D-09 No decision through a conversational assistant.** See `../3_architecture/03_eli_v3_integration.md`.

**D-10 Legal systems are data.** A jurisdiction pack holds structure and citation grammar, never
rules of law, and ships unvalidated.

**D-11 Legislation is judged on the relevant date; case law as it stands today.** A pack can
change how treatments are weighed (civil-law packs treat a contrary later decision as a conflict
for a person, not a failure).

**D-12 No training on matter data.**

**D-13 One profile per matter.** Tribunal-side and party-side use are different deployments with
different users, outputs and regulatory posture.

**D-14 A role on each matter narrows an account role; it never widens it.** Who someone is
(their account role) and what they do on one matter (lead, decision-maker, case worker, assistant,
observer, auditor) are separate, and both must allow an action. People already on matters when
roles on a matter were introduced keep exactly what their account allowed, so nobody lost access.

**D-15 Withhold, do not hide.** Material a person is not cleared for is listed as withheld, with
the reason, rather than left out, so nobody is misled about what a matter holds; its words are
never shown, and anything built from it (a drafted argument) is no more widely visible than it.

**D-16 A requirement's status says whether it is met.** The register records what the software
does; an organisation's duties are actions recorded in the application in a named person's name
and reviewed on time. "Partial" described the software, not the requirement, and is no longer
shown.

**D-17 The forms are the templates.** In-application forms are read from the governance
templates, so the questions cannot drift between paper and screen.

**D-18 The system checks itself every day, and acts only where acting is certain.** It opens an
incident when an approved report's law changes or a stored original is altered, and deletes a
closed matter's content when its retention ends; everything else is reported for a person.
Currency of the law comes from the approved sources and a named person's confirmation against the
official text, because the network is denied by default.

**D-19 One vocabulary.** Every state, reason, check, action and role a person is shown is worded
once (`domain/plain.py`) and used by the desktop application, the reports, the command line and,
through `/v1/words`, the browser application.

**D-20 Hard offline is enforced by the kernel, not by Python.** Intercepting Python's sockets
stops Python code only; native libraries, io_uring and child processes go round it. A seccomp
filter (Linux), the kernel sandbox (macOS) or a firewall rule (Windows) cannot be bypassed from
inside the program, and on Linux cannot be removed until it exits, so switching it off takes
effect only at the next start.

**D-21 Meaning ranks and files; it never verifies.** An embedding model changes which passages
research offers and which facts are filed under an issue. It does not decide that a source says
something: a passage found by meaning is quoted word for word and verified like any other, and
the report says how research was done. Research fuses the two rankings with the one by words
weighted 0.2, and a fact is linked to the issue it is closest to when it stands out for that
issue (z 0.25). Both settings were chosen on half of a benchmark and checked on the other half,
and both models measured chose the same ones. A higher setting tuned to the whole benchmark
would have reported better figures and meant less.

**D-22 What is measured is the code that runs.** The benchmarks call the research and linking
code a matter uses, not a copy, over legislation as its official databases publish it. Research
by words may not fall below its measured figures without a test failing. The figures are for
benchmarks written for this software; they are not a claim about real matters.

**D-23 ELI v3 opens the newest copy.** An installed copy of ELI Legal keeps ELI v3's record of
it current when it starts, taking the record over from a copy that is older or gone and never
from one of the same version, and installers register and unregister their own copy. A source
checkout registers only when told to, and ELI v3 hosting ELI Legal in its own process never
registers anything.

**D-24 Nothing derived from a case is kept beyond what its purge reaches.** Vectors of a case's
own words (its issues, its facts, what a party says of an authority) are made when needed and
thrown away. Keeping them would save a second or two a run, in a table shared by every matter,
and would leave something of the case behind when its contents are deleted. Only the vectors of
the legal sources' passages are kept: they are public law, not the case.

**D-25 A provision has its own status.** A section relied on is judged on its own repeal, not
only the Act's. The date of a repeal is the one legislation.gov.uk's annotation gives, not the
start date of the version that first shows it, which can be years earlier. What the annotation
cannot settle (a repeal in part, without a date) goes to a person, and a repeal of part of a
subsection is not detected: a passage quoted from it is still checked word for word.

**D-26 Meaning that links facts is marked, and the model chosen for it is one measured.** Meaning
finds about four times as many of the facts that bear on an issue as words do, and some of its
links are wrong: one model measured (bge-small) was less precise than words alone. A link made
by meaning alone is therefore marked in the report for the reviewer, and the model chosen
automatically is one measured to be at least as precise as words, where one is present.

**D-27 An EU act is read as in force on the date, and the authentic text is named.** An amended
act is read in the consolidated version in force on the relevant date. Consolidated texts are
documentation: the report's status basis says that the Official Journal texts are authentic.

**D-28 An approved report stops leaving the matter the moment its law fails (EL-001).** The
routine checks look at every approved report, not only the latest run. When an authority one
relies on is no longer confirmed as good law, a suspension and its incident are recorded
together, once per report, naming who already received it. Preparing and sending a release
consult the suspension immediately before acting, by every route. The approval and earlier
releases stay in the record: what changes is whether the report may leave now. Closing the
incident does not end the suspension; a named reviewer who may approve ends it, on a written
basis, either when the law is confirmed again for that report (checked again at that moment) or
when a later run, re-checked and approved after the suspension, replaces it.

**D-29 A report returned for correction is read again from the beginning.** Its steps all
finished cleanly, so restarting at "the first step that did not finish" began at the
verification gate and never read the correction. A returned run now restarts from the beginning
unless a person chooses a step, and a restart that would not read a document added since the
papers were read is refused. The law and standards packages are listed in a fixed order: the
report rebuilt at approval must equal the reviewed draft, and after a restart their order had
differed, so the corrected report could not be approved.

**D-30 Nothing under a preservation hold is deleted (EL-004).** A matter's content is deleted
at closure or when its retention ends, through one path. A preservation hold on the whole
matter refuses that before anything changes; a hold on named documents keeps those and lets the
rest go. Every deletion leaves a receipt of the hashes of the originals deleted and what was
kept, matched by the ledger. Preserving more is always safe, so the matter's lead may place a
hold; ending one is the legal or data-protection owner's decision, with a reason.

**D-31 An incident's deadline counts from awareness (EL-006).** Article 73 counts from when the
provider or deployer became aware, which is often before anyone enters the incident here. The
time and the way it became known are recorded; the time may be moved earlier but never later,
since later would lengthen the time to report. Until it is recorded, the deadline counts from
the entry, which can only be later. Each serious incident has an owner and a different stand-in;
when half the time is gone with no decision, the stand-in is told, once, on the record. Nothing
is reported to an authority by the software: a person decides and reports.

**D-32 Real matters need a deployment authorisation; practice matters say what they are
(EL-005).** A matter is opened as practice or real. Practice needs nothing and every report says
it is not for reliance, in its banner and in its summary alike; an approved practice run is shown
everywhere (desktop, browser, command line) as a completed practice review, never as "approved
for reliance", and the case details say which kind the case is. A real matter's work needs an authorisation in force for its legal
system and kind, resting on named evidence, signed by a provider lead and a different deployer
lead, pinned to the software version, policy and model, so that an upgrade or a changed model
is approved before it is used on real cases. Existing matters are practice: none was opened
under an authorisation.

**D-33 No page is dropped without a record; OCR text says it is OCR (EL-017).** A document was
marked processed while an image-only exhibit page was silently left out, so a reviewer could not
know the analysis missed it. Every page of a PDF is now accounted for. A page that is only an
image is read by OCR on this machine where Tesseract and Poppler are installed, and its text is
marked "(OCR)" with the page's confidence, because OCR misreads figures, dates and names; a page
OCR cannot read, or reads with low confidence, holds the run until a person checks it against
the original. Where OCR is not installed nothing is guessed: the page is reported unread.

**D-34 A fix to how documents are read reaches documents already read.** The page accounting
of 0.8.4 applied only to documents added after it, so a database from 0.8.3 kept its silently
missing pages. Each document records the reader version that read it; a PDF read by an earlier
one is read again from its stored original before the next run, and reports approved on the
old reading are flagged for review. Any document can be read again on request, without adding
it again.

**D-35 A report says its standing where it is read.** An approved report's file keeps the
status it was approved with: it is the file that was hashed. What it cannot say about itself
(suspended since, superseded, when the law was last checked and from where) is shown beside it
on screen and put above it, outside the hashed text, when it is downloaded.

**D-36 A deletion takes what was made from the matter.** Reports, outbox copies and evidence
packs in the application's folders go with a matter's content and are listed in the receipt by
their hashes; a preservation hold in force keeps them, since a report can quote any document.
Packs exported elsewhere are named in the receipt as beyond the application's control.

**D-37 Exhibits beside text are read, and approvals bind to evidence.** An image beside a page's
text may be an exhibit; with OCR it is read and marked as read from the image, and without OCR
it is a review task on a real matter. A deployment authorisation binds to its evidence
documents by hash and to the whole configuration it was approved for.
