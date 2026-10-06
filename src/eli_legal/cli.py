"""Command-line front end. Every command goes through the application services; none touches
the store directly. You act as whoever signed in with ``eli-legal login``; a decision asks for
your passphrase again."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import secrets
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

from eli_legal import __version__
from eli_legal.domain.enums import (
    AccessScope,
    DocumentType,
    IncidentSeverity,
    Profile,
    ReviewDecision,
    VerificationStatus,
)
from eli_legal.domain.errors import EliLegalError
from eli_legal.settings import Settings


def _services(args: argparse.Namespace) -> Any:
    from eli_legal.application.services import build_services

    if getattr(args, "_services", None) is None:
        args._services = build_services(Settings())
    return args._services


def _session_file() -> Path:
    """Where this operating-system user's sign-in is kept: beside the audit key, owner-only."""
    return Path(Settings().audit_key_file).parent / f".session_{getpass.getuser()}"


def _read_secret(args: argparse.Namespace, prompt: str) -> str:
    """A passphrase from the terminal, or one line of standard input for scripted use."""
    if getattr(args, "passphrase_stdin", False):
        return sys.stdin.readline().rstrip("\r\n")
    return getpass.getpass(prompt)


def _actor(args: argparse.Namespace) -> str:
    """The signed-in user. Identity comes from a session opened with a passphrase, never from
    a name typed on the command line."""
    from eli_legal.security import authn

    if getattr(args, "_actor", None):
        return str(args._actor)
    path = _session_file()
    token = path.read_text(encoding="ascii").strip() if path.is_file() else ""
    if not token:
        raise SystemExit("not signed in: run  eli-legal login USER")
    user = _services(args).users.session_user(token)
    authn.establish(user.user_id, "cli-session")
    args._actor = user.user_id
    return str(user.user_id)


@contextmanager
def _confirmed(args: argparse.Namespace, what: str) -> Iterator[str]:
    """A decision: ask for the passphrase again, and act with it confirmed."""
    from eli_legal.security import authn

    actor = _actor(args)
    phrase = _read_secret(args, f"Passphrase for {actor} (to {what}): ")
    _services(args).users.confirm(actor, phrase)
    with authn.stepped_up():
        yield actor


def _new_passphrase(args: argparse.Namespace, who: str) -> str:
    first = _read_secret(args, f"New passphrase for {who}: ")
    if not getattr(args, "passphrase_stdin", False):
        if getpass.getpass("Repeat it: ") != first:
            raise SystemExit("the two passphrases differ; nothing was changed")
    return first


def _out(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str, ensure_ascii=False))


def _pair(text: str, parts: int, what: str) -> list[str]:
    values = [v.strip() for v in text.split(":", parts - 1)]
    if len(values) != parts or not all(values):
        raise SystemExit(f"expected {what}, got {text!r}")
    return values


# ── set-up and health ────────────────────────────────────────────────────────
def cmd_init(args: argparse.Namespace) -> int:
    settings = Settings()
    for directory in (
        settings.db_path.parent,
        settings.data_dir,
        settings.artifacts_dir,
        settings.audit_key_file.parent,
    ):
        Path(directory).mkdir(parents=True, exist_ok=True)
    key = settings.audit_key_file
    if key.exists():
        print(f"audit key already present: {key}")
    else:
        fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write(secrets.token_hex(32))
        print(f"created audit key: {key}  (back it up separately from the database)")
    sv = _services(args)
    if args.admin:
        phrase = _new_passphrase(args, args.admin)
        sv.users.bootstrap_admin(args.admin, args.name or args.admin, passphrase=phrase)
        print(f"created first administrator: {args.admin}  (now: eli-legal login {args.admin})")
    print(f"store: {settings.db_path}   audit ledger: {settings.audit_db_path}")
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    sv = _services(args)
    settings = Settings()
    phrase = _read_secret(args, f"Passphrase for {args.user_id}: ")
    from eli_legal.domain.errors import SecondFactorRequired

    try:
        token = sv.users.login(
            args.user_id, phrase, method="cli-session", hours=settings.session_hours
        )
    except SecondFactorRequired:
        code = (
            sys.stdin.readline().strip()
            if getattr(args, "passphrase_stdin", False)
            else input("Code from your authenticator: ").strip()
        )
        token = sv.users.login(
            args.user_id, phrase, method="cli-session", hours=settings.session_hours, code=code
        )
    path = _session_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(token)
    print(f"signed in as {args.user_id} for {settings.session_hours:g} hours")
    return 0


def cmd_logout(args: argparse.Namespace) -> int:
    path = _session_file()
    if path.is_file():
        _services(args).users.logout(path.read_text(encoding="ascii").strip())
        path.unlink()
    print("signed out")
    return 0


