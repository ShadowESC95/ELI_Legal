# EU AI Act: a high-risk system under Annex III, point 8(a)

**Regulation (EU) 2024/1689, as amended by Regulation (EU) 2026/1744.** This is the regime ELI
Legal is built for. It applies in the same way in every member state of the European Union.
Nothing in this document depends on which member state the provider or the deployer is in.

This follows the classification and the list of provisions in the RAIMS use-case definition and
standards interpretation, and shows for each one what the system does, what the evidence is, and
what is still to do. Each row is also a row in the requirements register
(`src/eli_legal/governance/registers/requirements_register.csv`), which ties it to controls,
code and tests and is checked on every commit. Not legal advice: read the Regulation as amended.

## 1. Classification

**ELI Legal is a high-risk AI system under Article 6(2) and Annex III, point 8(a).**

> AI systems intended to be used by a judicial authority or on their behalf to assist a judicial
> authority in researching and interpreting facts and the law and in applying the law to a
> concrete set of facts, or to be used in a similar way in alternative dispute resolution.

Its intended purpose is exactly that: to assist an arbitration or ADR tribunal, or a court or
tribunal, in researching and interpreting the facts and the law of a specific dispute and in
relating the one to the other.

**Article 6(3) was considered and is not relied on.** It lets a provider treat an Annex III
system as not high-risk where it performs only a narrow procedural or preparatory task and does
not materially influence the outcome of decision-making. ELI Legal's output is meant to inform
the tribunal's analysis, so it can materially influence it. The derogation does not fit.

**The classification is recorded and must be re-checked** whenever the intended purpose, the
users or the boundary of a deployment changes. A form for doing so per deployment ships at
`src/eli_legal/governance/templates/classification_assessment.md`.

| Use | Position |
|---|---|
| By or for a court, tribunal or arbitral tribunal (`adjudicator` profile) | High-risk: the listed use |
| In mediation or conciliation (`neutral_facilitator` profile) | High-risk: "in a similar way in alternative dispute resolution" |
| By one party's own lawyers (`party_representative` profile) | The same system and the same controls. Whether that use alone would fall under point 8(a) does not matter for the provider: the intended purpose includes the high-risk uses, and the system is built to that standard throughout |

It is not, and must never be adapted into, a prohibited practice under Article 5: it does not
score people, predict offending, or assess anyone's character or credibility.

## 2. Roles (Article 3, Article 25)

| Role | In the use case | In general |
|---|---|---|
| **Provider** (Art. 3(3)) | The law firm that builds the system and supplies it under its own name | Whoever develops ELI Legal and places it on the market or puts it into service under their own name or trade mark |
| **Deployer** (Art. 3(4)) | The arbitration or ADR tribunal that uses it | The court, tribunal, arbitral body, mediator, chambers or firm using it under its authority |

A provider that also uses the system internally is both. **Article 25** is checked on any later
change: a deployer or distributor who puts their own name on the system, substantially modifies
it, or changes its intended purpose becomes a provider. The responsibility matrix
(`provider_deployer_matrix.csv`, shown in the Governance screen) allocates every duty.

## 3. When it applies

| Date | What applies |
|---|---|
| 1 August 2024 | Regulation (EU) 2024/1689 entered into force |
| 2 February 2025 | Prohibited practices (Art. 5); AI literacy (Art. 4) |
| 2 August 2025 | General-purpose model obligations; governance; penalties |
| 27 July 2026 | Regulation (EU) 2026/1744 entered into force, amending the Act |
| 2 August 2026 | General application |
| **2 December 2027** | **Chapter III, Sections 1 to 3 (the high-risk requirements and the provider and deployer obligations) for Annex III systems, including point 8(a).** Moved from 2 August 2026 by Regulation (EU) 2026/1744 |
| 2 August 2028 | High-risk obligations for AI in products under Annex I (not this system) |

Regulation (EU) 2026/1744 is also reported to have amended Article 4, the relationship between
the fundamental-rights and data-protection impact assessments, registration, and the penalty
regime. Read each of those provisions in its amended form.

The requirements are mapped and built now, because a tribunal will expect the measures to be in
place before it adopts a tool, whatever the date.

## 4. The requirements for high-risk systems (Articles 8 to 15)

