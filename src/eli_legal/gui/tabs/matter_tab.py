from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from eli_legal.domain import plain
from eli_legal.domain.profiles import profile_spec
from eli_legal.gui.matter_wizard import MatterWizard
from eli_legal.gui.people import People
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
from eli_legal.security import access


class PickDialog(QDialog):
    """Tick the items that apply."""

    def __init__(
        self, parent: QWidget, title: str, prompt: str, items: list[tuple[str, str, bool]]
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.addWidget(label(prompt, wrap=True))
        self.list = QListWidget()
        for key, text, ticked in items:
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setCheckState(Qt.CheckState.Checked if ticked else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        layout.addWidget(self.list)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def chosen(self) -> list[str]:
        out = []
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return out


class MatterTab(Tab):
    title = "📁 Matter"

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.matters = table(["Matter", "For", "Law", "Status"], stretch=0)
        self.matters.itemSelectionChanged.connect(self._picked)
        left = card(
            "Your matters",
            self.matters,
            row(button("Open a matter…", self._new, kind="primary"), None),
        )
        self.heading = label("", "title", wrap=True)
        self.summary = label("", wrap=True, selectable=True)
        self.note = label("", "muted", wrap=True)
        self.people = table(
            ["User", "Name", "Role on this matter", "Acts for", "Reads", "Reviewer"], stretch=4
        )
        self.sources = label("", wrap=True)
        right = QWidget()
        column = QVBoxLayout(right)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(card("Matter", self.heading, self.summary, self.note))
        column.addWidget(
            card(
                "People on this matter",
                self.people,
                row(
                    button("Grant access…", self._grant),
                    button("Change role…", self._change_role),
                    button("Revoke access", self._revoke),
                    button("Name the reviewers…", self._reviewers),
                    None,
                ),
            ),
            1,
        )
        column.addWidget(
            card(
                "Approved legal sources for this matter",
                self.sources,
                row(
                    button("Choose sources…", self._sources),
                    None,
                    button("Close this matter…", self._close, kind="danger"),
                ),
            )
        )
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([420, 760])
        self.root.addWidget(split)

    def refresh(self) -> None:
        matters = self.sv.matters.list_for(self.actor) if self.actor else []
        fill(
            self.matters,
            [
                [m.name, profile_spec(m.profile).label, m.jurisdiction, plain.state(m.status)]
                for m in matters
            ],
            ids=[m.matter_id for m in matters],
            state_columns=[3],
            keep_selection=False,
        )
        fit(self.matters, [0, 170, 60, 70])
        for index, listed in enumerate(matters):
            if listed.matter_id == self.mid:
                self.matters.blockSignals(True)
                self.matters.selectRow(index)
                self.matters.blockSignals(False)
        matter = self.session.matter
        if matter is None:
            self.heading.setText("No matter is open")
            self.summary.setText(
                "Open a matter to begin, or ask someone who owns one to grant you access."
            )
            self.note.setText("")
            self.sources.setText("")
            fill(self.people, [])
            return
        spec = profile_spec(matter.profile)
        self.heading.setText(matter.name)
        parties = "; ".join(f"{p.name} ({p.role})" for p in matter.parties) or "none recorded"
        issues = "".join(f"<li>{i}</li>" for i in matter.stated_issues) or "<li>none stated</li>"
        self.summary.setText(
            f"<b>Purpose:</b> {matter.purpose}<br><b>Prepared for:</b> {spec.label}<br>"
            f"<b>Legal system / governing law:</b> {matter.jurisdiction} / {matter.governing_law or matter.jurisdiction}"
            f"<br><b>Forum:</b> {matter.forum or '—'} &nbsp; <b>Rules:</b> {matter.procedural_rules or '—'}"
            f"<br><b>Law assessed as at:</b> {matter.relevant_date or 'not set (today)'}"
            f"<br><b>Parties:</b> {parties}<br><b>Issues stated:</b><ul>{issues}</ul>"
        )
        self.note.setText(spec.regulatory_note)
        members = (
            self.session.attempt(
                self, lambda: self.sv.matters.members(self.mid, self.actor), quiet=True
            )
            or []
        )
        fill(
            self.people,
            [
                [
                    m.user_id,
                    m.name,
                    access.MATTER_ROLES[m.matter_role].label if m.matter_role else "",
                    m.party or "—",
                    "Everything"
                    if len(m.reads) == len(access.ALL_SCOPES)
                    else ", ".join(plain.scope(r) for r in m.reads) or "Nothing (withheld)",
                    "named reviewer" if m.reviewer else "",
                ]
                for m in members
            ],
            ids=[m.user_id for m in members],
        )
        fit(self.people, [110, 150, 130, 140, 0, 110])
        self.sources.setText(
            ", ".join(sorted(matter.approved_source_ids))
            or "None. No legal research will be done and no cited authority can be checked."
        )

    def _picked(self) -> None:
        chosen = selected_id(self.matters)
        if chosen and chosen != self.mid:
            self.session.set_matter(chosen)

    def _new(self) -> None:
        wizard = MatterWizard(
            self,
            actor_id=self.actor,
            jurisdictions=self.sv.ctx.jurisdictions.codes(),
            default_jurisdiction=self.sv.ctx.settings.default_jurisdiction,
            users=self.sv.users.directory(self.actor),
            sources=[s for s in self.sv.sources.list() if s.approved],
            frameworks=[s for s in self.sv.frameworks.list(actor_id=self.actor) if s.usable],
            recommend=lambda profile, code: self.sv.frameworks.recommended(
                profile, code, actor_id=self.actor
            ),
            people=People(self.session, self.actor),
        )
        if wizard.exec() != QDialog.DialogCode.Accepted:
            return
        values = wizard.values()
        matter = self.session.attempt(
            self, lambda: self.sv.matters.create(actor_id=self.actor, **values), quiet=True
        )
        if matter is not None:
            self.session.set_matter(matter.matter_id)

    def _grant(self) -> None:
        matter = self.session.matter
        if matter is None:
            return
        spec = profile_spec(matter.profile)
        candidates = [
            (u.user_id, f"{u.display_name} ({u.user_id}) — {', '.join(sorted(u.roles))}", False)
            for u in self.sv.users.directory(self.actor)
            if u.active
            and u.user_id not in matter.authorised_user_ids
            and any(spec.allows_role(r) for r in u.roles)
        ]
        dialog = PickDialog(
            self,
            "Grant access",
            f"People whose roles are valid on a matter for: {spec.label}.",
            candidates,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            for uid in dialog.chosen():
                self._grant_one(uid)

    def _grant_one(self, user_id: str) -> None:
        self.session.attempt(
            self, lambda: self.sv.matters.grant(self.mid, actor_id=self.actor, user_id=user_id)
        )

    def _change_role(self) -> None:
        uid = selected_id(self.people)
        matter = self.session.matter
        if not uid or matter is None or uid == matter.owner_user_id:
            return
        items = [
            (code, f"{r.label} — {r.summary}", matter.member_roles.get(uid) == code)
            for code, r in access.MATTER_ROLES.items()
            if code != "lead"
        ]
        dialog = PickDialog(self, "Role on this matter", f"Tick one role for {uid}.", items)
        if dialog.exec() == QDialog.DialogCode.Accepted and len(dialog.chosen()) == 1:
            self.session.attempt(
                self,
                lambda: self.sv.matters.set_member(
                    self.mid, actor_id=self.actor, user_id=uid, matter_role=dialog.chosen()[0]
                ),
            )

    def _revoke(self) -> None:
        uid = selected_id(self.people)
        if uid:
            self.session.attempt(
                self, lambda: self.sv.matters.revoke(self.mid, actor_id=self.actor, user_id=uid)
            )

    def _reviewers(self) -> None:
        matter = self.session.matter
        if matter is None:
            return
        spec = profile_spec(matter.profile)
        users = {u.user_id: u for u in self.sv.users.directory(self.actor)}
        members = [
            users[uid]
            for uid in sorted({matter.owner_user_id, *matter.authorised_user_ids})
            if uid in users
        ]
        needs = plain.approvers(spec.reviewer_roles)
        can = [u for u in members if u.roles & spec.reviewer_roles]
        cannot = [u for u in members if not u.roles & spec.reviewer_roles]
        if not can:
            self._nobody_can_approve(matter, spec, members, needs)
            return
        items = [
            (
                u.user_id,
                f"{u.display_name} ({u.user_id})"
                + (
                    ""
                    if u.passphrase_hash
                    else " — has no passphrase yet, so cannot sign in to approve"
                ),
                u.user_id in matter.reviewer_user_ids,
            )
            for u in can
        ]
        dialog = PickDialog(
            self,
            "Named reviewers",
            "Only these people will be able to approve a report on this matter. Without at "
            f"least one, no run will start. On a matter for {spec.label.lower()} an approver "
            f"needs an account that is {needs}, and is on the matter as decision-maker."
            + (
                " Not listed, as their accounts cannot approve here: "
                + "; ".join(
                    f"{u.display_name} ({u.user_id}): {plain.roles(u.roles)}" for u in cannot
                )
                + "."
                if cannot
                else ""
            ),
            items,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.session.attempt(
                self,
                lambda: self.sv.matters.set_reviewers(
                    self.mid, actor_id=self.actor, reviewer_ids=dialog.chosen()
                ),
            )

    def _nobody_can_approve(self, matter, spec, members, needs) -> None:  # type: ignore[no-untyped-def]
        """Say why nobody can be named, and let an administrator change an account here."""
        people = People(self.session, self.actor)
        said = (
            f"Nobody on this matter can approve its report. On a matter for "
            f"{spec.label.lower()} an approver needs an account that is {needs}.\n\n"
            + "\n".join(
                f"• {u.display_name} ({u.user_id}): {plain.roles(u.roles)}" for u in members
            )
        )
        if not people.can_manage:
            QMessageBox.information(
                self,
                "Named reviewers",
                said + "\n\nAsk an administrator to give one of them such an account, or to "
                "add someone who has one.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Named reviewers",
            said + "\n\nChange what one of their accounts may do now?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        dialog = PickDialog(
            self,
            "Whose account?",
            f"Tick one person. Give them a ★ role ({needs}); then name them a reviewer.",
            [
                (u.user_id, f"{u.display_name} ({u.user_id}): {plain.roles(u.roles)}", False)
                for u in members
            ],
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or len(dialog.chosen()) != 1:
            return
        user = next(u for u in members if u.user_id == dialog.chosen()[0])
        if people.change(self, user, approve=spec.reviewer_roles, matter_label=spec.label):
            self.refresh()
            self._reviewers()

    def _sources(self) -> None:
        matter = self.session.matter
        if matter is None:
            return
        items = [
            (
                s.source_id,
                f"{s.name} — {', '.join(sorted(s.jurisdictions))}",
                s.source_id in matter.approved_source_ids,
            )
            for s in self.sv.sources.list()
            if s.approved
        ]
        dialog = PickDialog(
            self,
            "Legal sources",
            "Only approved sources are listed. The system can read nothing else.",
            items,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.session.attempt(
                self,
                lambda: self.sv.matters.set_sources(
                    self.mid, actor_id=self.actor, source_ids=dialog.chosen()
                ),
            )

    def _close(self) -> None:
        if not self.mid:
            return
        purge = QCheckBox("Also delete the documents, their text and the search index")
        reason = ReasonDialog.ask(
            self,
            "Close this matter",
            "Closing ends everyone's access but yours. The record of runs, reviews, releases, holds, incidents and the audit ledger is kept either way.",
            extra=[("", purge)],
        )
        if reason:
            self.session.decide(
                self,
                "close this matter",
                lambda: self.sv.matters.close(
                    self.mid, actor_id=self.actor, purge_content=purge.isChecked(), reason=reason
                ),
            )