def cmd_whoami(args: argparse.Namespace) -> int:
    user = _services(args).ctx.user(_actor(args))
    print(f"{user.user_id}  {user.display_name}  roles: {', '.join(sorted(user.roles)) or 'none'}")
    return 0


def cmd_passphrase(args: argparse.Namespace) -> int:
    sv = _services(args)
    target = args.user_id or _actor(args)
    if target == _actor(args):
        current = _read_secret(args, "Current passphrase: ")
        sv.users.set_passphrase(
            actor_id=target, user_id=target, new=_new_passphrase(args, target), current=current
        )
    else:
        with _confirmed(args, f"set the passphrase of {target}") as actor:
            sv.users.set_passphrase(
                actor_id=actor, user_id=target, new=_new_passphrase(args, target)
            )
    print(f"passphrase set for {target}; their open sessions are ended")
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    try:
        from eli_legal.gui.app import main as gui_main
    except ImportError as exc:
        raise SystemExit(
            f"the desktop application needs PySide6: pip install 'eli-legal[gui]'  ({exc})"
        ) from exc
    return int(gui_main([]))


def cmd_serve(args: argparse.Namespace) -> int:
    from eli_legal.api.serve import run

    return run(args)


def cmd_second_factor(args: argparse.Namespace) -> int:
    sv = _services(args)
    if args.factor_cmd == "setup":
        with _confirmed(args, "set up a second factor") as actor:
            secret, uri = sv.users.second_factor_begin(actor_id=actor)
        print(f"Add this key to your authenticator app:\n  {secret}\n  {uri}")
        code = input("Then enter the code it shows: ").strip()
        sv.users.second_factor_confirm(actor_id=actor, code=code)
        print("second factor enabled; you will be asked for a code at every sign-in")
    elif args.factor_cmd == "remove":
        target = args.user_id or _actor(args)
        with _confirmed(args, f"remove the second factor of {target}") as actor:
            sv.users.second_factor_remove(actor_id=actor, user_id=target)
        print(f"second factor removed for {target}; their sessions have been ended")
    return 0


