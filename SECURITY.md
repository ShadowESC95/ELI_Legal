# Security policy

ELI Legal handles case papers that may be privileged or personal, so a weakness in it matters.
Please report one privately, and please do not open a public issue for it.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository:
**[Report a vulnerability](https://github.com/ShadowESC95/ELI_Legal/security/advisories/new)**
(the Security tab, then *Report a vulnerability*). Only the maintainer sees the report.

Please include:

- the version (`eli-legal --version`) and how it was installed (AppImage, `.run`, `.deb`, Windows
  or macOS installer, or from source);
- what an attacker could do, and what they need first (a signed-in account, network access to
  the server, a document filed on a matter, access to the machine);
- the steps to reproduce it, or a proof of concept, using made-up case material only;
- whether you know of it being used against anyone.

Never send real case papers, personal data or credentials in a report.

## What happens next

| Step | When |
|---|---|
| Acknowledgement | within 5 working days |
| First assessment: confirmed or not, and how severe | within 10 working days |
| A fix, or a mitigation you can apply, for a confirmed high or critical issue | as soon as it is ready, normally within 30 days |
| Public advisory and credit (if you want it) | when the fix is released, or after 90 days, whichever is first, unless we agree otherwise |

A vulnerability that is being **actively exploited**, or a severe incident affecting the
security of ELI Legal, is notified as the EU Cyber Resilience Act requires (Regulation (EU)
2024/2847, Art. 14): an early warning within 24 hours of becoming aware, through the single
reporting platform, and the people using it are told what to do.

## Supported versions

Security fixes are made in the latest release. Earlier releases are not patched: upgrade to the
latest. Each release lists what changed in its notes.

## What each release carries

- `SHA256SUMS`: check a download before running it (`sha256sum -c SHA256SUMS --ignore-missing`).
- A software bill of materials in CycloneDX format (`ELI_Legal-<version>-sbom.cdx.json`): every
  Python component the installers are built from (as built for Linux), with its version.
- The release is built only if a known-vulnerability audit of those components (`pip-audit`)
  finds nothing outstanding. A known issue that cannot yet be fixed, and does not affect ELI
  Legal as it is used, is listed with its reason in `packaging/audit_exceptions.txt`.

## Scope

In scope: the desktop application, the server and its browser application, the command line,
the installers, and the ELI v3 edition in this repository.

Out of scope: weaknesses that need someone to already control the machine ELI Legal runs on or
its user account (the design documents say what that person could do); the security of the
operating system, disk encryption, backups or reverse proxy, which are the deploying
organisation's; and denial of service by an account the organisation trusts.

The security design is described in [docs/4_security](docs/4_security/01_security_and_privacy.md).
