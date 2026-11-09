# Test matrix

`pytest` runs everything; no network, model or ELI installation is needed.

| Area | File | What it establishes |
|---|---|---|
| Gates | `tests/unit/test_gates.py` | one passing check never verifies; failures hold; dependents hold; human results and overrides |
| Citations, dates | `tests/unit/test_citations_and_dates.py` | every pack recognises its own examples; no pack claims validation |
| Parsers, ingestion | `tests/unit/test_parsers_and_ingestion.py` | each format; unreadable files refused; originals immutable |
| Current law | `tests/unit/test_current_law.py` | overruled, stale, unknown, versions of legislation, civil-law policy |
| Policy, boundaries | `tests/unit/test_policy_and_boundaries.py` | prohibited actions; core controls cannot be disabled; outcome wording; injection patterns |
| Audit | `tests/security/test_audit.py` | missing key, tamper, removal, truncation, anchor forgery, rollback, minimisation |
| Access | `tests/security/test_access.py` | role + membership + profile; denials recorded; cross-matter; humans only; closure |
| Network, injection | `tests/security/test_network_and_injection.py` | egress refused; per-host windows; flagged file never reaches a model |
| Lifecycle | `tests/integration/test_lifecycle.py` | ingest to release; report integrity; restart; tampering blocks approval |
| Gold matter | `tests/evaluation/test_gold_matter.py` | each planted defect caught for the stated reason; scorecard |
| Model mode | `tests/evaluation/test_model_mode.py` | a misbehaving model contributes nothing unverified |
| Edition | `tests/edition/test_edition_contract.py` | ELI v3 contract; refused actions; no decisions or content via the host |
| Authentication | `tests/security/test_authentication.py` | a name alone is refused; no acting as someone else; decisions need step-up; sessions; the CLI with no harness |
| Chat, agents, sign-in | `tests/integration/test_chat_agents_signin.py` | grounded chat; agent mandates; passphrases; governed model change |
| Desktop application | `tests/gui/test_gui.py` | the window driven headlessly as a signed-in person |
| Registers | `tests/governance/test_registers.py` | registers match code and tests |
| Server, rules | `tests/api/test_api.py` | same rules as other front ends; no route without credentials; the whole lifecycle over HTTP |
| Server, protection | `tests/api/test_server_security.py` | cookie and CSRF; host, origin, size and rate checks; headers; lock-out; second factor; TLS rules; no path or network disclosure |
| Browser application | `tests/web/test_web_app.py` | a real browser engine against a real TLS server: sign-in, every screen, a decision with step-up |
| Roles on a matter, redaction | `tests/security/test_matter_roles_and_redaction.py` | a role on a matter narrows and never widens; only the lead manages the team; withheld material in lists, passages, findings, chat and the evidence pack; masking; oversight without content; drafted arguments scoped to what they rest on |
| Compliance, routine checks | `tests/governance/test_compliance_and_checks.py` | every requirement met, waiting or due, never partial; forms from the templates; step-up; review dates; training; retention enforced; the evaluation; drafted documents; an overruled authority after approval and an altered original each open an incident; results never show a matter to someone not on it; incident deadlines |
| Guidance | `tests/integration/test_guidance.py` | each stage of a matter points to the next thing to do, for the right person |
| Plain words | `tests/unit/test_plain_words.py` | every state, hold reason, check, action and role a person is shown has words, and a tone |
| Guidance over the server | `tests/api/test_guidance_api.py` | words, guide, team roles, compliance with step-up, checks and oversight over HTTP |
| Command line, guidance | `tests/integration/test_cli_guidance.py` | status, roles, compliance and checks as real invocations |

Set `ELI_V3_ROOT` to a real ELI v3 checkout to add a contract check against its own loader.
