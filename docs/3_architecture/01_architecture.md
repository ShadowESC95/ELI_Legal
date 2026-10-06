# Architecture

```text
 CLI            HTTP API            ELI v3 (edition pack)
   \               |                 /
    +--------- application services ---------+      the only thing a front end calls
                      |
        workflow runner + case-preparation steps
                      |
     legal modules  ·  governance (gates, holds, completeness)
                      |
   store (SQLite) · evidence vault · audit ledger · network guard · sources · inference
```

**One rule set, three front ends.** The CLI, the API and the ELI v3 capabilities all call the
same services, so access control, gates and audit behave identically whichever is used.

**The findings are the product; prose is rendered from them.** A model never writes a finding. It
selects sentences by number, links items by number, and drafts arguments that must cite verified
items. Every answer is validated against what it was given before anything is stored. The report
is assembled from verified findings, so nothing unverified can reach its body.

**Findings and their checks.**

| Kind | What it is | Checks required to be verified |
|---|---|---|
| fact | a sentence from a document, verbatim | provenance, evidence support |
| party authority | a party's reliance on an authority | provenance, evidence support, citation, current law |
| legal proposition | a passage from an authority, verbatim | provenance, citation, current law, proposition |
| application | an argument open to a party | dependency (only verified findings; no new figure or citation), outcome boundary |

For an authority a party cites, the system reports the reliance and checks existence and status.
It does not assert that the authority supports the party's point; the report says so and shows the
closest passage beside the party's sentence for a person to compare.

**Holds are records.** A hold has a scope (finding, document, step), a reason code, and is closed
only when its cause is gone or a named person excludes or waives with reasons. A run cannot reach
review with a hold open.

**Workflow.** One definition (`config/workflows/case_preparation.json`), executed by ELI Legal's
own runner: a step that does not finish cleanly stops everything downstream; each outcome is
logged; if the ledger cannot be written the run stops. Steps are stateless and finding ids are
derived from content, so a restart reproduces the same findings and keeps earlier human decisions.

**Storage.** One JSON document per record beside indexed `matter_id`, `run_id`, `kind`, `status`
columns. There is no method that reads or writes a matter record without a matter id. Full-text
search uses SQLite FTS5. The audit ledger is a separate database file.

**Standalone and hosted.** `build_context` composes everything from settings. Hosted by ELI v3,
only the inference adapter and the network gate differ; store, vault, ledger, access control and
workflow stay ELI Legal's own.
