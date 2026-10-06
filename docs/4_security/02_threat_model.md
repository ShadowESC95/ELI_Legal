# Threat model

Each threat maps to controls in `governance/control_register.csv` and risks in
`governance/risk_register.csv`, where the tests are named.

| Threat | Controls |
|---|---|
| Stale, overruled or superseded authority | C-09, C-11 |
| Invented or mis-cited authority | C-08, C-11 |
| Real authority cited for something it does not say | C-10 |
| Instruction hidden in a matter file | C-07, C-21, C-25 |
| Poisoned or unlicensed source | C-03 |
| Leakage between matters | C-01, C-02 |
| Over-broad tools; shell, web or desktop access | C-04, C-24, C-25 |
| Approval by an unauthorised person or by the system | C-14, C-28 |
| Report altered between review and release | C-15, C-20 |
| Audit record edited, truncated or rolled back | C-16, C-17 |
| Model states the outcome or invents particulars | C-13 |
| Confidential mediation material disclosed | C-20 |
| Silent change of model, prompt, tool or corpus | C-22 |
| Reviewer approves without reviewing | C-14, C-22 (signal only) |
| Disk theft | not controlled by the software (R-14) |

## The server

| Threat | What stops it | What remains |
|---|---|---|
| Traffic read on the network | TLS 1.2 or later; refusal to listen beyond the machine without it | A self-signed certificate nobody checked |
| A hostile web page drives a signed-in browser | SameSite=Strict cookie, CSRF value, origin check, no CORS | A browser defect |
| A hostile page reaches a local server under its own name (DNS rebinding) | Host allow-list | — |
| A filed document carries script | All content rendered as text; no inline script permitted | A browser defect |
| Passphrase guessing | Rate limit per address; account lock; second factor | Denial of access to a known user by deliberate lock-out |
| A stolen session cookie | HttpOnly, Secure, host-bound; idle and absolute time-outs; decisions need the passphrase again | Reading, until the session ends |
| A stolen API token | Decisions need the passphrase as well; deactivating the user revokes it | Reading whatever that user may read |
| Oversized or endless uploads | Length must be declared and within the limit before reading | — |
| Using the server to read the machine or call out | Import confined to one folder; only a local model server can be queried; the network guard | — |
| An insider with access to the machine | File permissions; the audit key is outside the database; tampering with the ledger is detected | Someone holding both the databases and the key can rewrite history up to the last checkpoint kept elsewhere |
