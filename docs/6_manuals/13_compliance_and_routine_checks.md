# Compliance and routine checks

## Why a requirement used to read "partial"

The requirements register lists every requirement of the instruments that apply (the EU AI Act as
a high-risk system under Article 6(2) and Annex III, point 8(a); the GDPR; ISO/IEC 42001) and
says what the **software** does about each: all of it, part of it, or nothing because it is a
duty of an **organisation**. A conformity assessment, a fundamental-rights impact assessment,
staff training, registration in the EU database: no software can do these for you. Read alone,
the register therefore showed many requirements as "partial" or "organisational", which was true
of the software and said nothing about whether the requirement was met.

Now every such duty is an **organisation action** that you complete and record in the
application, and each requirement is shown as one of:

| Status | Means |
|---|---|
| **Met by the software** | The software's controls carry it out; nobody has to do anything |
| **Met** | The software's part is in place and your organisation has recorded its part |
| **Waiting for your organisation** | Something is still to be done; the action is named |
| **Review due** | It was recorded, but its review date has passed |

Where to see it: Governance, "Requirements" (desktop and browser), `eli-legal compliance show`,
and a summary on the Home page. Selecting a requirement shows what the software does (its
controls) and what your organisation has recorded.

## The organisation actions

| Action | What it is | Evidence it leaves | Review |
|---|---|---|---|
| OA-01 | Classify the deployment; settle provider and deployer | The classification form (from `classification_assessment.md`) | yearly |
| OA-02 | Fundamental-rights, data-protection and AI system impact assessment | The impact form (from `impact_assessment.md`) | yearly |
| OA-03 | Train everyone who uses the system | A training record per person | per record |
| OA-04 | Review the risks | A statement, with notes | 90 days |
| OA-05 | Technical documentation (Annex IV) | A document the system drafts from its records, completed by you and signed off by its hash | 180 days |
| OA-06 | Issue the instructions for use | A statement | yearly |
| OA-07 | Evaluate accuracy against declared thresholds | The system's own evaluation result | 90 days |
| OA-08 | Quality management system | A statement | yearly |
| OA-09 | Retention periods | The periods, then enforced by the routine checks | yearly |
| OA-10 | Competent human oversight | A statement | yearly |
| OA-11 | Conformity assessment (Annex VI, internal control) | A statement; the application lists what remains first | yearly |
| OA-12 | EU declaration of conformity | A document the system drafts, signed off by its hash | yearly |
| OA-13 | Registration in the EU database | The registration number | yearly |
| OA-14 | Tell the people affected | A statement | yearly |
| OA-15 | Post-market monitoring and incident reporting | A statement naming who decides and reports | yearly |
| OA-16 | Secure the machines it runs on | A statement | 180 days |
| OA-17 | National data-protection rules | A statement | yearly |
| OA-18 | Review monitoring | A statement | 90 days |
| OA-19 | Importer, distributor, authorised representative | A statement, or that none is involved | yearly |
| OA-20 | Lawful basis and records of processing | A statement | yearly |
| OA-21 | Data governance | A statement | yearly |
| OA-22 | Assess each change before use | The change-assessment form (from `change_assessment.md`) | 180 days |

Any action may instead be recorded as **not applying**, with the reason (an authorised
representative, for example, only for a provider outside the Union).

**Who records them.** A governance officer or legal administrator, with their passphrase again.
Every record names the person, the date and its review date, and is written to the audit trail.

**The forms are the templates.** The questions in a form are read from the governance templates
shipped with the system, so the form on screen and the document on paper cannot differ.

**The evaluation.** OA-07 runs the synthetic matter with five known defects planted in it (an
overruled authority, a citation that does not exist, a status too old to rely on, a document with
text aimed at an AI system, a document that cannot be read) in a workspace of its own, and records
how many were caught, how many facts were verbatim and how many holds were unexpected, against the
thresholds you declare (all caught, all verbatim, none unexpected, unless you set others). It
measures the rule-based controls; accuracy on representative real matters remains yours to
measure.

**The drafted documents.** OA-05 and OA-12 draft the Annex IV documentation and the declaration
of conformity from the system's own records (version, intended purpose, workflow, every control,
every risk, the latest evaluation, where each requirement stands), mark what only the provider
can state, and give the document's SHA-256. The declaration says it is not to be issued until the
conformity assessment and every action needed before real use are recorded.

**Serious incidents.** An incident marked serious shows its EU AI Act Article 73 reporting deadline
(15 days; 10 for a person's death; 2 for a widespread infringement or a serious disruption of
critical infrastructure), counted from when it was opened here, until a named person decides
whether it is reportable and, if it was reported, when and under what reference.

## The routine checks

They run every day on their own (desktop application or server) and whenever someone with the
right asks (Governance, "Routine checks"; `eli-legal checks run`). See the
[administrator manual](04_administrator_manual.md#8-routine-checks) for the full list and for
running them from cron. In short, they confirm that:

- the audit trail and the registers are intact;
- every authority relied on in each matter's latest run is **still good law**, judged exactly as a
  run would judge it today; for an approved report, a change opens an incident, because someone
  may already have relied on it;
- each law and standards package in use was **checked against its official text** recently
  (180 days by default), and nothing in the law calendar has come into application since;
- each legal source's status information is recent enough to rely on;
- every stored original still matches the bytes that were filed;
- the organisation actions are recorded and in date, people are trained and secured, retention is
  applied, and nothing has waited too long.

**Keeping the law current.** No software can know that the law has changed unless a source tells
it. The system is denied the network by default and reads only approved sources, so currency comes
from two places, both checked every day: the status information in each approved source (import
a current copy regularly), and a named person's confirmation that each package still matches its
official text (Laws & Standards, "Confirm checked against the official text";
`eli-legal framework current PACK --note "…"`). The law calendar
(`src/eli_legal/config/law_calendar.json`, or `config/law_calendar.json` in your installation)
lists the dates on which parts of an instrument begin to apply; add your own.

**What a person not on a matter sees.** Results about a matter they are not on read "a matter
you are not on" and the kind of problem. Nothing more.
