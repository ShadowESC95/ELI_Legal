# Web application and server

The server lets people use ELI Legal from a browser, with the same sixteen pages as the desktop
application and the same rules. It also offers an API for programs.

## One machine does the work

Run ELI Legal on **one machine** that holds the cases and does all the work (reading papers, the
model, the checks): the desktop application there, and the server started from it or beside it.
Everyone else (judges, panel members, registrars, each party's lawyers, a party acting for
themselves, the governance officer) uses a **browser** on their own computer, tablet or phone and
signs in with their own account. Nothing is installed on their devices, and their devices do no
heavy work.

**The desktop application and the server share the same live data only when they use the same
data folder**: the installed program's (see [Where your data is](01_installation.md#where-your-data-is)).
A server started from the desktop application (below) always does. A server started from the
command line does when it is the installed program's `serve`. A developer's source checkout has
its own test data and accounts; its `serve` refuses to serve them while an installed copy's data
exists, unless given `--dev-data`. The server prints the data folder it serves when it starts, and
after signing in the browser's header shows which machine and installation it is serving (an
administrator also sees its data folder by resting the pointer on it; "Developer test data" is shown
in red): if it is not the one you expect, you are on the wrong data.

**What anyone does shows everywhere.** An action taken in the desktop application or in any
browser shows on everyone else's open page within about five seconds, without pressing F5 (in the
desktop application on the pages that only show the case; in the browser on the page in front of
you, but never while you are filling in a form or a box is open). What is waiting for each person
("waiting for you", the bell) is updated the same way.

## Starting it

**From the desktop application.** An administrator or a judge (or a tribunal member or an
arbitrator) opens Settings, System, Server; chooses *This computer only* or *Other computers on
the network*; and presses **Start the server…**, which asks for their passphrase again. For other
computers the server always uses TLS (a self-signed certificate is made, and its fingerprint
shown, if there is none) and everyone needs a code from an authenticator app. The panel shows the
address to give everyone. The server runs while that window is open, on the same data, and stops
when it closes; starting and stopping are both in the audit trail. Nobody else can start it.

**From the command line**, with the installed program (on Windows from *ELI Legal command line*;
on macOS `"/Applications/ELI Legal.app/Contents/MacOS/eli-legal" serve`; with the AppImage
`./ELI_Legal-0.8.22-linux-x86_64.AppImage serve`; see [Using the command line](14_command_line_guide.md)):

| Situation | Command | Then open |
|---|---|---|
| Just you, on this machine | `eli-legal serve` | `http://localhost:8443/` |
| A team, with your own certificate | `eli-legal serve --lan --tls-cert server.crt --tls-key server.key --allowed-host legal.example` | `https://legal.example:8443/` |
| A team, no certificate yet | `eli-legal serve --lan --self-signed` | the address it prints |
| Behind your reverse proxy | `eli-legal serve --behind-proxy --trusted-proxy 127.0.0.1 --allowed-host legal.example` | your proxy's address |

At least one user must exist first, for example `eli-legal init --admin jay` (your own user id). The server prints
the data folder it serves, where it is listening, the certificate's fingerprint, whether a second
factor is required, and when sessions end. Stop it with Ctrl+C. Started this way it keeps running
when the desktop application closes; to have it start with the machine, run it as a service (an
example for Linux is in [Server security](../4_security/04_server_security.md)).

**Letting other machines reach it.** Start it for the network (*Other computers on the network*,
or `--lan`), give everyone the address it shows (`https://<this machine's name or address>:8443/`),
and allow that port through this machine's firewall if it has one (Windows asks the first time;
on Linux, for example, `sudo ufw allow 8443/tcp`). Keep it on your internal network.

It will not listen beyond this machine without TLS, or without naming the reverse proxy it
trusts (`--behind-proxy --trusted-proxy`). The proxy must pass on the original `Host` header, or
every change is refused as cross-site.

**A self-signed certificate** makes each browser warn. Before accepting the warning, compare the
SHA-256 fingerprint the browser shows with the one the server printed. If they differ, stop.

Read [Server security](../4_security/04_server_security.md) before letting anyone else connect.

## Signing in from a browser

Enter your user, passphrase, and the code from your authenticator if you have one. Users are not
listed: you must know your own identifier.

If the server requires a second factor and you have not set one up, you are taken straight to
setting it up: add the key shown to an authenticator app on your phone (any standard one), then
enter the six-digit code it shows. From then on you need a code at every sign-in. If you lose the
phone, an administrator can remove the factor so you can set up a new one.

A session ends after thirty idle minutes or eight hours, when you sign out, and when your
passphrase changes. Sign out on a shared machine.

