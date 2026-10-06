# Loading ELI Legal into ELI v3

ELI Legal is a separate package. ELI v3 loads it as an **edition**, the unit v3 already defines
for a domain product that overlays the shared core and can be licensed on its own.

## The contract

| ELI v3 expects | ELI Legal provides |
|---|---|
| `manifest.json` with `edition`, `label`, `status`, `summary`, `default_persona`, `adds_capability_categories`, `report_templates`, `policy_module`, `requires_core`, `suggested_tiers` | `src/eli_legal/edition/manifest.json` |
| a policy module with `system_prompt_addendum()`, `output_disclaimer()`, `blocked_actions()` | `eli_legal.edition.policy` |
| capabilities registered with the core | `eli_legal.edition.capabilities` (ten `LEGAL_*` actions) |
| a way to find the pack | entry point `eli.editions` → `legal = eli_legal.edition:register` |

`eli-legal edition verify --eli-root <checkout>` loads the checkout's own edition loader, feeds it
this manifest, and checks the hooks and the three host modules the adapters use. It writes nothing.

## Two ways to connect it

**1. Shim (works with v3 as it is today).** v3 currently discovers editions only inside its own
tree. This writes three small files into `<eli>/eli/editions/legal/` — the manifest and two
modules that forward to the installed package — backing up what was there:

```bash
pip install /path/to/ELI_Legal          # into v3's environment
eli-legal edition install --eli-root /path/to/ELI_v3.0 --force
```

**2. Entry-point discovery (recommended; one small change in v3).**
`integrations/eli_v3/discover-installed-editions.patch` teaches v3's `discover_editions()` to also
read the `eli.editions` entry-point group, and adds `activate_edition()`. After that, any edition
installed as a package appears with no files copied into v3. An installed pack replaces an in-tree
scaffold of the same name and never displaces a pack the core ships. The patch applies cleanly to
v3.0.128 (`git apply --check`); it has not been applied.

## Licensing

`register(host, entitled=...)` refuses to activate when the host passes a set of entitled editions
that does not include `legal` (or `enterprise`). v3's licence payload does not yet carry edition
entitlements — its own loader marks that as a TODO — so until it does, the host should pass
`entitled` itself. Passing nothing means "the host did not say" and is allowed, which is what
standalone use needs.

## Isolation when hosted

- **Three host modules, no more.** `eli.cognition.gguf_inference` (the raw model call, which does
  not pass through the assistant's conversation pipeline or memory), `eli.core.netguard`, and
  `eli.tools.registry.capability_registry`. A test fails if any other `eli.*` import appears.
- **Everything else the host can do is refused.** `blocked_actions()` returns every host action
  except conversation, clock and machine status — 222 of v3.0.128's 239 — and any action v3 adds
  later is refused by default. Enforcing that list is the host's job.
- **No decision through the assistant.** Resolving a hold, verifying, approving, releasing and
  restarting are not capabilities. They are made by a named person in ELI Legal's own interface.
  A decision a sentence can trigger is not a human decision.
- **No content through the assistant.** Capabilities return status, counts, identifiers and file
  paths, because whatever they return enters the host's conversation history.
- **Own everything else.** Store, vault, audit ledger, access control, users and workflow runner
  are ELI Legal's. The acting user must exist in ELI Legal's own register.
- **Both network gates must open.** A legal source is reached only inside ELI Legal's per-host
  window and v3's own gate; v3's toggles alone never open one.

## The pattern for further editions

Finance, healthcare, VR or anything else follows the same four steps: its own package with its own
rules and store; a `manifest.json` in v3's schema; a policy module with the three hooks; and an
`eli.editions` entry point to a `register(host, entitled=...)` function. Nothing of ELI Legal is
needed by another edition, and nothing of another edition is needed by ELI Legal.
