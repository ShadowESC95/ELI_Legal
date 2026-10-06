# RAIMS Week 1 design to code

What the Week 1 design committed to, where it now lives, and the test that shows it working. This
is a trace to implementation and automated tests. It is not evidence of effectiveness on real
matters.

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
