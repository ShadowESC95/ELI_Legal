#!/usr/bin/env python3
"""Write the API and command-line references from the code, so they cannot drift from it.

    python scripts/generate_reference_docs.py

Re-run after changing a route or a command. CI can run it and fail if the files change.
"""

from __future__ import annotations

import argparse
import inspect
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = {"/health", "/v1/boundaries", "/v1/auth/login", "/v1/auth/logout", "/"}
SECTIONS = (
    ("Signing in and your own account", ("/health", "/v1/boundaries", "/v1/auth")),
    ("Users and roles", ("/v1/users", "/v1/roles")),
    ("The installation", ("/v1/system", "/v1/workflow", "/v1/config", "/v1/network")),
    ("Matters and documents", ("/v1/matters",)),
    ("Audit and governance", ("/v1/audit", "/v1/governance", "/v1/monitoring")),
    ("Approved legal sources", ("/v1/sources", "/v1/authorities")),
    ("Law and standards packages", ("/v1/frameworks",)),
    (
        "What to do next, compliance and the routine checks",
        ("/v1/words", "/v1/home", "/v1/compliance", "/v1/checks", "/v1/oversight"),
    ),
)


def _app():
    from eli_legal.api.app import create_app
    from eli_legal.application.services import build_services
    from eli_legal.settings import Settings

    tmp = Path(tempfile.mkdtemp())
    key = tmp / "secrets" / "audit.key"
    key.parent.mkdir()
    fd = os.open(key, os.O_WRONLY | os.O_CREAT, 0o600)
    os.write(fd, os.urandom(32).hex().encode())
    os.close(fd)
    settings = Settings(
        _env_file=None, audit_key_file=key, db_path=tmp / "a.db", audit_db_path=tmp / "b.db",
        data_dir=tmp / "m", artifacts_dir=tmp / "art",
    )  # fmt: skip
    return create_app(build_services(settings, install_network_guard=False))


def _describe(endpoint) -> str:
    doc = inspect.getdoc(endpoint)
    if doc:
        return " ".join(doc.split())
    return endpoint.__name__.replace("_", " ").capitalize() + "."


