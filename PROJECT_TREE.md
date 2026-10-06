# ELI Legal full project tree

```text
ELI_Legal/
├── .github/
│   └── workflows/
│       └── ci.yml
├── artifacts/
│   ├── evidence/
│   │   └── .gitkeep
│   ├── incidents/
│   │   └── .gitkeep
│   └── runs/
│       └── .gitkeep
├── config/
│   ├── jurisdictions/
│   │   └── IE.json
│   ├── workflows/
│   │   └── adr_case_analysis.json
│   ├── policy.default.json
│   └── source_registry.example.json
├── data/
│   ├── matters/
│   │   └── .gitkeep
│   └── source_cache/
│       └── .gitkeep
├── docs/
│   ├── 01_PROJECT_CHARTER.md
│   ├── 02_REQUIREMENTS.md
│   ├── 03_ARCHITECTURE.md
│   ├── 04_ELI_V3_INTEGRATION.md
│   ├── 05_DATA_MODEL.md
│   ├── 06_SECURITY_AND_PRIVACY.md
│   ├── 07_EVALUATION_PLAN.md
│   ├── 08_OPERATIONS_RUNBOOK.md
│   ├── 09_THREAT_MODEL.md
│   ├── 10_DECISIONS.md
│   ├── 11_SOURCE_CONNECTOR_STANDARD.md
│   ├── 12_EVIDENCE_AND_AUDIT_STANDARD.md
│   ├── 13_TEST_MATRIX.md
│   ├── 14_ROADMAP.md
│   └── 15_RAIMS_TRACEABILITY.md
├── governance/
│   ├── change_assessment_template.md
│   ├── control_register.csv
│   ├── evidence_register.csv
│   ├── incident_template.md
│   ├── provider_deployer_matrix.csv
│   ├── README.md
│   └── risk_register.csv
├── scripts/
│   ├── bootstrap_project.ps1
│   ├── bootstrap_project.sh
│   ├── generate_audit_key.py
│   └── verify_tree.py
├── secrets/
│   └── .gitkeep
├── src/
│   └── eli_legal/
│       ├── adapters/
│       │   ├── eli_v3/
│       │   │   ├── __init__.py
│       │   │   ├── adapter.py
│       │   │   └── README.md
│       │   ├── external/
│       │   │   ├── __init__.py
│       │   │   └── base.py
│       │   ├── local/
│       │   │   ├── __init__.py
│       │   │   ├── file_documents.py
│       │   │   ├── hmac_audit.py
│       │   │   └── in_memory.py
│       │   └── __init__.py
│       ├── api/
│       │   ├── routes/
│       │   │   ├── __init__.py
│       │   │   ├── evidence.py
│       │   │   ├── health.py
│       │   │   ├── matters.py
│       │   │   ├── reviews.py
│       │   │   ├── runs.py
│       │   │   └── sources.py
│       │   ├── __init__.py
│       │   ├── app.py
│       │   └── schemas.py
│       ├── application/
│       │   ├── __init__.py
│       │   ├── incident_service.py
│       │   ├── matter_service.py
│       │   ├── monitoring_service.py
│       │   ├── report_service.py
│       │   ├── review_service.py
│       │   ├── run_service.py
│       │   ├── source_service.py
│       │   └── verification_service.py
│       ├── domain/
│       │   ├── __init__.py
│       │   ├── enums.py
│       │   ├── errors.py
│       │   ├── models.py
│       │   └── policy.py
│       ├── governance/
│       │   ├── __init__.py
│       │   └── gates.py
│       ├── legal/
│       │   ├── __init__.py
│       │   ├── case_law_retriever.py
│       │   ├── citation_verifier.py
│       │   ├── current_law_citator.py
│       │   ├── document_coverage.py
│       │   ├── evaluation_suite.py
│       │   ├── evidence_mapper.py
│       │   ├── fact_extractor.py
│       │   ├── human_review_gate.py
│       │   ├── issue_mapper.py
│       │   ├── legal_document_processor.py
│       │   ├── matter_manager.py
│       │   ├── proposition_verifier.py
│       │   ├── report_builder.py
│       │   ├── rules_engine.py
│       │   └── source_registry.py
│       ├── observability/
│       │   ├── __init__.py
│       │   ├── metrics.py
│       │   └── tracing.py
│       ├── persistence/
│       │   ├── migrations/
│       │   │   └── .gitkeep
│       │   ├── __init__.py
│       │   ├── schema.sql
│       │   └── sqlite.py
│       ├── ports/
│       │   ├── __init__.py
│       │   ├── audit.py
│       │   ├── capabilities.py
│       │   ├── clock.py
│       │   ├── documents.py
│       │   ├── inference.py
│       │   ├── legal_sources.py
│       │   ├── model_registry.py
│       │   ├── permissions.py
│       │   ├── retrieval.py
│       │   ├── storage.py
│       │   └── workflow.py
│       ├── security/
│       │   ├── __init__.py
│       │   ├── content_boundary.py
│       │   ├── matter_guard.py
│       │   ├── prompt_injection.py
│       │   ├── rbac.py
│       │   ├── redaction.py
│       │   └── tool_policy.py
│       ├── workflows/
│       │   ├── __init__.py
│       │   └── adr_case_analysis.py
│       ├── __init__.py
│       ├── cli.py
│       └── settings.py
├── tests/
│   ├── evaluation/
│   │   └── test_stale_authority_scenario.py
│   ├── fixtures/
│   │   ├── matter_isolation/
│   │   │   └── .gitkeep
│   │   ├── prompt_injection/
│   │   │   └── .gitkeep
│   │   └── stale_authority/
│   │       └── .gitkeep
│   ├── integration/
│   │   └── test_audit_chain.py
│   ├── security/
│   │   ├── test_boundaries.py
│   │   └── test_prompt_injection.py
│   └── unit/
│       ├── test_content_boundary.py
│       ├── test_human_review_actor.py
│       ├── test_human_review_gate.py
│       ├── test_matter_guard.py
│       ├── test_policy.py
│       ├── test_source_registry.py
│       └── test_verification_gate.py
├── .env.example
├── .gitignore
├── compose.yaml
├── CREATE_TREE_COMMANDS.sh
├── Dockerfile
├── Makefile
├── pyproject.toml
├── README.md
├── SETUP_COMMANDS.md
├── START_HERE.md
└── TREE.txt
```
