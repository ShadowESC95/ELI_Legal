# Future ELI v3 integration

Do not import ELI v2/v3 internals from legal-domain code. Integrate only through `eli_legal.ports`.

Candidate mappings later:

| ELI Legal port | ELI v3 service candidate |
|---|---|
| InferencePort | local/model-agnostic inference |
| WorkflowPort | DAG/orchestration |
| RetrievalPort | hybrid retrieval |
| DocumentPort | document ingestion/parsing |
| AuditPort | evidence ledger |
| ModelRegistryPort | model/version abstraction |
| CapabilityPort | approved capabilities/health |

The ELI v3 adapter must expose only capabilities explicitly authorised for ELI Legal. Personal memory, desktop control, self-modification, proactive assistant behaviour and general shell execution remain outside the legal capability set.
