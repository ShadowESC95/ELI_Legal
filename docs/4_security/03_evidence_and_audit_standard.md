# Evidence and audit standard

**Record as it happens.** Each step outcome, each set of verification results (by digest), each
hold and its resolution, each human verification, review, restart, release and delivery is
appended to the ledger when it occurs. Nothing is reconstructed afterwards.

**What an event holds.** Actor, matter, run, action, subject, outcome, hashes, versions. The
ledger refuses fields named for content and any string over 300 characters.

**Integrity.** Each event is signed with HMAC-SHA-256 over the previous signature, a sequence
number and the event. This detects an edited, removed or reordered event.

**Truncation.** A chain with its newest events removed is still internally consistent. A signed
head anchor kept beside the key, not beside the database, records the length and last signature;
a shorter chain fails.

**Rollback.** Restoring an old database and its old anchor together is invisible locally.
`eli-legal audit checkpoint` produces a signed statement to keep off the machine;
`eli-legal audit verify --against` then exposes the rollback.

**Completeness.** A chain proves recorded events were not altered, not that every event was
recorded. For each run the store is reconciled with the ledger: every finished step (with a hash
of its outputs), hold, resolution and review must have its event, and the digest of all
verification results must match the last one logged. This runs in final validation, again at
approval, and in the evidence pack.

**What integrity does not prove.** That the legal analysis is right. HMAC authenticates the
record; the verification checks and the human reviewer address the substance.

**Key.** At least 32 bytes, owner-only permissions, stored apart from the database. Each event
records its key id, and a ledger can be opened with retired keys so older events still verify.

**Evidence pack.** `eli-legal evidence M R` exports the run, document manifest (hashes, not
content), findings, verification results, holds, tasks, reviews, incidents, releases, the reports,
the run's audit events, the chain and completeness results with a checkpoint, and the
configuration in force — each file hashed in `MANIFEST.json`.