def api_reference() -> str:
    app = _app()
    rows: dict[str, list[str]] = {title: [] for title, _ in SECTIONS}
    sub = {"runs": "Runs, findings, review and release", "incidents": "Incidents"}
    extra: dict[str, list[str]] = {v: [] for v in sub.values()}
    for route in app.routes:
        methods = sorted((getattr(route, "methods", None) or set()) - {"HEAD", "OPTIONS"})
        path = getattr(route, "path", "")
        if not methods or path.startswith("/assets") or path == "/":
            continue
        line = f"| `{' '.join(methods)}` | `{path}` | {'no' if path in PUBLIC else 'yes'} | {_describe(route.endpoint)} |"
        if any(k in path for k in ("/runs", "/claims", "/holds", "/releases")):
            extra[sub["runs"]].append(line)
        elif "/incidents" in path:
            extra[sub["incidents"]].append(line)
        else:
            for title, prefixes in SECTIONS:
                if any(
                    path == p or path.startswith(p + "/") or path.startswith(p + "?")
                    for p in prefixes
                ):
                    rows[title].append(line)
                    break
            else:
                # A route no section claims would be left out of the reference without a word.
                raise SystemExit(f"no section of the API reference covers {path}; add one")
    rows.update(extra)
    total = sum(len(v) for v in rows.values())
    out = [
        "# API reference",
        "",
        "Generated from the server's routes by `scripts/generate_reference_docs.py`. Do not edit by hand.",
        "",
        f"The server exposes {total} operations under `/v1`, plus `/health` and the browser application at `/`.",
        "It has no other routes: no general assistant, no shell, no device or media control, no plug-ins.",
        "",
        "## Conventions",
        "",
        "- **Credentials.** Either the session cookie set by `POST /v1/auth/login` (browsers), or",
        "  `Authorization: Bearer <token>` (programs). Nothing else is accepted.",
        "- **Changing anything from a browser session** also needs the header `X-ELI-CSRF`, whose value",
        "  is returned by sign-in and by `GET /v1/auth/session`.",
        "- **Decisions.** Resolving a hold, recording a check, reviewing, restarting, releasing, closing a",
        "  matter, approving a source, changing the model, managing users and recording compliance work",
        "  or a law package's check need the caller's",
        "  passphrase with the request: `X-ELI-Passphrase`, or `X-ELI-Passphrase-B64` (base64 of the",
        "  UTF-8 text) for passphrases with characters a header cannot carry. Sent without it, such a",
        '  request is answered `401` with `"error": "StepUpRequired"`; send it again with the header.',
        '- **Errors** are JSON: `{"error": "<Name>", "detail": "<why, in plain words>"}`.',
        "",
        "| Status | `error` | Meaning |",
        "|---|---|---|",
        "| 400 | `UnknownHost`, `BadRequest` | Wrong host name, or a malformed request |",
        "| 401 | `AuthenticationFailed`, `StepUpRequired`, `SecondFactorRequired` | Not signed in; passphrase needed; code needed |",
        "| 403 | `PolicyDenied`, `MatterAccessDenied`, `CrossOrigin`, `Forbidden` | Not permitted for this role, matter or origin |",
        "| 404 | `NotFound` | No such record in a matter you may see |",
        "| 409 | `VerificationGateFailed`, `InvalidState` | A gate or the state of the run forbids it |",
        "| 411 / 413 | `LengthRequired`, `TooLarge` | Body length not declared, or over the limit |",
        "| 422 | `InvalidInput` | A field is missing, malformed or too long |",
        "| 423 | `AccountLocked` | Too many failed attempts |",
        "| 429 | `TooManyRequests` | Rate limit; see `Retry-After` |",
        "",
        "Uploading a document: `POST /v1/matters/{id}/documents?filename=<name>` with the file as the",
        "request body (`Content-Type: application/octet-stream`); optional query fields `party_id`,",
        "`doc_type`, `scope`, `custodian`.",
        "",
    ]
    for title, lines in rows.items():
        if lines:
            out += [
                f"## {title}",
                "",
                "| Method | Path | Sign-in | What it does |",
                "|---|---|---|---|",
                *lines,
                "",
            ]
    return "\n".join(out)


def cli_reference() -> str:
    from eli_legal.cli import build_parser

    parser = build_parser()
    out = [
        "# Command-line reference",
        "",
        "Generated from the program by `scripts/generate_reference_docs.py`. Do not edit by hand.",
        "",
        "`eli-legal <command> --help` shows the options of any command. Sign in first",
        "(`eli-legal login <user>`); a decision asks for your passphrase again. For scripted use,",
        "`--passphrase-stdin` reads the passphrase from standard input instead of the terminal.",
        "",
        "| Command | What it does |",
        "|---|---|",
    ]

    def walk(p: argparse.ArgumentParser, prefix: str) -> None:
        for action in p._actions:
            if not isinstance(action, argparse._SubParsersAction):
                continue
            helps = {c.dest: c.help or "" for c in action._choices_actions}
            for name, child in action.choices.items():
                has_children = any(
                    isinstance(a, argparse._SubParsersAction) for a in child._actions
                )
                options = [
                    a.option_strings[-1] if a.option_strings else f"<{a.dest}>"
                    for a in child._actions
                    if not isinstance(a, (argparse._HelpAction, argparse._SubParsersAction))
                ]
                text = helps.get(name) or child.description or ""
                shown = f"`{prefix}{name}{' ' + ' '.join(options) if options and not has_children else ''}`"
                out.append(f"| {shown} | {text} |")
                walk(child, f"{prefix}{name} ")

    walk(parser, "eli-legal ")
    return "\n".join(out) + "\n"


def main() -> int:
    targets = {
        ROOT / "docs" / "3_architecture" / "06_api_reference.md": api_reference(),
        ROOT / "docs" / "6_manuals" / "07_command_line_reference.md": cli_reference(),
    }
    for path, text in targets.items():
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
