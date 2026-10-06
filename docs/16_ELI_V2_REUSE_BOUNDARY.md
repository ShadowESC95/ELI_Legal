# ELI v2 reuse boundary

## Reuse or adapt

| ELI v2 module | ELI Legal use |
|---|---|
| `eli/core/dag.py` | Generic workflow/DAG scheduling, retries, dependency blocking. |
| `eli/cognition/gguf_inference.py` | Local model-agnostic inference behind `InferencePort`. |
| `eli/core/netguard.py` | Offline-by-default fail-closed network control; scoped egress only. |
| `eli/plugins/document_reader/plugin.py` | File-format parsing only; no personal-memory indexing. |
| `eli/runtime/evidence_ledger.py` | Design reference for HMAC-SHA256 audit; Legal keeps its own hardened ledger. |
| vector/FAISS/KG primitives | Adapt later, but every index/query must be matter-scoped. |

## Do not import wholesale

- `eli/kernel/engine.py`
- `eli/cognition/agent_bus.py`
- desktop/full-control modules
- shell executor/router
- personal memory/profile
- proactive assistant
- self-improvement/self-patching

The legal application must remain independently testable and must not require ELI to be installed.
