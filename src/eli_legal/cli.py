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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from eli_legal import __version__
from eli_legal.domain import plain
from eli_legal.domain.enums import (
    AccessScope,
    DocumentType,
    IncidentSeverity,
    Profile,
    ReviewDecision,
    VerificationStatus,
)
from eli_legal.domain.errors import EliLegalError
from eli_legal.security import access
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
        from eli_legal.system_libraries import window_cannot_start

        raise SystemExit(
            f"the desktop application cannot start. {window_cannot_start(exc)}"
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
    elif args.source_cmd == "add-live":
        from dataclasses import replace

        from eli_legal.adapters.sources import live

        source = replace(
            live.preset(args.kind, args.source_id or args.kind),
            terms_reviewed=args.terms_reviewed,
        )
        sv.sources.register(source, actor_id=_actor(args))
        print(f"registered {source.source_id}: {source.name} (not yet approved)")
        print(f"  licence: {source.licence}")
        print(f"  may contact only: {', '.join(source.hosts)}")
        if not args.terms_reviewed:
            print("  read the terms, then register it again with --terms-reviewed to approve it")
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
    elif args.source_cmd == "index":
        coverage = sv.sources.index(args.source_id, actor_id=_actor(args))
        print(
            f"{args.source_id}: {coverage.total} passages searchable by meaning "
            f"({coverage.indexed_now} embedded now) with {sv.ctx.embedder.model_id}"
        )
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
            frameworks=args.framework,
            recommended_frameworks=not args.no_recommended_frameworks,
            team=[_member(m) for m in args.member or []],
            reviewers=args.reviewer or [],
            sources=args.source or [],
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
        sv.matters.grant(
            args.matter,
            actor_id=actor,
            user_id=args.user_id,
            matter_role=args.role,
            party=args.acts_for,
        )
    elif c == "people":
        for m in sv.matters.members(args.matter, actor):
            role = access.MATTER_ROLES[m.matter_role].label if m.matter_role else ""
            reads = (
                "everything"
                if len(m.reads) == len(access.ALL_SCOPES)
                else ", ".join(plain.scope(r).lower() for r in m.reads) or "nothing"
            )
            print(
                f"{m.user_id:16s} {role:15s} {('acts for ' + m.party) if m.party else '':28s} "
                f"reads: {reads}{'  · reviews' if m.reviewer else ''}"
            )
    elif c == "role":
        sv.matters.set_member(
            args.matter,
            actor_id=actor,
            user_id=args.user_id,
            matter_role=args.role,
            party=args.acts_for,
            clear_party=args.no_party,
            reads=args.reads,
        )
    elif c == "revoke":
        sv.matters.revoke(args.matter, actor_id=actor, user_id=args.user_id)
    elif c == "reviewers":
        sv.matters.set_reviewers(args.matter, actor_id=actor, reviewer_ids=args.user_id)
    elif c == "sources":
        sv.matters.set_sources(args.matter, actor_id=actor, source_ids=args.source_id)
    elif c == "frameworks":
        if args.pack_id:
            sv.frameworks.set_for_matter(args.matter, actor_id=actor, pack_ids=args.pack_id)
        for state in sv.frameworks.for_matter(args.matter, actor_id=actor):
            print(f"{state.pack.pack_id:32} {state.pack.title}  [{state.why}]")
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


def _member(text: str) -> Any:
    from eli_legal.application.matter_service import TeamMember

    parts = [p.strip() for p in text.split(":")]
    if not parts[0]:
        raise SystemExit(f"expected USER[:ROLE[:PARTY]], got {text!r}")
    return TeamMember(
        parts[0], parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else None
    )


def cmd_status(args: argparse.Namespace) -> int:
    """Where a matter stands and what to do next; or, with no matter, what is waiting for you
    everywhere, and the latest routine checks."""
    sv = _services(args)
    actor = _actor(args)
    if args.matter:
        guide = sv.guidance.for_matter(args.matter, actor_id=actor)
        print(guide.matter_name)
        print(f"  {guide.headline}")
        print(f"  You are {guide.role.lower()} on this matter. {guide.reads}")
        print()
        for n, stage in enumerate(guide.stages, start=1):
            mark = {"done": "✓", "current": "▶"}.get(stage.state, " ")
            print(f"  {mark} {n}. {stage.title:18s} {stage.detail}")
        print()
        print("What to do next:" if guide.steps else "Nothing is waiting on this matter.")
        for step in guide.steps:
            print(f"  • {step.title}")
            print(f"      {step.why}")
            if not step.can_do:
                print(f"      You cannot do this. {step.who}")
        return 0
    work = sv.guidance.my_work(actor_id=actor)
    print("Waiting for you:" if work else "Nothing is waiting for you.")
    for w in work:
        print(f"  • {w.matter_name}: {w.text}   ({w.matter_id})")
    latest = sv.checks.latest()
    print()
    print(f"Routine checks: {latest.headline}" if latest else "Routine checks: not run yet.")
    print(f"Compliance: {sv.compliance.overview(actor_id=actor).headline}")
    return 0


def cmd_compliance(args: argparse.Namespace) -> int:
    sv = _services(args)
    actor = _actor(args)
    c = args.compliance_cmd
    if c == "show":
        overview = sv.compliance.overview(actor_id=actor)
        print(overview.headline)
        for r in overview.requirements:
            if args.all or r.state != "software":
                print(
                    f"  {r.requirement_id:11s} {plain.state(r.state):30s} {r.reference:28s} {r.requirement[:70]}"
                )
    elif c == "actions":
        for a in sv.compliance.overview(actor_id=actor).actions:
            print(
                f"  {a.action.action_id}  {plain.state(a.state) if a.state != 'done' else 'Done':30s} {a.action.title}"
            )
            if a.state in ("waiting", "review_due"):
                print(f"         {a.detail}")
    elif c == "form":
        action = sv.compliance.action(args.action)
        _out(
            {f.key: f"({f.label})" for f in action.form}
            if action.form
            else {"statement": action.statement}
        )
    elif c == "record":
        answers = json.loads(Path(args.answers).read_text(encoding="utf-8")) if args.answers else {}
        with _confirmed(args, f"record {args.action}"):
            record = sv.compliance.record(
                args.action,
                actor_id=actor,
                answers=answers,
                confirmed=args.confirm,
                notes=args.notes or "",
                reference=args.reference or "",
                not_applicable=args.not_applicable,
            )
        print(
            f"{record.record_id}: {record.summary}"
            + (f" Review by {record.review_by}." if record.review_by else "")
        )
    elif c == "retention":
        with _confirmed(args, "set the retention periods"):
            record = sv.compliance.set_retention(
                actor_id=actor, audit_days=args.audit_days, closed_matter_days=args.closed_days
            )
        print(record.summary)
    elif c == "training":
        if args.user_id:
            with _confirmed(args, f"record training for {args.user_id}"):
                sv.compliance.record_training(
                    actor_id=actor,
                    user_id=args.user_id,
                    course=args.course,
                    completed_on=date.fromisoformat(args.completed),
                    expires_on=date.fromisoformat(args.expires) if args.expires else None,
                )
        for t in sv.compliance.training():
            print(f"  {t.user_id:16s} {t.completed_on} → {t.expires_on}  {t.course}")
        missing = sv.compliance.untrained()
        print("No current record: " + (", ".join(missing) if missing else "nobody"))
    elif c == "evaluate":
        with _confirmed(args, "run the accuracy evaluation"):
            record = sv.compliance.run_evaluation(actor_id=actor)
        print(record.summary)
        if record.answers.get("missed"):
            print(f"Missed: {record.answers['missed']}")
    elif c == "draft":
        path, digest = sv.compliance.generate(args.kind, actor_id=actor)
        print(path)
        print(f"sha256 {digest}")
    elif c == "sign-off":
        with _confirmed(args, f"sign off {args.action}"):
            record = sv.compliance.sign_off(args.action, actor_id=actor, sha256=args.sha256)
        print(record.summary)
    return 0


def cmd_checks(args: argparse.Namespace) -> int:
    """Run the routine checks (from cron or a timer, or by hand), or show the latest."""
    sv = _services(args)
    if args.checks_cmd == "run":
        run = sv.checks.run(actor_id=_actor(args)) if not args.as_system else sv.checks.run()
    else:
        found = sv.checks.latest()
        if found is None:
            print("The routine checks have not run yet.")
            return 0
        run = found
    actor = _actor(args) if not getattr(args, "as_system", False) else None
    results = sv.checks.for_viewer(run, actor_id=actor) if actor else run.results
    print(run.headline)
    for r in results:
        mark = {"ok": "✓", "attention": "!", "failed": "✗"}.get(r.state, "?")
        print(f"  {mark} {r.title}: {r.summary}")
        for item in r.items[:10]:
            print(f"      - {item.text}")
        for done in r.acted:
            print(f"      did: {done}")
        if r.state != "ok" and r.what_to_do:
            print(f"      what to do: {r.what_to_do}")
    return 0 if run.state == "ok" else 1


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Measure legal research and fact linking against answers fixed in advance."""
    from eli_legal.adapters.inference.embedding import from_settings
    from eli_legal.evaluation import linking, research
    from eli_legal.legal.semantic import SemanticIndex
    from eli_legal.settings import HOME

    settings = Settings()
    embedder = from_settings(
        args.embedding or settings.embedding_model, extra_dirs=settings.models_dirs, home=HOME
    )
    folder = Path(settings.db_path).parent / "evaluation"
    out: dict[str, Any] = {"embedding_model": embedder.model_id if embedder.available else ""}
    if not embedder.available:
        out["embedding_note"] = embedder.reason
    if args.benchmark in ("research", "all"):
        out["research"] = research.run(
            folder, semantic_for=lambda store: SemanticIndex(store, embedder)
        )
    if args.benchmark in ("linking", "all"):
        from eli_legal.persistence.sqlite import Store

        cache = Store(folder / "linking.db")
        out["linking"] = linking.run(SemanticIndex(cache, embedder) if embedder.available else None)
    if args.json:
        print(json.dumps(out, indent=2))
        return 0
    if not embedder.available:
        print(f"Searching by meaning is not measured: {embedder.reason}.")
    if "research" in out:
        r = out["research"]
        print(
            f"Legal research: {r['issues']} issues over {r['corpus']['passages']} passages of "
            f"{r['corpus']['instruments']} EU and UK instruments"
        )
        print(
            "  method     recall@5  recall@10  MRR    nDCG@10  offered in point  "
            "governing offered  closest passage in point"
        )
        for x in r["results"]:
            print(
                f"  {x['method']:9s}  {x['recall_5']:.2f}      {x['recall_10']:.2f}       "
                f"{x['mrr']:.2f}   {x['ndcg_10']:.2f}     {x['offered_in_point']:.0%}"
                f"               {x['governing_offered']:.0%}"
                f"                {x['closest_passage_in_point']:.0%}"
            )
    if "linking" in out:
        k = out["linking"]
        print(f"Linking facts to issues: {k['facts']} facts in {k['disputes']} disputes")
        print("  method                 precision  recall  F1")
        for x in k["results"]:
            name = "words" if x["method"] == "words" else "words and meaning"
            print(f"  {name:21s}  {x['precision']:.2f}       {x['recall']:.2f}    {x['f1']:.2f}")
    return 0


def cmd_network(args: argparse.Namespace) -> int:
    """Hard offline: show it, switch it on now, or set it for every start."""
    sv = _services(args)
    c = args.network_cmd
    if c == "offline":
        status = sv.network.go_offline(actor_id=_actor(args))
    elif c == "at-start":
        from eli_legal.settings import ENV_FILE

        with _confirmed(args, "change whether ELI Legal starts hard offline") as actor:
            status = sv.network.set_at_every_start(
                actor_id=actor, on=args.state == "on", persist_to=ENV_FILE
            )
    else:
        status = sv.network.status()
    print(
        "Hard offline: "
        + (f"ON, enforced by {status['enforced_by']}" if status["hard_offline"] else "off")
    )
    if status["hard_offline"]:
        print(f"  {status['detail']}")
        print(f"  checked by a refused native connection: {'yes' if status['verified'] else 'no'}")
    print(f"At every start: {'on' if status['at_every_start'] else 'off'}")
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
        f"run {summary['run_id']}: {plain.state(summary['status'])}  "
        f"(started by {summary['started_by']})"
    )
    for step in summary["steps"]:
        kind = "person" if step["manual"] else ""
        print(f"  {step['step']:26s} {plain.state(step['status']):18s} {kind:7s} {step['detail']}")
    print("  findings: " + ", ".join(f"{k}={v}" for k, v in sorted(summary["findings"].items())))
    for hold in summary["open_holds"]:
        print(
            f"  HOLD {hold['hold_id']} [{hold['scope']}] {plain.hold_reason(hold['reason'])}: "
            f"{hold['detail']}"
        )
    print(f"  open verification tasks: {summary['open_tasks']}")
    if summary["report"]:
        r = summary["report"]
        print(
            f"  report v{r['version']} {plain.state(r['release_status']).lower()}  "
            f"sha256 {r['sha256']}\n    {r['path']}"
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
    elif c == "hold":
        with _confirmed(args, "put this run on hold"):
            hold = sv.holds.place(args.matter, args.run, actor_id=actor, reason=args.reason)
        print(
            f"on hold: {hold.hold_id}  (lift with: eli-legal hold {args.matter} {hold.hold_id} --action lift --reason …)"
        )
        run = sv.runs.get(args.matter, args.run, actor_id=actor)
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
            f"{h.hold_id}  {plain.state(h.status):8s} [{h.scope.value}] "
            f"{plain.hold_reason(h.reason_code)}: {h.detail}  subject={h.subject_id}{closed}"
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


def cmd_preserve(args: argparse.Namespace) -> int:
    """Preservation holds: nothing they cover is deleted until released."""
    sv = _services(args)
    actor = _actor(args)
    if args.preserve_cmd == "list":
        for h in sv.preservation.list(args.matter, actor_id=actor):
            what = "whole matter" if h.scope == "matter" else f"{len(h.document_ids)} document(s)"
            print(f"{h.hold_id}  {h.status:8s} {what}  {h.authority}: {h.legal_basis}")
    elif args.preserve_cmd == "place":
        with _confirmed(args, "place a preservation hold"):
            hold = sv.preservation.place(
                args.matter,
                actor_id=actor,
                legal_basis=args.basis,
                authority=args.authority,
                document_ids=args.document or [],
                review_by=date.fromisoformat(args.review_by) if args.review_by else None,
            )
        print(hold.hold_id)
    elif args.preserve_cmd == "release":
        with _confirmed(args, "release a preservation hold"):
            hold = sv.preservation.release(
                args.matter, args.hold, actor_id=actor, reason=args.reason
            )
        print(f"{hold.hold_id}: {hold.status}")
    return 0


def cmd_reliance(args: argparse.Namespace) -> int:
    """Approved reports suspended from reliance, and ending a suspension."""
    sv = _services(args)
    actor = _actor(args)
    if args.reliance_cmd == "list":
        for b in sv.reliance.list(args.matter, actor_id=actor):
            print(
                f"{b.block_id}  {b.status:10s} run {b.run_id}  {len(b.authority_ids)} authority(ies)"
                f"  incident {b.incident_id or '-'}"
                + (f"  received by: {', '.join(b.recipient_ids)}" if b.recipient_ids else "")
            )
    elif args.reliance_cmd == "resolve":
        with _confirmed(args, "end the suspension of an approved report"):
            block = sv.reliance.resolve(
                args.matter,
                args.block,
                actor_id=actor,
                basis=args.basis,
                superseded_by_run_id=args.superseded_by or "",
            )
        print(f"{block.block_id}: {block.status}")
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
    elif args.incident_cmd == "aware":
        with _confirmed(args, "record when an incident became known"):
            incident = sv.incidents.record_awareness(
                args.matter,
                args.incident,
                actor_id=actor,
                aware_at=datetime.fromisoformat(args.aware_at).astimezone(timezone.utc),
                basis=args.basis,
                aware_by=args.aware_by or "",
                occurred_at=datetime.fromisoformat(args.occurred_at).astimezone(timezone.utc)
                if args.occurred_at
                else None,
            )
        from eli_legal.application.incident_service import reporting_deadline

        deadline = reporting_deadline(incident)
        print(f"{incident.incident_id}: aware {incident.aware_at}"
              + (f"; report due by {deadline.date().isoformat()}" if deadline else ""))  # fmt: skip
    elif args.incident_cmd == "assign":
        incident = sv.incidents.assign(
            args.matter, args.incident, actor_id=actor, owner=args.owner, backup=args.backup
        )
        print(
            f"{incident.incident_id}: owner {incident.owner_user_id}, stand-in {incident.backup_user_id}"
        )
    elif args.incident_cmd == "report":
        on = date.fromisoformat(args.reported_on) if args.reported_on else None
        with _confirmed(args, "record the reporting decision"):
            incident = sv.incidents.decide_reporting(
                args.matter,
                args.incident,
                actor_id=actor,
                reportable=args.reportable == "yes",
                reason=args.reason,
                serious_kind=args.kind,
                reported_on=datetime(on.year, on.month, on.day, tzinfo=timezone.utc)
                if on
                else None,
                reference=args.reference,
            )
        print(
            f"{incident.incident_id}: "
            + (
                "reported"
                if incident.reported_at
                else "reportable"
                if incident.reportable
                else "not reportable"
            )
        )
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
    inference: Any = (
        OpenAICompatInference(base_url=args.model_url, model=args.model) if args.model else None
    )
    if args.gguf:
        from eli_legal.adapters.inference.gguf import GgufInference
        from eli_legal.legal.llm import working_context_tokens

        inference = GgufInference(
            args.gguf,
            n_ctx=args.gguf_context,
            n_gpu_layers=args.gguf_gpu_layers,
            working_ctx=working_context_tokens(),
        )
        inference.on_load = lambda report: print(f"model loaded: {report.describe()}")
    print(f"ELI Legal demonstration — synthetic dispute, fictional law — workspace: {root}\n")
    result = run_demo(root, inference=inference)
    return 0 if result.final_status == "approved_for_reliance" else 1


def cmd_bundle(args: argparse.Namespace) -> int:
    from eli_legal import bundle

    target = Path(args.into) if getattr(args, "into", None) else None
    if args.bundle_cmd == "register":
        if getattr(args, "if_eli_v3", False) and target is None and not bundle.eli_v3_present():
            print("ELI v3 is not on this machine; nothing registered")
            return 0
        path = bundle.register(target)
        print(
            f"registered with ELI v3: {path}\nELI v3 will offer to open ELI Legal (its Bundles menu, or: eli --bundle legal)"
        )
    elif args.bundle_cmd == "unregister":
        removed = bundle.unregister(target, this_copy=getattr(args, "this_copy", False))
        print("\n".join(f"removed {p}" for p in removed) or "ELI Legal was not registered")
    else:
        _out(
            {
                **bundle.describe(),
                "command": bundle.own_command(),
                "registers_in": [str(p) for p in bundle.v3_bundle_dirs()],
            }
        )
    return 0


def cmd_licence(args: argparse.Namespace) -> int:
    from eli_sdk import InvalidKey

    from eli_legal import licensing

    if args.licence_cmd == "activate":
        try:
            lic = licensing.activate(args.key)
        except InvalidKey as exc:
            print(f"not activated: {exc}", file=sys.stderr)
            return 2
        print(f"activated: {lic.label} {lic.major_version}.x, {lic.tier}, {lic.seats} seat(s)")
        return 0
    if args.licence_cmd == "remove":
        print(
            "removed this machine's ELI Legal key"
            if licensing.remove()
            else "no ELI Legal key here"
        )
        return 0
    got = licensing.status()
    _out(
        {
            "licensed": got.granted,
            "reason": got.reason,
            "required": licensing.required(),
            "keys": str(licensing.store().directory),
        }
    )
    return 0


def cmd_framework(args: argparse.Namespace) -> int:
    from eli_legal.legal.frameworks import pack_to_dict

    sv = _services(args)
    actor = _actor(args)
    c = args.framework_cmd
    if c == "list":
        for state in sv.frameworks.list(actor_id=actor):
            p = state.pack
            print(
                f"{p.pack_id:32} {p.scope:15} {','.join(p.jurisdictions):10} {p.short_title}  [{state.why}]"
            )
    elif c == "current":
        with _confirmed(args, f"confirm {args.pack_id} is current"):
            sv.checks.confirm_law_current(
                args.pack_id,
                actor_id=actor,
                checked_on=date.fromisoformat(args.checked_on),
                note=args.note,
            )
        print(f"{args.pack_id}: checked against the official text on {args.checked_on}")
    elif c == "show":
        state = sv.frameworks.get(args.pack_id, actor_id=actor)
        _out({**state.as_dict(), "pack": pack_to_dict(state.pack)})
    elif c == "import":
        path = Path(args.file)
        state = sv.frameworks.import_file(
            path.name,
            path.read_bytes(),
            actor_id=actor,
            title=args.title,
            pack_id=args.pack_id,
            issuer=args.issuer,
            version=args.pack_version,
        )
        print(
            f"imported {state.pack.pack_id}: {len(state.pack.requirements)} requirement(s); {state.why}"
        )
    elif c == "approve":
        with _confirmed(args, f"approve the package {args.pack_id}") as who:
            print(sv.frameworks.approve(args.pack_id, actor_id=who).why)
    elif c == "validate":
        with _confirmed(args, f"record a validation of {args.pack_id}") as who:
            print(sv.frameworks.validate(args.pack_id, actor_id=who, lawyer=args.by).why)
    elif c == "withdraw":
        print(sv.frameworks.withdraw(args.pack_id, actor_id=actor).why)
    elif c == "reinstate":
        with _confirmed(args, f"reinstate {args.pack_id}") as who:
            print(sv.frameworks.reinstate(args.pack_id, actor_id=who).why)
    elif c == "remove":
        sv.frameworks.remove(args.pack_id, actor_id=actor)
        print(f"removed {args.pack_id}")
    elif c == "export":
        text = sv.frameworks.export(args.pack_id, actor_id=actor)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"written to {args.out}")
        else:
            print(text, end="")
    elif c == "context":
        print(sv.frameworks.context_for(args.matter, actor_id=actor) or "No package applies.")
    return 0


def cmd_model(args: argparse.Namespace) -> int:
    from eli_legal.settings import ENV_FILE

    sv = _services(args)
    c = args.model_cmd
    if c == "show":
        _out(sv.config.current() | {"machine": sv.config.machine()})
        return 0
    if c == "plan":
        sv.ctx.authorizer().require_global(_actor(args), "config.manage")
        by_name = {m.name: str(m.path) for m in sv.config.gguf_models()}
        path = by_name.get(args.model, args.model)
        if not Path(path).is_file():
            raise SystemExit(f"no GGUF file {args.model!r}; see: eli-legal model list")
        _out(
            {"machine": sv.config.machine()["summary"]}
            | sv.config.preview(
                path,
                gguf_context=args.context,
                gguf_gpu_layers=args.gpu_layers,
                gguf_threads=args.threads,
            )
        )
        return 0
    if c == "list":
        sv.ctx.authorizer().require_global(_actor(args), "config.manage")
        found = sv.config.gguf_models()
        print(
            "GGUF models on this machine:"
            if found
            else "No GGUF model was found in ELI's model folders."
        )
        for m in found:
            print(f"  {m.name:60} {m.size / 1e9:6.1f} GB  {m.location}\n    {m.path}")
        if not sv.config.current()["gguf_supported"]:
            print(
                "  (llama.cpp for Python is not installed here, so these cannot run: pip install 'eli-legal[gguf]')"
            )
        try:
            served = sv.config.available_models(sv.ctx.settings.inference_url)
        except EliLegalError:
            served = []
        print(
            f"Model server at {sv.ctx.settings.inference_url}: "
            + (", ".join(served) or "none answered")
        )
        return 0
    model, verifier = args.model, args.verifier
    if args.backend == "gguf":
        by_name = {m.name: str(m.path) for m in sv.config.gguf_models()}
        model = by_name.get(model, model)
        verifier = by_name.get(verifier, verifier)
        if model and not Path(model).is_file():
            raise SystemExit(f"no GGUF file {model!r}; see: eli-legal model list")
    options = {
        k: v
        for k, v in (
            ("gguf_context", args.context),
            ("gguf_gpu_layers", args.gpu_layers),
            ("gguf_threads", args.threads),
        )
        if v is not None
    }
    with _confirmed(args, "change the model") as who:
        current = sv.config.set_model(
            actor_id=who,
            backend=args.backend,
            url=args.url,
            model=model,
            verifier_model=verifier,
            persist_to=ENV_FILE,
            **options,
        )
    print(f"model: {current['active_model_id']}   verifier: {current['active_verifier_id']}")
    return 0


def cmd_gpu(args: argparse.Namespace) -> int:
    from eli_legal.adapters.inference import gpu_runtime, hardware

    c = args.gpu_cmd
    if c == "probe":  # run by the program itself, in a process of its own
        return gpu_runtime.probe(args.folder)
    if c == "status":
        machine = hardware.detect(force=True)
        _out(
            {"machine": machine.as_dict() | {"summary": machine.describe()}} | gpu_runtime.status()
        )
        return 0
    sv = _services(args)
    with _confirmed(args, "install a graphics runtime") as who:
        installed = sv.config.install_gpu_runtime(actor_id=who, wheel=Path(args.file))
    print(installed["summary"])
    return 0


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
    a = s.add_parser("add-live", help="a live official database: eu_cellar or uk_open")
    a.add_argument("kind", choices=["eu_cellar", "uk_open"])
    a.add_argument("--id", dest="source_id", help="the source's identifier (default: the kind)")
    a.add_argument(
        "--terms-reviewed",
        action="store_true",
        help="you have read the database's licence and it permits this use",
    )
    a = s.add_parser("import")
    a.add_argument("source_id")
    a.add_argument("directory")
    s.add_parser(
        "index", help="embed a source's passages for searching by meaning now, not during a run"
    ).add_argument("source_id")

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
    a.add_argument(
        "--framework",
        action="append",
        default=[],
        metavar="PACKAGE",
        help="a law or standards package to apply (repeatable); see: eli-legal framework list",
    )
    a.add_argument(
        "--no-recommended-frameworks",
        action="store_true",
        help="apply only the packages named, not the recommended ones as well",
    )
    a.add_argument(
        "--member",
        action="append",
        help="USER[:ROLE[:PARTY]] someone else on the matter, their role on it, whom they act for",
    )
    a.add_argument("--reviewer", action="append", help="a named reviewer (repeat)")
    a.add_argument("--source", action="append", help="an approved legal source (repeat)")
    s.add_parser("list")
    s.add_parser("show").add_argument("matter")
    for name in ("grant", "revoke"):
        a = s.add_parser(name)
        a.add_argument("matter")
        a.add_argument("user_id")
        if name == "grant":
            a.add_argument("--role", choices=sorted(access.MATTER_ROLES), help="role on the matter")
            a.add_argument("--acts-for", help="the party they act for")
    s.add_parser("people", help="who is on the matter, in which role, reading what").add_argument(
        "matter"
    )
    a = s.add_parser("role", help="change a person's role on the matter, party or clearance")
    a.add_argument("matter")
    a.add_argument("user_id")
    a.add_argument("--role", choices=sorted(access.MATTER_ROLES))
    a.add_argument("--acts-for")
    a.add_argument("--no-party", action="store_true", help="no longer acting for a party")
    a.add_argument(
        "--reads",
        nargs="*",
        choices=[x.value for x in AccessScope],
        help="the material they may read (none given: nothing)",
    )
    a = s.add_parser("reviewers")
    a.add_argument("matter")
    a.add_argument("user_id", nargs="+")
    a = s.add_parser("sources")
    a.add_argument("matter")
    a.add_argument("source_id", nargs="*")
    a = s.add_parser("frameworks", help="show, or set, the law and standards packages applied")
    a.add_argument("matter")
    a.add_argument("pack_id", nargs="*")
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
    a = s.add_parser(
        "hold", help="put a run on hold while it waits for review, or suspend an approved one"
    )
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
    p.add_argument(
        "--action",
        required=True,
        choices=["exclude", "waive", "lift"],
        help="lift: release a run a person put on hold",
    )
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

    a = s.add_parser(
        "aware", help="when the provider or deployer became aware (Art. 73 counts from it)"
    )
    a.add_argument("matter")
    a.add_argument("incident")
    a.add_argument("--aware-at", required=True, help="date and time, e.g. 2026-11-14T09:30+00:00")
    a.add_argument("--basis", required=True, help="how it became known")
    a.add_argument("--aware-by", help="who became aware, if not you")
    a.add_argument("--occurred-at", help="when it happened, if known")
    a = s.add_parser("assign", help="the incident's owner and a different stand-in")
    a.add_argument("matter")
    a.add_argument("incident")
    a.add_argument("--owner", required=True)
    a.add_argument("--backup", required=True)

    a = s.add_parser("report", help="decide whether a serious incident is reportable (Art. 73)")
    a.add_argument("matter")
    a.add_argument("incident")
    a.add_argument("--reportable", choices=["yes", "no"], required=True)
    a.add_argument("--reason", required=True)
    a.add_argument("--kind", default="general", choices=["general", "death", "widespread"])
    a.add_argument("--reported-on", help="the date it was reported, if it was")
    a.add_argument("--reference", default="")

    p = add("preserve", cmd_preserve, "preservation holds: keep a matter's content from deletion")
    s = p.add_subparsers(dest="preserve_cmd", required=True)
    s.add_parser("list").add_argument("matter")
    a = s.add_parser("place", help="keep the whole matter, or named documents, from deletion")
    a.add_argument("matter")
    a.add_argument("--basis", required=True, help="what requires it: the order, claim, notice")
    a.add_argument("--authority", required=True, help="on whose authority")
    a.add_argument("--document", action="append", help="a document id; repeat; none = all")
    a.add_argument("--review-by", help="the date to review whether it is still needed")
    a = s.add_parser("release", help="end a hold (the legal or data-protection owner)")
    a.add_argument("matter")
    a.add_argument("hold")
    a.add_argument("--reason", required=True)

    p = add("reliance", cmd_reliance, "approved reports suspended from reliance")
    s = p.add_subparsers(dest="reliance_cmd", required=True)
    s.add_parser("list").add_argument("matter")
    a = s.add_parser(
        "resolve",
        help="end a suspension: the law confirmed again for the report, or a later approved run "
        "that replaces it",
    )
    a.add_argument("matter")
    a.add_argument("block")
    a.add_argument("--basis", required=True, help="the legal status found, by whom, from where")
    a.add_argument("--superseded-by", help="a later run, re-checked and approved, that replaces it")

    p = add("network", cmd_network, "hard offline: the kernel refuses every network connection")
    s = p.add_subparsers(dest="network_cmd", required=True)
    s.add_parser("status")
    s.add_parser("offline", help="switch hard offline on now, until the program exits")
    s.add_parser("at-start", help="start hard offline every time (or not)").add_argument(
        "state", choices=["on", "off"]
    )

    p = add("status", cmd_status, "where a matter stands and what to do next")
    p.add_argument("matter", nargs="?")

    p = add("compliance", cmd_compliance, "the organisation's compliance work")
    s = p.add_subparsers(dest="compliance_cmd", required=True)
    s.add_parser("show", help="where each requirement stands").add_argument(
        "--all", action="store_true", help="include those met by the software alone"
    )
    s.add_parser("actions", help="what the organisation must do, and where each stands")
    s.add_parser("form", help="the questions of an action, as JSON to fill in").add_argument(
        "action"
    )
    a = s.add_parser("record", help="record an action as done, or as not applying")
    a.add_argument("action")
    a.add_argument("--answers", help="a JSON file of answers to the action's form")
    a.add_argument("--confirm", action="store_true", help="confirm the action's statement")
    a.add_argument("--notes")
    a.add_argument("--reference", help="a registration number, or where a document is kept")
    a.add_argument("--not-applicable", action="store_true")
    a = s.add_parser("retention", help="how long the audit trail and closed matters are kept")
    a.add_argument("--audit-days", type=int, required=True)
    a.add_argument("--closed-days", type=int, required=True)
    a = s.add_parser("training", help="list training records, or record one")
    a.add_argument("user_id", nargs="?")
    a.add_argument("--course", default="AI literacy and the instructions for use")
    a.add_argument("--completed", default=date.today().isoformat())
    a.add_argument("--expires")
    s.add_parser("evaluate", help="run the accuracy evaluation on the planted-defect matter")
    s.add_parser("draft", help="draft the Annex IV documentation or the declaration").add_argument(
        "kind", choices=["annex_iv", "declaration"]
    )
    a = s.add_parser("sign-off", help="sign off a drafted document by its SHA-256")
    a.add_argument("action", choices=["OA-05", "OA-12"])
    a.add_argument("--sha256", required=True)

    p = add("evaluate", cmd_evaluate, "measure legal research and fact linking on benchmarks")
    p.add_argument("benchmark", nargs="?", choices=["research", "linking", "all"], default="all")
    p.add_argument(
        "--embedding", default="", help="an embedding GGUF to measure; the configured one if not"
    )
    p.add_argument("--json", action="store_true")

    p = add("checks", cmd_checks, "run or show the routine checks")
    s = p.add_subparsers(dest="checks_cmd", required=True)
    a = s.add_parser("run")
    a.add_argument(
        "--as-system",
        action="store_true",
        help="run as the system's schedule does (for cron or a timer), without signing in",
    )
    s.add_parser("show")

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
    p.add_argument(
        "--gguf", metavar="FILE", help="a GGUF model file to run in process with llama.cpp"
    )
    p.add_argument(
        "--gguf-context", type=int, default=0, help="0 sizes it to the model and this machine"
    )
    p.add_argument(
        "--gguf-gpu-layers", type=int, default=-1, help="-1 as many as fit, 0 the processor only"
    )

    p = add(
        "framework", cmd_framework, "law and standards packages: list, inspect, import, approve"
    )
    s = p.add_subparsers(dest="framework_cmd", required=True)
    s.add_parser("list")
    s.add_parser("show").add_argument("pack_id")
    a = s.add_parser("import", help="a JSON package, a CSV register, or a document of rules")
    a.add_argument("file")
    a.add_argument("--title", default="")
    a.add_argument("--id", dest="pack_id", default="")
    a.add_argument("--issuer", default="")
    a.add_argument("--version", dest="pack_version", default="1")
    s.add_parser("approve").add_argument("pack_id")
    a = s.add_parser("current", help="record that you checked a package against its official text")
    a.add_argument("pack_id")
    a.add_argument("--note", required=True, help="the text checked against")
    a.add_argument("--checked-on", default=date.today().isoformat())
    a = s.add_parser("validate", help="record a qualified lawyer's validation of a package")
    a.add_argument("pack_id")
    a.add_argument("--by", required=True, help="the lawyer's name")
    s.add_parser("withdraw").add_argument("pack_id")
    s.add_parser("reinstate").add_argument("pack_id")
    s.add_parser("remove").add_argument("pack_id")
    a = s.add_parser("export")
    a.add_argument("pack_id")
    a.add_argument("--out")
    s.add_parser("context", help="what the model is told on a matter").add_argument("matter")

    p = add("bundle", cmd_bundle, "make this copy available to ELI v3 as a bundle")
    s = p.add_subparsers(dest="bundle_cmd", required=True)
    s.add_parser("show")
    register = s.add_parser("register")
    register.add_argument(
        "--if-eli-v3", action="store_true", help="only if ELI v3 is on this machine (installers)"
    )
    unregister = s.add_parser("unregister")
    unregister.add_argument(
        "--this-copy", action="store_true", help="only if ELI v3's record names this copy"
    )
    for one in (register, unregister):
        one.add_argument("--into", help="ELI v3's bundles folder, if not the usual one")

    p = add("licence", cmd_licence, "this copy's licence: show it, activate a key, remove it")
    s = p.add_subparsers(dest="licence_cmd")
    s.add_parser("status")
    s.add_parser("activate").add_argument(
        "key", help="an ELI Legal key, or an ELI v3 key that includes it"
    )
    s.add_parser("remove")

    p = add("model", cmd_model, "show, find or choose the model")
    s = p.add_subparsers(dest="model_cmd", required=True)
    s.add_parser("show")
    s.add_parser("list", help="GGUF models found on this machine, and a model server's models")
    a = s.add_parser("use", help="choose a GGUF file, a server model, ELI v3's model, or none")
    a.add_argument("backend", choices=["gguf", "openai_compat", "eli_v3", "none"])
    a.add_argument(
        "model",
        nargs="?",
        default="",
        help="GGUF file (path or name from 'model list'), or a server's model name",
    )
    a.add_argument("--verifier", default="")
    a.add_argument("--url", default="")
    b = s.add_parser("plan", help="how a GGUF file would be placed on this machine, and why")
    b.add_argument("model", help="GGUF file (path or name from 'model list')")
    for one in (a, b):
        one.add_argument(
            "--context", type=int, help="tokens; 0 sizes it to the model and this machine"
        )
        one.add_argument(
            "--gpu-layers", type=int, help="-1 as many as fit, 0 the processor only, n at most n"
        )
        one.add_argument("--threads", type=int, help="0 chooses for you")

    p = add("gpu", cmd_gpu, "the graphics card and the llama.cpp that uses it")
    s = p.add_subparsers(dest="gpu_cmd", required=True)
    s.add_parser("status", help="this machine, the llama.cpp in use, the graphics packs found")
    a = s.add_parser("install", help="install a graphics pack from a file on this machine")
    a.add_argument("file", help="cuda-… or vulkan-llama_cpp_python-….whl, as published with ELI")
    s.add_parser("probe").add_argument("folder")
    return parser


_UNLICENSED_COMMANDS = {"licence", "bundle"}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        # A console that cannot show a character (common on Windows) must not stop the program.
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    if args.command != "bundle":
        from eli_legal import bundle

        bundle.refresh_registration()  # ELI v3 opens the newest copy on this machine
    if args.command not in _UNLICENSED_COMMANDS:
        from eli_legal import licensing

        if not licensing.allowed():
            print(licensing.explain(), file=sys.stderr)
            return 3
    if args.command != "serve" and Settings().hard_offline:
        from eli_legal.security import hard_offline

        hard_offline.go_offline()
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
