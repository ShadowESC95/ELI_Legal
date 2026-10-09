# Laws & Standards

The packages of law, regulation and standards a matter must comply with. Each one is given to the
model, enforced where the system can, confirmed by the reviewer where only a person can, and
listed in the report.

## What ships

| Package | Kind | Recommended for |
|---|---|---|
| EU AI Act: high-risk system, Annex III point 8(a) (Reg. 2024/1689 as amended by 2026/1744) | EU | every matter under EU law |
| GDPR (Reg. 2016/679) | EU | every matter under EU law |
| Mediation Directive (2008/52/EC) | EU | mediation |
| Council of Europe Framework Convention on AI (CETS 225) | international | courts, tribunals, neutrals |
| CEPEJ European Ethical Charter | international | courts, tribunals, neutrals |
| Fair trial: ECHR Art. 6, EU Charter Art. 47 | international | decision-makers |
| Arbitration due process: UNCITRAL Model Law, New York Convention | international | international arbitration |
| SVAMC Guidelines on AI in arbitration | professional | international arbitration |
| ISO/IEC 42001:2023 | standard | chosen by the organisation |
| Ireland: Data Protection Act 2018; Practice Directions HC 142 / CA 16; Mediation Act 2017 | national | matters under Irish law |
| England and Wales: judicial AI guidance; Arbitration Act 1996 | national | matters under that law |
| Germany: right to be heard; France: principe de la contradiction | national | decision-makers there |
| ABA Formal Opinion 512 | professional | US lawyers |
| Example organisation policy | template | never; copy it |

Every shipped package is a summary written for this software. Each says so in the report until a
qualified lawyer's validation of that exact version is recorded (Record a lawyer's validation).

## Choosing them for a matter

When you open a matter, the packages recommended for its kind and legal system are ticked. Change
them there, or later in the tab under "Packages applied to the open matter". A change applies from
the next run; each run records the exact version of every package it used.

## How each requirement is met

| Shown as | What happens |
|---|---|
| enforced by the system | Named controls carry it out; the report names them |
| given to the model | Told to the model in every call on the matter, after the system's own rules and never in place of them |
| reviewer confirms | Appears among the limits the reviewer must tick before approval |
| disclosed in the report | Its statement is printed under Disclosures |
| for the organisation | Listed in the report as an obligation of the provider or deployer |

A package can also tighten the system: a shorter limit on how old an authority's status
confirmation may be, and terms model-drafted text may never contain. It cannot loosen anything.

"What the model is told…" shows exactly what the model receives.

## Your own requirements

Import a package or document:

- a JSON package: Export any package for the format, edit it, import it under a new id;
- a CSV register with columns `id, reference, title, text, effect` (and optionally `profiles`,
  `instruction`, `statement`);
- a document of your rules (PDF, Word, ODT, RTF, HTML, text): each numbered clause becomes a rule
  for the model, and the reviewer confirms the work meets the document as a whole.

An imported package cannot be used until someone with the right (legal administrator, governance
officer) approves it, with their passphrase. Changing it withdraws the approval. A requirement
that reads like an instruction aimed at an AI system stops it being approved. A run whose package
has since changed cannot be approved; restart it.

Command line: `eli-legal framework list | show | import | approve | validate | withdraw |
reinstate | remove | export | context`, and `eli-legal matter frameworks <matter> [ids…]`.
