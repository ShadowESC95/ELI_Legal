# ELI v3 integration files

`discover-installed-editions.patch` is a proposed change to ELI v3's `eli/editions/__init__.py`.
It has **not** been applied to any ELI checkout. To review and apply it yourself:

```bash
cd /path/to/ELI_v3.0
git apply --check /path/to/ELI_Legal/integrations/eli_v3/discover-installed-editions.patch
git apply         /path/to/ELI_Legal/integrations/eli_v3/discover-installed-editions.patch
```

What it adds: discovery of edition packs installed as their own packages (entry-point group
`eli.editions`), an `external` flag and `location` on `Edition`, and `activate_edition()`. In-tree
discovery is unchanged. See `docs/3_architecture/03_eli_v3_integration.md`.
