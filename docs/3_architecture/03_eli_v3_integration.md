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

## Opening ELI Legal from ELI v3 (bundles)

ELI v3 can open ELI Legal in place of its own window, or beside it. ELI Legal is a *bundle*: a
separate application on ELI v3's core. The contract is ELI v3's `eli/bundles` (see its
`docs/BUNDLES.md`); other bundles (ELI VR, Healthcare, Finance) use the same one.

| How ELI Legal is installed | How ELI v3 finds it | Runs |
|---|---|---|
| In ELI v3's Python environment (`pip install eli-legal`) | the `eli.bundles` entry point (`eli_legal.bundle:describe`) | inside ELI v3's process, with ELI v3's loaded model unless another is chosen |
| On its own (AppImage, installer) | `legal.json` in ELI v3's `bundles` folder: written by the `.run` and Windows installers, and by every installed copy when it starts and the record names no copy, a removed one or an older version; `eli-legal bundle register` writes it by hand | as its own program |
| Downloaded, never started | ELI v3 looks in Desktop, Downloads and Applications for the files its legal edition names | as its own program |

**Which copy ELI v3 opens.** ELI v3 looks afresh each time it starts and opens one copy: the
installed package, else the registered copy, else one found by looking. Each gives way to a
strictly newer version, so an old copy never hides a new release (a change to ELI v3's bundle
discovery made on 10 November 2026; earlier releases of ELI v3 prefer the package or the
registration whatever its version, and take the most recently changed file found).
Looking skips setup programs and takes the highest version. A copy registers itself only
when it is newer than the one registered, so two copies of the same version never take turns,
and an uninstaller removes the record only if it names its own copy. Installing a release does
not install it into ELI v3's Python environment: a package installed there stays at its version
until it is upgraded with pip.

From ELI v3: the start-up question (ELI v3 or a bundle), `eli --bundle legal`, `eli --bundles`, or
the Bundles menu. Opened this way ELI Legal keeps its data in its own folder, never ELI v3's, and
keeps every control it has on its own.
