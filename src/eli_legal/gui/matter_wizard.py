"""Opening a matter, one question at a time.

Six short pages instead of one long form: who the work is for; the matter and its legal system;
the parties and the issues; the team, with each person's role on the matter, the party they act
for and whether they review; the legal sources and the law and standards that apply; and a
summary to check before anything is created. Everything is checked by the services when the
matter is opened, in one step, so a refusal leaves nothing half-made.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFormLayout,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from eli_legal.application.matter_service import TeamMember
from eli_legal.domain import plain
from eli_legal.domain.enums import Profile
from eli_legal.domain.profiles import PROFILES, profile_spec
from eli_legal.gui.widgets import button, label, row
from eli_legal.security import access

PARTY_ROLES = (
    "claimant",
    "respondent",
    "applicant",
    "appellant",
    "third party",
    "interested party",
)
ID = Qt.ItemDataRole.UserRole


class _Page(QWizardPage):
    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        self.setTitle(title)
        self.setSubTitle(subtitle)
        self.box = QVBoxLayout(self)


class MatterWizard(QWizard):
    """``values()`` gives the arguments for ``MatterService.create``."""

    def __init__(
        self,
        parent: QWidget,
        *,
        actor_id: str,
        jurisdictions: list[str],
        default_jurisdiction: str,
        users: list[Any],
        sources: list[Any],
        frameworks: list[Any],
        recommend: Any,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Open a matter")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setMinimumSize(820, 620)
        self.actor_id = actor_id
        me = next((u for u in users if u.user_id == actor_id), None)
        self._my_roles: set[str] = set(me.roles) if me else set()
        self._users = [u for u in users if u.active and u.user_id != actor_id]
        self._sources = sources
        self._frameworks = frameworks
        self._recommend = recommend
        self.addPage(self._who())
        self.addPage(self._matter(jurisdictions, default_jurisdiction))
        self.addPage(self._parties())
        self.addPage(self._team())
        self.addPage(self._law())
        self.addPage(self._check())
        self.currentIdChanged.connect(self._entered)

    # ── 1. who it is for ─────────────────────────────────────────────────────
    def _who(self) -> QWizardPage:
        page = _Page(
            "Who is this work for?",
            "This fixes who may work on the matter, what the output may say, and how the law "
            "classifies the use. It cannot be changed later.",
        )
        self.profile_group = QButtonGroup(page)
        for index, (profile, spec) in enumerate(PROFILES.items()):
            choice = QRadioButton(spec.label)
            choice.setProperty("profile", profile.value)
            self.profile_group.addButton(choice, index)
            say = (
                "May assess the merits for its own client; never words a decision."
                if spec.outcome_policy == "merits_assessment"
                else "Never says who should succeed."
            )
            roles = ", ".join(sorted(plain.role(r) for r in spec.roles))
            page.box.addWidget(choice)
            page.box.addWidget(
                label(
                    f"Output: {spec.report_template.replace('_', ' ')}. {say} People: {roles}.",
                    "muted",
                    wrap=True,
                )
            )
            if index == 0:
                choice.setChecked(True)
        page.box.addStretch(1)
        return page

    @property
    def profile(self) -> Profile:
        checked = self.profile_group.checkedButton()
        return Profile(checked.property("profile")) if checked else Profile.ADJUDICATOR

    # ── 2. the matter ────────────────────────────────────────────────────────
    def _matter(self, jurisdictions: list[str], default: str) -> QWizardPage:
        page = _Page(
            "The matter",
            "A name everyone on it will recognise, what the work is for, and the legal system.",
        )
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Harbour Freight Ltd v Northwind Logistics Ltd")
        self.purpose = QLineEdit()
        self.purpose.setPlaceholderText("Case analysis for the tribunal ahead of the hearing")
        self.jurisdiction = QComboBox()
        self.jurisdiction.addItems(jurisdictions)
        self.jurisdiction.setEditable(True)
        if default in jurisdictions:
            self.jurisdiction.setCurrentText(default)
        self.governing = QComboBox()
        self.governing.addItems(["(same as the legal system)", *jurisdictions])
        self.forum = QLineEdit()
        self.forum.setPlaceholderText("Arbitration seated in Dublin under the 2010 Act")
        self.rules = QLineEdit()
        self.has_date = QCheckBox("Assess the law as it stood on")
        self.relevant = QDateEdit(QDate.currentDate())
        self.relevant.setCalendarPopup(True)
        self.relevant.setDisplayFormat("yyyy-MM-dd")
        form.addRow("Name *", self.name)
        form.addRow("Purpose *", self.purpose)
        form.addRow("Legal system", self.jurisdiction)
        form.addRow("Governing law", self.governing)
        form.addRow("Forum", self.forum)
        form.addRow("Procedural rules", self.rules)
        form.addRow(self.has_date, self.relevant)
        page.box.addLayout(form)
        page.box.addWidget(
            label(
                "The date is usually when the events happened. Without one, legislation is "
                "judged as it stands today, and the report says so.",
                "muted",
                wrap=True,
            )
        )
        page.registerField("name*", self.name)
        page.registerField("purpose*", self.purpose)
        page.box.addStretch(1)
        return page

    # ── 3. parties and issues ────────────────────────────────────────────────
    def _parties(self) -> QWizardPage:
        page = _Page(
            "Parties and issues",
            "Each party once, with its role. Frame each issue as a question the work must answer.",
        )
        self.parties = QTableWidget(0, 2)
        self.parties.setHorizontalHeaderLabels(["Party", "Role"])
        self.parties.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.parties.verticalHeader().setVisible(False)
        self.parties.setMinimumHeight(140)
        page.box.addWidget(self.parties)
        page.box.addWidget(
            row(
                button("Add a party", lambda: self._add_party("", "")),
                button("Remove the selected party", self._remove_party),
                None,
            )
        )
        self.represents = QComboBox()
        self.parties.itemChanged.connect(lambda _item: self._refresh_represents())
        self._add_party("", "claimant")
        self._add_party("", "respondent")
        self.represents_row = label("We act for")
        form = QFormLayout()
        form.addRow(self.represents_row, self.represents)
        page.box.addLayout(form)
        self.issues = QPlainTextEdit()
        self.issues.setPlaceholderText(
            "One per line, as a question:\nWhether time for delivery was of the essence\n"
            "Whether the notice of 28 April 2023 validly terminated the agreement"
        )
        self.issues.setMaximumHeight(120)
        page.box.addWidget(label("Issues"))
        page.box.addWidget(self.issues)
        return page

    def _add_party(self, name: str, role_name: str) -> None:
        r = self.parties.rowCount()
        self.parties.insertRow(r)
        self.parties.setItem(r, 0, QTableWidgetItem(name))
        roles = QComboBox()
        roles.setEditable(True)
        roles.addItems(PARTY_ROLES)
        roles.setCurrentText(role_name or "claimant")
        self.parties.setCellWidget(r, 1, roles)

    def _remove_party(self) -> None:
        r = self.parties.currentRow()
        if r >= 0:
            self.parties.removeRow(r)
            self._refresh_represents()

    def _refresh_represents(self) -> None:
        keep = self.represents.currentText()
        self.represents.blockSignals(True)
        self.represents.clear()
        self.represents.addItems([name for name, _ in self.party_list()])
        if keep:
            self.represents.setCurrentText(keep)
        self.represents.blockSignals(False)

    def party_list(self) -> list[tuple[str, str]]:
        out = []
        for r in range(self.parties.rowCount()):
            item = self.parties.item(r, 0)
            roles = self.parties.cellWidget(r, 1)
            name = item.text().strip() if item else ""
            role_name = roles.currentText().strip() if isinstance(roles, QComboBox) else ""
            if name and role_name:
                out.append((name, role_name))
        return out

    # ── 4. the team ──────────────────────────────────────────────────────────
    def _team(self) -> QWizardPage:
        page = _Page(
            "The team",
            "Tick who works on the matter and choose each person's role on it. You lead it. "
            "Only people whose account fits this kind of matter are listed.",
        )
        self.team = QTableWidget(0, 5)
        self.team.setHorizontalHeaderLabels(
            ["Person", "Account", "Role on this matter", "Acts for", "Reviews"]
        )
        self.team.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.team.verticalHeader().setVisible(False)
        self.team.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        page.box.addWidget(self.team, 1)
        self.role_help = label(
            "<br>".join(
                f"<b>{r.label}</b>: {r.summary}"
                for code, r in access.MATTER_ROLES.items()
                if code != "lead"
            ),
            "muted",
            wrap=True,
        )
        page.box.addWidget(self.role_help)
        self.reviewer_self = QCheckBox("I review and approve the report myself")
        self.reviewer_self.setChecked(True)
        page.box.addWidget(self.reviewer_self)
        return page

    def _fill_team(self) -> None:
        spec = profile_spec(self.profile)
        eligible = [u for u in self._users if any(spec.allows_role(r) for r in u.roles)]
        parties = [name for name, _ in self.party_list()]
        self.team.setRowCount(0)
        for user in eligible:
            r = self.team.rowCount()
            self.team.insertRow(r)
            who = QTableWidgetItem(f"{user.display_name} ({user.user_id})")
            who.setFlags(who.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            who.setCheckState(Qt.CheckState.Unchecked)
            who.setData(ID, user.user_id)
            self.team.setItem(r, 0, who)
            self.team.setItem(r, 1, QTableWidgetItem(plain.roles(user.roles)))
            roles = QComboBox()
            for code, matter_role in access.MATTER_ROLES.items():
                roles.addItem(matter_role.label, code)
                roles.setItemData(
                    roles.count() - 1, matter_role.summary, Qt.ItemDataRole.ToolTipRole
                )
            roles.setCurrentIndex(
                roles.findData(access.covering_role(user.roles, allow_lead=False))
            )
            self.team.setCellWidget(r, 2, roles)
            acts = QComboBox()
            acts.addItem("(nobody in particular)", "")
            for name in parties:
                acts.addItem(name, name)
            self.team.setCellWidget(r, 3, acts)
            reviews = QCheckBox()
            reviews.setEnabled(bool(user.roles & spec.reviewer_roles))
            reviews.setToolTip(
                "Can approve the report"
                if reviews.isEnabled()
                else "Their account cannot approve on this kind of matter"
            )
            self.team.setCellWidget(r, 4, reviews)
        can_review = bool(self._my_roles & spec.reviewer_roles)
        self.reviewer_self.setEnabled(can_review)
        self.reviewer_self.setChecked(can_review and self.reviewer_self.isChecked())
        self.reviewer_self.setToolTip(
            "" if can_review else "Your account cannot approve on this kind of matter"
        )

    def team_members(self) -> tuple[list[TeamMember], list[str]]:
        team: list[TeamMember] = []
        reviewers: list[str] = [self.actor_id] if self.reviewer_self.isChecked() else []
        for r in range(self.team.rowCount()):
            who = self.team.item(r, 0)
            if who is None or who.checkState() != Qt.CheckState.Checked:
                continue
            roles, acts, reviews = (self.team.cellWidget(r, c) for c in (2, 3, 4))
            uid = str(who.data(ID))
            team.append(
                TeamMember(
                    uid,
                    roles.currentData() if isinstance(roles, QComboBox) else "",
                    (acts.currentData() or None) if isinstance(acts, QComboBox) else None,
                )
            )
            if isinstance(reviews, QCheckBox) and reviews.isChecked():
                reviewers.append(uid)
        return team, reviewers

    # ── 5. sources and law ───────────────────────────────────────────────────
    def _law(self) -> QWizardPage:
        page = _Page(
            "Legal sources, law and standards",
            "The system reads only the approved sources you tick. The law and standards "
            "packages recommended for this kind of matter and legal system are ticked for you.",
        )
        self.source_list = QListWidget()
        self.source_list.setMaximumHeight(140)
        self.law_list = QListWidget()
        page.box.addWidget(label("<b>Approved legal sources</b>"))
        page.box.addWidget(self.source_list)
        page.box.addWidget(
            label(
                "Without a source no legal research is done and no cited authority can be "
                "checked; you can add one later.",
                "muted",
                wrap=True,
            )
        )
        page.box.addWidget(label("<b>Law and standards</b>"))
        page.box.addWidget(self.law_list, 1)
        return page

    def _fill_law(self) -> None:
        code = self.jurisdiction.currentText().strip()
        self.source_list.clear()
        for source in self._sources:
            item = QListWidgetItem(f"{source.name} — {', '.join(sorted(source.jurisdictions))}")
            item.setData(ID, source.source_id)
            covers = code in source.jurisdictions or "*" in source.jurisdictions
            item.setCheckState(Qt.CheckState.Checked if covers else Qt.CheckState.Unchecked)
            self.source_list.addItem(item)
        wanted = set(self._recommend(self.profile.value, code)) if self._recommend else set()
        self.law_list.clear()
        for state in self._frameworks:
            star = "★ " if state.pack.pack_id in wanted else ""
            item = QListWidgetItem(f"{star}{state.pack.title}  ·  {state.pack.scope}")
            item.setToolTip(state.why)
            item.setData(ID, state.pack.pack_id)
            item.setCheckState(
                Qt.CheckState.Checked if state.pack.pack_id in wanted else Qt.CheckState.Unchecked
            )
            self.law_list.addItem(item)

    @staticmethod
    def _ticked(widget: QListWidget) -> list[str]:
        return [
            str(widget.item(i).data(ID))
            for i in range(widget.count())
            if widget.item(i).checkState() == Qt.CheckState.Checked
        ]

    # ── 6. check ─────────────────────────────────────────────────────────────
    def _check(self) -> QWizardPage:
        page = _Page("Check and open", "Nothing is created until you press Finish.")
        self.summary = label("", wrap=True, selectable=True)
        page.box.addWidget(self.summary)
        page.box.addStretch(1)
        return page

    def _entered(self, page_id: int) -> None:
        if page_id == 2:
            rep = self.profile is Profile.PARTY_REPRESENTATIVE
            self.represents.setVisible(rep)
            self.represents_row.setVisible(rep)
            self._refresh_represents()
        if page_id == 3:
            self._fill_team()
        if page_id == 4:
            self._fill_law()
        if page_id == 5:
            v = self.values()
            spec = profile_spec(v["profile"])
            team = "".join(
                f"<li>{m.user_id}: {access.MATTER_ROLES[m.matter_role].label}"
                + (f", acts for {m.party}" if m.party else "")
                + ("; reviews" if m.user_id in v["reviewers"] else "")
                + "</li>"
                for m in v["team"]
            )
            issues = "".join(f"<li>{i}</li>" for i in v["stated_issues"]) or "<li>none</li>"
            self.summary.setText(
                f"<b>{v['name']}</b> — {v['purpose']}<br>"
                f"For: {spec.label}. Legal system: {v['jurisdiction']}"
                + (f"; governing law {v['governing_law']}" if v["governing_law"] else "")
                + (f"; law as at {v['relevant_date']}" if v["relevant_date"] else "")
                + "<br>Parties: "
                + ("; ".join(f"{n} ({r})" for n, r in v["parties"]) or "none")
                + (f"<br>We act for: {v['represented_party']}" if v["represented_party"] else "")
                + f"<br>Issues:<ul>{issues}</ul>"
                + f"You lead it{' and review it' if self.actor_id in v['reviewers'] else ''}."
                + (f"<ul>{team}</ul>" if team else "<br>Nobody else is on it yet.<br>")
                + f"Sources: {', '.join(v['sources']) or 'none'}<br>"
                + f"Law and standards: {len(v['frameworks'])} packages."
                + (
                    ""
                    if v["reviewers"]
                    else "<br><b>No reviewer is named:</b> the analysis will not start until "
                    "someone is."
                )
            )

    def values(self) -> dict[str, Any]:
        qd = self.relevant.date()
        governing = self.governing.currentText()
        team, reviewers = self.team_members()
        rep = self.profile is Profile.PARTY_REPRESENTATIVE
        return {
            "name": self.name.text().strip(),
            "purpose": self.purpose.text().strip(),
            "profile": self.profile,
            "jurisdiction": self.jurisdiction.currentText().strip(),
            "governing_law": None if governing.startswith("(") else governing,
            "forum": self.forum.text().strip(),
            "procedural_rules": self.rules.text().strip(),
            "relevant_date": date(qd.year(), qd.month(), qd.day())
            if self.has_date.isChecked()
            else None,
            "parties": self.party_list(),
            "stated_issues": [
                i.strip() for i in self.issues.toPlainText().splitlines() if i.strip()
            ],
            "represented_party": (self.represents.currentText().strip() or None) if rep else None,
            "frameworks": self._ticked(self.law_list),
            "recommended_frameworks": False,
            "team": team,
            "reviewers": reviewers,
            "sources": self._ticked(self.source_list),
        }
