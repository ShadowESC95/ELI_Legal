from __future__ import annotations

from datetime import date
from typing import Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from eli_legal.domain.enums import Profile
from eli_legal.domain.profiles import PROFILES, profile_spec
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


def _pairs(text: str) -> list[tuple[str, str]]:
    out = []
    for line in text.splitlines():
        if ":" in line:
            name, role = line.rsplit(":", 1)
            if name.strip() and role.strip():
                out.append((name.strip(), role.strip()))
    return out


class NewMatterDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        jurisdictions: list[str],
        default: str,
        frameworks: Any = None,
        recommend: Any = None,
    ) -> None:
        super().__init__(parent)
        # frameworks: usable package states; recommend(profile, jurisdiction) -> recommended ids
        self._frameworks = list(frameworks or [])
        self._recommend = recommend
        self.setWindowTitle("Open a matter")
        self.setMinimumWidth(620)
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.purpose = QLineEdit()
        self.profile = QComboBox()
        for profile, spec in PROFILES.items():
            self.profile.addItem(spec.label, profile.value)
        self.note = label("", "muted", wrap=True)
        self.jurisdiction = QComboBox()
        self.jurisdiction.addItems(jurisdictions)
        if default in jurisdictions:
            self.jurisdiction.setCurrentText(default)
        self.jurisdiction.setEditable(True)
        self.governing = QComboBox()
        self.governing.addItems(["(same as jurisdiction)", *jurisdictions])
        self.forum = QLineEdit()
        self.rules = QLineEdit()
        self.has_date = QCheckBox("Assess the law as at")
        self.relevant = QDateEdit(QDate.currentDate())
        self.relevant.setCalendarPopup(True)
        self.relevant.setDisplayFormat("yyyy-MM-dd")
        self.parties = QPlainTextEdit()
        self.parties.setPlaceholderText("One per line —  Name: role\nHarbour Freight Ltd: claimant")
        self.parties.setMaximumHeight(80)
        self.issues = QPlainTextEdit()
        self.issues.setPlaceholderText("One issue per line, framed as a question —  Whether …")
        self.issues.setMaximumHeight(90)
        self.represents = QLineEdit()
        self.represents.setPlaceholderText(
            "The party you act for (party-representative matters only)"
        )
        form.addRow("Name", self.name)
        form.addRow("Purpose", self.purpose)
        form.addRow("Who is this for", self.profile)
        form.addRow("", self.note)
        form.addRow("Jurisdiction", self.jurisdiction)
        form.addRow("Governing law", self.governing)
        form.addRow("Forum", self.forum)
        form.addRow("Procedural rules", self.rules)
        form.addRow(self.has_date, self.relevant)
        form.addRow("Parties", self.parties)
        form.addRow("Issues", self.issues)
        form.addRow("Represents", self.represents)
        self.laws = QListWidget()
        self.laws.setMaximumHeight(150)
        for state in self._frameworks:
            item = QListWidgetItem(f"{state.pack.title}  ·  {state.pack.scope}")
            item.setData(Qt.ItemDataRole.UserRole, state.pack.pack_id)
            item.setToolTip(state.why)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.laws.addItem(item)
        if self._frameworks:
            form.addRow(
                "Law and standards",
                label(
                    "Ticked: the packages recommended for this kind of matter and legal system. "
                    "Change them here, or later in Laws & Standards.",
                    "muted",
                    wrap=True,
                ),
            )
            form.addRow("", self.laws)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.profile.currentIndexChanged.connect(self._profile_changed)
        self.jurisdiction.currentTextChanged.connect(lambda _t: self._tick_recommended())
        self._profile_changed()

    def _profile_changed(self) -> None:
        spec = profile_spec(Profile(self.profile.currentData()))
        say = (
            "may assess the merits for its own client"
            if spec.outcome_policy == "merits_assessment"
            else "never says who should succeed"
        )
        self.note.setText(
            f"Output: {spec.report_template.replace('_', ' ')}. It {say}. {spec.disclaimer}"
        )
        self.represents.setEnabled(
            Profile(self.profile.currentData()) is Profile.PARTY_REPRESENTATIVE
        )
        self._tick_recommended()

    def _tick_recommended(self) -> None:
        if not self._recommend or not hasattr(self, "laws"):
            return
        wanted = set(
            self._recommend(self.profile.currentData(), self.jurisdiction.currentText().strip())
        )
        for i in range(self.laws.count()):
            item = self.laws.item(i)
            item.setCheckState(
                Qt.CheckState.Checked
                if item.data(Qt.ItemDataRole.UserRole) in wanted
                else Qt.CheckState.Unchecked
            )

    def values(self) -> dict[str, Any]:
        qd = self.relevant.date()
        governing = self.governing.currentText()
        return {
            "name": self.name.text().strip(),
            "purpose": self.purpose.text().strip(),
            "profile": Profile(self.profile.currentData()),
            "jurisdiction": self.jurisdiction.currentText().strip(),
            "governing_law": None if governing.startswith("(") else governing,
            "forum": self.forum.text().strip(),
            "procedural_rules": self.rules.text().strip(),
            "relevant_date": date(qd.year(), qd.month(), qd.day())
            if self.has_date.isChecked()
            else None,
            "parties": _pairs(self.parties.toPlainText()),
            "stated_issues": [
                i.strip() for i in self.issues.toPlainText().splitlines() if i.strip()
            ],
            "represented_party": self.represents.text().strip() or None,
            "frameworks": [
                str(self.laws.item(i).data(Qt.ItemDataRole.UserRole))
                for i in range(self.laws.count())
                if self.laws.item(i).checkState() == Qt.CheckState.Checked
            ],
            "recommended_frameworks": False,
        }


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
        self.people = table(["User", "Name", "Roles", "Reviewer"], stretch=2)
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
                [m.name, profile_spec(m.profile).label, m.jurisdiction, m.status.value]
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
            f"<b>Jurisdiction / governing law:</b> {matter.jurisdiction} / {matter.governing_law or matter.jurisdiction}"
            f"<br><b>Forum:</b> {matter.forum or '—'} &nbsp; <b>Rules:</b> {matter.procedural_rules or '—'}"
            f"<br><b>Law assessed as at:</b> {matter.relevant_date or 'not set (today)'}"
            f"<br><b>Parties:</b> {parties}<br><b>Issues stated:</b><ul>{issues}</ul>"
        )
        self.note.setText(spec.regulatory_note)
        users = {u.user_id: u for u in self.sv.users.directory(self.actor)}
        members = sorted({matter.owner_user_id, *matter.authorised_user_ids})
        fill(
            self.people,
            [
                [
                    uid,
                    users[uid].display_name if uid in users else "(unknown)",
                    ", ".join(sorted(users[uid].roles)) if uid in users else "",
                    "named reviewer" if uid in matter.reviewer_user_ids else "",
                ]
                for uid in members
            ],
            ids=members,
        )
        fit(self.people, [130, 160, 0, 110])
        self.sources.setText(
            ", ".join(sorted(matter.approved_source_ids))
            or "None. No legal research will be done and no cited authority can be checked."
        )

    def _picked(self) -> None:
        chosen = selected_id(self.matters)
        if chosen and chosen != self.mid:
            self.session.set_matter(chosen)

    def _new(self) -> None:
        packs = self.sv.ctx.jurisdictions.codes()
        states = [s for s in self.sv.frameworks.list(actor_id=self.actor) if s.usable]
        dialog = NewMatterDialog(
            self,
            packs,
            self.sv.ctx.settings.default_jurisdiction,
            frameworks=states,
            recommend=lambda profile, code: self.sv.frameworks.recommended(
                profile, code, actor_id=self.actor
            ),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
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
        items = [
            (uid, f"{users[uid].display_name} ({uid})", uid in matter.reviewer_user_ids)
            for uid in sorted({matter.owner_user_id, *matter.authorised_user_ids})
            if uid in users and users[uid].roles & spec.reviewer_roles
        ]
        dialog = PickDialog(
            self,
            "Named reviewers",
            "Only these people will be able to approve a report on this matter. Without at least one, no run will start.",
            items,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.session.attempt(
                self,
                lambda: self.sv.matters.set_reviewers(
                    self.mid, actor_id=self.actor, reviewer_ids=dialog.chosen()
                ),
            )

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
