# Security and privacy

| Measure | How | Limit |
|---|---|---|
| Identity | no service acts on a name alone: a front end must have checked a passphrase session, a passphrase sign-in or a token; a signed-in person cannot act as anyone else; every event records how identity was proved; five wrong attempts lock the account; a second factor (one-time code) is available everywhere and required by default for a networked server | a passphrase and code can still be shared or coerced; no hardware keys; no single sign-on; lock-out can be used to deny a known user access |
| Decisions | resolving a hold, verifying, reviewing, restarting, releasing, closing, approving a source, changing the model, adding users and changing their roles or passphrases need the passphrase again | deactivating a user, revoking a source and stopping a run do not: each takes access away rather than granting it, and each is recorded |
| Access | account role + matter membership + account role valid for the matter's profile + the person's role on the matter (lead, decision-maker, case worker, assistant, observer, auditor), which only ever narrows; only the lead manages the team; every refusal logged | — |
| Clearance and redaction | each person reads only the material their role on the matter clears them for, and never what another party gave in confidence if they act for a party; anything else is withheld with the reason in lists, passages, findings, chat, the report, warnings and the evidence pack; drafted arguments are never shown more widely than what they rest on; observers and auditors see contact, bank, card and identity numbers masked; oversight of every matter shows no content of one the person is not on; attempts to read withheld material are logged | masking is by pattern and is not exhaustive; names, dates and amounts are not masked |
| Matter isolation | every query carries the matter id; cross-matter writes refused; cross-matter attempts logged | — |
| Network | denied by default; a window opens for one approved host at a time | guards Python sockets in this process; hard offline, below, is the kernel-level rule beneath it |
| Hard offline | the kernel refuses every network connection from the program, whatever code asks: Python, native libraries such as llama.cpp, io_uring, child processes. Linux: a seccomp filter on every thread, applied at once and impossible to remove until the program exits. macOS: started inside the kernel sandbox. Windows: an outbound firewall rule for the program. A server binds its port first and keeps answering | Windows needs an administrator once to add the rule; without one, and on other systems or processors, it is the program's own guard only, and the header says so |
| Model endpoint | must be on this machine unless its host is approved | a remote endpoint would receive matter content: assess before approving one |
| Untrusted content | fenced with a random marker; look-alike markers defused; hidden characters stripped; text addressed to a model flagged and held | detection is by pattern and is not exhaustive |
| Evidence integrity | originals stored once, read-only, hash-addressed, re-verified on read | — |
| Audit | HMAC-SHA-256 chain, sequence numbers, head anchor beside the key, signed checkpoints | a holder of key and anchor can rewrite history: keep checkpoints off the machine |
| Minimisation | the ledger refuses content fields and long strings | — |
| Retention | chosen at set-up (the first-run window or `eli-legal init`), not left unset by accident; closing a matter ends access and can delete documents, text and indexes; the routine checks delete a closed matter's content when its own retention period (else the organisation's) ends, report open matters idle too long, and can run daily from the operating system's scheduler (`eli-legal checks timer --install`); the audit trail cannot be set below six months and is never shortened | the periods are the organisation's to set |
| Files on disk | ELI Legal's programs create everything private (umask 077): folders 0700, the databases and their write-ahead files 0600, vault originals 0400; what an earlier version left readable by others is tightened at start, never following a link out of its folders | on Windows the permission bits do not apply; the user's profile folder keeps others out. Another process of the same user can read them: that is what full-disk encryption and the operating-system account are for |
| Deletion | deleted database rows are overwritten (secure_delete); after a matter's content is deleted the search index is merged, the database rebuilt (VACUUM) and the write-ahead log emptied; files ELI Legal deletes are overwritten before removal; the receipt records each step | on a solid-state or copy-on-write disk an overwrite may not reach the old blocks; backups keep what they copied until they expire |
| Vulnerabilities | reported privately ([SECURITY.md](../../SECURITY.md)), handled on a stated timeline, notified under the Cyber Resilience Act Art. 14 when actively exploited; each release carries a CycloneDX bill of materials and is built only if a known-vulnerability audit of what it ships passes, any exception recorded with its reason | the audit covers the Python components, not the operating system or the bundled Qt and native libraries beyond their Python packages |
| Routine checks | daily: the audit chain, the registers, whether every authority relied on is still good law, law package currency, source age, stored originals against their hashes, compliance, accounts, retention, old holds and incident deadlines; an altered original or a changed authority in an approved report opens an incident | they find what their data shows: a source's status is only as current as its last import |
| Credentials | passphrases as salted PBKDF2-SHA-256 hashes; session and API tokens stored only as hashes; sessions expire; changing a passphrase or deactivating a user ends them | the command-line session file is readable by that operating-system user |
| Server | TLS or loopback only; host, origin, rate and size checks before any route; HttpOnly SameSite cookie plus CSRF value; strict content-security policy; matter content shown as text; no CORS; see [Server security](04_server_security.md) | not penetration-tested; no web-application firewall; one process |

**Not provided by the software.** Encryption at rest (use an encrypted volume), backups, key
escrow and malware scanning of uploads. TLS is provided by the server itself, or by your reverse
proxy. OCR needs Tesseract installed (and Poppler for scanned PDF pages); without it a scan or a
photograph is reported unread and holds the run. The server rate-limits sign-in and requests per
address.

**Personal data.** Case files routinely contain personal data and may contain special-category
data. The software supports minimisation, access control and deletion; lawful basis, records of
processing, impact assessment and data-subject rights are for the controller.

**Model training.** Matter data is never used to train or fine-tune a model. Fine-tuning on case
material would put privileged content into weights that cannot be isolated by matter or deleted at
matter close.
