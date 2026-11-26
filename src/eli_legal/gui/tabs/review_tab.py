from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from eli_legal.application.party_service import ANSWERS
from eli_legal.application.reliance_service import BARRED, standing_line
from eli_legal.domain import plain
from eli_legal.domain.enums import HoldScope, ReviewDecision, VerificationStatus
from eli_legal.domain.models import Claim, Hold, RelianceBlock, Run
from eli_legal.domain.release import ReleasePackage
from eli_legal.gui import theme
from eli_legal.gui.hold_window import HoldWindow
from eli_legal.gui.run_controls import RESUMABLE, hold_run, lift_hold, restart_run
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import (
    ReasonDialog,
    button,
    card,
    fill,
    fit,
    label,
    row,
    selected_id,
    table,
)
from eli_legal.workflows.case_preparation import warning_id

_STATUS_OF_REASON = {
    "verification_failed": "failed",
    "verification_inconclusive": "inconclusive",
    "verification_conflict": "conflict",
    "verification_missing": "not_run",
}


def _party_name(tab: Tab, party_id: str) -> str:
    try:
        matter = tab.sv.matters.get(tab.mid, tab.actor)
    except Exception:  # noqa: BLE001 - only a name for display
        return "a party"
    return next((p.name for p in matter.parties if p.party_id == party_id), "a party")


def _found(hold: Hold) -> str:
    """A hold's detail ("current_law: status today: overruled …") as a sentence."""
    check, sep, rest = hold.detail.partition(": ")
    status = _STATUS_OF_REASON.get(hold.reason_code)
    if sep and status and plain.check_meaning(check):
        return plain.check_result(check, status, rest)
    return hold.detail[:1].upper() + hold.detail[1:] if hold.detail else ""


