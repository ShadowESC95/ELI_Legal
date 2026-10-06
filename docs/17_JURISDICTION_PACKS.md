# Jurisdiction packs

A pack is one JSON file in `src/eli_legal/config/jurisdictions/` (or a deployment's own
`./config/jurisdictions/`). It tells the system how a legal system is organised. It never states
the law.

| Field | Meaning |
|---|---|
| `code`, `name`, `legal_family`, `languages` | identity |
| `date_order` | how to read `03/04/2021` (`dmy` or `mdy`) |
| `applies_also` | other packs whose law also applies (EU law in a member state) |
| `court_hierarchy` | courts by level |
| `citation_patterns` | `id`, `kind`, `regex`, `example`; `@ACT` is the shared "Title Act Year" grammar |
| `status_policy` | per kind of authority: treatments that `fail` and those that are a `conflict` for a person |
| `status_max_age_days` | how old a status confirmation may be |
| `official_sources` | where the law is officially published (information only; nothing is fetched) |
| `pack_status` | `structural` or `fallback` |
| `validated_by` | the qualified lawyer who checked the pack; `null` until someone has |

Shipped: `IE`, `GB-EAW`, `EU`, `US-FED`, `DE`, `FR`, `INT-ARB`, `GENERIC`. All are unvalidated
and every report says so. A matter in a jurisdiction with no pack uses `GENERIC`, recognises
little, and says that too.

## Adding a legal system

1. Copy the nearest pack. Set the hierarchy and write a citation pattern for each form of
   citation in use, each with a real `example`. The test suite checks every pattern against its
   own example.
2. Decide the status policy with a lawyer of that jurisdiction. In systems without binding
   precedent, a later contrary decision is normally a `conflict`, not a `fail`.
3. Have the pack reviewed and set `validated_by`.
4. Register and approve a source that covers the jurisdiction. A pack with no source can
   recognise citations but can check none.

Set `require_validated_jurisdiction_packs` in the policy to refuse runs on unvalidated packs.