def cmd_unlock(args: argparse.Namespace) -> int:
    with _confirmed(args, f"unlock {args.user_id}") as actor:
        _services(args).users.unlock(actor_id=actor, user_id=args.user_id)
    print(f"unlocked {args.user_id}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    settings = Settings()
    problems: list[str] = []
    print(f"ELI Legal {__version__} doctor")
    print(f"  mode: {settings.mode}   network default: {settings.network_default}")
    if settings.network_default.lower() != "deny":
        problems.append("network default is not deny")
    for label, path in (("policy", settings.policy_file), ("workflow", settings.workflow_file)):
        print(f"  {label}: {path}")
        if not Path(path).exists():
            problems.append(f"{label} file missing: {path}")
    if not settings.audit_key_file.exists():
        problems.append(f"audit key missing: {settings.audit_key_file} (run: eli-legal init)")
    if not problems:
        try:
            sv = _services(args)
            chain = sv.ctx.audit.report()
            print(
                f"  audit chain: {'valid' if chain.ok else 'INVALID — ' + chain.error} ({chain.count} events)"
            )
            if not chain.ok:
                problems.append(f"audit chain invalid: {chain.error}")
            print(f"  jurisdiction packs: {', '.join(sv.ctx.jurisdictions.codes())}")
            approved = [s.source_id for s in sv.ctx.sources.list() if s.approved]
            print(f"  approved legal sources: {', '.join(approved) or 'none'}")
            print(f"  model: {sv.ctx.model.model_id}   verifier: {sv.ctx.verifier_model.model_id}")
            print(f"  network guard installed: {sv.ctx.guard.installed}")
            print(
                f"  workflow: {sv.ctx.workflow.workflow_id} {sv.ctx.workflow.version}; policy {sv.ctx.policy.version}"
            )
        except EliLegalError as exc:
            problems.append(f"{type(exc).__name__}: {exc}")
    for problem in problems:
        print(f"  ERROR: {problem}")
    if not problems:
        print("  OK")
    return 1 if problems else 0


def cmd_show_policy(args: argparse.Namespace) -> int:
    from eli_legal.domain.policy import RuntimePolicy

    settings = Settings()
    RuntimePolicy.from_file(settings.policy_file)  # validates
    print(Path(settings.policy_file).read_text(encoding="utf-8"))
    return 0


def cmd_jurisdictions(args: argparse.Namespace) -> int:
    sv = _services(args)
    for code in sv.ctx.jurisdictions.codes():
        pack = sv.ctx.jurisdictions.get(code)
        validated = f"validated by {pack.validated_by}" if pack.validated else "NOT validated"
        print(
            f"{pack.code:8s} {pack.name:40s} {pack.legal_family:14s} {pack.pack_status:11s} {validated}"
        )
    return 0


# ── users and sources ────────────────────────────────────────────────────────
def cmd_user(args: argparse.Namespace) -> int:
    sv = _services(args)
    if args.user_cmd == "list":
        for u in sv.ctx.store.list_users():
            state = "active" if u.active else "inactive"
            print(
                f"{u.user_id:20s} {u.display_name:26s} {u.actor_type.value:7s} {state:9s} {', '.join(sorted(u.roles))}"
            )
    elif args.user_cmd == "add":
        with _confirmed(args, f"create or change user {args.user_id}") as actor:
            sv.users.add_user(
                actor_id=actor,
                user_id=args.user_id,
                display_name=args.name or args.user_id,
                roles=args.role,
            )
        print(f"user {args.user_id}: {', '.join(args.role)}")
        if sv.users.needs_passphrase(args.user_id):
            print(f"  set their first passphrase with: eli-legal passphrase {args.user_id}")
    elif args.user_cmd == "token":
        with _confirmed(args, f"issue an API token for {args.user_id}") as actor:
            token = sv.users.issue_token(actor_id=actor, user_id=args.user_id, label=args.label)
        print(token)
        print("store this token now; it cannot be shown again", file=sys.stderr)
    elif args.user_cmd == "deactivate":
        sv.users.deactivate(actor_id=_actor(args), user_id=args.user_id)
        print(f"deactivated {args.user_id}")
    return 0


def cmd_source(args: argparse.Namespace) -> int:
    from eli_legal.legal.source_registry import RegisteredSource

    sv = _services(args)
    if args.source_cmd == "list":
        for s in sv.sources.list():
            state = f"approved by {s.approved_by}" if s.approved else "not approved"
            print(
                f"{s.source_id:28s} {','.join(sorted(s.jurisdictions)):12s} {s.connector:13s} {state}"
            )
    elif args.source_cmd == "add":
        sv.sources.register(
            RegisteredSource(
                source_id=args.source_id,
                name=args.name,
                jurisdictions=frozenset(args.jurisdiction),
                source_types=tuple(args.type or ()),
                authority_owner=args.owner,
                licence=args.licence,
                terms_reviewed=args.terms_reviewed,
                freshness=args.freshness,
                treatment_semantics=args.status_semantics,
                authoritative_for=tuple(args.authoritative_for or ()),
                inspection=args.inspection,
            ),
            actor_id=_actor(args),
        )
        print(f"registered {args.source_id} (not yet approved)")
    elif args.source_cmd == "approve":
        with _confirmed(args, f"approve the legal source {args.source_id}") as actor:
            sv.sources.approve(args.source_id, actor_id=actor)
        print(f"approved {args.source_id}")
    elif args.source_cmd == "revoke":
        sv.sources.revoke(args.source_id, actor_id=_actor(args))
        print(f"revoked {args.source_id}")
    elif args.source_cmd == "import":
        imported = sv.sources.import_corpus(args.source_id, args.directory, actor_id=_actor(args))
        for a in imported:
            print(f"  {a.citation:36s} {a.kind.value:12s} {a.status.value}")
        print(f"imported {len(imported)} authorities into {args.source_id}")
    return 0


# ── matters and documents ────────────────────────────────────────────────────
def cmd_matter(args: argparse.Namespace) -> int:
    sv = _services(args)
    actor = _actor(args)
    c = args.matter_cmd
    if c == "create":
        matter = sv.matters.create(
            actor_id=actor,
            name=args.name,
            purpose=args.purpose,
            jurisdiction=args.jurisdiction,
            profile=Profile(args.profile),
            governing_law=args.governing_law,
            forum=args.forum,
            procedural_rules=args.rules,
            relevant_date=date.fromisoformat(args.relevant_date) if args.relevant_date else None,
            parties=[tuple(_pair(p, 2, "NAME:ROLE")) for p in args.party],
            stated_issues=args.issue,
            represented_party=args.represents,
        )
        print(matter.matter_id)
    elif c == "list":
        for m in sv.matters.list_for(actor):
            print(
                f"{m.matter_id}  {m.status.value:7s} {m.profile.value:21s} {m.jurisdiction:7s} {m.name}"
            )
    elif c == "show":
        m = sv.matters.get(args.matter, actor)
        _out(
            {
                "matter_id": m.matter_id,
                "name": m.name,
                "status": m.status.value,
                "profile": m.profile.value,
                "jurisdiction": m.jurisdiction,
                "governing_law": m.governing_law,
                "relevant_date": m.relevant_date,
                "parties": [
                    {"party_id": p.party_id, "name": p.name, "role": p.role} for p in m.parties
                ],
                "issues": m.stated_issues,
                "members": sorted(m.authorised_user_ids),
                "reviewers": sorted(m.reviewer_user_ids),
                "sources": sorted(m.approved_source_ids),
            }
        )
    elif c == "grant":
        sv.matters.grant(args.matter, actor_id=actor, user_id=args.user_id)
    elif c == "revoke":
        sv.matters.revoke(args.matter, actor_id=actor, user_id=args.user_id)
    elif c == "reviewers":
        sv.matters.set_reviewers(args.matter, actor_id=actor, reviewer_ids=args.user_id)
    elif c == "sources":
        sv.matters.set_sources(args.matter, actor_id=actor, source_ids=args.source_id)
    elif c == "set":
        sv.matters.update(
            args.matter,
            actor_id=actor,
            relevant_date=date.fromisoformat(args.relevant_date) if args.relevant_date else None,
            stated_issues=args.issue or None,
            forum=args.forum,
            procedural_rules=args.rules,
            add_parties=[tuple(_pair(p, 2, "NAME:ROLE")) for p in args.party or []],
        )
    elif c == "close":
        with _confirmed(args, "close this matter"):
            counts = sv.matters.close(
                args.matter, actor_id=actor, purge_content=args.purge, reason=args.reason
            )
        print(f"closed {args.matter}" + (f"; deleted {counts}" if args.purge else ""))
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    sv = _services(args)
    actor = _actor(args)
    matter = sv.ctx.matter_for(args.matter, actor, "document.ingest")
    party_id = None
    if args.party:
        party_id = next(
            (p.party_id for p in matter.parties if p.name.lower() == args.party.lower()), None
        )
        if party_id is None:
            raise SystemExit(f"{args.party!r} is not a party to this matter")
    for path in args.path:
        for d in sv.ingestion.ingest_path(
            matter=matter,
            actor_id=actor,
            path=path,
            doc_type=DocumentType(args.type) if args.type else None,
            party_id=party_id,
            access_scope=AccessScope(args.scope),
            custodian=args.custodian,
        ):
            note = f"  [{', '.join(d.injection_flags)}]" if d.injection_flags else ""
            print(
                f"{d.document_id}  {d.status.value:11s} {d.doc_type.value:18s} {d.filename}{note} {d.error}"
            )
    return 0


def cmd_docs(args: argparse.Namespace) -> int:
    sv = _services(args)
    for d in sv.matters.documents(args.matter, _actor(args)):
        print(
            f"{d.document_id}  {d.status.value:11s} {d.doc_type.value:18s} {d.access_scope.value:18s} {d.sha256[:16]}  {d.filename}"
        )
    return 0


# ── runs, findings, holds, verification ──────────────────────────────────────
def _print_summary(summary: dict[str, Any]) -> None:
    print(
        f"run {summary['run_id']}: {summary['status'].upper()}  (started by {summary['started_by']})"
    )
    for step in summary["steps"]:
        kind = "manual" if step["manual"] else ""
        print(f"  {step['step']:26s} {step['status']:8s} {kind:7s} {step['detail']}")
    print("  findings: " + ", ".join(f"{k}={v}" for k, v in sorted(summary["findings"].items())))
    for hold in summary["open_holds"]:
        print(f"  HOLD {hold['hold_id']} [{hold['scope']}] {hold['reason']}: {hold['detail']}")
    print(f"  open verification tasks: {summary['open_tasks']}")
    if summary["report"]:
        r = summary["report"]
        print(
            f"  report v{r['version']} {r['release_status']}  sha256 {r['sha256']}\n    {r['path']}"
        )


def cmd_run(args: argparse.Namespace) -> int:
    sv = _services(args)
    actor = _actor(args)
    c = args.run_cmd
    if c == "start":
        run = sv.runs.start(args.matter, actor_id=actor)
    elif c == "resume":
        with _confirmed(args, "restart this run"):
            run = sv.runs.resume(
                args.matter, args.run, actor_id=actor, reason=args.reason, from_step=args.from_step
            )
    elif c == "stop":
        run = sv.runs.stop(args.matter, args.run, actor_id=actor, reason=args.reason)
    elif c == "list":
        for r in sv.runs.list(args.matter, actor_id=actor):
            print(
                f"{r.run_id}  {r.status.value:24s} {r.created_at:%Y-%m-%d %H:%M}  by {r.initiated_by}"
            )
        return 0
    else:
        run = sv.runs.get(args.matter, args.run, actor_id=actor)
    summary = sv.runs.summary(args.matter, run.run_id, actor_id=actor)
    _out(summary) if args.json else _print_summary(summary)
    return 0


def cmd_claims(args: argparse.Namespace) -> int:
    sv = _services(args)
    for c in sv.verification.claims(args.matter, args.run, actor_id=_actor(args)):
        if args.status and c.status.value != args.status:
            continue
        if args.kind and c.kind.value != args.kind:
            continue
        cite = f" [{c.citation}]" if c.citation else ""
        print(f"{c.claim_id}  {c.kind.value:17s} {c.status.value:10s}{cite} {c.text[:110]}")
        if c.status_reason:
            print(f"    reason: {c.status_reason}")
    return 0


def cmd_holds(args: argparse.Namespace) -> int:
    sv = _services(args)
    for h in sv.holds.list(args.matter, args.run, actor_id=_actor(args), open_only=not args.all):
        closed = f" -> {h.resolution.value} by {h.resolved_by}" if h.resolution else ""
        print(
            f"{h.hold_id}  {h.status.value:8s} [{h.scope.value}] {h.reason_code}: {h.detail}  subject={h.subject_id}{closed}"
        )
    return 0


def cmd_hold(args: argparse.Namespace) -> int:
    sv = _services(args)
    with _confirmed(args, f"{args.action} this hold") as actor:
        hold = sv.holds.resolve(
            args.matter, args.hold, actor_id=actor, action=args.action, reason=args.reason
        )
    print(f"{hold.hold_id}: {hold.resolution.value if hold.resolution else ''}")
    return 0


def cmd_tasks(args: argparse.Namespace) -> int:
    sv = _services(args)
    actor = _actor(args)
    claims = {c.claim_id: c for c in sv.verification.claims(args.matter, args.run, actor_id=actor)}
    for t in sv.verification.tasks(args.matter, args.run, actor_id=actor):
        claim = claims.get(t.claim_id)
        print(f"{t.task_id}  check={t.verification_type:16s} claim={t.claim_id}")
        print(f"    {t.question}")
        if claim:
            print(f"    {claim.citation or ''} “{claim.text[:140]}”")
            print(f"    system: {claim.status_reason}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    sv = _services(args)
    with _confirmed(args, f"record this check as {args.result}") as actor:
        result = sv.verification.record_human_result(
            args.matter,
            args.claim,
            actor_id=actor,
            verification_type=args.check,
            status=VerificationStatus(args.result),
            reason=args.reason,
        )
    print(
        f"{result.verification_id}: {result.status.value}"
        + (" (override)" if result.override else "")
    )
    return 0


# ── report, review, release ──────────────────────────────────────────────────
def cmd_report(args: argparse.Namespace) -> int:
    sv = _services(args)
    summary = sv.runs.summary(args.matter, args.run, actor_id=_actor(args))
    if not summary["report"]:
        raise SystemExit("no report has been drafted for this run")
    if args.path:
        print(summary["report"]["path"])
    else:
        print(Path(summary["report"]["path"]).read_text(encoding="utf-8"))
        print(f"\nsha256 {summary['report']['sha256']}", file=sys.stderr)
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    from eli_legal.workflows.case_preparation import warning_id

    sv = _services(args)
    actor = _actor(args)
    summary = sv.runs.summary(args.matter, args.run, actor_id=actor)
    report = summary["report"] or {}
    acknowledged = list(args.acknowledge or [])
    if args.decision == "approve":
        limits = report.get("warnings", [])
        if limits:
            print("Limits of this report:")
            for w in limits:
                print(f"  - {w}")
        if args.acknowledge_all:
            acknowledged = [warning_id(w) for w in limits]
    decision = {
        "approve": ReviewDecision.APPROVE,
        "reject": ReviewDecision.REJECT,
        "return": ReviewDecision.RETURN_FOR_CORRECTION,
    }[args.decision]
    with _confirmed(args, f"{args.decision} this report"):
        review = sv.reviews.decide(
            args.matter,
            args.run,
            actor_id=actor,
            decision=decision,
            reasons=args.reasons,
            report_hash=args.report_hash or "",
            acknowledged=acknowledged,
        )
    after = sv.runs.summary(args.matter, args.run, actor_id=actor)
    print(f"{review.review_id}: {review.decision.value}; run is {after['status']}")
    if after["report"]:
        print(after["report"]["path"])
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    sv = _services(args)
    actor = _actor(args)
    if args.release_cmd == "prepare":
        recipients = [tuple(_pair(r, 3, "ID:NAME:ADDRESS")) for r in args.to]
        package = sv.releases.prepare(args.matter, args.run, actor_id=actor, recipients=recipients)
        print(package.release_id)
        for r in package.recipients:
            print(
                f"  {r.recipient_id:36s} {'entitled' if r.authorised_for_matter else 'NOT ENTITLED'}"
            )
    else:
        with _confirmed(args, "release this report to the confirmed recipients"):
            receipts = sv.delivery.distribute(
                args.matter, args.release, actor_id=actor, confirmed_recipient_ids=args.confirm
            )
        for r in receipts:
            print(f"{r.recipient_id}: {r.status}  {r.detail}")
    return 0


def cmd_incident(args: argparse.Namespace) -> int:
    sv = _services(args)
    actor = _actor(args)
    if args.incident_cmd == "list":
        for i in sv.incidents.list(args.matter, actor_id=actor):
            print(f"{i.incident_id}  {i.status:6s} {i.severity.value:8s} {i.category}: {i.detail}")
    elif args.incident_cmd == "open":
        incident = sv.incidents.create(
            args.matter,
            actor_id=actor,
            category=args.category,
            detail=args.detail,
            severity=IncidentSeverity(args.severity),
            run_id=args.run,
        )
        print(incident.incident_id)
    else:
        sv.incidents.close(
            args.matter,
            args.incident,
            actor_id=actor,
            containment=args.containment,
            reason=args.reason,
        )
        print(f"closed {args.incident}")
    return 0


# ── audit, evidence, monitoring, governance ──────────────────────────────────
def cmd_audit(args: argparse.Namespace) -> int:
    from eli_legal.adapters.local.hmac_audit import Checkpoint

    sv = _services(args)
    actor = _actor(args)
    ledger = sv.ctx.audit
    if args.audit_cmd == "verify":
        sv.ctx.authorizer().require_global(actor, "audit.verify")
        expected = (
            Checkpoint.from_json(Path(args.against).read_text(encoding="utf-8"))
            if args.against
            else None
        )
        report = ledger.report(expected=expected)
        print(
            f"{'VALID' if report.ok else 'INVALID: ' + report.error}  events={report.count}  keys={','.join(report.key_ids)}"
        )
        return 0 if report.ok else 2
    if args.audit_cmd == "checkpoint":
        sv.ctx.authorizer().require_global(actor, "audit.verify")
        text = ledger.checkpoint().to_json()
        if args.out:
            Path(args.out).write_text(text + "\n", encoding="utf-8")
            print(f"wrote {args.out}; keep a copy off this machine")
        else:
            print(text)
        return 0
    matter = sv.ctx.matter_for(args.matter, actor, "audit.read")
    events = list(ledger.events(matter_id=matter.matter_id))[-args.n :]
    for e in events:
        print(
            f"{e['seq']:6d} {e['created_at'][:19]} {e['event_type']:22s} {e['actor_id']:14s} {e['outcome']:12s} {e['subject_id']}"
        )
    return 0


def cmd_evidence(args: argparse.Namespace) -> int:
    sv = _services(args)
    print(sv.evidence_pack(args.matter, args.run, actor_id=_actor(args), out_dir=args.out))
    return 0


def cmd_monitor(args: argparse.Namespace) -> int:
    sv = _services(args)
    _out(sv.monitoring.snapshot(actor_id=_actor(args)).to_dict())
    return 0


def cmd_governance(args: argparse.Namespace) -> int:
    from eli_legal.governance.registers import check_registers

    problems = check_registers(Path(args.root))  # --root is a source checkout, for test names
    for p in problems:
        print(f"  PROBLEM: {p}")
    print("governance registers: " + ("OK" if not problems else f"{len(problems)} problem(s)"))
    return 1 if problems else 0


def cmd_edition(args: argparse.Namespace) -> int:
    from eli_legal import edition

    if args.edition_cmd == "manifest":
        _out(edition.manifest())
    elif args.edition_cmd == "install":
        for path in edition.install_into_eli(args.eli_root, force=args.force):
            print(f"wrote {path}")
    else:
        for line in edition.verify_against_eli(args.eli_root):
            print(line)
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from eli_legal.adapters.inference.local import OpenAICompatInference
    from eli_legal.demo_run import run_demo

    root = Path(args.dir) if args.dir else Path(tempfile.mkdtemp(prefix="eli_legal_demo_"))
    inference = (
        OpenAICompatInference(base_url=args.model_url, model=args.model) if args.model else None
    )
    print(f"ELI Legal demonstration — synthetic dispute, fictional law — workspace: {root}\n")
    result = run_demo(root, inference=inference)
    return 0 if result.final_status == "approved_for_reliance" else 1


# ── parser ───────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eli-legal", description="Governed legal case preparation"
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--passphrase-stdin",
        action="store_true",
        help="read passphrases from standard input instead of prompting (for scripts)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add(
        name: str, handler: Callable[[argparse.Namespace], int], help_text: str = ""
    ) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(handler=handler)
        return p

    p = add("init", cmd_init, "create directories, the audit key and the first administrator")
    p.add_argument("--admin")
    p.add_argument("--name")
    add("login", cmd_login, "sign in with your passphrase").add_argument("user_id")
    add("logout", cmd_logout, "end your session")
    add("whoami", cmd_whoami, "show who is signed in")
    p = add("passphrase", cmd_passphrase, "change your passphrase, or set another user's")
    p.add_argument("user_id", nargs="?")
    add("gui", cmd_gui, "open the desktop application")
    p = add("serve", cmd_serve, "start the server and browser application")
    from eli_legal.api.serve import add_arguments as _serve_arguments

    _serve_arguments(p)
    p = add("second-factor", cmd_second_factor, "set up or remove an authenticator code")
    s = p.add_subparsers(dest="factor_cmd", required=True)
    s.add_parser("setup", help="set up your own")
    s.add_parser("remove", help="remove yours, or (administrator) someone else's").add_argument(
        "user_id", nargs="?"
    )
    add("unlock", cmd_unlock, "unlock an account locked after failed sign-ins").add_argument(
        "user_id"
    )
    add("doctor", cmd_doctor, "check the installation")
    add("show-policy", cmd_show_policy, "print the runtime policy")
    add("jurisdictions", cmd_jurisdictions, "list jurisdiction packs")

    p = add("user", cmd_user, "manage users")
    s = p.add_subparsers(dest="user_cmd", required=True)
    s.add_parser("list")
    a = s.add_parser("add")
    a.add_argument("user_id")
    a.add_argument("--name")
    a.add_argument("--role", action="append", required=True)
    a = s.add_parser("token")
    a.add_argument("user_id")
    a.add_argument("--label", default="")
    s.add_parser("deactivate").add_argument("user_id")

    p = add("source", cmd_source, "manage the approved-source register")
    s = p.add_subparsers(dest="source_cmd", required=True)
    s.add_parser("list")
    a = s.add_parser("add")
    a.add_argument("source_id")
    a.add_argument("--name", required=True)
    a.add_argument("--jurisdiction", action="append", required=True)
    a.add_argument("--type", action="append")
    a.add_argument("--owner", required=True, help="who publishes the material")
    a.add_argument("--licence", required=True, help="terms under which it may be used")
    a.add_argument("--terms-reviewed", action="store_true")
    a.add_argument("--freshness", default="")
    a.add_argument(
        "--status-semantics", required=True, help="what a status answer from this source means"
    )
    a.add_argument(
        "--authoritative-for",
        action="append",
        help="citation pattern id this source is complete for",
    )
    a.add_argument("--inspection", default="")
    for name in ("approve", "revoke"):
        s.add_parser(name).add_argument("source_id")
    a = s.add_parser("import")
    a.add_argument("source_id")
    a.add_argument("directory")

    p = add("matter", cmd_matter, "manage matters")
    s = p.add_subparsers(dest="matter_cmd", required=True)
    a = s.add_parser("create")
    a.add_argument("--name", required=True)
    a.add_argument("--purpose", required=True)
    a.add_argument("--jurisdiction", required=True)
    a.add_argument("--profile", required=True, choices=[x.value for x in Profile])
    a.add_argument("--governing-law")
    a.add_argument("--forum", default="")
    a.add_argument("--rules", default="")
    a.add_argument("--relevant-date")
    a.add_argument("--party", action="append", default=[], help="NAME:ROLE")
    a.add_argument("--issue", action="append", default=[])
    a.add_argument("--represents", help="party name (party-representative profile)")
    s.add_parser("list")
    s.add_parser("show").add_argument("matter")
    for name in ("grant", "revoke"):
        a = s.add_parser(name)
        a.add_argument("matter")
        a.add_argument("user_id")
    a = s.add_parser("reviewers")
    a.add_argument("matter")
    a.add_argument("user_id", nargs="+")
    a = s.add_parser("sources")
    a.add_argument("matter")
    a.add_argument("source_id", nargs="*")
    a = s.add_parser("set")
    a.add_argument("matter")
    a.add_argument("--relevant-date")
    a.add_argument("--issue", action="append")
    a.add_argument("--forum")
    a.add_argument("--rules")
    a.add_argument("--party", action="append")
    a = s.add_parser("close")
    a.add_argument("matter")
    a.add_argument("--reason", required=True)
    a.add_argument("--purge", action="store_true", help="delete documents, text and indexes")

    p = add("ingest", cmd_ingest, "take documents into a matter")
    p.add_argument("matter")
    p.add_argument("path", nargs="+")
    p.add_argument("--party", help="name of the party that filed or disclosed it")
    p.add_argument("--type", choices=[x.value for x in DocumentType])
    p.add_argument(
        "--scope", default=AccessScope.ALL_PARTIES.value, choices=[x.value for x in AccessScope]
    )
    p.add_argument("--custodian", default="")
    add("docs", cmd_docs, "list a matter's documents").add_argument("matter")

    p = add("run", cmd_run, "start, inspect, stop or restart a run")
    p.add_argument("--json", action="store_true")
    s = p.add_subparsers(dest="run_cmd", required=True)
    s.add_parser("start").add_argument("matter")
    s.add_parser("list").add_argument("matter")
    a = s.add_parser("status")
    a.add_argument("matter")
    a.add_argument("run")
    a = s.add_parser("resume")
    a.add_argument("matter")
    a.add_argument("run")
    a.add_argument("--reason", required=True)
    a.add_argument("--from", dest="from_step")
    a = s.add_parser("stop")
    a.add_argument("matter")
    a.add_argument("run")
    a.add_argument("--reason", required=True)

    p = add("claims", cmd_claims, "list a run's findings")
    p.add_argument("matter")
    p.add_argument("run")
    p.add_argument("--status")
    p.add_argument("--kind")
    p = add("holds", cmd_holds, "list holds")
    p.add_argument("matter")
    p.add_argument("run")
    p.add_argument("--all", action="store_true")
    p = add("hold", cmd_hold, "resolve a hold by a named decision")
    p.add_argument("matter")
    p.add_argument("hold")
    p.add_argument("--action", required=True, choices=["exclude", "waive"])
    p.add_argument("--reason", required=True)
    p = add("tasks", cmd_tasks, "checks waiting for a person")
    p.add_argument("matter")
    p.add_argument("run")
    p = add("verify", cmd_verify, "record a person's verification result")
    p.add_argument("matter")
    p.add_argument("claim")
    p.add_argument(
        "--check",
        required=True,
        choices=["citation", "current_law", "proposition", "evidence_support", "provenance"],
    )
    p.add_argument("--result", required=True, choices=["verified", "failed"])
    p.add_argument("--reason", required=True)

    p = add("report", cmd_report, "show the current report")
    p.add_argument("matter")
    p.add_argument("run")
    p.add_argument("--path", action="store_true")
    p = add("review", cmd_review, "approve, reject or return a report")
    p.add_argument("matter")
    p.add_argument("run")
    p.add_argument("--decision", required=True, choices=["approve", "reject", "return"])
    p.add_argument("--reasons", required=True)
    p.add_argument("--report-hash", help="sha256 of the report version you reviewed")
    p.add_argument("--acknowledge", action="append", help="id of a stated limit you accept")
    p.add_argument(
        "--acknowledge-all",
        action="store_true",
        help="accept every stated limit (they are printed first)",
    )
    p = add("release", cmd_release, "prepare and stage an approved report")
    s = p.add_subparsers(dest="release_cmd", required=True)
    a = s.add_parser("prepare")
    a.add_argument("matter")
    a.add_argument("run")
    a.add_argument("--to", action="append", required=True, help="ID:NAME:ADDRESS")
    a = s.add_parser("send")
    a.add_argument("matter")
    a.add_argument("release")
    a.add_argument(
        "--confirm", action="append", required=True, help="recipient id, repeated in order"
    )

    p = add("incident", cmd_incident, "manage incidents")
    s = p.add_subparsers(dest="incident_cmd", required=True)
    s.add_parser("list").add_argument("matter")
    a = s.add_parser("open")
    a.add_argument("matter")
    a.add_argument("--category", required=True)
    a.add_argument("--detail", required=True)
    a.add_argument("--severity", default="medium", choices=[x.value for x in IncidentSeverity])
    a.add_argument("--run")
    a = s.add_parser("close")
    a.add_argument("matter")
    a.add_argument("incident")
    a.add_argument("--containment", required=True)
    a.add_argument("--reason", required=True)

    p = add("audit", cmd_audit, "verify or read the audit ledger")
    s = p.add_subparsers(dest="audit_cmd", required=True)
    s.add_parser("verify").add_argument("--against", help="a checkpoint file kept off this machine")
    s.add_parser("checkpoint").add_argument("--out")
    a = s.add_parser("tail")
    a.add_argument("matter")
    a.add_argument("-n", type=int, default=30)
    p = add("evidence", cmd_evidence, "export the evidence pack for a run")
    p.add_argument("matter")
    p.add_argument("run")
    p.add_argument("--out")
    add("monitor", cmd_monitor, "post-deployment monitoring snapshot")
    add(
        "governance", cmd_governance, "check the governance registers against the code"
    ).add_argument("--root", default=".")
    p = add(
        "edition",
        cmd_edition,
        "ELI edition pack: show, install into or verify against an ELI checkout",
    )
    s = p.add_subparsers(dest="edition_cmd", required=True)
    s.add_parser("manifest")
    a = s.add_parser("install")
    a.add_argument("--eli-root", required=True)
    a.add_argument("--force", action="store_true")
    s.add_parser("verify").add_argument("--eli-root", required=True)
    p = add("demo", cmd_demo, "run a synthetic dispute through the whole lifecycle")
    p.add_argument("--dir")
    p.add_argument("--model", help="local model name, e.g. qwen2.5:14b")
    p.add_argument("--model-url", default="http://127.0.0.1:11434/v1")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except EliLegalError as exc:
        print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"not found: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