class ReviewTab(Tab):
    title = "⚖ Review"

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.inner = QTabWidget()
        self.root.addWidget(self.inner)
        self._claims: dict[str, Claim] = {}

        # holds
        self.show_closed = QCheckBox("Show resolved holds too")
        self.show_closed.toggled.connect(self.refresh)
        self.holds = table(["On hold", "Why", "What the system found", "What", "State"], stretch=3)
        self.holds.itemSelectionChanged.connect(self._explain)
        self.holds.doubleClicked.connect(lambda _index: self._open_hold())
        self.explain = label("", wrap=True, selectable=True)
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(
            label(
                "A hold closes when its check passes, or when a named person decides, with reasons. Nothing reaches review while one is open. Double-click a hold, or select it and press Open, to see what caused it (the exact words, or the original) and decide it.",
                "muted",
                wrap=True,
            )
        )
        # The divider between the holds and what the chosen one means can be dragged.
        split = QSplitter(Qt.Orientation.Vertical)
        split.setChildrenCollapsible(False)
        split.addWidget(self.holds)
        split.addWidget(card("What this hold means", self.explain))
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        box.addWidget(split, 1)
        self._explain()
        box.addWidget(
            row(
                button(
                    "Open…",
                    self._open_hold,
                    kind="primary",
                    tip="What caused it, the exact words or the original, and what you can do",
                ),
                button("Verify by hand…", self._verify, tip="You checked the authority yourself"),
                button("Take out of reliance…", lambda: self._resolve("exclude"), kind="danger"),
                button(
                    "Accept the gap…",
                    lambda: self._resolve("waive"),
                    tip="For an unread document or a flagged file you have read",
                ),
                self.show_closed,
                None,
            )
        )
        self.inner.addTab(page, "Holds")

        # tasks
        self.tasks = table(
            ["Check", "What to confirm", "About", "What the system found"], stretch=2
        )
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(label("Checks the system could not complete on its own.", "muted"))
        box.addWidget(self.tasks, 1)
        box.addWidget(row(button("Record the result…", self._task_result, kind="primary"), None))
        self.inner.addTab(page, "Checks for you")

        # report
        self.report = QTextBrowser()
        self.report_info = label("", "muted", selectable=True)
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(self.report_info)
        box.addWidget(self.report, 1)
        self.inner.addTab(page, "Report")

        # decision
        self.limits = QListWidget()
        self.limits.setWordWrap(True)
        self.reasons = QPlainTextEdit()
        self.reasons.setPlaceholderText("Your reasons for the decision (recorded with your name)")
        self.reasons.setMaximumHeight(110)
        self.decision_note = label("", wrap=True)
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(self.decision_note)
        # When this person cannot decide the report: who can, and how to get it to them.
        self.who_text = label("", wrap=True, selectable=True)
        self.switch_person = button(
            "Switch person…",
            self._switch_person,
            kind="primary",
            tip="Sign out here and sign in as the person who decides",
        )
        self.name_reviewer = button(
            "Name another reviewer…",
            lambda: self._go_reviewers(),
            tip="Case details → Name the reviewers",
        )
        self.who_card = card(
            "Who can decide this",
            self.who_text,
            row(self.switch_person, self.name_reviewer, None),
        )
        self.who_card.hide()
        box.addWidget(self.who_card)
        split = QSplitter(Qt.Orientation.Vertical)
        split.setChildrenCollapsible(False)
        split.addWidget(
            card("Limits of this report — tick each one to show you have read it", self.limits)
        )
        split.addWidget(card("Reasons", self.reasons))
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        box.addWidget(split, 1)
        self.approve = button(
            "Approve for reliance…", lambda: self._decide(ReviewDecision.APPROVE), kind="primary"
        )
        self.send_back = button(
            "Return for correction…", lambda: self._decide(ReviewDecision.RETURN_FOR_CORRECTION)
        )
        self.reject = button("Reject…", lambda: self._decide(ReviewDecision.REJECT), kind="danger")
        self.restart = button("↻ Restart to make the corrections…", self._restart)
        box.addWidget(
            row(
                self.approve,
                self.send_back,
                self.reject,
                self.restart,
                None,
                button("Put on hold…", lambda: hold_run(self)),
                button("Lift the hold…", lambda: lift_hold(self)),
            )
        )
        self.inner.addTab(page, "Decision")

        # release
        self.recipients = QListWidget()
        self.release_note = label("", wrap=True)
        self.packages = table(["Release", "State", "Recipients", "Entitled?"], stretch=2)
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(self.release_note)
        box.addWidget(card("Who should receive the approved report", self.recipients))
        box.addWidget(
            row(
                button("Prepare the release", self._prepare),
                None,
                button("Suspend reliance (put on hold)…", lambda: hold_run(self)),
                button("Lift the hold…", lambda: lift_hold(self)),
            )
        )
        self.end_suspension = button("End the suspension…", self._end_suspension)
        self.end_suspension.setToolTip(
            "For a named reviewer: once the law is confirmed again for this report, or a later "
            "run, re-checked and approved, replaces it"
        )
        box.addWidget(row(self.end_suspension, None))
        box.addWidget(card("Prepared releases", self.packages), 1)
        box.addWidget(
            row(
                button("Confirm these recipients and stage it…", self._send, kind="primary"),
                label(
                    "Nothing is sent: the report is placed in the outbox for collection.", "muted"
                ),
                None,
            )
        )
        self.inner.addTab(page, "Release")

    def refresh(self) -> None:
        self._claims = {}
        if not (self.mid and self.rid):
            for widget in (self.holds, self.tasks, self.packages):
                fill(widget, [])
            self.report.clear()
            self.report_info.setText("No run is open.")
            self.limits.clear()
            self.recipients.clear()
            self.decision_note.setText("Start a run on the Progress page.")
            return
        summary = self.session.attempt(
            self, lambda: self.sv.runs.summary(self.mid, self.rid, actor_id=self.actor), quiet=True
        )
        if summary is None:
            return
        claims = (
            self.session.attempt(
                self,
                lambda: self.sv.verification.claims(self.mid, self.rid, actor_id=self.actor),
                quiet=True,
            )
            or []
        )
        self._claims = {c.claim_id: c for c in claims}
        docs = {
            d.document_id: d
            for d in self.session.attempt(
                self, lambda: self.sv.matters.documents(self.mid, self.actor), quiet=True
            )
            or []
        }

        def subject(scope: HoldScope, subject_id: str) -> str:
            if scope is HoldScope.CLAIM and subject_id in self._claims:
                claim = self._claims[subject_id]
                return f"{claim.citation or ''} “{claim.text}”".strip()
            if scope is HoldScope.DOCUMENT and subject_id in docs:
                return docs[subject_id].title or docs[subject_id].filename
            return subject_id

        holds = self.sv.holds.list(
            self.mid, self.rid, actor_id=self.actor, open_only=not self.show_closed.isChecked()
        )
        fill(
            self.holds,
            [
                [
                    {
                        "claim": "A finding",
                        "document": "A document",
                        "step": "A step",
                        "run": "The run",
                    }[h.scope.value],
                    plain.hold_reason(h.reason_code),
                    _found(h),
                    subject(h.scope, h.subject_id),
                    plain.state(h.status)
                    + (
                        f" — {plain.resolution(h.resolution).lower()} by {h.resolved_by}"
                        if h.resolution
                        else ""
                    ),
                ]
                for h in holds
            ],
            ids=[h.hold_id for h in holds],
            state_columns=[4],
        )
        fit(self.holds, [90, 170, 320, 0, 200])
        self._holds = {h.hold_id: h for h in holds}
        self.inner.setTabText(0, f"Holds ({sum(1 for h in holds if h.status.value == 'open')})")

        tasks = self.sv.verification.tasks(self.mid, self.rid, actor_id=self.actor)
        fill(
            self.tasks,
            [
                [
                    plain.check_name(t.verification_type),
                    t.question,
                    subject(HoldScope.CLAIM, t.claim_id),
                    self._claims[t.claim_id].status_reason if t.claim_id in self._claims else "",
                ]
                for t in tasks
            ],
            ids=[t.task_id for t in tasks],
        )
        fit(self.tasks, [170, 300, 0, 330])
        self._tasks = {t.task_id: t for t in tasks}
        self.inner.setTabText(1, f"Checks for you ({len(tasks)})")

        report = summary["report"]
        # A refresh rebuilds the lists; what the reviewer ticked stays ticked for the same report.
        previous: dict = getattr(self, "_report", None) or {}  # type: ignore[type-arg]
        same = bool(report) and previous.get("sha256") == report.get("sha256")
        kept_limits = (
            {
                str(self.limits.item(i).data(Qt.ItemDataRole.UserRole))
                for i in range(self.limits.count())
                if self.limits.item(i).checkState() == Qt.CheckState.Checked
            }
            if same
            else set()
        )
        kept_recipients = {
            str(self.recipients.item(i).data(Qt.ItemDataRole.UserRole)[0])
            for i in range(self.recipients.count())
            if self.recipients.item(i).checkState() == Qt.CheckState.Checked
        }
        self.limits.clear()
        if report:
            shown = self.session.attempt(
                self,
                lambda: self.sv.reviews.report_text(self.mid, self.rid, actor_id=self.actor),
                quiet=True,
            )
            text, withheld = shown if shown else ("_The report could not be read._", False)
            self.report.setMarkdown(text)
            state = plain.run_state(
                report["release_status"], real=bool(summary.get("real"))
            ).lower()
            st = self.session.attempt(
                self,
                lambda: self.sv.reliance.standing(self.mid, self.rid, actor_id=self.actor),
                quiet=True,
            )
            self.report_info.setText(
                (f"<b>{escape(standing_line(st))}</b><br>" if st else "")
                + f"Version {report['version']} · {state} · SHA-256 {report['sha256'][:16]}…"
                + (
                    " · material your role does not include is withheld from this copy"
                    if withheld
                    else ""
                )
            )
            warnings = (
                self.session.attempt(
                    self,
                    lambda: self.sv.reviews.pending_warnings(
                        self.mid, self.rid, actor_id=self.actor
                    ),
                    quiet=True,
                )
                or []
            )
            for warning in warnings:
                ident, _, said = warning.partition(": ")
                item = QListWidgetItem(said or warning)
                item.setToolTip(f"Recorded as acknowledged: {ident}")
                item.setData(Qt.ItemDataRole.UserRole, warning_id(warning))
                item.setCheckState(
                    Qt.CheckState.Checked
                    if warning_id(warning) in kept_limits
                    else Qt.CheckState.Unchecked
                )
                self.limits.addItem(item)
        else:
            self.report.clear()
            self.report_info.setText("No report has been drafted yet.")
        self._report = report
        status = summary["status"]
        colour = theme.colour_for(status)
        ready = {
            "awaiting_human_review": "It can be approved by a named reviewer. Approval is tied "
            "to the exact report version shown in the Report tab.",
            "returned_for_correction": "It was returned for correction, so it cannot be "
            "approved, and lifting a hold does not change that. Make the corrections (add or "
            "replace a document, record a check on a finding), then press <b>Restart to make "
            "the corrections</b>: it reads everything again from the papers and brings a new "
            "draft back here for review.",
            "held": "It is on hold. See what is holding it under Holds and checks, deal with "
            "each, then restart it; a hold a person placed is lifted with Lift the hold.",
            "stopped": "It was stopped. Restart it to carry on, or start a new run.",
            "approved_for_reliance": "It is approved. Release is on the Release tab."
            if summary.get("real")
            else "Its practice review is complete: a practice matter is never for reliance. "
            "Release is on the Release tab.",
        }.get(status, "It cannot be approved in this state.")
        self.decision_note.setText(
            f"The run is <b style='color:{colour}'>"
            f"{plain.run_state(status, real=bool(summary.get('real'))).lower()}</b>. {ready}"
        )
        reviewing = status == "awaiting_human_review"
        # Who may decide, by the rules the decision applies: never a greyed-out dead end.
        deciders = (
            self.sv.reviews.deciders(self.mid, self.rid, actor_id=self.actor) if reviewing else None
        )
        blocked = deciders is not None and not deciders["you_can"]
        self._show_who(deciders if blocked else None)
        for decision_button in (self.approve, self.send_back, self.reject):
            decision_button.setEnabled(reviewing and not blocked)
            decision_button.setToolTip(
                f"You cannot decide this: you {deciders['why_not']}. See 'Who can decide this'."
                if blocked and deciders
                else ""
                if reviewing
                else "Only a report awaiting review can be decided"
            )
        self.restart.setVisible(status in {s.value for s in RESUMABLE})

        matter = self.session.matter
        self.recipients.clear()
        if matter:
            users = {u.user_id: u for u in self.sv.users.directory(self.actor)}
            people = [
                (uid, f"{users[uid].display_name} — member of this matter" if uid in users else uid)
                for uid in sorted({matter.owner_user_id, *matter.authorised_user_ids})
            ]
            people += [(p.party_id, f"{p.name} — {p.role} (a party)") for p in matter.parties]
            for key, text in people:
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, (key, text.split(" — ")[0]))
                item.setCheckState(
                    Qt.CheckState.Checked if key in kept_recipients else Qt.CheckState.Unchecked
                )
                self.recipients.addItem(item)
        packages = self.sv.ctx.store.list(ReleasePackage, self.mid, run_id=self.rid)
        fill(
            self.packages,
            [
                [
                    p.release_id[-8:],
                    plain.state(p.status),
                    ", ".join(r.display_name for r in p.recipients),
                    "yes"
                    if all(r.authorised_for_matter for r in p.recipients)
                    else "NO — "
                    + ", ".join(
                        r.display_name for r in p.recipients if not r.authorised_for_matter
                    ),
                ]
                for p in packages
            ],
            ids=[p.release_id for p in packages],
        )
        fit(self.packages, [90, 150, 0, 260])
        self._packages = {p.release_id: p for p in packages}
        blocks = [b for b in self.sv.ctx.store.list(RelianceBlock, self.mid, run_id=self.rid)
                  if b.status in BARRED]  # fmt: skip
        self._blocks = blocks
        self.end_suspension.setVisible(any(b.status == "active" for b in blocks))
        if blocks:
            first = blocks[0]
            self.release_note.setText(
                f"<b style='color:{theme.colour_for('held')}'>Reliance on this report is "
                "suspended.</b> "
                + (
                    "A later run, re-checked and approved, replaces it."
                    if first.status == "superseded"
                    else "An authority it relies on is no longer confirmed as good law (see "
                    "the incident on the matter). Nothing more may be prepared or sent from it."
                    + (
                        f" Already received by {len(first.recipient_ids)} recipient(s), who "
                        "should be told."
                        if first.recipient_ids
                        else ""
                    )
                )
            )
        else:
            self.release_note.setText(
                "Only an approved report can be released, and only to people entitled to it. A tribunal's memorandum is not released to a party."
                if status == "approved_for_reliance"
                else "A report can be released once it has been approved."
            )

    # ── holds and checks ─────────────────────────────────────────────────────
    def _explain(self) -> None:
        hold = getattr(self, "_holds", {}).get(selected_id(self.holds))
        if hold is None:
            self.explain.setText(
                "Select a hold above to see what it means and what you can do about it."
            )
            return
        said = plain.hold_explanation(hold.reason_code)
        options = "".join(f"<li>{o}</li>" for o in said.options)
        answers = "".join(
            f"<li><b>{escape(a.by)}</b> ({escape(_party_name(self, a.party_id))}), "
            f"{a.at:%d %b %Y %H:%M}: {escape(ANSWERS.get(a.kind, a.kind))}. "
            f"{escape(a.reasons)}"
            + (
                f" (the copy is {escape(a.replacement_document_id)})"
                if a.replacement_document_id
                else ""
            )
            + "</li>"
            for a in hold.answers
        )
        self.explain.setText(
            f"<b>{said.headline}.</b> {said.why}<br><b>What you can do:</b><ul>{options}</ul>"
            + (f"<b>The party that filed it answered:</b><ul>{answers}</ul>" if answers else "")
            + f"<span style='color:{theme.MUTED}'>The system found: {_found(hold)}</span>"
        )

    def _show_who(self, deciders: dict | None) -> None:  # type: ignore[type-arg]
        """Say why this person cannot decide, name who can, and offer the way to them."""
        if not deciders:
            self.who_card.hide()
            return
        why = deciders["why_not"]
        mine = (
            "You started this run, and nobody approves their own run (EU AI Act Art. 14: the "
            "person who reviews is not the one who ran it)."
            if why.startswith("started")
            else f"You cannot decide it: {why}."
        )
        who = deciders["who"]
        if who:
            names = ", ".join(f"<b>{escape(w['name'])}</b> ({escape(w['user_id'])})" for w in who)
            how = (
                f"It can be decided by {names}. They see it under 'waiting for you'. On this "
                "machine: <b>Switch person…</b> and sign in as them. Elsewhere: they sign in to "
                "the browser application if the server is running (Settings → System → Server)."
            )
        else:
            how = (
                "<b>Nobody can decide it yet</b>: no other named reviewer of this matter may "
                "decide it. Name one (a judge, tribunal member or arbitrator on the matter) with "
                "<b>Name another reviewer…</b>."
            )
        self.who_text.setText(f"{mine}<br>{how}")
        self.switch_person.setVisible(bool(who))
        self.who_card.show()

    def _switch_person(self) -> None:
        window = self.window()
        if hasattr(window, "sign_out"):
            window.sign_out()

    def _go_reviewers(self) -> None:
        window = self.window()
        if hasattr(window, "go"):
            window.go("matter")
        from eli_legal.gui.tabs.matter_tab import MatterTab

        target = getattr(window, "page", None)
        if callable(target):
            matter_page = target(MatterTab)
            matter_page._reviewers()

    def _open_hold(self) -> None:
        hold_id = selected_id(self.holds)
        if not hold_id or not self.mid:
            return
        window = self.session.attempt(
            self,
            lambda: HoldWindow(self, self.session, self.mid, hold_id, record_check=self._record),
            quiet=True,
        )
        if window is not None:
            window.exec()
            self.refresh()

    def _resolve(self, action: str) -> None:
        hold_id = selected_id(self.holds)
        if not hold_id:
            return
        text = (
            "The finding stays visible in the report under “Findings not to be relied on”, with your reason."
            if action == "exclude"
            else "You are accepting this gap. It will be stated in the report as a limit."
        )
        reason = ReasonDialog.ask(
            self, "Take out of reliance" if action == "exclude" else "Accept the gap", text
        )
        if reason:
            self.session.decide(
                self,
                f"{action} this hold",
                lambda: self.sv.holds.resolve(
                    self.mid, hold_id, actor_id=self.actor, action=action, reason=reason
                ),
            )

    def _record(self, claim_id: str, default_check: str) -> None:
        check = QComboBox()
        for key in ("citation", "current_law", "proposition", "evidence_support", "provenance"):
            check.addItem(plain.check_name(key), key)
        check.setCurrentIndex(max(0, check.findData(default_check)))
        result = QComboBox()
        result.addItem("Verified — I checked and it holds", VerificationStatus.VERIFIED.value)
        result.addItem("Failed — I checked and it does not hold", VerificationStatus.FAILED.value)
        reason = ReasonDialog.ask(
            self,
            "Record a check by hand",
            "Say what you checked and where. Recording a failed system check as verified is an override: it needs that permission and is shown in the report.",
            extra=[("Check", check), ("Result", result)],
        )
        if reason:
            self.session.decide(
                self,
                "record this check in your name",
                lambda: self.sv.verification.record_human_result(
                    self.mid,
                    claim_id,
                    actor_id=self.actor,
                    verification_type=check.currentData(),
                    status=VerificationStatus(result.currentData()),
                    reason=reason,
                ),
            )

    def _verify(self) -> None:
        hold = getattr(self, "_holds", {}).get(selected_id(self.holds))
        if hold is not None and hold.scope is HoldScope.CLAIM:
            self._record(hold.subject_id, hold.detail.split(":", 1)[0].strip())

    def _task_result(self) -> None:
        task = getattr(self, "_tasks", {}).get(selected_id(self.tasks))
        if task is not None:
            self._record(task.claim_id, task.verification_type)

    # ── decision and release ─────────────────────────────────────────────────
    def _decide(self, decision: ReviewDecision) -> None:
        report = getattr(self, "_report", None) or {}
        acknowledged = [
            str(self.limits.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(self.limits.count())
            if self.limits.item(i).checkState() == Qt.CheckState.Checked
        ]
        verb = {
            ReviewDecision.APPROVE: "approve this report for reliance",
            ReviewDecision.REJECT: "reject this report",
            ReviewDecision.RETURN_FOR_CORRECTION: "return this report for correction",
        }[decision]
        self.session.decide(
            self,
            verb,
            lambda: self.sv.reviews.decide(
                self.mid,
                self.rid,
                actor_id=self.actor,
                decision=decision,
                reasons=" ".join(self.reasons.toPlainText().split()),
                report_hash=report.get("sha256", ""),
                acknowledged=acknowledged,
            ),
        )

    def _restart(self) -> None:
        restart_run(self, lambda _r: self.session.notify(), self._restart_failed)

    def _restart_failed(self, exc: Exception) -> None:
        self.session.attempt(self, lambda: (_ for _ in ()).throw(exc))

    def _end_suspension(self) -> None:
        block = next((b for b in getattr(self, "_blocks", []) if b.status == "active"), None)
        if block is None:
            return
        how = QComboBox()
        how.addItem("the law is confirmed again for this report", "")
        for run in self.sv.ctx.store.list(Run, self.mid):
            if run.run_id != block.run_id and run.status.value == "approved_for_reliance":
                how.addItem(f"replaced by the later approved run {run.run_id[-8:]}", run.run_id)
        basis = ReasonDialog.ask(
            self,
            "End the suspension",
            "Only a named reviewer who may approve ends a suspension. Either the authority is "
            "confirmed again for this report (a qualified person's confirmation of its current "
            "status, made after the suspension, recorded on the finding), or a later run, "
            "re-checked and approved after the suspension, replaces the report, which then stays "
            "barred. Write down the basis: the status found, by whom, from which source, and "
            "what it means for the report.",
            extra=[("How it ends", how)],
        )
        if basis:
            self.session.decide(
                self,
                "end the suspension of this report",
                lambda: self.sv.reliance.resolve(
                    self.mid,
                    block.block_id,
                    actor_id=self.actor,
                    basis=basis,
                    superseded_by_run_id=how.currentData() or "",
                ),
            )

    def _prepare(self) -> None:
        chosen = [
            self.recipients.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.recipients.count())
            if self.recipients.item(i).checkState() == Qt.CheckState.Checked
        ]
        recipients = [(key, name, "collect from the outbox") for key, name in chosen]
        self.session.attempt(
            self,
            lambda: self.sv.releases.prepare(
                self.mid, self.rid, actor_id=self.actor, recipients=recipients
            ),
        )

    def _send(self) -> None:
        package = getattr(self, "_packages", {}).get(selected_id(self.packages))
        if package is None:
            return
        ids = [r.recipient_id for r in package.recipients]
        names = ", ".join(r.display_name for r in package.recipients)
        self.session.decide(
            self,
            f"release the approved report to: {names}",
            lambda: self.sv.delivery.distribute(
                self.mid, package.release_id, actor_id=self.actor, confirmed_recipient_ids=ids
            ),
        )
