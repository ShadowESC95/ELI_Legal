# Server security

The server puts privileged and confidential material on a network. This document says what
protects it, what does not, and how to deploy it. Controls DG-01.15 and DG-01.17 to HO-01.6 in the control
register name the code and the tests.

## What the server is

One process, started with `eli-legal serve`. It serves a JSON API under `/v1` and the browser
application at `/`. It is a shell over the same services the desktop application calls: roles,
matter membership, gates, holds and the audit ledger apply unchanged.

It has no general assistant, no shell, no file browser, no device or media control, no plug-ins,
no WebSocket, and no route that makes it call another machine.

## What protects it

| Layer | What it does | What it does not do |
|---|---|---|
| **Listening** | This machine only, by default. It refuses to listen beyond it without TLS, or a reverse proxy you declare by address | It is not a firewall |
| **TLS** | 1.2 or later. Your certificate, or a self-signed one it makes and whose fingerprint it prints | A self-signed certificate protects only if someone checks the fingerprint |
| **Host name** | A request must name a host this server answers to. Defeats DNS rebinding | — |
| **Origin** | A request that changes anything must come from the server's own pages | — |
| **No CORS** | No other origin may read a response | — |
| **Rate** | Ten sign-in attempts a minute per client address; 600 requests a minute overall | In memory, per process; not a defence against a distributed attack |
| **Size** | A body must declare its length and be within the limit before any of it is read | — |
| **Sign-in** | Passphrase, and a code where a second factor is set up. An unknown user looks the same as a wrong passphrase, and costs the same time | — |
| **Lock-out** | Five wrong attempts in a row lock the account for fifteen minutes; an administrator can unlock | Someone who knows a user's name can lock them out |
| **Second factor** | Six-digit codes from an authenticator app; a code cannot be used twice. Required by default when other machines can connect | The secret is stored in the database, as it stands; protect the database file and encrypt the disk. No hardware keys |
| **Session** | A cookie scripts cannot read, never sent on a cross-site request, bound to the host and Secure over TLS. Ends after 30 idle minutes or 8 hours, on sign-out, and when the passphrase changes | One process holds sessions; restarting the server does not end them, since they are in the database |
| **CSRF** | Any change needs a value only the server's own page was given | — |
| **Decisions** | Need the passphrase again, sent with the request | — |
| **Page** | Loads nothing from anywhere else. No inline script or style. All matter content is shown as text, never as markup | A browser defect remains possible: keep browsers patched |
| **Responses** | Strict content-security policy, no framing, no content-type guessing, no referrer, no caching of matter content | — |
| **Input** | Unknown fields refused; every string bounded; a refusal never repeats what was sent | — |
| **Disclosure** | No server path is returned. A corpus loads only from inside the import folder. A model server is queried only on this machine, or on a host approved as a legal source | — |
| **Audit** | Every sign-in, refusal and decision is in the ledger, with how identity was proved | Client addresses are in the server's access log, not the ledger |

## What it does not include

No web-application firewall, intrusion detection, malware scanning, single sign-on, hardware
security keys, encryption at rest, or high availability. No penetration test has been carried
out. Treat it as software for an internal network, behind your own controls.

## Deploying it

### One person, one machine

```
eli-legal serve
```

It listens on `http://localhost:8443/`. Nothing outside the machine can reach it. This is the
only arrangement in which running without TLS is accepted.

### A team on an internal network, with your own certificate (recommended)

```
eli-legal serve --lan --tls-cert /path/to/server.crt --tls-key /path/to/server.key \
    --allowed-host legal.chambers.example
```

Give every name people will type as `--allowed-host`; requests under any other name are refused.
A second factor is required of every user. Restrict the port with your firewall to the people
who need it.

### A team, with no certificate yet

```
eli-legal serve --lan --self-signed
```

The server makes a certificate and prints its SHA-256 fingerprint. Each user's browser will warn.
Before accepting, compare the fingerprint the browser shows with the one printed. Replace it
with a certificate from your own authority as soon as you can.

### Behind a reverse proxy

```
eli-legal serve --host 127.0.0.1 --behind-proxy --trusted-proxy 127.0.0.1 \
    --allowed-host legal.chambers.example
```

The proxy terminates TLS and must forward the original `Host`. Only the addresses you name are
believed about who the client is. The proxy must not add CORS headers, cache responses, or strip
the security headers.

### Do not

- Expose the server to the internet. Use a VPN.
- Run it without TLS beyond one machine. It will refuse.
- Turn off the second-factor requirement on a network (`--require-second-factor no`) without
  another control that replaces it.
- Run more than one server process over the same data folder.
- Put the data folder on an unencrypted disk or a shared drive.

## Running it as a service (Linux)

```ini
# /etc/systemd/system/eli-legal.service
[Unit]
Description=ELI Legal server
After=network.target

[Service]
User=eli-legal
Environment=ELI_LEGAL_HOME=/var/lib/eli-legal
ExecStart=/usr/bin/eli-legal serve --lan --tls-cert /etc/eli-legal/server.crt --tls-key /etc/eli-legal/server.key --allowed-host legal.chambers.example
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/eli-legal

[Install]
WantedBy=multi-user.target
```

Create the first administrator before starting it:
`sudo -u eli-legal ELI_LEGAL_HOME=/var/lib/eli-legal eli-legal init --admin <id>` (it asks how
long the record is kept; unattended, give `--audit-days N --closed-matter-days N`). The service
user's files are created private to it (folders 0700, databases 0600).

## Checking a deployment

| Check | How |
|---|---|
| It refuses another host name | `curl -k -H 'Host: other.example' https://server:8443/health` returns 400 |
| It sends the protections | `curl -kI https://server:8443/` shows `content-security-policy`, `strict-transport-security`, `x-frame-options: DENY` |
| Nothing answers without sign-in | `curl -k https://server:8443/v1/matters` returns 401 |
| The certificate is the one you installed | Compare the fingerprint in the start-up output with the browser's |
| The audit chain verifies | Record of actions, "Verify the chain", or `eli-legal audit verify` |

## Reporting a weakness

Report it privately to the maintainer before disclosing it. There is no bug-bounty programme.
