# RAIMS requirement-to-code traceability

This map turns the supplied Week 1 design into implementation locations. It is a design trace, not evidence that a control is effective.

| Requirement / design choice | Project location | Initial test/evidence |
|---|---|---|
| Approved users, sources and tools | `security/matter_guard.py`, `legal/source_registry.py`, `security/tool_policy.py` | matter/source unit tests; access logs later |
| Matter separation | `Matter.matter_id`, `security/matter_guard.py`, persistence rules | `test_cross_matter_access_denied` |
| Source/version capture | `SourceVersion`, source registry, connector standard | source manifest to be implemented |
| Claim-to-source traceability | `Claim`, `EvidenceLink`, `EvidenceMapper` | claim/evidence records |
| Independent legal-status check | `legal/current_law_citator.py` | `test_stale_authority_cannot_be_marked_verified` |
| Citation verification | `legal/citation_verifier.py` | connector-specific gold tests later |
| Proposition support | `legal/proposition_verifier.py` | gold proposition dataset later |
| Source content treated as data | `security/content_boundary.py`, `security/prompt_injection.py` | prompt-injection tests |
| Failed verification holds dependent work | `governance/gates.py`, ADR DAG config | verification-gate tests |
| Named human approval; agent cannot approve itself | `legal/human_review_gate.py` | human-review tests |
| Stop, correct, revalidate, authorised restart | `application/run_service.py`, runbook | restart exercise later |
| HMAC-SHA-256 audit chain | `adapters/local/hmac_audit.py` | tamper test + key-missing test |
| Fail closed if audit key unavailable | audit adapter | `test_missing_audit_key_fails_closed` |
| Minimise confidential/privileged log content | `security/redaction.py`, audit standard | log-content tests later |
| Model/tool version evidence | `Run.model_versions`, `Run.tool_versions` | run manifest later |
| Monitoring failed checks/reviewer corrections | `application/monitoring_service.py` | monitoring thresholds later |
| Manual fallback / bounded autonomy | policy + runbook + workflow states | operational exercise later |
| No final award/party contact/evidence mutation | `config/policy.default.json` | boundary test |
| Test known matters, stale law and hostile files | `tests/evaluation`, `tests/fixtures` | evaluation pack grows with gold cases |
| Reassess material changes | governance change template + roadmap | completed change assessments |
| ELI v3 integration without personal capabilities | `ports/`, `adapters/eli_v3/`, integration doc | contract tests when v3 adapter exists |
