# Legal source standard

A source can be approved only when the register records: who publishes it; the licence or terms
and that they were reviewed; the jurisdictions covered; what a status answer from it means; the
only hosts it may contact (if it uses the network); and how a person can inspect the original.
`eli-legal source approve` refuses otherwise.

A source may also declare the citation patterns it is **complete** for. Only then does "not found"
mean "does not exist"; otherwise it means "could not be confirmed" and goes to a person.

Existence, current status and support for a proposition are three different answers. A connector
result is never by itself a verified proposition.

## The local corpus connector

The one connector shipped reads a corpus you load: `eli-legal source import <source> <dir>`.
Each authority is a JSON file:

```json
{
  "citation": "[2022] XXSC 7",
  "aliases": ["Corvin Freight v Dalmere Holdings"],
  "title": "Corvin Freight v Dalmere Holdings",
  "jurisdiction": "XX",
  "kind": "case",
  "court": "Supreme Court",
  "decision_date": "2022-06-10",
  "status": "in_force",
  "status_checked_at": "2026-10-04T09:00:00+00:00",
  "status_basis": "who or what says so",
  "treatments": [{"treatment": "overruled", "effective_date": "2024-01-15", "by_citation": "…"}],
  "text": "…"            
}
```

`text_file` (a path inside the corpus) may replace `text`. For legislation, give `effective_from`
and `effective_to`; several versions of one instrument share a citation and the version in force
on the matter's relevant date is the one used. `kind` is `case`, `legislation`, `rule`, `treaty`
or `secondary`. Treatments that change standing: `overruled`, `reversed`, `superseded`,
`repealed`, `amended`, `doubted`. A status older than the pack's limit (30 days by default) is
inconclusive.

## Writing another connector

Implement `LegalSourcePort` (`src/eli_legal/ports/legal_sources.py`): `describe`, `search`,
`resolve`, `get`, `passages`, `status`. Reach the network only inside `NetworkGuard.allow(host=…)`.
Record the retrieved text's hash and retrieval time as a source version. Add recorded-response
tests; do not test against a live service in CI.
