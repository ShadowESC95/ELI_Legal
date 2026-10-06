# Security and privacy

| Measure | How | Limit |
|---|---|---|
| Identity | no service acts on a name alone: a front end must have checked a passphrase session, a passphrase sign-in or a token; a signed-in person cannot act as anyone else; every event records how identity was proved; five wrong attempts lock the account; a second factor (one-time code) is available everywhere and required by default for a networked server | a passphrase and code can still be shared or coerced; no hardware keys; no single sign-on; lock-out can be used to deny a known user access |
| Decisions | resolving a hold, verifying, reviewing, restarting, releasing, closing, approving a source, changing the model and managing users need the passphrase again | — |
| Access | permitted role + matter membership + role valid for the matter's profile; every refusal logged | — |
| Matter isolation | every query carries the matter id; cross-matter writes refused; cross-matter attempts logged | — |
| Network | denied by default; a window opens for one approved host at a time | guards Python sockets in this process; put an OS or container egress rule beneath it |
| Model endpoint | must be on this machine unless its host is approved | a remote endpoint would receive matter content: assess before approving one |
| Untrusted content | fenced with a random marker; look-alike markers defused; hidden characters stripped; text addressed to a model flagged and held | detection is by pattern and is not exhaustive |
| Evidence integrity | originals stored once, read-only, hash-addressed, re-verified on read | — |
| Audit | HMAC-SHA-256 chain, sequence numbers, head anchor beside the key, signed checkpoints | a holder of key and anchor can rewrite history: keep checkpoints off the machine |
| Minimisation | the ledger refuses content fields and long strings | — |
| Retention | closing a matter ends access and can delete documents, text and indexes | retention periods are the organisation's to set |
| Credentials | passphrases as salted PBKDF2-SHA-256 hashes; session and API tokens stored only as hashes; sessions expire; changing a passphrase or deactivating a user ends them | the command-line session file is readable by that operating-system user |
| Server | TLS or loopback only; host, origin, rate and size checks before any route; HttpOnly SameSite cookie plus CSRF value; strict content-security policy; matter content shown as text; no CORS; see [Server security](04_server_security.md) | not penetration-tested; no web-application firewall; one process |

**Not provided by the software.** Encryption at rest (use an encrypted volume), backups, key
escrow, TLS termination, OCR, malware scanning of uploads, and rate limiting.

**Personal data.** Case files routinely contain personal data and may contain special-category
data. The software supports minimisation, access control and deletion; lawful basis, records of
processing, impact assessment and data-subject rights are for the controller.

**Model training.** Matter data is never used to train or fine-tune a model. Fine-tuning on case
material would put privileged content into weights that cannot be isolated by matter or deleted at
matter close.
