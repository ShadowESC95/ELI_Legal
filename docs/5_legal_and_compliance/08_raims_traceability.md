# RAIMS Week 1 design to code

What the Week 1 design committed to, where it now lives, and the test that shows it working. This
is a trace to implementation and automated tests. It is not evidence of effectiveness on real
matters.

## Controls are identified by the RAIMS control map

The five controls of the Week 5 Control Map identify every control in ELI Legal. Each of the
system's controls is a numbered part of one (HO-01.2), placed at a stage of the Week 7 lifecycle
table, with its former number (C-14) kept beside it so earlier records and packages still
resolve (`src/eli_legal/governance/registers/control_families.csv`, `lifecycle_stages.csv`,
`control_register.csv`; `eli-legal governance` checks all three against the code).

| Control | What it needs | Minimum evidence fields | Evidence owner | When |
|---|---|---|---|---|
| RM-01 Risk management | The risk decision, and any hold or restart | Risk limit; exception or hold; action; decision; restart authorisation | Governance Lead | Risk, change or hold |
| HO-01 Human oversight | A named reviewer, the exact report hash and the decision | Reviewer ID; report hash; known limits; approve or reject reason | Deployer reviewer | Every report |
| TR-01 Transparency | The claim, its source and its limitations, shown | Claim ID; source and locator; status and date; visible limitations | Source Owner | Each material claim |
| MO-01 Monitoring | Alerts, and what was done about them | Threshold; alert; affected run; owner; follow-up; re-test | Validation Lead | Run or incident |
| DG-01 Data governance | The approved source, and three separate checks | Approved source and version; three checks; hold and dependency trace | Legal Source Owner | Retrieve or check |

Each run's evidence pack carries `raims_controls.json`: for each of the five, every minimum field
read from the run's own records and said to be present, missing or not yet due (MO-01.9). Security,
access and audit controls are parts of DG-01 and MO-01, as the Week 10 taxonomy places them.

## The instruments named in the use case, and where each is addressed

| Named in the Week 1 papers | Requirement rows | Document |
|---|---|---|
| EU AI Act, Reg. (EU) 2024/1689 as amended by Reg. (EU) 2026/1744: Art. 3 roles; Art. 25 | AIA-03 | [EU AI Act](02_eu_ai_act.md) section 2 |
| Art. 4 AI literacy | AIA-04 | section 6 |
| Art. 6(2)-(3), Annex III 8(a) classification; Art. 6(3) considered and not relied on | AIA-06 | section 1 |
| Arts. 8-15: risk management, data governance, technical documentation (Annex IV), logging, transparency, human oversight, accuracy, robustness, cybersecurity | AIA-09 to AIA-15 | section 4 |
| Arts. 16-27 provider and deployer obligations, incl. 26(2), 26(6), 27 | AIA-16, AIA-19, AIA-26, AIA-27 | sections 5, 6 |
| Art. 43 conformity assessment by internal control (Annex VI); Arts. 47-49 | AIA-43 | section 7 |
| Art. 50 transparency | AIA-50 | section 8 |
| Arts. 72-73 post-market monitoring and serious incidents | AIA-72 | section 9 |
| Application of Chapter III Sections 1-3 to Annex III systems from 2 December 2027 | — | section 3 |
| GDPR, Reg. (EU) 2016/679: Arts. 5, 25, 32 | GDPR-05, GDPR-25, GDPR-32 (also GDPR-22, GDPR-35) | [Data protection](03_data_protection.md) |
| Data Protection Act 2018 (the local example of national law) | DPA-NAT | [Jurisdiction notes](06_jurisdiction_notes.md) |
| ISO/IEC 42001:2023: 6.1.2-6.1.3, 6.1.4, 7.5, 8.1-8.4, 9.1, 10.2 | ISO-6.1, ISO-6.1.4, ISO-7.5, ISO-8.1, ISO-9.1, ISO-10.2 | [ISO/IEC 42001](09_iso_iec_42001.md) |
| ISO/IEC 42001 Annex A: A.5, A.6.2, A.6.2.8, A.7.4-A.7.5, intended use | ISO-6.1.4, ISO-A.6.2, ISO-A.6.2.8, ISO-A.7, ISO-A.9.4 | [ISO/IEC 42001](09_iso_iec_42001.md) |
| Provider is the law firm; deployer is the tribunal | AIA-03; `provider_deployer_matrix.csv` | [EU AI Act](02_eu_ai_act.md) section 2 |

