from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from eli_legal.adapters.sources import live
from eli_legal.domain import glossary
from eli_legal.domain.models import Authority, AuthorityPassage
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import button, card, fill, fit, label, row, selected_id, table
from eli_legal.legal.source_registry import RegisteredSource


class _SourceDialog(QDialog):
    """A collection of legal texts of your own: every field in plain words, with an example."""

    # (field, caption, what it means and an example, required)
    FIELDS: tuple[tuple[str, str, str, bool], ...] = (
        ("source_id", "Short name",
         "A short name the system uses, without spaces. For example: our_judgments", True),
        ("name", "Full name",
         "What people will see. For example: Our firm's collection of employment judgments", True),
        ("jurisdictions", "Legal systems it covers", "", True),
        ("owner", "Who publishes it",
         "Who the material comes from. For example: our own firm, or a court's website", True),
        ("licence", "Licence or terms of use",
         "The terms under which you may use it. For example: Open Government Licence v3.0, "
         "or: our own documents", True),
        ("status", "How it says whether law is still in force",
         "For example: each judgment notes whether it was later overruled, as at the date "
         "shown. If it does not say, write: it does not say", True),
        ("freshness", "How often it is brought up to date",
         "For example: checked every month", False),
        ("complete_for", "Complete for (advanced)",
         "Leave this empty unless the collection holds every judgment of a kind. Then a "
         "citation of that kind that is not found here is treated as possibly wrong.", False),
        ("inspection", "Where the original can be read",
         "For example: a web address where each text can be read in full", False),
    )  # fmt: skip

    def __init__(self, parent: QWidget, jurisdictions: list[tuple[str, str]]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add your own collection of legal texts")
        self.resize(720, 780)
        outer = QVBoxLayout(self)
        outer.addWidget(
            label(
                "Use this for Acts and judgments you hold yourself. For the official EU or UK "
                "databases, use “Add an official database” instead. A source can be approved "
                "only once these are filled in; rest the pointer on any field for an explanation.",
                "muted",
                wrap=True,
            )
        )
        codes = "; ".join(f"{code} = {name}" for code, name in jurisdictions)
        page = QWidget()
        column = QVBoxLayout(page)
        self.fields: dict[str, QLineEdit] = {}
        for key, caption, hint, required in self.FIELDS:
            if key == "jurisdictions":
                hint = f"Codes separated by commas. Available: {codes}"
            field = QLineEdit()
            example = hint.split("For example: ", 1)[1] if "For example: " in hint else ""
            field.setPlaceholderText(example)
            field.setToolTip(glossary.tooltip(caption, hint) or hint)
            self.fields[key] = field
            column.addWidget(label(f"<b>{caption}</b>" + ("" if required else " (optional)")))
            column.addWidget(field)
            column.addWidget(label(hint, "muted", wrap=True))
            column.addSpacing(6)
        column.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)
        self.terms = QCheckBox("I have read the licence or terms, and they allow this use")
        self.terms.setToolTip(glossary.tooltip("Licence"))
        outer.addWidget(self.terms)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Add it")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

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


class _OfficialDialog(QDialog):
    """An official database, with everything about it already filled in: read its licence."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add an official database")
        self.setMinimumWidth(640)
        box = QVBoxLayout(self)
        box.addWidget(
            label(
                "These are the official, free databases of legislation and judgments. ELI Legal "
                "looks up each Act or judgment a case relies on there when it is first needed, "
                "and only from that database's own website. Choose one, read its licence, and "
                "add it. An administrator then approves it on this page.",
                wrap=True,
            )
        )
        self.choice = QComboBox()
        for kind in live.CONNECTORS:
            preset = live.preset(kind, kind)
            self.choice.addItem(preset.name, kind)
        self.choice.currentIndexChanged.connect(self._show)
        box.addWidget(self.choice)
        self.about = label("", wrap=True, selectable=True)
        box.addWidget(card("Its licence", self.about))
        self.read = QCheckBox("I have read the licence, and it allows this use")
        box.addWidget(self.read)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Add it")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        box.addWidget(buttons)
        self._show()

    def _show(self) -> None:
        preset = live.preset(self.kind, self.kind)
        self.about.setText(
            f"<b>Published by:</b> {preset.authority_owner}<br>"
            f"<b>Covers:</b> {', '.join(sorted(preset.jurisdictions))}<br>"
            f"<b>Licence:</b> {preset.licence}<br><b>What it can tell:</b> "
            f"{preset.treatment_semantics}"
        )

    @property
    def kind(self) -> str:
        return str(self.choice.currentData())

    def source(self) -> RegisteredSource:
        return replace(live.preset(self.kind, self.kind), terms_reviewed=self.read.isChecked())


class SourcesTab(Tab):
    title = "📚 Sources"

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.sources = table(
            [
                "Short name",
                "Name",
                "Legal systems",
                "State",
                "Approved by",
                "Licence",
                "How it says whether law is still in force",
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
                "Legal sources — the only places the law is read from",
                label(
                    "Add where the law comes from, then approve it. Nothing that is not approved "
                    "is ever read. Most people need only an official database.",
                    "muted",
                    wrap=True,
                ),
                self.sources,
                row(
                    button(
                        "Add an official database (EU or UK)…",
                        self._official,
                        kind="primary",
                        tip="The free official databases of legislation and judgments",
                    ),
                    button(
                        "Add your own collection…",
                        self._register,
                        tip="Acts and judgments you hold yourself",
                    ),
                    button(
                        "Approve…",
                        self._approve,
                        tip="Allow the selected source to be read. A decision in your name.",
                    ),
                    button("Revoke", self._revoke, kind="danger", tip="Stop it being read"),
                    button(
                        "Load texts into it from a folder…",
                        self._import,
                        tip="For your own collection: a folder of prepared records (*.json)",
                    ),
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

    def _official(self) -> None:
        dialog = _OfficialDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.session.attempt(
                self, lambda: self.sv.sources.register(dialog.source(), actor_id=self.actor)
            )

    def _register(self) -> None:
        registry = self.sv.ctx.jurisdictions
        dialog = _SourceDialog(self, [(c, registry.get(c).name) for c in registry.codes()])
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
