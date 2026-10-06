# Security and privacy

| Measure | How | Limit |
|---|---|---|
| Access | permitted role + matter membership + role valid for the matter's profile; every refusal logged | identity is as strong as the deployment's account and token handling |
| Matter isolation | every query carries the matter id; cross-matter writes refused; cross-matter attempts logged | — |
| Network | denied by default; a window opens for one approved host at a time | guards Python sockets in this process; put an OS or container egress rule beneath it |
| Model endpoint | must be on this machine unless its host is approved | a remote endpoint would receive matter content: assess before approving one |
| Untrusted content | fenced with a random marker; look-alike markers defused; hidden characters stripped; text addressed to a model flagged and held | detection is by pattern and is not exhaustive |
| Evidence integrity | originals stored once, read-only, hash-addressed, re-verified on read | — |
| Audit | HMAC-SHA-256 chain, sequence numbers, head anchor beside the key, signed checkpoints | a holder of key and anchor can rewrite history: keep checkpoints off the machine |
| Minimisation | the ledger refuses content fields and long strings | — |
| Retention | closing a matter ends access and can delete documents, text and indexes | retention periods are the organisation's to set |
| API | bearer tokens stored as hashes; deactivating a user revokes them | run it behind TLS |

**Not provided by the software.** Encryption at rest (use an encrypted volume), backups, key
escrow, TLS termination, OCR, malware scanning of uploads, and rate limiting.

**Personal data.** Case files routinely contain personal data and may contain special-category
data. The software supports minimisation, access control and deletion; lawful basis, records of
processing, impact assessment and data-subject rights are for the controller.

**Model training.** Matter data is never used to train or fine-tune a model. Fine-tuning on case
material would put privileged content into weights that cannot be isolated by matter or deleted at
matter close.
