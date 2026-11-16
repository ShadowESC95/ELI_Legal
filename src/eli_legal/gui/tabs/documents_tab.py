from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from eli_legal.domain import plain
from eli_legal.domain.enums import AccessScope, DocumentStatus, DocumentType
from eli_legal.domain.models import Document
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import button, card, fill, fit, label, row, selected_id, table


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
        for scope in AccessScope:
            self.scope.addItem(plain.scope(scope), scope.value)
            self.scope.setItemData(
                self.scope.count() - 1, plain.scope_meaning(scope), Qt.ItemDataRole.ToolTipRole
            )
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
                    button("Re-read from the original", self._reread),
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
                    plain.kind(d.doc_type),
                    names.get(d.party_id or "", d.custodian or "—"),
                    plain.state(d.status)
                    + (
                        "; page(s) "
                        + ", ".join(
                            f"{n} ({c:g}%)"
                            for n, c in sorted(d.ocr_pages.items(), key=lambda kv: int(kv[0]))
                        )
                        + " read by OCR: check quotations against the original"
                        if d.ocr_pages
                        else ""
                    )
                    + (f": {d.error}" if d.error else ""),
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
            f"{plain.count(len(docs), 'document')}: {len(docs) - len(unread)} read, "
            f"{len(unread)} not read"
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
        """Ask, file by file, what each document is, who filed it and who may see it, then
        take them in and say plainly what happened to each."""
        matter = self.session.matter
        if matter is None or not paths:
            return
        files: list[Path] = []
        for path in paths:
            root = Path(path)
            files += (
                sorted(f for f in root.rglob("*") if f.is_file() and not f.name.startswith("."))
                if root.is_dir()
                else [root]
            )
        if not files:
            return
        intake = IntakeDialog(
            self,
            files,
            parties=[(p.party_id, f"{p.name} ({p.role})") for p in matter.parties],
            kind=self.kind.currentData() or "",
            party=self.party.currentData() or "",
            scope=self.scope.currentData(),
            custodian=self.custodian.text().strip(),
        )
        if intake.exec() != QDialog.DialogCode.Accepted:
            return
        plan = intake.plan()

        def work() -> list[Document]:
            out: list[Document] = []
            for item in plan:
                out += self.sv.ingestion.ingest_path(
                    matter=matter,
                    actor_id=self.actor,
                    path=item["path"],
                    doc_type=DocumentType(item["kind"]) if item["kind"] else None,
                    party_id=item["party"] or None,
                    access_scope=AccessScope(item["scope"]),
                    custodian=item["custodian"],
                )
            return out

        taken = self.session.attempt(self, work)
        if taken:
            QMessageBox.information(self, "Documents taken in", _outcome(taken))

    def _reread(self) -> None:
        """Read the chosen document again from its stored original: after an upgrade of the
        reader, or once OCR is installed. Nothing has to be added again."""
        document_id = selected_id(self.docs)
        if not document_id:
            return
        self.session.attempt(
            self,
            lambda: self.sv.ingestion.reread(
                self.mid, document_id, actor_id=self.actor, why="asked for on the Documents page"
            ),
        )
        self.session.notify()

    def _files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add documents")
        self._ingest(paths)

    def _folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Add every document in a folder")
        self._ingest([path] if path else [])


def _outcome(documents: list[Document]) -> str:
    """What happened to each document, as a person would want to be told."""
    read = [d for d in documents if d.status is DocumentStatus.PROCESSED]
    unread = [d for d in documents if d.status is not DocumentStatus.PROCESSED]
    flagged = [d for d in documents if d.injection_flags]
    lines = [f"{plain.count(len(read), 'document')} read."]
    if unread:
        lines.append(
            f"{plain.count(len(unread), 'document')} could not be read. Each will hold the "
            "analysis until someone accepts the gap or adds a readable copy:"
        )
        lines += [f"  • {d.filename}: {d.error or plain.state(d.status)}" for d in unread]
    if flagged:
        lines.append(
            f"{plain.count(len(flagged), 'document contains', 'documents contain')} text that "
            "looks addressed to an AI system. It is kept as evidence; nothing in it reaches a "
            "model until a person has looked at it:"
        )
        lines += [f"  • {d.filename}" for d in flagged]
    return "\n".join(lines)


class IntakeDialog(QDialog):
    """One row per file: what it is, who filed it, who may see it, where it came from."""

    def __init__(
        self,
        parent: QWidget,
        files: list[Path],
        *,
        parties: list[tuple[str, str]],
        kind: str,
        party: str,
        scope: str,
        custodian: str,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add documents")
        self.setMinimumSize(980, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(
            label(
                "Check each document before it is taken in. Who may see it decides who on the "
                "matter can read it and whether it can ever appear in a shared report; hover "
                "over a choice for what it means. Originals are stored once, read-only.",
                wrap=True,
            )
        )
        self.files = files
        self.grid = QTableWidget(len(files), 5)
        self.grid.setHorizontalHeaderLabels(
            ["File", "What it is", "Filed by", "Who may see it", "Where it came from"]
        )
        self.grid.verticalHeader().setVisible(False)
        self.grid.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for r, path in enumerate(files):
            name = QTableWidgetItem(path.name)
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name.setToolTip(str(path))
            self.grid.setItem(r, 0, name)
            kinds = QComboBox()
            kinds.addItem("Work it out from the document", "")
            for doc_type in DocumentType:
                kinds.addItem(plain.kind(doc_type), doc_type.value)
            kinds.setCurrentIndex(max(0, kinds.findData(kind)))
            self.grid.setCellWidget(r, 1, kinds)
            filer = QComboBox()
            filer.addItem("(nobody in particular)", "")
            for party_id, text in parties:
                filer.addItem(text, party_id)
            filer.setCurrentIndex(max(0, filer.findData(party)))
            self.grid.setCellWidget(r, 2, filer)
            scopes = QComboBox()
            for access_scope in AccessScope:
                scopes.addItem(plain.scope(access_scope), access_scope.value)
                scopes.setItemData(
                    scopes.count() - 1,
                    plain.scope_meaning(access_scope),
                    Qt.ItemDataRole.ToolTipRole,
                )
            scopes.setCurrentIndex(max(0, scopes.findData(scope)))
            self.grid.setCellWidget(r, 3, scopes)
            self.grid.setItem(r, 4, QTableWidgetItem(custodian))
        self.grid.resizeColumnsToContents()
        layout.addWidget(self.grid, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            f"Take in {plain.count(len(files), 'document')}"
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def plan(self) -> list[dict[str, str]]:
        out = []
        for r, path in enumerate(self.files):
            kinds, filer, scopes = (self.grid.cellWidget(r, c) for c in (1, 2, 3))
            where = self.grid.item(r, 4)
            out.append(
                {
                    "path": str(path),
                    "kind": kinds.currentData() if isinstance(kinds, QComboBox) else "",
                    "party": filer.currentData() if isinstance(filer, QComboBox) else "",
                    "scope": scopes.currentData() if isinstance(scopes, QComboBox) else "",
                    "custodian": where.text().strip() if where else "",
                }
            )
        return out
