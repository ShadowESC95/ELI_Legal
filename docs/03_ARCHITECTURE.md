# Architecture

ELI Legal uses a ports-and-adapters boundary so the legal product remains independently testable.

```text
UI / API / CLI
      |
Application services
      |
Legal domain modules
      |
Workflow + governance gates
      |
Ports ---------------------------------------------------+
 | inference | retrieval | documents | audit | storage | |
 +-------------------------------------------------------+
      |                                      |
Standalone adapters                      Future ELI v3 adapter
```

Every persistent object is matter-scoped. Every material claim has a stable claim ID and one or more evidence/source links. Verification states are explicit rather than inferred from prose.

The legal workflow is a DAG. Downstream generation is not allowed to consume a failed critical verification result as if it were successful. Holds are first-class states, not warnings embedded in text.
