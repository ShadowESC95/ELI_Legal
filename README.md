# ELI Legal

Standalone, governance-first legal/ADR AI system scaffold derived from the ELI platform architecture.

**Status:** design/prototype scaffold. It is **not** a deployed tribunal system, does not make awards or final legal decisions, and its legal competence has not been established.

## Purpose

ELI Legal is designed for an authorised arbitration/ADR matter where bounded automated steps may ingest matter documents, research approved legal sources, map facts/issues/evidence, verify citations and legal status, draft a source-linked analysis, and then stop at a named human review gate before any output can be relied upon.

The project is deliberately separate from ELI v2/v3. Integration is through narrow ports/adapters so the specialist legal application can later consume ELI v3 inference, DAG, retrieval, document, audit, API and model-abstraction services without inheriting personal-assistant capabilities.

## Non-negotiable boundaries

- No autonomous award or final decision.
- No autonomous contact with parties.
- No evidence alteration.
- No autonomous privilege/disclosure decision outside an approved role.
- No unapproved web, source or tool access.
- No general shell, desktop control, personal memory, self-modification or proactive personal-assistant behaviour in the legal runtime.
- No material claim may be labelled verified without claim-to-source verification and legal-status checks where applicable.
- Failed or missing verification holds the affected finding and dependent work.
- A named authorised human must approve release for reliance; an agent cannot approve itself.
- Matter isolation is mandatory.
- Audit integrity is fail-closed: no protected audit key, no governed run.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\\Scripts\\activate
python -m pip install -U pip
pip install -e '.[dev]'
cp .env.example .env                   # Windows PowerShell: Copy-Item .env.example .env
python scripts/generate_audit_key.py
pytest
python -m eli_legal.cli doctor
python -m eli_legal.cli show-policy
```

Optional API:

```bash
uvicorn eli_legal.api.app:app --reload
```

## First implementation slice

1. Matter Manager + per-matter RBAC.
2. Approved Legal Source Registry.
3. Ingestion + immutable source manifest.
4. Claim/evidence model with provenance.
5. Citation and proposition verification.
6. Current-law/citator adapter contract.
7. ADR workflow DAG with hard verification gates.
8. Human Review Gate.
9. Fail-closed HMAC audit ledger.
10. Evaluation harness for stale authority, prompt injection, unauthorised matter access and audit tampering.

See `docs/` and `governance/` before implementing connectors or models. The scaffold includes placeholders for the full legal layer listed in the RAIMS design: Matter Manager, Source Registry, Case-Law Retriever, Current-Law/Citator, Citation Verifier, Proposition Verifier, Evidence/Issue Mappers, Court/ADR Rules Engine, Human Review Gate and Legal Evaluation Suite.
