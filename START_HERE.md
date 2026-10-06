# Start here

1. `pip install -e '.[dev,all]'`, then `eli-legal demo` to watch a synthetic dispute go from
   filing to an approved, released report, with each control narrated as it acts.
2. `./eli_legal.sh` opens the desktop application. `eli-legal serve` starts the server and
   browser application on this machine.
3. `README.md` says what the system does and does not do.
4. `docs/README.md` is the index to everything else: project, requirements, architecture,
   security, legal and compliance, manuals.
5. `make check` runs tests, lint, type checks and the governance register check.
6. `packaging/linux/build.sh` builds the Linux installers into `dist/installers`.
7. Before any real matter: `docs/5_legal_and_compliance/01_legal_overview.md` lists what must be
   true first.
