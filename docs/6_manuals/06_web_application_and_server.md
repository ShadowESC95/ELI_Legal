# Web application and server

The server lets people use ELI Legal from a browser, with the same eleven screens as the desktop
application and the same rules. It also offers an API for programs. It is one command.

## Starting it

| Situation | Command | Then open |
|---|---|---|
| Just you, on this machine | `eli-legal serve` | `http://localhost:8443/` |
| A team, with your own certificate | `eli-legal serve --lan --tls-cert server.crt --tls-key server.key --allowed-host legal.example` | `https://legal.example:8443/` |
| A team, no certificate yet | `eli-legal serve --lan --self-signed` | the address it prints |
| Behind your reverse proxy | `eli-legal serve --behind-proxy --trusted-proxy 127.0.0.1 --allowed-host legal.example` | your proxy's address |

At least one user must exist first (`eli-legal init --admin <id>`). The server prints where it
is listening, the certificate's fingerprint, whether a second factor is required, and when
sessions end. Stop it with Ctrl+C.

It will not listen beyond this machine without TLS. That is not configurable.

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
- **Files** are uploaded from your machine: choose them on the Evidence screen. The limit is
  250 MB each unless your administrator changed it.
- **Runs** execute on the server. You can close the browser and come back.
- **Downloads** (the report, a checkpoint, the evidence pack) are saved by your browser. Treat
  them as you would the matter's papers.
- **Loading a corpus** takes a folder name inside the server's import folder, not a file from
  your machine.
- The page loads nothing from any other site and stores nothing in your browser beyond the
  session cookie.

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