Every row id above is in `requirements_register.csv` with its controls, and
`eli-legal governance` fails if a control it names has lost its code or its tests.

## The three tests promised in the Week 1 presentation

| Promised test | Result | Test |
|---|---|---|
| Outdated authority: does verification hold the affected claim? | Held, wherever the authority appears, naming what overruled it and when | `test_outdated_authority_is_held_wherever_it_appears` |
| Altered or missing audit event: does the integrity or completeness check flag it? | Edited, removed, truncated and rolled-back records are each detected; a store that disagrees with the ledger blocks approval | `test_audit_tamper_detected`, `test_audit_truncation_detected`, `test_rolling_back_database_and_anchor_together_is_caught_by_an_off_machine_checkpoint`, `test_verification_results_altered_in_the_store_are_caught_by_the_completeness_check` |
| Unauthorised matter access: do permissions deny access and record the attempt? | Denied, and an `access_denied` event is written with the reason | `test_unauthorised_matter_access_is_denied_and_recorded` |

## Design statements

| Week 1 statement | Where | Test |
|---|---|---|
| "The citation check confirms the case exists, not that it still applies" | separate citation and current-law checks; `governance/gates.py` | `test_citation_existing_is_not_enough_to_verify_an_authority` |
| "An unresolved material claim cannot be marked verified or released" | gates, holds, review service | `test_stale_authority_cannot_be_marked_verified`, `test_the_whole_lifecycle_from_ingestion_to_approved_release` |
| "A high score cannot average that failure away" | worst result per check counts; no scoring | `test_one_passing_result_cannot_outvote_a_failing_one_for_the_same_check` |
| "Hold the affected work, preserve the evidence, require authorised review" | hold records; named resolution; controlled restart | `test_held_claims_close_only_by_passing_checks_or_by_a_named_exclusion`, `test_restart_reproduces_findings_and_keeps_human_decisions` |
| "A second agent agreeing is not enough" | `legal/proposition_verifier.py` | `test_a_second_model_can_only_make_a_proposition_check_stricter` |
| RBAC plus matter permissions; no role grants every matter | `security/authorizer.py`, `domain/profiles.py` | `test_role_and_matter_membership_are_both_required` |
| Separate authority to run, review, export and restart | role table in `security/rbac.py` | `tests/security/test_access.py` |
| HMAC-SHA-256 chain; keys, checkpoints, sequence and completeness checks | `adapters/local/hmac_audit.py`, `governance/completeness.py` | `tests/security/test_audit.py` |
| Record evidence as the work occurs | every step and decision logged when it happens | `test_evidence_pack_accounts_for_the_run` |
| Logs minimised; references and hashes rather than content | ledger refuses content fields | `test_the_ledger_refuses_content_so_logs_stay_minimal` |
| Anything the system reads is data, never an instruction | fenced content; flagged files held | `test_a_flagged_file_raises_a_hold_and_an_incident_and_never_reaches_a_model` |
| Document-coverage checks | coverage step and holds | `test_unreadable_and_hostile_documents_are_each_held_for_a_person` |
| The agent cannot approve itself; no approver, no run | humans only hold roles; named reviewer required | `test_only_a_human_can_hold_a_role_review_or_resolve`, `test_a_run_cannot_start_without_a_named_human_reviewer` |
| The tribunal keeps the final decision | decision wording refused; policy prohibitions | `test_wording_that_is_the_decision_itself_is_never_allowed` |
| Provider / deployer responsibility split | `governance/provider_deployer_matrix.csv` | — |

## Where the code departs from the Week 1 papers

- **One profile per matter.** The Definition Pack lists tribunal members and solicitors together
  as users. Here a matter belongs to the tribunal, or to a neutral, or to one party's lawyers.
- **No fine-tuning on reviewed reports.** The pack proposed optional QLoRA training. It is left
  out: it would place matter content in model weights that cannot be isolated or deleted.
- **No confidence scores.** Each check passes, fails, conflicts or is inconclusive.
