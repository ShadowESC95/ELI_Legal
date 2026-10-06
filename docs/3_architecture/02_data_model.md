# Data model

Identifiers: `matter_id`, `document_id`, `chunk_id`, `run_id`, `issue_id`, `claim_id`,
`verification_id`, `hold_id`, `task_id`, `review_id`, `report_id`, `release_id`, `incident_id`,
and for sources `source_id`, `authority_id`, `source_version_id`, `passage_id`.

| Record | Holds |
|---|---|
| Matter | profile, jurisdiction, governing law, forum, relevant date, parties, stated issues, members, named reviewers, approved sources |
| Document | filename, SHA-256, type, party, access scope, custodian, status, injection flags, any waiver |
| Chunk | one paragraph of a document, with its locator and hash |
| Claim (finding) | kind, verbatim text, evidence links, issue links, dependencies, party, date, authority, status and reason |
| EvidenceLink | target (document or authority), passage, locator, quotation and its hash |
| Authority | one dated version of a legal source: citation, court, dates in force, status, when the status was last confirmed and on what basis, treatment history |
| VerificationResult | check type, status, verifier, detail; whether by a person and whether it overrides the system |
| Hold | scope, subject, reason code; who resolved it, how and why |
| VerificationTask | a check routed to a person |
| Run / RunStep | status, versions of model, prompts, tools, workflow and policy; each step's outcome |
| HumanReview | reviewer, decision, reasons, the report hash reviewed, limits acknowledged |
| Report | version, hash, audience, release status, the audit head it was built against |
| ReleasePackage | exact report version, recipients and whether each is entitled |
| Incident | category, severity, containment, closure |
| AuditEvent | actor, action, subject, outcome, hashes, versions; no content |

Finding ids are derived from run, kind, source and text, so re-running a step reproduces the same
ids. Legal sources are not matter data and live in their own tables; a matter reaches them only
through the sources it has approved.

A model's stated confidence is never stored as, or treated as, verification.
