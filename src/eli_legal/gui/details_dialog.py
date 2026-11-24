"""Correct a case's details after it is opened: its name and purpose, the forum and rules, the
date the law is assessed at, the parties and the issues to decide. Each change is recorded."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from eli_legal.domain.models import Matter, Party
from eli_legal.gui.widgets import button, card, label, row

ROLES = (
    "claimant",
    "respondent",
    "applicant",
    "appellant",
    "prosecution",
    "defence",
    "third party",
    "intervener",
)


class MatterDetailsDialog(QDialog):
    def __init__(self, parent: QWidget, matter: Matter, *, focus: str = "") -> None:
        super().__init__(parent)
        self.matter = matter
        self.setWindowTitle(f"Case details: {matter.name}")
        self.setMinimumSize(760, 640)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(matter.name)
        self.purpose = QLineEdit(matter.purpose)
        self.forum = QLineEdit(matter.forum)
        self.forum.setPlaceholderText("e.g. Arbitration seated in Dublin under the 2010 Act")
        self.rules = QLineEdit(matter.procedural_rules)
        self.rules.setPlaceholderText("e.g. UNCITRAL Arbitration Rules 2021")
        self.when = QDateEdit()
        self.when.setCalendarPopup(True)
        self.when.setDisplayFormat("d MMMM yyyy")
        given = matter.relevant_date
        self.when.setDate(
            QDate(given.year, given.month, given.day) if given else QDate.currentDate()
        )
        self.unset = QCheckBox("Not set")
        self.unset.setChecked(given is None)
        self.unset.toggled.connect(lambda on: self.when.setEnabled(not on))
        self.when.setEnabled(given is not None)
        form.addRow("Name", self.name)
        form.addRow("What it is for", self.purpose)
        form.addRow("Forum", self.forum)
        form.addRow("Rules", self.rules)
        form.addRow("Law assessed as at", row(self.when, self.unset, None))
        layout.addLayout(form)

        self.parties = QTableWidget(0, 2)
        self.parties.setHorizontalHeaderLabels(["Party", "Role"])
        self.parties.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.parties.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.parties.verticalHeader().setVisible(False)
        for party in matter.parties:
            self._add_party(party.name, party.role, party.party_id)
        layout.addWidget(
            card(
                "Parties",
                label(
                    "Double-click a name or role to correct it. A party someone acts for, or "
                    "whose papers or findings are in the case, can be renamed but not removed. "
                    f"Roles: {', '.join(ROLES)}, or your own word.",
                    "muted",
                    wrap=True,
                ),
                self.parties,
                row(
                    button("Add a party", lambda: self._add_party("", "", "", edit=True)),
                    button("Remove the selected party", self._remove_party),
                    None,
                ),
            ),
            1,
        )
        self.issues = QPlainTextEdit("\n".join(matter.stated_issues))
        self.issues.setPlaceholderText(
            "One issue per line, as a question the tribunal must answer, e.g.\n"
            "Was time of the essence of the delivery obligation?\n"
            "Was the notice of termination of 28 April 2023 valid?"
        )
        layout.addWidget(
            card(
                "Issues to decide",
                label(
                    "Framed here, the analysis follows the questions you need answered; left "
                    "empty, they are taken from the papers. A change applies from the next run.",
                    "muted",
                    wrap=True,
                ),
                self.issues,
            ),
            1,
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if focus == "issues":
            self.issues.setFocus(Qt.FocusReason.OtherFocusReason)

    def _add_party(self, name: str, role: str, party_id: str, *, edit: bool = False) -> None:
        at = self.parties.rowCount()
        self.parties.insertRow(at)
        first = QTableWidgetItem(name)
        first.setData(Qt.ItemDataRole.UserRole, party_id)
        self.parties.setItem(at, 0, first)
        self.parties.setItem(at, 1, QTableWidgetItem(role))
        if edit:
            self.parties.setCurrentCell(at, 0)
            self.parties.editItem(first)

    def _remove_party(self) -> None:
        at = self.parties.currentRow()
        if at >= 0:
            self.parties.removeRow(at)

    # ── what was chosen ──────────────────────────────────────────────────────
    def chosen_parties(self) -> list[Party]:
        kept = {p.party_id: p for p in self.matter.parties}
        out = []
        for at in range(self.parties.rowCount()):
            name_item, role_item = self.parties.item(at, 0), self.parties.item(at, 1)
            name = name_item.text().strip() if name_item else ""
            role = role_item.text().strip() if role_item else ""
            if not name and not role:
                continue
            party_id = str(name_item.data(Qt.ItemDataRole.UserRole) or "") if name_item else ""
            before = kept.get(party_id)
            party = Party(name=name, role=role)
            if before is not None:
                party.party_id = before.party_id
                party.represented_by = before.represented_by
            out.append(party)
        return out

    def chosen_issues(self) -> list[str]:
        return [line.strip() for line in self.issues.toPlainText().splitlines() if line.strip()]

    def chosen_date(self) -> date | None:
        if self.unset.isChecked():
            return None
        d = self.when.date()
        return date(d.year(), d.month(), d.day())
