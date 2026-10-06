# Data model

Core identifiers: `matter_id`, `run_id`, `document_id`, `source_id`, `source_version_id`, `claim_id`, `verification_id`, `review_id`, `incident_id`.

Core records:

- Matter: purpose, scope, jurisdiction, authorised users, approved tools/sources, status.
- SourceVersion: origin, retrieval/effective date, jurisdiction, hash, legal-status metadata.
- Claim: text, materiality, uncertainty, source links, verification state.
- EvidenceLink: claim -> document/source span with provenance.
- VerificationResult: type, result, verifier, evidence, timestamp, confidence dimensions.
- ReviewDecision: named reviewer, decision, reasons, overrides, timestamp.
- AuditEvent: actor, action, object, outcome, matter/run IDs, protected chain link.

Do not treat free-text LLM confidence as legal verification.
