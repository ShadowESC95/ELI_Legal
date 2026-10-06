from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFileDialog, QLineEdit, QPlainTextEdit, QSplitter

from eli_legal.domain.enums import AccessScope, DocumentType
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import button, card, fill, fit, label, row, selected_id, table

_SCOPES = {
    AccessScope.ALL_PARTIES: "Before all parties",
    AccessScope.NEUTRAL_ONLY: "The neutral's own note",
    AccessScope.PARTY_CONFIDENTIAL: "Given in confidence by one party",
    AccessScope.PRIVILEGED: "Privileged",
}


class DocumentsTab(Tab):
    title = "📄 Evidence"

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.party = QComboBox()
        self.kind = QComboBox()
        self.kind.addItem("Work it out from the document", "")
        for doc_type in DocumentType:
            self.kind.addItem(doc_type.value.replace("_", " ").capitalize(), doc_type.value)
        self.scope = QComboBox()
        for scope, text in _SCOPES.items():
            self.scope.addItem(text, scope.value)
        self.custodian = QLineEdit()
        self.custodian.setPlaceholderText("Where it came from (chain of custody)")
        self.coverage = label("", wrap=True)
        self.docs = table(
            ["Ref", "Document", "Type", "From", "Status", "Passages", "Flags", "SHA-256"], stretch=1
        )
        self.docs.itemSelectionChanged.connect(self._show)
        self.passages = table(["Where", "Text (as read from the document)"])
        self.passages.itemSelectionChanged.connect(self._passage)
        self.reader = QPlainTextEdit()
        self.reader.setReadOnly(True)
        self.root.addWidget(
            card(
                "Take documents into this matter",
                row(
                    label("Filed by"),
                    self.party,
                    label("Type"),
                    self.kind,
                    label("Who may see it"),
                    self.scope,
                    self.custodian,
                    stretch_last=True,
                ),
                row(
                    button("Add files…", self._files, kind="primary"),
                    button("Add a folder…", self._folder),
                    self.coverage,
                    stretch_last=True,
                ),
            )
        )
        lower = QSplitter()
        lower.addWidget(card("Passages of the selected document", self.passages))
        lower.addWidget(card("Passage", self.reader))
        lower.setSizes([640, 420])
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(
            card("Documents (originals are stored once, read-only, by hash)", self.docs)
        )
        split.addWidget(lower)
        split.setSizes([330, 300])
        self.root.addWidget(split, 1)

    def refresh(self) -> None:
        matter = self.session.matter
        self.party.clear()
        self.party.addItem("(nobody in particular)", "")
        if matter is None:
            fill(self.docs, [])
            fill(self.passages, [])
            self.coverage.setText("Open a matter first.")
            return
        for party in matter.parties:
            self.party.addItem(f"{party.name} ({party.role})", party.party_id)
        names = {p.party_id: p.name for p in matter.parties}
        docs = (
            self.session.attempt(
                self, lambda: self.sv.matters.documents(self.mid, self.actor), quiet=True
            )
            or []
        )
        fill(
            self.docs,
            [
                [
                    f"D{i}",
                    d.title or d.filename,
                    d.doc_type.value.replace("_", " "),
                    names.get(d.party_id or "", d.custodian or "—"),
                    d.status.value + (f": {d.error}" if d.error else ""),
                    d.segment_count,
                    ", ".join(d.injection_flags),
                    d.sha256[:16],
                ]
                for i, d in enumerate(docs, start=1)
            ],
            ids=[d.document_id for d in docs],
            state_columns=[4],
        )
        fit(self.docs, [44, 0, 130, 170, 210, 70, 190, 130])
        unread = [d for d in docs if d.status.value not in ("processed", "waived")]
        flagged = [d for d in docs if d.injection_flags]
        self.coverage.setText(
            f"{len(docs)} document(s): {len(docs) - len(unread)} read, {len(unread)} not read"
            + (f", {len(flagged)} flagged for text addressed to an AI system" if flagged else "")
            + ". A document that was not read holds the run until someone accepts the gap."
            if docs
            else "No documents yet."
        )
        self._show()

    def _show(self) -> None:
        document_id = selected_id(self.docs)
        self.reader.clear()
        if not document_id:
            fill(self.passages, [])
            return
        chunks = (
            self.session.attempt(
                self,
                lambda: self.sv.matters.passages(self.mid, document_id, self.actor),
                quiet=True,
            )
            or []
        )
        fill(
            self.passages,
            [[c.locator, c.text] for c in chunks],
            ids=[c.chunk_id for c in chunks],
            keep_selection=False,
        )
        fit(self.passages, [90, 0])
        self._chunks = {c.chunk_id: c for c in chunks}

    def _passage(self) -> None:
        chunk = getattr(self, "_chunks", {}).get(selected_id(self.passages))
        if chunk is not None:
            self.reader.setPlainText(f"{chunk.locator}\n\n{chunk.text}")

    def _ingest(self, paths: list[str]) -> None:
        matter = self.session.matter
        if matter is None or not paths:
            return
        kind = self.kind.currentData()

        def work() -> int:
            count = 0
            for path in paths:
                count += len(
                    self.sv.ingestion.ingest_path(
                        matter=matter,
                        actor_id=self.actor,
                        path=path,
                        doc_type=DocumentType(kind) if kind else None,
                        party_id=self.party.currentData() or None,
                        access_scope=AccessScope(self.scope.currentData()),
                        custodian=self.custodian.text().strip(),
                    )
                )
            return count

        self.session.attempt(self, work)

    def _files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add documents")
        self._ingest(paths)

    def _folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Add every document in a folder")
        self._ingest([path] if path else [])
