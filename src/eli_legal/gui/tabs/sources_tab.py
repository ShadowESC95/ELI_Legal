from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QSplitter,
    QWidget,
)

from eli_legal.domain.models import Authority, AuthorityPassage
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import button, card, fill, fit, label, row, selected_id, table
from eli_legal.legal.source_registry import RegisteredSource


class _SourceDialog(QDialog):
    def __init__(self, parent: QWidget, jurisdictions: list[str]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Register a legal source")
        self.setMinimumWidth(560)
        form = QFormLayout(self)
        form.addRow(
            label(
                "A source can only be approved once its publisher, licence, coverage and what its status answers mean are recorded.",
                "muted",
                wrap=True,
            )
        )
        self.fields = {
            name: QLineEdit()
            for name in (
                "source_id",
                "name",
                "jurisdictions",
                "owner",
                "licence",
                "status",
                "freshness",
                "complete_for",
                "inspection",
            )
        }
        self.fields["jurisdictions"].setPlaceholderText(
            f"comma-separated, e.g. {', '.join(jurisdictions[:3])}"
        )
        self.fields["complete_for"].setPlaceholderText(
            "citation pattern ids for which “not found” means “does not exist” (optional)"
        )
        self.terms = QCheckBox("The licence or terms have been reviewed and permit this use")
        for caption, key in (
            ("Identifier", "source_id"),
            ("Name", "name"),
            ("Jurisdictions", "jurisdictions"),
            ("Published by", "owner"),
            ("Licence / terms", "licence"),
            ("What a status answer means", "status"),
            ("How current it is", "freshness"),
            ("Complete for", "complete_for"),
            ("How to inspect the original", "inspection"),
        ):
            form.addRow(caption, self.fields[key])
        form.addRow("", self.terms)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def source(self) -> RegisteredSource:
        value = {k: w.text().strip() for k, w in self.fields.items()}
        return RegisteredSource(
            source_id=value["source_id"],
            name=value["name"] or value["source_id"],
            jurisdictions=frozenset(
                j.strip() for j in value["jurisdictions"].split(",") if j.strip()
            ),
            authority_owner=value["owner"],
            licence=value["licence"],
            terms_reviewed=self.terms.isChecked(),
            treatment_semantics=value["status"],
            freshness=value["freshness"],
            authoritative_for=tuple(
                p.strip() for p in value["complete_for"].split(",") if p.strip()
            ),
            inspection=value["inspection"],
        )


class SourcesTab(Tab):
    title = "📚 Sources"

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.sources = table(
            [
                "Source",
                "Name",
                "Covers",
                "State",
                "Approved by",
                "Licence",
                "What its status answers mean",
            ],
            stretch=6,
        )
        self.sources.itemSelectionChanged.connect(self._show)
        self.authorities = table(
            [
                "Citation",
                "Title",
                "Kind",
                "Court",
                "Date",
                "Status",
                "Status last confirmed",
                "In force",
            ],
            stretch=1,
        )
        self.authorities.itemSelectionChanged.connect(self._text)
        self.reader = QPlainTextEdit()
        self.reader.setReadOnly(True)
        self.root.addWidget(
            card(
                "Approved-source register — the only legal sources the system may read",
                self.sources,
                row(
                    button("Register a source…", self._register),
                    button("Approve…", self._approve, kind="primary"),
                    button("Revoke", self._revoke, kind="danger"),
                    button("Load authorities from a folder…", self._import),
                    None,
                ),
            )
        )
        split = QSplitter()
        split.addWidget(card("What the selected source holds", self.authorities))
        split.addWidget(card("Text", self.reader))
        split.setSizes([760, 440])
        self.root.addWidget(split, 1)

    def refresh(self) -> None:
        sources = self.sv.sources.list()
        fill(
            self.sources,
            [
                [
                    s.source_id,
                    s.name,
                    ", ".join(sorted(s.jurisdictions)),
                    "approved" if s.approved else "registered",
                    s.approved_by or "",
                    s.licence,
                    s.treatment_semantics,
                ]
                for s in sources
            ],
            ids=[s.source_id for s in sources],
            state_columns=[3],
        )
        fit(self.sources, [180, 230, 80, 90, 110, 260, 0])
        self._show()

    def _show(self) -> None:
        source_id = selected_id(self.sources)
        self.reader.clear()
        if not source_id or not self.actor:
            fill(self.authorities, [])
            return
        authorities: list[Authority] = (
            self.session.attempt(
                self,
                lambda: self.sv.sources.authorities(source_id, actor_id=self.actor),
                quiet=True,
            )
            or []
        )
        fill(
            self.authorities,
            [
                [
                    a.citation,
                    a.title,
                    a.kind.value,
                    a.court,
                    a.decision_date or "",
                    a.status.value,
                    a.status_checked_at.date().isoformat() if a.status_checked_at else "never",
                    f"{a.effective_from or ''} → {a.effective_to or ''}"
                    if (a.effective_from or a.effective_to)
                    else "",
                ]
                for a in authorities
            ],
            ids=[a.authority_id for a in authorities],
            state_columns=[5],
            keep_selection=False,
        )
        fit(self.authorities, [200, 0, 90, 190, 90, 90, 150, 170])
        self._authorities = {a.authority_id: a for a in authorities}

    def _text(self) -> None:
        authority = getattr(self, "_authorities", {}).get(selected_id(self.authorities))
        if authority is None:
            return
        passages: list[AuthorityPassage] = (
            self.session.attempt(
                self,
                lambda: self.sv.sources.authority_text(authority.authority_id, actor_id=self.actor),
                quiet=True,
            )
            or []
        )
        history = "\n".join(
            f"   {t.effective_date}: {t.treatment}"
            + (f" by {t.by_citation}" if t.by_citation else "")
            for t in authority.treatments
        )
        head = f"{authority.citation} — {authority.title}\nStatus: {authority.status.value}; basis: {authority.status_basis or 'not stated'}"
        self.reader.setPlainText(
            head
            + (f"\nHistory:\n{history}" if history else "")
            + "\n\n"
            + "\n\n".join(f"{p.locator}  {p.text}" for p in passages)
        )

    def _register(self) -> None:
        dialog = _SourceDialog(self, self.sv.ctx.jurisdictions.codes())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.session.attempt(
                self, lambda: self.sv.sources.register(dialog.source(), actor_id=self.actor)
            )

    def _approve(self) -> None:
        source_id = selected_id(self.sources)
        if source_id:
            self.session.decide(
                self,
                f"approve the legal source “{source_id}”",
                lambda: self.sv.sources.approve(source_id, actor_id=self.actor),
            )

    def _revoke(self) -> None:
        source_id = selected_id(self.sources)
        if source_id:
            self.session.attempt(
                self, lambda: self.sv.sources.revoke(source_id, actor_id=self.actor)
            )

    def _import(self) -> None:
        source_id = selected_id(self.sources)
        if not source_id:
            return
        folder = QFileDialog.getExistingDirectory(self, "Folder of authority records (*.json)")
        if folder:
            self.session.attempt(
                self, lambda: self.sv.sources.import_corpus(source_id, folder, actor_id=self.actor)
            )
