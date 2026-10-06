# EU AI Act

Regulation (EU) 2024/1689. Not legal advice; article numbers are pointers to the text. Dates
below reflect the Act as amended in 2026 **as reported**; confirm them in the Official Journal.

## 1. Is ELI Legal a high-risk AI system?

**For court, tribunal and ADR use: plan on yes.**

Annex III, point 8(a) lists as high-risk:

> AI systems intended to be used by a judicial authority or on their behalf to assist a judicial
> authority in researching and interpreting facts and the law and in applying the law to a
> concrete set of facts, or to be used in a similar way in alternative dispute resolution.

The `adjudicator` profile does exactly this, and the `neutral_facilitator` profile is ADR. Recital
61 explains the concern (effect on democracy, the rule of law, individual freedoms, the right to
an effective remedy and a fair trial), says that ADR is covered where the outcome produces legal
effects for the parties, and says that such tools may support but must not replace the judge:
the final decision must remain human. It also says purely ancillary administrative tasks are not
high-risk; ELI Legal is not that.

**The exception in Article 6(3)** lets a provider treat an Annex III system as not high-risk
where it poses no significant risk because it only performs a narrow procedural task, improves
the result of a completed human activity, detects decision patterns without replacing human
assessment, or performs a preparatory task. A provider relying on it must document the
assessment before placing the system on the market and register it (Article 6(4), 49(2)).
"Preparatory task" is arguable for ELI Legal, but the system researches and interprets facts and
law for a specific dispute, which is the listed use. The cautious course, taken here, is to
treat it as high-risk for adjudicator and ADR use. This is a question for counsel.

**For a party's own lawyers** (`party_representative`): point 8(a) is addressed to use by or for
a judicial authority, or similarly in ADR. A firm preparing its own client's case is probably
outside it. That reading should be confirmed, and it does not change the product's status: the
provider's intended purpose includes the high-risk uses.

**Not prohibited practices.** ELI Legal does not score people, predict offending, infer emotions
or categorise people biometrically (Article 5). It should never be adapted to do so.

## 2. Dates

| Date | What applies |
|---|---|
| 1 August 2024 | The Act entered into force |
| 2 February 2025 | Prohibited practices (Article 5); AI literacy (Article 4) |
| 2 August 2025 | General-purpose model obligations; governance; penalties |
| 2 August 2026 | General application, including transparency duties (Article 50) |
| **2 December 2027** | High-risk obligations for Annex III systems. This was originally 2 August 2026. The "Digital Omnibus" amendment, reported as endorsed by the Parliament on 16 June 2026 and approved by the Council on 29 June 2026, moved it |
| 2 August 2028 | High-risk obligations for AI in products under Annex I (not relevant here) |

**Check the amended text as published in the Official Journal before relying on any of these.**
The postponement is a longer runway, not an exemption: a court or tribunal may reasonably expect
the measures to be in place before it adopts a tool, whatever the legal deadline.

## 3. Who is what

| Role | Who | Note |
|---|---|---|
| Provider | Whoever develops ELI Legal and places it on the market or puts it into service under their own name or trade mark (Article 3(3)) | A deployer who puts their own name on it, substantially modifies it, or changes its intended purpose becomes a provider (Article 25) |
| Deployer | The court service, tribunal, arbitral institution, mediator, chambers or firm using it under its authority (Article 3(4)) | |
| Provider of a general-purpose model | Whoever made the language model a deployer chooses to run | ELI Legal ships no model |
| Authorised representative | Needed if the provider is established outside the EU (Article 22) | |

## 4. Provider duties and where they stand

