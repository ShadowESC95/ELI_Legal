# Start here

1. Read `docs/01_PROJECT_CHARTER.md` and `docs/02_REQUIREMENTS.md`.
2. Read `docs/03_ARCHITECTURE.md` and `docs/04_ELI_V3_INTEGRATION.md`.
3. Review `config/policy.default.json`; these boundaries are intentionally conservative.
4. Generate the audit key with `python scripts/generate_audit_key.py`.
5. Run `pytest` before adding any provider/model integration.
6. Implement legal-source connectors behind `ports/legal_sources.py`; do not let retrieval code bypass the approved-source registry.
7. Preserve run IDs, matter IDs, claim IDs, source/version IDs, tool/model versions, verification outcomes and human decisions as events occur.