| Provision | What it requires | What the system does | Evidence | State and what remains |
|---|---|---|---|---|
| **Art. 8** | Comply with the requirements, taking account of intended purpose and the state of the art | The requirements below are each tied to controls | Requirements register | See each row |
| **Art. 9** Risk management | A continuous, documented process over the lifecycle; Art. 9(2)(c): evaluate risks from post-market data; Art. 9(8): test against prior defined metrics | A risk register of 21 risks, each tied to controls and to code and tests, checked automatically. Monitoring feeds alerts from control evidence | `risk_register.csv`; `eli-legal governance`; Governance screen | **Partly.** A periodic process owned by an accountable person, and the feed from deployments back into the file, are organisational and not yet set up |
| **Art. 10** Data and data governance | Relevant, representative, documented data; provenance | The system trains no model. Every legal source is registered with its origin, owner, licence, version and retrieval date before it can be used; every document is hashed and its origin recorded | Source register; document vault; evidence pack | **Partly.** Bites on evaluation data: the evaluation set is one synthetic matter |
| **Art. 11, Annex IV** Technical documentation | Drawn up before placing on the market and kept up to date | Architecture, data model, controls, tests, intended purpose, limits and instructions are documented, and the registers are generated evidence | `docs/3_architecture`, `docs/4_security`, registers | **Partly.** Not yet assembled in the Annex IV structure; the application drafts the Annex IV file from the system's own records for the provider to complete and sign off (OA-05) |
| **Art. 12** Record-keeping | Automatic logging of events over the lifetime | Every step, tool call, source with version and date, model and prompt version, hold, decision and release is logged in a signed chain; each run's record is reconciled with it | Audit Trail; evidence pack; `tests/security/test_audit.py` | **Implemented** |
| **Art. 13** Transparency and instructions for use | Enough for deployers to interpret output and use it properly; instructions issued to the deployer | Every report states its limits and what was and was not verified; each agent's mandate, each finding's checks and each hold's reason are shown; instructions for use ship | `docs/6_manuals/08_instructions_for_use.md`; report section 8 | **Implemented**, to be adapted per deployment |
| **Art. 14** Human oversight | Art. 14(4)(a) understand capacities and limits; (b) remain aware of automation bias; (c) correctly interpret output; (d) decide not to use or to override; (e) intervene or stop | A named reviewer is required before any run; holds stop work until a person decides; every stated limit must be acknowledged before approval; the reviewer can exclude, return or reject; any authorised person can stop a run; approvals that follow no challenge are flagged | Review screen; `test_only_a_human_can_hold_a_role_review_or_resolve`; monitoring alert | **Implemented.** Making review real is the deployer's |
| **Art. 15** Accuracy, robustness, cybersecurity | Art. 15(1),(3): appropriate and declared accuracy; (4): resilience to errors and inconsistencies; (5): resilience to attempts to alter use, outputs or performance | Three separate checks on every authority; nothing passes on a partial result; re-running reproduces findings; text addressed to a model is flagged, held and kept out of prompts; proven identity, lock-out, second factor; hardened server; network denied | `tests/evaluation`, `tests/security`, `tests/api` | **Partly.** No accuracy figure on representative real matters can be declared. No penetration test; a built-in evaluation measures how many planted defects are caught against declared thresholds (OA-07) |

## 5. Provider obligations (Articles 16 to 25)

| Provision | What it requires | State |
|---|---|---|
| **Art. 16** | Ensure compliance with Arts. 8 to 15; identify the provider on the system; and the duties below | Organisational; each duty below is an organisation action recorded in the application |
| **Art. 17** Quality management system | Documented policies, procedures and instructions | **Not done.** Where it is documented and who runs it is recorded in the application (OA-08) |
| **Art. 18** Keep documentation | Ten years after placing on the market | **Not arranged.** Retention periods are set and enforced in the application (OA-09); the ten-year keeping is the provider's |
| **Art. 19** Automatically generated logs | Keep the logs under the provider's control | **Implemented** in each installation; retention at the provider is organisational |
| **Art. 20** Corrective action and duty of information | Withdraw, disable or recall; inform deployers and authorities | **Partly.** Holds, incidents and controlled restart exist per installation; the routine checks open an incident when an approved report's law changes; the provider's procedure is recorded in the application (OA-15) |
| **Art. 21** Cooperation with authorities | Provide information and access to logs on request | The evidence pack is built for this; the contact point is recorded (OA-15) |
| **Art. 22** Authorised representative | For providers established outside the Union | Only if that applies; whether it does is recorded (OA-19) |
| **Art. 25** Responsibilities along the value chain | See section 2 | Checked on any change of role |

## 6. Deployer obligations (Articles 26 and 27)

