# Command-line reference

Generated from the program by `scripts/generate_reference_docs.py`. Do not edit by hand.

`eli-legal <command> --help` shows the options of any command. Sign in first
(`eli-legal login <user>`); a decision asks for your passphrase again. For scripted use,
`--passphrase-stdin` reads the passphrase from standard input instead of the terminal.

| Command | What it does |
|---|---|
| `eli-legal init --admin --name --audit-days --closed-matter-days --inactive-matter-days --retention-later` | create directories, the audit key and the first administrator |
| `eli-legal login <user_id>` | sign in with your passphrase |
| `eli-legal logout` | end your session |
| `eli-legal whoami` | show who is signed in |
| `eli-legal passphrase <user_id>` | change your passphrase, or set another user's |
| `eli-legal gui` | open the desktop application |
| `eli-legal serve --host --port --lan --tls-cert --tls-key --self-signed --behind-proxy --trusted-proxy --allowed-host --require-second-factor --api-docs` | start the server and browser application |
| `eli-legal second-factor` | set up or remove an authenticator code |
| `eli-legal second-factor setup` | set up your own |
| `eli-legal second-factor remove <user_id>` | remove yours, or (administrator) someone else's |
| `eli-legal unlock <user_id>` | unlock an account locked after failed sign-ins |
| `eli-legal doctor` | check the installation |
| `eli-legal show-policy` | print the runtime policy |
| `eli-legal jurisdictions` | list jurisdiction packs |
| `eli-legal user` | manage users |
| `eli-legal user list` |  |
| `eli-legal user add <user_id> --name --role` |  |
| `eli-legal user token <user_id> --label` |  |
| `eli-legal user deactivate <user_id>` |  |
| `eli-legal source` | manage the approved-source register |
| `eli-legal source list` |  |
| `eli-legal source add <source_id> --name --jurisdiction --type --owner --licence --terms-reviewed --freshness --status-semantics --authoritative-for --inspection` |  |
| `eli-legal source approve <source_id>` |  |
| `eli-legal source revoke <source_id>` |  |
| `eli-legal source add-live <kind> --id --terms-reviewed` | a live official database: eu_cellar or uk_open |
| `eli-legal source import <source_id> <directory>` |  |
| `eli-legal source index <source_id>` | embed a source's passages for searching by meaning now, not during a run |
| `eli-legal matter` | manage matters |
| `eli-legal matter create --name --purpose --jurisdiction --profile --governing-law --forum --rules --relevant-date --party --issue --represents --real --retention-days --framework --no-recommended-frameworks --member --reviewer --source` |  |
| `eli-legal matter list` |  |
| `eli-legal matter show <matter>` |  |
| `eli-legal matter grant <matter> <user_id> --role --acts-for` |  |
| `eli-legal matter revoke <matter> <user_id>` |  |
| `eli-legal matter people <matter>` | who is on the matter, in which role, reading what |
| `eli-legal matter role <matter> <user_id> --role --acts-for --no-party --reads` | change a person's role on the matter, party or clearance |
| `eli-legal matter reviewers <matter> <user_id>` |  |
| `eli-legal matter sources <matter> <source_id>` |  |
| `eli-legal matter frameworks <matter> <pack_id>` | show, or set, the law and standards packages applied |
| `eli-legal matter set <matter> --retention-days --organisation-retention --relevant-date --issue --forum --rules --party` |  |
| `eli-legal matter close <matter> --reason --purge` |  |
| `eli-legal ingest <matter> <path> --party --type --scope --custodian` | take documents into a matter |
| `eli-legal docs <matter> --reread` | list a matter's documents, or read one again from its original |
| `eli-legal run` | start, inspect, stop or restart a run |
| `eli-legal run start <matter>` |  |
| `eli-legal run list <matter>` |  |
| `eli-legal run status <matter> <run>` |  |
| `eli-legal run resume <matter> <run> --reason --from` |  |
| `eli-legal run stop <matter> <run> --reason` |  |
| `eli-legal run hold <matter> <run> --reason` | put a run on hold while it waits for review, or suspend an approved one |
| `eli-legal claims <matter> <run> --status --kind` | list a run's findings |
| `eli-legal holds <matter> <run> --all` | list holds |
| `eli-legal hold <matter> <hold> --action --reason` | resolve a hold by a named decision |
| `eli-legal tasks <matter> <run>` | checks waiting for a person |
| `eli-legal verify <matter> <claim> --check --result --reason` | record a person's verification result |
| `eli-legal report <matter> <run> --path` | show the current report |
| `eli-legal review <matter> <run> --decision --reasons --report-hash --acknowledge --acknowledge-all` | approve, reject or return a report |
| `eli-legal release` | prepare and stage an approved report |
| `eli-legal release prepare <matter> <run> --to` |  |
| `eli-legal release send <matter> <release> --confirm` |  |
| `eli-legal incident` | manage incidents |
| `eli-legal incident list <matter>` |  |
| `eli-legal incident open <matter> --category --detail --severity --run` |  |
| `eli-legal incident close <matter> <incident> --containment --reason` |  |
| `eli-legal incident aware <matter> <incident> --aware-at --basis --aware-by --occurred-at` | when the provider or deployer became aware (Art. 73 counts from it) |
| `eli-legal incident assign <matter> <incident> --owner --backup` | the incident's owner and a different stand-in |
| `eli-legal incident report <matter> <incident> --reportable --reason --kind --reported-on --reference` | decide whether a serious incident is reportable (Art. 73) |
| `eli-legal deployment` | approve the use of ELI Legal on real matters |
| `eli-legal deployment list` |  |
| `eli-legal deployment propose --intended-use --provider --deployer --jurisdiction --profile --effective-from --expires-on --evidence --data-class` | set out what is to be approved, with its evidence |
| `eli-legal deployment sign <authorisation> --as-lead` | sign as the provider lead or the deployer lead |
| `eli-legal deployment revoke <authorisation> --reason` | withdraw it at once |
| `eli-legal preserve` | preservation holds: keep a matter's content from deletion |
| `eli-legal preserve list <matter>` |  |
| `eli-legal preserve place <matter> --basis --authority --document --review-by` | keep the whole matter, or named documents, from deletion |
| `eli-legal preserve release <matter> <hold> --reason` | end a hold (the legal or data-protection owner) |
| `eli-legal reliance` | approved reports suspended from reliance |
| `eli-legal reliance list <matter>` |  |
| `eli-legal reliance resolve <matter> <block> --basis --superseded-by` | end a suspension: the law confirmed again for the report, or a later approved run that replaces it |
| `eli-legal network` | hard offline: the kernel refuses every network connection |
| `eli-legal network status` |  |
| `eli-legal network offline` | switch hard offline on now, until the program exits |
| `eli-legal network at-start <state>` | start hard offline every time (or not) |
| `eli-legal status <matter>` | where a matter stands and what to do next |
| `eli-legal compliance` | the organisation's compliance work |
| `eli-legal compliance show --all` | where each requirement stands |
| `eli-legal compliance actions` | what the organisation must do, and where each stands |
| `eli-legal compliance form <action>` | the questions of an action, as JSON to fill in |
| `eli-legal compliance record <action> --answers --confirm --notes --reference --not-applicable` | record an action as done, or as not applying |
| `eli-legal compliance retention --audit-days --closed-days --inactive-days` | how long the audit trail and closed matters are kept |
| `eli-legal compliance training <user_id> --course --completed --expires` | list training records, or record one |
| `eli-legal compliance evaluate` | run the accuracy evaluation on the planted-defect matter |
| `eli-legal compliance draft <kind>` | draft the Annex IV documentation or the declaration |
| `eli-legal compliance sign-off <action> --sha256` | sign off a drafted document by its SHA-256 |
| `eli-legal evaluate <benchmark> --embedding --json` | measure legal research and fact linking on benchmarks |
| `eli-legal checks` | run or show the routine checks |
| `eli-legal checks run --as-system` |  |
| `eli-legal checks show` |  |
| `eli-legal checks timer --install --remove` | run the checks daily from the system's scheduler, even with the program closed |
| `eli-legal audit` | verify or read the audit ledger |
| `eli-legal audit verify --against` |  |
| `eli-legal audit checkpoint --out` |  |
| `eli-legal audit tail <matter> -n` |  |
| `eli-legal evidence <matter> <run> --out` | export the evidence pack for a run |
| `eli-legal monitor` | post-deployment monitoring snapshot |
| `eli-legal governance --root` | check the governance registers against the code |
| `eli-legal edition` | ELI edition pack: show, install into or verify against an ELI checkout |
| `eli-legal edition manifest` |  |
| `eli-legal edition install --eli-root --force` |  |
| `eli-legal edition verify --eli-root` |  |
| `eli-legal demo --dir --model --model-url --gguf --gguf-context --gguf-gpu-layers` | run a synthetic dispute through the whole lifecycle |
| `eli-legal framework` | law and standards packages: list, inspect, import, approve |
| `eli-legal framework list` |  |
| `eli-legal framework show <pack_id>` |  |
| `eli-legal framework import <file> --title --id --issuer --version` | a JSON package, a CSV register, or a document of rules |
| `eli-legal framework approve <pack_id>` |  |
| `eli-legal framework current <pack_id> --note --checked-on` | record that you checked a package against its official text |
| `eli-legal framework validate <pack_id> --by` | record a qualified lawyer's validation of a package |
| `eli-legal framework withdraw <pack_id>` |  |
| `eli-legal framework reinstate <pack_id>` |  |
| `eli-legal framework remove <pack_id>` |  |
| `eli-legal framework export <pack_id> --out` |  |
| `eli-legal framework context <matter>` | what the model is told on a matter |
| `eli-legal bundle` | make this copy available to ELI v3 as a bundle |
| `eli-legal bundle show` |  |
| `eli-legal bundle register --if-eli-v3 --into` |  |
| `eli-legal bundle unregister --this-copy --into` |  |
| `eli-legal licence` | this copy's licence: show it, activate a key, remove it |
| `eli-legal licence status` |  |
| `eli-legal licence activate <key>` |  |
| `eli-legal licence remove` |  |
| `eli-legal model` | show, find or choose the model |
| `eli-legal model show` |  |
| `eli-legal model list` | GGUF models found on this machine, and a model server's models |
| `eli-legal model use <backend> <model> --verifier --url --context --gpu-layers --threads` | choose a GGUF file, a server model, ELI v3's model, or none |
| `eli-legal model plan <model> --context --gpu-layers --threads` | how a GGUF file would be placed on this machine, and why |
| `eli-legal gpu` | the graphics card and the llama.cpp that uses it |
| `eli-legal gpu status` | this machine, the llama.cpp in use, the graphics packs found |
| `eli-legal gpu install <file>` | install a graphics pack from a file on this machine |
| `eli-legal gpu probe <folder>` |  |
