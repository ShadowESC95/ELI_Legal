# Glossary

| Term | Meaning here |
|---|---|
| Access scope | Who may see a document: all parties, the neutral only, one party in confidence, or privileged. |
| Agent | One step of the workflow presented with its mandate: what it reads, writes and may never do. Four "agents" are people. |
| Approved source | A legal source that has been registered, with its owner, licence and status semantics recorded, and then approved by an authorised person. Nothing else can be searched. |
| Audit ledger | The append-only record of every step, hold, decision and release. Each event is signed over the one before it with a key held outside the database. |
| Authority | A case, statute or other legal source cited for a proposition. |
| Bench memorandum | The report produced for a decision-maker. It contains no view on the outcome. |
| Checkpoint | A signed statement of where the audit chain stands, kept somewhere else so a rollback can be detected. |
| Claim | The internal name for a finding. |
| Corpus | A set of authorities loaded into an approved source from files. |
| Decision | An action recorded in a person's name that needs their passphrase again: resolving a hold, recording a check, reviewing, restarting, releasing, closing a matter, approving a source, changing the model, managing users. |
| Deployer | The organisation that uses the system under its own authority: a court service, tribunal, chambers or firm. |
| Evidence pack | An export for one run: manifests, findings, checks, decisions, versions and the audit extract. Identifiers and hashes, not document text. |
| Finding | One located, checkable statement: a fact, an authority a party relies on, a legal proposition, or an application of law to fact. |
| Gate | The rule that a finding is verified only when every check its kind requires has passed. |
| Hold | A recorded stop on a finding, a document, a step or a run. It closes when its check passes or a named person decides, with reasons. |
| Jurisdiction pack | A data file describing a legal system's courts and citation forms. It holds no rules of law. |
| Locator | Where a passage is: document, page, paragraph. |
| Matter | One dispute, with its parties, issues, documents, runs and people. Records never cross matters. |
| Named reviewer | The person, on the matter, who must approve before anything is relied on. |
| Outbox | Where a released report is staged. Nothing is sent from it automatically. |
| Passage | A numbered paragraph of a document or authority, the unit every finding points back to. |
| Profile | What kind of user the matter is for: adjudicator, neutral facilitator, or party representative. It fixes who may work on it and what the output may say. |
| Provider | Whoever develops the system and places it on the market or puts it into service under their name. |
| Relevant date | The date as at which the law is checked. |
| Run | One execution of the workflow over a matter's documents. |
| Second factor | A six-digit code from an authenticator app, needed at sign-in in addition to the passphrase. |
| Step-up | Giving the passphrase again at the moment of a decision. |
| Treatment | How later law has affected an authority: overruled, reversed, amended, repealed, followed. |
| Verification | One of seven checks: provenance, evidence support, citation, current law, proposition, dependency, outcome boundary. |
| Waive / exclude | Two ways a person closes a hold: accept the gap (or accept flagged words as ordinary evidence) and continue, or take the item out of reliance. |
| Describe by hand | Closing a hold on a document that could not be read: a person types what the original shows or says, and the words become its text, marked as theirs. |
| Readable copy | Closing a hold on a document that could not be read by filing a clearer scan, the native file or a written description for the same party; the hold closes once the copy is read. |
| Data folder | Where an installed copy keeps its databases, keys and files (Linux `~/.local/share/eli-legal`, Windows `%LOCALAPPDATA%\ELI Legal`, macOS `~/Library/Application Support/ELI Legal`). The desktop application, the server and the command line share one set of cases only when they use the same one. |