| Provision | What it requires | What helps |
|---|---|---|
| **Art. 26(1)** | Use the system in accordance with the instructions for use | Instructions for use |
| **Art. 26(2)** | Assign oversight to people with the competence, training and authority | Named reviewers, whose role on the matter must let them approve; a role on each matter; training recorded per person, and reviewers without it reported by the routine checks (OA-03, OA-10) |
| **Art. 26(4)** | Input data relevant and sufficiently representative, where the deployer controls it | Coverage check; unread documents hold the run |
| **Art. 26(5)** | Monitor operation; suspend and inform on risk or serious incident | Monitoring; incidents; stop |
| **Art. 26(6)** | Keep the automatically generated logs, at least six months | The ledger is on from the first run and never shortened; the retention setting cannot go below six months (OA-09); the deployer keeps it with its key |
| **Art. 26(7)** | Inform workers' representatives before use at work | — |
| **Art. 26(8)**, 49(3) | Public authorities register their use | — |
| **Art. 26(11)** | Inform people subject to decisions made with the system's assistance | A tribunal needs a position on how |
| **Art. 27** | Fundamental-rights impact assessment before first use, for bodies governed by public law and private bodies providing public services | Completed and signed in the application (OA-02), whose form is the `impact_assessment.md` template, combined with the data-protection assessment |
| **Art. 4** | AI literacy of the people operating and using the system | User manual; instructions for use; training recorded per person in the application (OA-03), and anyone working on matters without a current record reported by the routine checks |

## 7. Conformity and registration (Articles 43, 47 to 49)

| Provision | What it requires | State |
|---|---|---|
| **Art. 43**, Annex VI | Conformity assessment before placing on the market. For Annex III points 2 to 8 the route is **internal control** under Annex VI: no notified body | **Not done.** The application shows which actions remain before it can be recorded (OA-11) |
| **Art. 47** | EU declaration of conformity | **Not done.** The application drafts it from the system's records, marked not to be issued until the assessment is recorded (OA-12) |
| **Art. 48** | CE marking | **Not done** |
| **Art. 49** | Registration in the EU database | **Not done.** The registration number is recorded in the application (OA-13) |

## 8. Transparency (Article 50)

Where relevant to how people interact with the system and how its output is used. The users are
professionals who chose the tool, and the application says what it is. Reports label anything a
model drafted, name the model, and keep it apart from findings taken word for word from
documents. If a report or an extract is passed on, the labels go with it.

## 9. After placing on the market (Articles 72 and 73)

| Provision | What it requires | State |
|---|---|---|
| **Art. 72** Post-market monitoring | A plan, running continuously, that feeds the risk management file | **Partly.** Each installation computes monitoring from control evidence. A provider-side plan and a channel for deployers to report are not set up |
| **Art. 73** Serious incidents | Report to the market surveillance authority of the member state where it occurred | **Partly.** An incident can be marked serious for a person to assess. No reporting procedure exists |

## 10. What a deployment hands an assessor

| Evidence named in the use case | Where it comes from |
|---|---|
| Technical documentation and the risk management file (Art. 11, Annex IV; Art. 9) | `docs/`, the registers |
| Instructions for use issued to the deployer (Art. 13) | `docs/6_manuals/08_instructions_for_use.md` |
| Per-run logs: plan, tool calls, sources with versions and dates, model and prompt versions (Art. 12) | The audit ledger; the evidence pack for any run |
| Named reviewer and the record of each decision (Art. 14, 26(2)) | Review records, bound to the report's hash |
| Training records (Art. 4) | The deployer's |
| Post-market monitoring data (Art. 72) | Governance, Monitoring; `eli-legal monitor` |

## 11. The order of work for the provider

1. Record the classification and the Article 6(3) reasoning, and who the provider is.
2. Appoint an accountable person; write the quality management system (Art. 17).
3. Assemble the technical documentation in the Annex IV structure from what exists.
4. Set accuracy thresholds in advance; test on matters with known answers; declare the results
   (Art. 9(8), 15).
5. Write the post-market monitoring plan and the serious-incident procedure (Arts. 72, 73).
6. Carry out the internal-control conformity assessment (Art. 43, Annex VI); sign the declaration
   (Art. 47); affix the CE marking (Art. 48); register (Art. 49).

## 12. Penalties (Article 99)

Up to EUR 15 million or 3% of worldwide annual turnover for breach of operator obligations; up
to EUR 7.5 million or 1% for supplying incorrect information. The regime for smaller enterprises
was amended by Regulation (EU) 2026/1744; read the current text.

## 9. Where each requirement stands, live

The requirements register lists, for every requirement above and of the GDPR and ISO/IEC 42001,
what the software does about it. That alone would read as "partial" wherever an organisation also
has a duty. In the application (Governance, "Requirements"; `eli-legal compliance show`) each
requirement is instead shown as **met by the software**, **met** (the software's part done and
the organisation's part recorded), **waiting for your organisation** (naming the action), or
**review due**. See [Compliance and routine checks](../6_manuals/13_compliance_and_routine_checks.md).
