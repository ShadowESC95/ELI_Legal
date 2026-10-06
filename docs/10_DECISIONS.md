# Architecture decision log

## ADR-001 — Separate product, adapter-ready for ELI v3
Accepted. The legal domain must not depend directly on ELI internals.

## ADR-002 — Hard gates are state, not prose
Accepted. Verification failures create `HOLD`/`BLOCKED` states consumed by the workflow engine.

## ADR-003 — Audit fail-closed
Accepted. HMAC key absence is a startup/run failure for governed workflows; no downgrade to an unkeyed chain.

## ADR-004 — Legal source status verification separated from generation
Accepted. A generator agreeing with itself is not independent verification.
