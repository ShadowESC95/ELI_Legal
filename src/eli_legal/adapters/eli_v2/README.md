# ELI v2 reuse boundary

ELI Legal may reuse only selected generic ELI v2 infrastructure through adapters:

- `eli.core.dag` — dependency-aware task orchestration.
- `eli.cognition.gguf_inference.generate` — local/model-agnostic GGUF inference.
- `eli.core.netguard` — fail-closed offline-by-default networking and scoped egress.
- `eli.plugins.document_reader.plugin.DocumentReaderPlugin` — PDF/DOCX/ODT/EPUB/text parsing only.
- selected vector/graph primitives may be adapted later for **matter-scoped** retrieval.

Do not import the ELI personal-assistant kernel, desktop control, shell executor, personal memory,
self-modification, proactive assistant, or the general agent bus into the legal domain.

The legal domain and governance code must depend only on `ports/`; these adapters are replaceable by
standalone implementations today and ELI v3 adapters later.
