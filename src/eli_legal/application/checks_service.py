"""Routine checks: is everything still valid, correct and up to date?

A run checks the law as it stood when the run was made. The law moves on, sources age, files
can be altered on disk, people's training lapses and a closed matter's content outlives its
retention period. These checks look at all of that on a schedule (daily by default, and when
someone asks), say what they found in plain words with what to do about it, and act where acting
is safe and certain:

- an authority relied on in an *approved* report that is no longer good law opens an incident,
  because someone may already be relying on that report;
- a stored original whose bytes no longer match its hash opens an incident;
- a closed matter's content is deleted when its retention period ends.

Everything else is reported for a person to decide. Every run of the checks, and every action
it takes, is written to the audit trail under the actor ``system`` or the person who asked.

The results never disclose a matter's content to someone who is not on it: they read "a matter
you are not on" and the kind of problem, nothing more.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from eli_legal.application import archive_service
from eli_legal.application.compliance_service import ComplianceService, Retention
from eli_legal.application.container import AppContext
from eli_legal.application.incident_service import needs_escalation, reporting_deadline
from eli_legal.application.ingestion_service import READER_VERSION
from eli_legal.application.preservation_service import PreservationHeld, active_holds, dispose
from eli_legal.application.reliance_service import no_longer_confirmed, open_or_extend
from eli_legal.domain import plain
from eli_legal.domain.enums import (
    ClaimKind,
    ClaimStatus,
    IncidentSeverity,
    MatterStatus,
    RunStatus,
)
from eli_legal.domain.errors import InvalidInput
from eli_legal.domain.models import (
    Claim,
    Document,
    Hold,
    Incident,
    Matter,
    Run,
    new_id,
    utcnow,
)
from eli_legal.governance.registers import check_registers
from eli_legal.governance.retention import CONTENT, KINDS
from eli_legal.persistence.connect import ENCRYPTION_AVAILABLE
from eli_legal.security import access, authn

log = logging.getLogger("eli_legal.checks")
RUNS = "routine_check_run"
KEEP_RUNS = 60
SYSTEM = "system"
_RELIED = (ClaimKind.PARTY_AUTHORITY, ClaimKind.LEGAL_PROPOSITION)
_APPROVED = (RunStatus.APPROVED_FOR_RELIANCE,)
_OLD_HOLD_DAYS = 14
_CHANGED = "authority_changed_after_approval"


@dataclass(slots=True)
class CheckItem:
    text: str  # for someone who may see the matter (or for anyone, if it concerns none)
    matter_id: str = ""
    general: str = ""  # what anyone else is told: no content, just the kind of problem


@dataclass(slots=True)
class CheckResult:
    check_id: str
    title: str
    state: str  # ok | attention | failed | could_not_run
    summary: str
    what_to_do: str = ""
    items: list[CheckItem] = field(default_factory=list)
    acted: list[str] = field(default_factory=list)  # what the check itself did


@dataclass(slots=True)
class CheckRun:
    started_at: datetime
    actor_id: str
    results: list[CheckResult]
    run_id: str = field(default_factory=lambda: new_id("chk"))
    finished_at: datetime | None = None

    @property
    def state(self) -> str:
        order = ("failed", "could_not_run", "attention", "ok")
        states = {r.state for r in self.results}
        return next((s for s in order if s in states), "ok")

    @property
    def headline(self) -> str:
        bad = [r for r in self.results if r.state != "ok"]
        if not bad:
            return f"All {len(self.results)} routine checks are clear."
        return (
            f"{plain.count(len(bad), 'check')} of {len(self.results)} "
            f"need{'s' if len(bad) == 1 else ''} attention: "
            + ", ".join(r.title for r in bad)
            + "."
        )


class ChecksService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    # ── running ──────────────────────────────────────────────────────────────
    def due(self, now: datetime | None = None) -> bool:
        """Whether a scheduled run is due. With the schedule switched off (0 hours) nothing is
        ever due on its own; people can still run the checks."""
        if self.ctx.settings.checks_every_hours <= 0:
            return False
        last = self.latest()
        if last is None or last.finished_at is None:
            return True
        hours = self.ctx.settings.checks_every_hours
        return (now or utcnow()) - last.finished_at >= timedelta(hours=hours)

    def _encryption(self, actor_id: str, today: date) -> CheckResult:
        """Whether the working database and the audit ledger are encrypted at rest."""
        plain = [
            name
            for name, part in (
                ("the working database", self.ctx.store),
                ("the audit ledger", self.ctx.audit),
            )
            if not getattr(part, "encrypted", False)
        ]
        if not plain:
            return CheckResult(
                "encryption",
                "Encryption at rest",
                "ok",
                "The working database and the audit ledger are encrypted (SQLCipher, AES-256); "
                "their key is kept in the secrets folder.",
            )
        why = (
            "SQLCipher is not installed in this copy of ELI Legal"
            if not ENCRYPTION_AVAILABLE
            else "they could not be converted when ELI Legal started (Record of actions: "
            "database_encrypted says why)"
        )
        return CheckResult(
            "encryption",
            "Encryption at rest",
            "attention",
            f"The databases are not encrypted: {' and '.join(plain)} ({why}).",
            "Use an installed copy of ELI Legal (it includes SQLCipher), or install "
            "sqlcipher3-wheels; then start ELI Legal with nothing else using its data, and it "
            "converts them. Until then, keep the data folder on an encrypted disk.",
        )

    def run(self, *, actor_id: str = SYSTEM, today: date | None = None) -> CheckRun:
        """Run every check. The system runs them on its schedule; a person who asks needs the
        right to run them."""
        if actor_id != SYSTEM:
            authn.require(actor_id)
            self.ctx.authorizer().require_global(actor_id, "checks.run")
        today = today or utcnow().date()
        run = CheckRun(started_at=utcnow(), actor_id=actor_id, results=[])
        for check in (
            self._audit_chain,
            self._encryption,
            self._registers,
            self._authorities,
            self._law_packages,
            self._sources,
            self._originals,
            self._compliance,
            self._people,
            self._training,
            self._retention,
            self._open_work,
        ):
            try:
                run.results.append(check(actor_id, today))
            except Exception as exc:  # one broken check must not hide the others
                run.results.append(
                    CheckResult(
                        check.__name__.strip("_"),
                        check.__name__.strip("_").replace("_", " ").capitalize(),
                        "could_not_run",
                        f"The check could not run: {type(exc).__name__}: {exc}",
                        "Tell the technical administrator.",
                    )
                )
        run.finished_at = utcnow()
        self.ctx.store.put_registry(RUNS, f"{run.started_at.isoformat()}_{run.run_id}", run)
        for old in self.history()[KEEP_RUNS:]:
            self.ctx.store.delete_registry(RUNS, f"{old.started_at.isoformat()}_{old.run_id}")
        self.ctx.log(
            "routine_check",
            actor_id=actor_id,
            matter_id="-",
            action="checks.run",
            subject_id=run.run_id,
            outcome="ok" if run.state == "ok" else "attention",
            object_type="routine_check",
            payload={r.check_id: r.state for r in run.results}
            | {"acted": sum(len(r.acted) for r in run.results)},
        )
        return run

    def start_schedule(self, *, poll_seconds: float = 1800.0) -> threading.Event:
        """Run the checks whenever they fall due, on a thread of their own, until the returned
        event is set. For a long-running server; the desktop application has its own timer.
        A check that cannot run is reported in its result, never raised here."""
        stop = threading.Event()

        def loop() -> None:
            while not stop.is_set():
                try:
                    if self.due():
                        self.run()
                except Exception:  # the next poll tries again; the failure is in the log
                    log.exception("routine checks could not run")
                stop.wait(poll_seconds)

        if self.ctx.settings.checks_every_hours > 0:
            threading.Thread(target=loop, name="eli-legal-checks", daemon=True).start()
        return stop

    def history(self) -> list[CheckRun]:
        return sorted(
            self.ctx.store.list_registry(RUNS, CheckRun), key=lambda r: r.started_at, reverse=True
        )

    def latest(self) -> CheckRun | None:
        runs = self.history()
        return runs[0] if runs else None

    def for_viewer(self, run: CheckRun, *, actor_id: str) -> list[CheckResult]:
        """The results as this person may read them: an item about a matter they are not on is
        replaced by its general description."""
        authn.require(actor_id)
        authz = self.ctx.authorizer()
        mine: dict[str, bool] = {}

        def visible(matter_id: str) -> bool:
            if matter_id not in mine:
                matter = self.ctx.store.get_matter(matter_id)
                mine[matter_id] = matter is not None and authz.can_matter(
                    matter, actor_id, "matter.read"
                )
            return mine[matter_id]

        out = []
        for r in run.results:
            items = [
                i
                if not i.matter_id or visible(i.matter_id)
                else CheckItem(
                    text=f"{access.WITHHELD} a matter you are not on "
                    f"({plain.short_id(i.matter_id)}): {i.general or 'needs attention'}",
                    matter_id=i.matter_id,
                    general=i.general,
                )
                for i in r.items
            ]
            out.append(
                CheckResult(r.check_id, r.title, r.state, r.summary, r.what_to_do, items, r.acted)
            )
        return out

    def confirm_law_current(
        self, pack_id: str, *, actor_id: str, checked_on: date, note: str
    ) -> None:
        """Record that a named person checked a law package's summary against the official
        text on a date. Restarts the clock on that package's review."""
        authn.require_step_up(actor_id, "confirm a law package is current")
        self.ctx.authorizer().require_global(actor_id, "framework.manage")
        pack = self.ctx.frameworks.require(pack_id)
        if len(note.strip()) < 10:
            raise InvalidInput("say what was checked and against which text")
        if checked_on > utcnow().date():
            raise InvalidInput("a check cannot be dated in the future")
        record = {
            "pack_id": pack.pack_id,
            "fingerprint": pack.fingerprint,
            "checked_on": checked_on.isoformat(),
            "checked_by": actor_id,
            "note": note.strip(),
        }
        self.ctx.store.put_registry("law_currency", pack.pack_id, _Currency(**record))
        self.ctx.log(
            "law_currency_confirmed",
            actor_id=actor_id,
            matter_id="-",
            action="framework.manage",
            subject_id=pack.pack_id,
            outcome="confirmed",
            object_type="framework",
            payload={"checked_on": record["checked_on"], "fingerprint": pack.fingerprint},
        )

    def law_checked_on(self, pack_id: str) -> tuple[date | None, str]:
        """When a package was last checked against the official text, and by whom."""
        confirmed = self.ctx.store.get_registry("law_currency", pack_id, _Currency)
        pack = self.ctx.frameworks.get(pack_id)
        as_at = _date(pack.as_at) if pack else None
        checked = _date(confirmed.checked_on) if confirmed is not None else None
        if confirmed is not None and checked is not None and (as_at is None or checked >= as_at):
            return checked, confirmed.checked_by
        return as_at, "the package's own date"

    # ── the checks ───────────────────────────────────────────────────────────
    def _open_matters(self) -> list[Matter]:
        return [m for m in self.ctx.store.list_matters() if m.status is not MatterStatus.CLOSED]

    def _audit_chain(self, actor_id: str, today: date) -> CheckResult:
        report = self.ctx.audit.report()
        if report.ok:
            return CheckResult(
                "audit_chain",
                "Audit trail intact",
                "ok",
                f"All {report.count} events are present, in order and unaltered.",
            )
        return CheckResult(
            "audit_chain",
            "Audit trail intact",
            "failed",
            f"The audit trail does not verify: {report.error}.",
            "Stop relying on any output until the cause is found; compare with your last "
            "exported checkpoint and open an incident.",
        )

    def _registers(self, actor_id: str, today: date) -> CheckResult:
        problems = check_registers(None)
        if not problems:
            return CheckResult(
                "registers",
                "Governance registers consistent",
                "ok",
                "Every control points at code that exists and every requirement, risk and "
                "organisation action links up.",
            )
        return CheckResult(
            "registers",
            "Governance registers consistent",
            "failed",
            f"{plain.count(len(problems), 'problem')} in the registers that ship with this copy.",
            "This copy may have been altered. Reinstall it, or tell the provider.",
            [CheckItem(p) for p in problems[:20]],
        )

    def _authorities(self, actor_id: str, today: date) -> CheckResult:
        """Is every authority relied on still good law, judged exactly as a run would judge it
        today? In each matter's latest run, and in every report approved for reliance, however
        old: a report released earlier may still be relied on after a later run (EL-001)."""
        items: list[CheckItem] = []
        acted: list[str] = []
        checked = 0
        for matter in self._open_matters():
            runs = self.ctx.store.list(Run, matter.matter_id)
            if not runs:
                continue
            latest = runs[-1]
            looked = [r for r in runs if r.status in _APPROVED]
            if latest not in looked:
                looked.append(latest)
            for run in looked:
                approved = run.status in _APPROVED
                flagged = no_longer_confirmed(self.ctx, matter, run)
                if flagged is None:
                    break
                checked += sum(
                    1
                    for c in self.ctx.store.list(Claim, matter.matter_id, run_id=run.run_id)
                    if c.kind in _RELIED and c.status is ClaimStatus.VERIFIED and c.authority_id
                )
                if not flagged:
                    continue
                where = (
                    (
                        "the latest approved report"
                        if run is latest
                        else "an earlier approved report"
                    )
                    if approved
                    else "the latest run"
                )
                for f in flagged.values():
                    items.append(
                        CheckItem(
                            f"{f.authority.citation}, relied on in {where} of “{matter.name}” "
                            f"({plain.count(len(f.claim_ids), 'finding')}): {f.said}",
                            matter.matter_id,
                            "an authority relied on is no longer confirmed as good law",
                        )
                    )
                if not approved:
                    continue
                block, changed = open_or_extend(self.ctx, matter, run, flagged)
                if changed:
                    told = (
                        f" {plain.count(len(block.recipient_ids), 'recipient')} already received "
                        "it and should be told."
                        if block.recipient_ids
                        else ""
                    )
                    acted.append(
                        f"Suspended reliance on an approved report of matter "
                        f"{plain.short_id(matter.matter_id)} and opened an incident: an authority "
                        f"it relies on is no longer confirmed as good law.{told}"
                    )
        if not items:
            return CheckResult(
                "authorities",
                "Authorities still good law",
                "ok",
                f"All {plain.count(checked, 'authority', 'authorities')} relied on in the latest "
                "runs and approved reports are still confirmed as good law.",
            )
        return CheckResult(
            "authorities",
            "Authorities still good law",
            "attention",
            f"{plain.count(len(items), 'authority', 'authorities')} relied on "
            f"{'is' if len(items) == 1 else 'are'} no longer confirmed as good law.",
            "For a report not yet approved, run the matter again before review. An approved "
            "report is suspended from reliance until a named reviewer confirms the law again or "
            "approves a new run that replaces it; see the incident, and tell whoever received it.",
            items,
            acted,
        )

    def _law_packages(self, actor_id: str, today: date) -> CheckResult:
        """Is each law package in use recent enough, and has anything in the law calendar come
        into application since it was summarised?"""
        days = self.ctx.settings.law_review_days
        in_use = {i for m in self._open_matters() for i in m.framework_ids}
        calendar = _calendar(self.ctx.settings.law_calendar_file)
        items: list[CheckItem] = []
        for pack_id in sorted(in_use):
            pack = self.ctx.frameworks.get(pack_id)
            if pack is None:
                continue
            checked_on, by = self.law_checked_on(pack_id)
            if checked_on is None:
                items.append(
                    CheckItem(f"{pack.title}: no date of checking against the official text.")
                )
            elif (today - checked_on).days > days:
                items.append(
                    CheckItem(
                        f"{pack.title}: last checked against the official text on "
                        f"{checked_on.isoformat()} ({by}), more than {days} days ago."
                    )
                )
            for entry in calendar:
                if entry.get("pack_id") != pack_id:
                    continue
                when = _date(entry["date"])
                if when is None:
                    continue
                if checked_on is not None and checked_on < when <= today:
                    items.append(
                        CheckItem(
                            f"{pack.title}: since it was last checked ({checked_on.isoformat()}), "
                            f"{entry['what']} (from {when.isoformat()})"
                        )
                    )
                elif today < when <= today + timedelta(days=days):
                    items.append(
                        CheckItem(
                            f"{pack.title}: from {when.isoformat()}, {entry['what']} "
                            f"({(when - today).days} days from now)"
                        )
                    )
        if not items:
            return CheckResult(
                "law_packages",
                "Law and standards up to date",
                "ok",
                f"Every package in use was checked against its official text within {days} days, "
                "and nothing in the law calendar is due.",
            )
        return CheckResult(
            "law_packages",
            "Law and standards up to date",
            "attention",
            f"{plain.count(len(items), 'point')} about the law and standards in use.",
            "Check each package against its official text (Laws and standards → the package → "
            "'Confirm checked against the official text'), and update it if the law has changed.",
            items,
        )

    def _sources(self, actor_id: str, today: date) -> CheckResult:
        """How old is the status information in each approved source in use?"""
        in_use: dict[str, list[Matter]] = {}
        for m in self._open_matters():
            for sid in m.approved_source_ids:
                in_use.setdefault(sid, []).append(m)
        items: list[CheckItem] = []
        now = utcnow()
        for sid in sorted(in_use):
            source = self.ctx.sources.get(sid)
            if source is None or not source.approved:
                items.append(
                    CheckItem(f"Source {sid} is used by a matter but is no longer approved.")
                )
                continue
            stale = 0
            total = 0
            for authority in self.ctx.store.list_authorities([sid]):
                total += 1
                pack = self.ctx.jurisdictions.get(authority.jurisdiction)
                limit = pack.status_max_age_days if pack else 365
                checked = authority.status_checked_at
                if checked is None or (now - checked).days > limit:
                    stale += 1
            if stale:
                items.append(
                    CheckItem(
                        f"{source.name}: the status of {stale} of {total} authorities was last "
                        "confirmed too long ago to be relied on without a person checking."
                    )
                )
        if not items:
            return CheckResult(
                "sources",
                "Legal sources current",
                "ok",
                f"The status information in the {plain.count(len(in_use), 'source')} in use is "
                "recent enough to rely on.",
            )
        return CheckResult(
            "sources",
            "Legal sources current",
            "attention",
            f"{plain.count(len(items), 'source')} in use {'has' if len(items) == 1 else 'have'} "
            "status information too old to rely on.",
            "Import a current copy of the source (Sources → Import), then run affected matters "
            "again.",
            items,
        )

    def _originals(self, actor_id: str, today: date) -> CheckResult:
        """Are the stored originals still exactly the bytes that were filed?"""
        items: list[CheckItem] = []
        acted: list[str] = []
        count = 0
        for matter in self._open_matters():
            for document in self.ctx.store.list(Document, matter.matter_id):
                if not document.vault_ref:
                    continue
                count += 1
                if self.ctx.vault.verify(matter.matter_id, document.sha256):
                    continue
                items.append(
                    CheckItem(
                        f"“{document.title or document.filename}” in “{matter.name}” no longer "
                        "matches the bytes that were filed (missing or altered).",
                        matter.matter_id,
                        "a stored original is missing or altered",
                    )
                )
                incident = Incident(
                    matter_id=matter.matter_id,
                    run_id=None,
                    category="original_altered",
                    detail=f"stored original {document.sha256[:12]} is missing or altered",
                    created_by=SYSTEM,
                    severity=IncidentSeverity.SERIOUS,
                )
                already = any(
                    i.category == "original_altered" and document.sha256[:12] in i.detail
                    for i in self.ctx.store.list(Incident, matter.matter_id)
                    if i.status == "open"
                )
                if not already:
                    self.ctx.store.put(incident)
                    self.ctx.log(
                        "incident_opened",
                        actor_id=SYSTEM,
                        matter_id=matter.matter_id,
                        action="incident.manage",
                        subject_id=incident.incident_id,
                        outcome="open",
                        object_type="incident",
                        payload={
                            "category": incident.category,
                            "severity": incident.severity.value,
                            "affected_findings": 0,
                        },
                    )
                    acted.append(
                        f"Opened a serious incident on matter {plain.short_id(matter.matter_id)}: "
                        "a stored original is missing or altered."
                    )
        if not items:
            return CheckResult(
                "originals",
                "Stored documents unaltered",
                "ok",
                f"All {plain.count(count, 'stored original')} match the bytes that were filed.",
            )
        return CheckResult(
            "originals",
            "Stored documents unaltered",
            "failed",
            f"{plain.count(len(items), 'stored original')} no longer match what was filed.",
            "Do not rely on findings from these documents. Restore the originals from backup and "
            "investigate how they changed; the incident records it.",
            items,
            acted,
        )

    def _compliance(self, actor_id: str, today: date) -> CheckResult:
        overview = ComplianceService(self.ctx).status(today=today)
        outstanding = [a for a in overview.actions if a.state in ("waiting", "review_due")]
        if not outstanding:
            return CheckResult(
                "compliance",
                "Organisation's compliance work",
                "ok",
                overview.headline,
            )
        due = [a for a in outstanding if a.state == "review_due"]
        return CheckResult(
            "compliance",
            "Organisation's compliance work",
            "attention",
            overview.headline,
            "Open Governance → Compliance and record each action, or record why it does not apply.",
            [
                CheckItem(f"{a.action.action_id} {a.action.title}: {a.detail}")
                for a in sorted(outstanding, key=lambda a: (a not in due, a.action.action_id))
            ],
        )

    def _training(self, actor_id: str, today: date) -> CheckResult:
        """The organisation's own models: any that may no longer be used, any waiting for a
        person, and autonomous mode's step (it trains and checks; a person approves)."""
        from eli_legal.application.training_service import TrainingService
        from eli_legal.domain.errors import InvalidState

        training = TrainingService(self.ctx)
        policy = training.policy()
        if not policy.enabled and not training.models():
            return CheckResult(
                "training", "Training the organisation's model", "ok", "Training is off."
            )
        acted: list[str] = []
        if policy.enabled and policy.mode == "autonomous":
            step = training.autonomous_step()
            acted += [str(d) for d in step.get("did") or []]
        items: list[CheckItem] = []
        in_use = str(self.ctx.settings.inference_model or "")
        for m in training.models():
            if m.status in ("approved", "candidate"):
                try:
                    training._sources_allowed(m)
                    blocked = (
                        "trained on cases since erased or withdrawn" if m.erased_sources else ""
                    )
                except InvalidState as exc:
                    blocked = str(exc)
                if blocked:
                    using = " It is in use: choose another model in Settings." if (
                        in_use and m.gguf_path and Path(in_use).resolve() == Path(m.gguf_path).resolve()
                    ) else ""  # fmt: skip
                    items.append(CheckItem(
                        f"{m.name} ({m.model_id}) may no longer be used: {blocked}. Retire it.{using}"
                    ))  # fmt: skip
                    continue
            if m.status == "candidate":
                verdict = "its checks support approval" if (m.evaluation or {}).get(
                    "supports_approval") else "its checks do not support approval"  # fmt: skip
                items.append(CheckItem(
                    f"{m.name} ({m.model_id}) is waiting for the compliance officer: {verdict}."
                ))  # fmt: skip
        waiting = sum(v for k, v in training.counts().items() if k.startswith("candidate"))
        if waiting:
            items.append(CheckItem(f"{waiting} training examples are waiting for a lawyer."))
        summary = (
            f"Training is {'on (' + policy.mode + ')' if policy.enabled else 'off'}; "
            f"{len(training.models())} model(s) trained."
        )
        return CheckResult(
            "training",
            "Training the organisation's model",
            "attention" if items else "ok",
            summary,
            "Open Set-up → Train your own model." if items else "",
            items,
            acted,
        )

    def _people(self, actor_id: str, today: date) -> CheckResult:
        items: list[CheckItem] = []
        untrained = set(ComplianceService(self.ctx).untrained(today))
        reviewers = {u for m in self._open_matters() for u in m.reviewer_user_ids}
        for user in self.ctx.store.list_users():
            if not user.active:
                continue
            if not user.passphrase_hash:
                items.append(CheckItem(f"{user.display_name} ({user.user_id}) has no passphrase."))
            state = self.ctx.store.auth_state(user.user_id)
            if state["locked_until"] and state["locked_until"] > utcnow():
                items.append(CheckItem(f"{user.display_name} ({user.user_id}) is locked out."))
            if user.user_id in reviewers and user.user_id in untrained:
                items.append(
                    CheckItem(
                        f"{user.display_name} ({user.user_id}) is a named reviewer with no "
                        "current training record."
                    )
                )
            if user.user_id in reviewers and not state["totp_secret"]:
                items.append(
                    CheckItem(
                        f"{user.display_name} ({user.user_id}) is a named reviewer without a "
                        "second factor."
                    )
                )
        if not items:
            return CheckResult(
                "people", "People and sign-in", "ok", "Every account is ready and secured."
            )
        return CheckResult(
            "people",
            "People and sign-in",
            "attention",
            f"{plain.count(len(items), 'point')} about people and sign-in.",
            "Settings → Users and roles: set passphrases, unlock accounts; Governance → "
            "Compliance: record training; ask reviewers to set up a second factor.",
            items,
        )

    def _retire(
        self,
        matter: Matter,
        retention: Retention | None,
        today: date,
        acted: list[str],
        items: list[CheckItem],
    ) -> None:
        """Each kind of a closed matter's content goes when its own period ends: its archive's key
        destroyed, or the kind deleted from the working database. A preservation hold keeps it.
        The decision record goes last, once nothing it accounts for is left."""
        mid = matter.matter_id
        short = plain.short_id(mid)
        closed = matter.closed_at.date() if matter.closed_at else today
        whose = "this matter's" if matter.retention_days is not None else "the organisation's"

        def days(kind: str) -> int | None:
            if retention is not None:
                return retention.days_for(kind, matter)
            return None if kind == "record" else matter.retention_days

        due: list[str] = []
        periods: dict[str, int] = {}
        for kind in CONTENT:
            d = days(kind.code)
            if d is not None and closed + timedelta(days=d) <= today:
                due.append(kind.code)
                periods[kind.code] = d

        def period(codes: list[str]) -> str:
            spans = sorted({periods[c] for c in codes})
            ended = max(closed + timedelta(days=periods[c]) for c in codes)
            return (
                f"{'/'.join(map(str, spans))}-day retention ({whose}) ended on {ended.isoformat()}"
            )

        archived = [k for k in due if self.ctx.archive.has(mid, k)]
        live = [
            k for k in due if k not in archived and archive_service.live(self.ctx, matter, KINDS[k])
        ]

        def names(codes: list[str]) -> str:
            return ", ".join(KINDS[c].name.lower() for c in codes)

        if archived:
            try:
                archive_service.destroy(
                    self.ctx, matter, actor_id=SYSTEM, kinds=archived, event="retention_purge",
                    why=f"{whose} retention of {'/'.join(str(periods[c]) for c in archived)} "
                    f"days ended: {', '.join(archived)}",
                )  # fmt: skip
                acted.append(
                    f"Destroyed the archived {names(archived)} of a closed matter ({short}) whose "
                    f"{period(archived)}: their keys are gone, so no copy can be read."
                )
            except PreservationHeld as held:
                items.append(
                    CheckItem(
                        f"A closed matter ({short}) is past its retention for its "
                        f"{names(archived)}, and its archive is kept: {held}",
                        mid,
                        "kept under a preservation hold",
                    )
                )
        if live:
            try:
                counts = dispose(
                    self.ctx, matter, actor_id=SYSTEM, kinds=live, event="retention_purge",
                    why=f"{whose} retention of {'/'.join(str(periods[c]) for c in live)} days "
                    f"ended: {', '.join(live)}",
                )  # fmt: skip
                if any(v for k, v in counts.items() if k != "preserved_documents"):
                    acted.append(
                        f"Deleted the {names(live)} of a closed matter ({short}) whose "
                        f"{period(live)}."
                    )
            except PreservationHeld as held:
                items.append(
                    CheckItem(
                        f"A closed matter ({short}) is past its retention period and kept: {held}",
                        mid,
                        "kept under a preservation hold",
                    )
                )
        record = days("record")
        if record is not None and closed + timedelta(days=record) <= today:
            left = [
                k.code
                for k in CONTENT
                if self.ctx.archive.has(mid, k.code) or archive_service.live(self.ctx, matter, k)
            ]
            if not left and not active_holds(self.ctx, mid):
                archive_service.forget_record(
                    self.ctx, matter, actor_id=SYSTEM,
                    why=f"the decision record's retention of {record} days ended",
                )  # fmt: skip
                acted.append(
                    f"Removed the decision record of a closed matter ({short}) as its "
                    f"{record}-day retention ended; the audit trail keeps what happened."
                )

    def _retention(self, actor_id: str, today: date) -> CheckResult:
        """Delete closed matters' content on time (each matter's own period, else the
        organisation's), keep what a preservation hold covers, and report open matters idle for
        longer than the organisation allows."""
        retention = ComplianceService(self.ctx).retention()
        acted: list[str] = []
        items: list[CheckItem] = []
        for matter in self.ctx.store.list_matters():
            if matter.status is not MatterStatus.CLOSED or matter.closed_at is None:
                continue
            self._retire(matter, retention, today, acted, items)
        idle = self._idle_matters(retention.inactive_matter_days if retention else 0, today)
        items += idle
        if retention is None:
            return CheckResult(
                "retention",
                "Retention",
                "attention",
                "No retention periods are set for the organisation, so only matters given their "
                "own period are deleted on time.",
                "Governance → Compliance → OA-09: set how long the audit trail and a closed "
                "matter's documents are kept.",
                items,
                acted=acted,
            )
        events = self.ctx.audit.report().count
        summary = (
            f"Audit trail kept at least {retention.audit_days} days ({events} events, never "
            f"truncated); closed matters' documents deleted after {retention.closed_matter_days} "
            "days unless a matter sets its own period."
        )
        if idle:
            return CheckResult(
                "retention",
                "Retention",
                "attention",
                summary + f" {plain.count(len(idle), 'open matter')} idle too long.",
                "Close a matter that is finished, so its content goes on time; or record on it "
                "why it stays open.",
                items,
                acted=acted,
            )
        return CheckResult("retention", "Retention", "ok", summary, items=items, acted=acted)

    def _idle_matters(self, days: int, today: date) -> list[CheckItem]:
        """Open matters with no recorded activity for more than ``days`` days."""
        if days <= 0:
            return []
        latest: dict[str, str] = {}
        for event in self.ctx.audit.events():
            mid = event.get("matter_id")
            if mid and mid != "-" and event.get("event_type") != "notification_sent":
                latest[mid] = max(latest.get(mid, ""), str(event.get("created_at", "")))
        out: list[CheckItem] = []
        for matter in self.ctx.store.list_matters():
            if matter.status is MatterStatus.CLOSED:
                continue
            last = latest.get(matter.matter_id) or matter.created_at.isoformat()
            since = (today - datetime.fromisoformat(last).date()).days
            if since > days:
                out.append(
                    CheckItem(
                        f"“{matter.name}” has had no recorded activity for {since} days "
                        f"(the organisation allows {days}).",
                        matter.matter_id,
                        "idle: close it, or record why it stays open",
                    )
                )
        return out

    def _open_work(self, actor_id: str, today: date) -> CheckResult:
        items: list[CheckItem] = []
        acted: list[str] = []
        now = utcnow()
        for matter in self._open_matters():
            mid = matter.matter_id
            old = [
                h
                for h in self.ctx.store.list(Hold, mid, status="open")
                if (now - h.created_at).days > _OLD_HOLD_DAYS
            ]
            if old:
                items.append(
                    CheckItem(
                        f"“{matter.name}”: {plain.count(len(old), 'hold')} open for more than "
                        f"{_OLD_HOLD_DAYS} days.",
                        mid,
                        f"{plain.count(len(old), 'hold')} open for more than {_OLD_HOLD_DAYS} days",
                    )
                )
            # An approved report whose PDFs were read before every page was accounted for may
            # rest on a document with a page silently missing: it needs a new run and review.
            paged = any(d.media_type == "application/pdf"
                        for d in self.ctx.store.list(Document, mid))  # fmt: skip
            for run in self.ctx.store.list(Run, mid):
                if (
                    paged
                    and run.status in _APPROVED
                    and run.tool_versions.get("document_reader") != READER_VERSION
                ):
                    items.append(
                        CheckItem(
                            f"“{matter.name}”: a report approved on PDFs read by an earlier "
                            "version of the reader, which could miss a scanned page or an "
                            "exhibit pasted beside text without a record: run the matter again "
                            "and review the new report.",
                            mid,
                            "an approved report needs review: read before every page was "
                            "accounted for",
                        )
                    )
            for incident in self.ctx.store.list(Incident, mid):
                if incident.status != "open":
                    continue
                deadline = reporting_deadline(incident)
                if needs_escalation(incident, now):
                    # Half the time to report is gone and nobody has decided: the stand-in is
                    # told, once, and it is on the record.
                    def escalate(i: Incident) -> None:
                        i.escalated_at = utcnow()

                    incident = self.ctx.store.change(Incident, mid, incident.incident_id, escalate)
                    self.ctx.log(
                        "incident_escalated",
                        actor_id=SYSTEM,
                        matter_id=mid,
                        action="incident.manage",
                        subject_id=incident.incident_id,
                        outcome="escalated",
                        object_type="incident",
                        payload={
                            "owner": incident.owner_user_id,
                            "backup": incident.backup_user_id,
                            "counted_from": "awareness" if incident.aware_at else "entry",
                        },
                    )
                    acted.append(
                        f"Escalated a serious incident on matter {plain.short_id(mid)} to "
                        f"{incident.backup_user_id or 'the matter lead'}: half the time to report "
                        "is gone and no decision is recorded."
                    )
                if deadline is not None:
                    left = (deadline - now).days
                    when = (
                        f"overdue since {deadline.date().isoformat()}"
                        if left < 0
                        else f"due by {deadline.date().isoformat()} ({left} days)"
                    )
                    items.append(
                        CheckItem(
                            f"“{matter.name}”: a serious incident ({incident.category.replace('_', ' ')}) "
                            f"must be reported to the market surveillance authority unless a person "
                            f"decides it is not reportable: {when}.",
                            mid,
                            f"a serious incident's reporting deadline: {when}",
                        )
                    )
        if not items and not acted:
            return CheckResult(
                "open_work",
                "Holds and incidents",
                "ok",
                "No hold has waited too long and no serious incident is awaiting a reporting "
                "decision.",
            )
        return CheckResult(
            "open_work",
            "Holds and incidents",
            "attention",
            f"{plain.count(len(items), 'point')} waiting for a person.",
            "Resolve old holds in Review; decide on each serious incident in Governance → "
            "Incidents.",
            items,
            acted,
        )


@dataclass(slots=True)
class _Currency:
    pack_id: str
    fingerprint: str
    checked_on: str
    checked_by: str
    note: str


def _date(text: str | None) -> date | None:
    try:
        return date.fromisoformat(str(text)[:10]) if text else None
    except ValueError:
        return None


def _calendar(path: Path) -> list[dict[str, str]]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = raw.get("entries", []) if isinstance(raw, dict) else []
    return [e for e in entries if isinstance(e, dict) and "date" in e and "what" in e]