| Duty | Article | State |
|---|---|---|
| Risk management system, kept up over the lifecycle | 9 | **Partly.** A risk register tied to controls exists and is checked against the code. A documented, periodic process run by an accountable person does not |
| Data and data governance | 10 | **Partly.** The system trains no model. The duty bites on evaluation data: the evaluation set is synthetic and small |
| Technical documentation (Annex IV) | 11 | **Partly.** Architecture, data model, controls and tests are documented. They are not assembled in the Annex IV structure |
| Record-keeping: automatic logs | 12 | **Implemented.** Tamper-evident ledger, per-run reconciliation, evidence pack |
| Transparency and instructions for use | 13 | **Implemented**, to be adapted per deployment. Every report states its limits |
| Human oversight by design | 14 | **Implemented.** Named reviewer, holds, stop and restart, acknowledgement of limits, monitoring of unchallenged approvals |
| Accuracy, robustness, cybersecurity, with declared metrics | 15 | **Partly.** Controls and a gold evaluation matter exist. **No accuracy figure on real matters can be declared** |
| Quality management system | 17 | **Not done** |
| Keep documentation for ten years | 18 | **Not arranged** |
| Corrective action and duty to inform | 20 | **Not arranged** |
| Conformity assessment | 43 | **Not done.** For Annex III point 8 this is internal control (Annex VI), not a notified body |
| EU declaration of conformity; CE marking | 47, 48 | **Not done** |
| Registration in the EU database | 49 | **Not done** |
| Post-market monitoring plan | 72 | **Partly.** Monitoring is computed in each installation. A provider-side plan and a channel for deployers to report does not exist |
| Serious-incident reporting | 73 | **Partly.** Incidents can be marked serious for a person to assess. No reporting procedure exists |
| AI literacy of staff | 4 | **For the provider's own people: not arranged** |

## 5. Deployer duties

| Duty | Article | What helps |
|---|---|---|
| Use it according to the instructions for use | 26(1) | [Instructions for use](../6_manuals/08_instructions_for_use.md) |
| Assign oversight to people with the competence, training and authority | 26(2) | Named reviewers; roles |
| Make sure input data is relevant and sufficiently representative, where the deployer controls it | 26(4) | Coverage check; unread documents hold the run |
| Monitor operation; suspend and tell the provider on risk or serious incident | 26(5) | Monitoring; incidents; stop |
| Keep the automatically generated logs at least six months | 26(6) | The ledger; back it up with its key |
| Tell workers' representatives before use at work | 26(7) | — |
| Public authorities: register the use | 26(8), 49(3) | — |
| Tell people who are subject to decisions made with its assistance | 26(11) | For courts and tribunals this needs a considered position |
| Fundamental-rights impact assessment before first use, for public bodies and private bodies providing public services | 27 | Template in `src/eli_legal/governance/templates/` |
| Give an explanation of the system's role in a decision, on request | 86 | Evidence pack; the report states what it relied on |
| AI literacy of staff | 4 | [User manual](../6_manuals/03_user_manual.md) |

## 6. Transparency duties that apply regardless of risk class (Article 50)

- A person interacting with the system must know it is an AI system. The users are professionals
  who chose it; the application says what it is.
- Machine-generated text should be identifiable as such. Reports label arguments drafted by a
  model, name the model, and separate them from findings taken verbatim from documents. If a
  report or an extract is passed on, keep those labels.

## 7. The model

The Act puts duties on whoever provides a general-purpose model. A deployer choosing a model
should prefer one whose provider publishes the documentation the Act requires, and should record
which model and version produced what. ELI Legal records the model identity for each run.

## 8. Penalties

Up to EUR 15 million or 3% of worldwide annual turnover for breach of operator obligations; up
to EUR 7.5 million or 1% for supplying incorrect information; for small and medium-sized
enterprises, whichever of the two amounts is lower (Article 99).

## 9. Related instruments

| Instrument | Relevance |
|---|---|
| Council of Europe Framework Convention on Artificial Intelligence and Human Rights, Democracy and the Rule of Law (2024) | Binds states that ratify it; covers use by public authorities, including courts |
| CEPEJ European Ethical Charter on the use of AI in judicial systems (2018) | Five principles: fundamental rights, non-discrimination, quality and security, transparency, "under user control". A useful test of a deployment |
| ISO/IEC 42001 (AI management systems), ISO/IEC 23894 (AI risk management) | A route to the quality and risk management the Act asks for |
| Harmonised standards under the Act (CEN-CENELEC JTC 21) | Following them, once cited in the Official Journal, gives a presumption of conformity. Their lateness was the stated reason for the postponement |

## 10. A workable order of work for the provider

1. Decide and record the classification, with counsel.
2. Appoint an accountable person; write the quality management system.
3. Assemble the technical documentation in the Annex IV structure from what exists.
4. Set accuracy thresholds; measure on representative matters; declare the results.
5. Write the post-market monitoring plan and the serious-incident procedure.
6. Carry out the internal-control conformity assessment; sign the declaration; register.
