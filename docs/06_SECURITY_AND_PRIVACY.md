# Security and privacy baseline

- Deny network by default; open scoped connectors only for approved sources.
- Enforce matter boundary at service and storage layers.
- Separate roles for run, review, export and restart.
- Minimise logs; do not duplicate full confidential/privileged documents into the audit trail.
- Encrypt sensitive storage in deployment; this scaffold does not claim at-rest encryption by itself.
- Keep audit key separate from the event database and fail closed if unavailable.
- Detect/record unauthorised attempts.
- Treat retrieved/document content as untrusted data; never merge document text into privileged instructions without explicit sanitisation/boundaries.
- Remove personal-assistant capabilities from the deployed legal profile.