## Using it

Exactly as described in the [User manual](03_user_manual.md). Differences from the desktop
application:

- **Decisions** open a box asking for your passphrase. A wrong one records nothing.
- **Files** are uploaded from your machine: choose them on the Documents page. The limit is
  250 MB each unless your administrator changed it (other requests are limited to 1 MB). A scan
  or a photograph is read by OCR on the server while other sessions carry on.
- **Notifications.** The bell in the header says how many things are waiting for you: holds to
  clear, a report to review, a report returned or suspended, on any matter you can act on. When a
  new one arrives a notice appears with an **Open** button, and the count shows in the browser
  tab, within a few seconds, whoever else is signed in. Nothing is sent outside ELI Legal.
- **Live pages.** What someone else does on the case you have open shows on your page within about
  five seconds, without reloading; never while you are filling in a form or a box is open.
- **Not in the browser yet:** the hold window (the exact words that caused a hold, the original
  shown on screen, describing an unreadable document by hand, filing a readable copy in its
  place), editing a case's details after it is opened (its issues, parties, name and purpose; the API can
  change the issues, dates, forum and rules), deployment
  authorisations, preservation holds, ending a reliance suspension, incident awareness and
  owners, choosing a real rather than a practice matter, and re-reading a document. Use the
  desktop application on the main machine, the command line or the API for those.
- **Runs** execute on the server. You can close the browser and come back.
- **Reports released to you** are on *Released to me*: read them, or download them as PDF, Word or
  Markdown, each copy stamped with your name (see the [User manual](03_user_manual.md#reports-released-to-you)).
- **For a party's people**, see [Everyone in the case](#everyone-in-the-case).
- **Downloads** (the report, a checkpoint, the evidence pack) are saved by your browser. Treat
  them as you would the matter's papers.
- **Loading a corpus** takes a folder name inside the server's import folder, not a file from
  your machine.
- The page loads nothing from any other site and stores nothing in your browser beyond the
  session cookie.

## Everyone in the case

Each person in a case signs in with their own account, from their own machine: the tribunal's
people (judge, panel members, registrar) and each party's people (prosecution, defence, a
claimant's or respondent's solicitor or barrister, or a party acting for themselves). To let them
reach the server from their own machines, start it for the network with TLS
(`eli-legal serve --lan --self-signed`, or a proper certificate); every account then needs a code
from an authenticator app, and each person is walked through setting one up at their first
sign-in. How to give a party's people an account and add them to the matter is in the
[Administrator manual](04_administrator_manual.md).

Someone who acts for a party sees one page, **Your side's filings**, for each case they are on:

- **The case**: the forum, the parties, and which party they act for.
- **Waiting for your answer**: each hold on a paper their side filed, with why it is held (it
  could not be read, a page was read badly, it carries instructions aimed at an AI) and what they
  can do. They answer with their passphrase: *I have filed a readable copy* (after filing it),
  *Ask to withdraw it*, or *Explain*. The answer is shown to the tribunal beside the hold; the
  tribunal decides the hold. The bell tells them when an answer is wanted, and the tribunal's
  people who decide holds when it is in.
- **File a paper for your side**: always filed for the party they act for, under their name;
  served on all parties, or, if ticked, for the tribunal only.
- **Papers on the case**: what is served on all parties and their own side's papers, to read.
  Another party's confidential papers are not listed at all.

The tribunal's analysis (findings, checks, runs, the report, chat, the record of actions) is not
shown to a party, and every other page and route refuses them by the same rules that refuse
anyone else.

## The API

For programs. Every operation is listed in the [API reference](../3_architecture/06_api_reference.md).

```
# A token for a program, issued to a named user (shown once)
eli-legal user token <user> --label "nightly export"

curl https://legal.example:8443/v1/matters -H "Authorization: Bearer <token>"

# A decision also needs that user's passphrase
curl -X POST https://legal.example:8443/v1/matters/<matter>/holds/<hold>/resolve \
  -H "Authorization: Bearer <token>" -H "X-ELI-Passphrase: <passphrase>" \
  -H "Content-Type: application/json" \
  -d '{"action": "exclude", "reason": "Overruled; not to be relied on."}'
```

A token acts as that user and can do only what they can. Because a decision needs the passphrase
as well, a token left in a script cannot approve anything by itself. Do not put a passphrase in a
script either: decisions are for people.

`eli-legal serve --api-docs` adds the interactive description at `/docs`. It is off by default.

## What the server will not do

It has no general chat, no web search, no file browser, no shell, and no way to make it contact
another machine. It serves the legal and governance functions and nothing else.
