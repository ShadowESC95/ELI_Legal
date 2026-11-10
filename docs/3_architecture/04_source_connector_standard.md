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

## Live official databases

`eli-legal source add-live eu_cellar --terms-reviewed` (or `uk_open`) registers a live source
with its publisher, licence, hosts and status meaning declared; `eli-legal source approve` then
admits it, and it is used on matters that list it.

| Connector | Reaches | Resolves | Status it gives |
|---|---|---|---|
| `eu_cellar` | publications.europa.eu, eur-lex.europa.eu | CELEX, ECLI, case numbers, "Regulation (EU) 2016/679", "Directive 95/46/EC" | Legislation: in force, entry into force and application, end of validity, the repealing act. Judgments: no treatment recorded, so unknown and for a person, who is told how many later judgments and Advocate General's opinions cite it and the latest three |
| `uk_open` | www.legislation.gov.uk, caselaw.nationalarchives.gov.uk | Acts by title and year, SIs, neutral citations | Legislation: the current version and, for a relevant date before it, the version then in force, each with its dates and repealed sections. Judgments: none recorded, so unknown and for a person |

An authority is fetched when first needed, stored as a dated source version with its hash,
retrieval time, status and repeal history, and answered from the store for 24 hours. Every
request goes through the network guard to the source's own hosts over HTTPS; under hard
offline none is made. The UK judgments are under the Open Justice Licence, which requires a
transactional licence from the National Archives for computational analysis: obtain one before
approving `uk_open` for that use. Ireland's statute book and courts offer no open interface; use
a corpus. A licensed citator (case-law treatment) can be connected through this same standard.

## Writing another connector

Implement `LegalSourcePort` (`src/eli_legal/ports/legal_sources.py`): `describe`, `search`,
`resolve`, `get`, `passages`, `status`. Reach the network only inside `NetworkGuard.allow(host=…)`.
Record the retrieved text's hash and retrieval time as a source version. Add recorded-response
tests; do not test against a live service in CI.
