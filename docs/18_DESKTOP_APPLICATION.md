# Desktop application

`eli-legal gui` (or `./eli_legal.sh`, or `python -m eli_legal`) opens the desktop application. It
needs the `gui` extra: `pip install 'eli-legal[gui]'`. It is a front end over the same services
as the command line and the API, so access control, gates, holds and audit behave identically.
It looks and behaves like the ELI desktop applications, and contains only legal and governance
functions: there is no general assistant, no shell, no screen or desktop control, no web access.

## Signing in

On first start it creates the audit key and asks you to create the first administrator. After
that, everyone signs in with their own passphrase. An administrator sets a new user's first
passphrase; the user then changes it. Everything you do is recorded under your name together
with how you proved who you are. **A decision asks for your passphrase again** at the moment you
make it.

## The header

Always visible: the open matter and who it is for; whether the audit chain verifies and how many
events it holds; that the network is denied by default; which model is in use, if any; and who
is signed in, with their roles.

## Tabs

| Tab | What it is for |
|---|---|
| 📁 Matter | Open a matter under a profile; parties, issues, relevant date; who has access; the named reviewers; the approved sources; close a matter. |
| 📄 Evidence | Take documents in (who filed them, what they are, who may see them); read any document as located passages; see what was not read and what was flagged. |
| 💬 Chat | Ask about the matter. Answers come from its documents, the run's findings and the approved sources, each with its locator and whether it may be relied on. With a model, a short summary whose every sentence is tied to its sources. It will not say who should win, and nothing can be decided from chat. |
| 🕸 DAG | The workflow as a graph, coloured by what happened to each step. Start, stop or restart a run; select a step to see what it did. Runs execute in the background. |
| 🤖 Agents | Each step as an agent with a fixed mandate: what it reads, what it writes, what it may never do, which controls it carries out, and what it did in the selected run. Three are model-assisted (marked ✦); four are people. |
| 🔎 Findings | Every finding of the run with its source passage, its checks and who decided them. Record a check by hand, or take a held finding out of reliance. |
| ⚖ Review | Holds; checks waiting for a person; the report; the decision (tick each stated limit, give reasons, approve / return / reject); release to confirmed recipients. |
| 🧾 Audit Trail | The ledger for the matter, including how each actor's identity was proved; verify the chain; reconcile a run's record; export a checkpoint or the evidence pack. |
| 🛡 Governance | The requirement, control, risk and responsibility registers; monitoring computed from control evidence; incidents. |
| 📚 Sources | The approved-source register; register, approve or revoke a source; load a corpus; read what a source holds and each authority's status history. |
| ⚙ Settings | Your passphrase; users and roles; the model; the legal systems installed; the policy; this installation. |

## What it will not let you do

Whatever your role does not permit. Refusals are shown in the system's own words and, where they
concern a matter, are written to the audit trail. The application cannot be used to approve as
someone else: a decision needs the signed-in person's own passphrase.

## Limits

A passphrase proves knowledge of a secret, not presence. There is no second factor and no
lockout after repeated failures; both belong on the roadmap before use on real matters. The
application shows matter content on screen: use it on a machine and in a place appropriate to
that content.
