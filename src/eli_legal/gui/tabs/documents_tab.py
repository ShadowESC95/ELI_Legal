from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from eli_legal.domain import plain
from eli_legal.domain.enums import AccessScope, DocumentStatus, DocumentType
from eli_legal.domain.models import Document
from eli_legal.gui import theme
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import button, card, fill, fit, label, row, selected_id, table

# Files a folder carries that are not evidence: system and editor leftovers.
_JUNK = {"thumbs.db", "desktop.ini", ".ds_store", "icon\r"}


def collect(paths: list[str]) -> tuple[list[Path], list[str]]:
    """Every file in what was given (folders searched all the way down), and what was left out
    and why: hidden files, system leftovers, an Office lock file, an empty file."""
    files: list[Path] = []
    skipped: list[str] = []
    seen: set[Path] = set()

    def consider(path: Path) -> None:
        name = path.name
        if name.startswith(".") or name.lower() in _JUNK:
            skipped.append(f"{name}: a hidden or system file")
        elif name.startswith("~$"):
            skipped.append(f"{name}: a lock file an open Office document leaves behind")
        elif path.stat().st_size == 0:
            skipped.append(f"{name}: empty")
        elif path.resolve() not in seen:
            seen.add(path.resolve())
            files.append(path)

    for given in paths:
        root = Path(given)
        if root.is_dir():
            for path in sorted(root.rglob("*")):
                if any(part.startswith(".") for part in path.relative_to(root).parts[:-1]):
                    continue  # inside a hidden folder
                if path.is_file():
                    consider(path)
        elif root.is_file():
            consider(root)
    return files, skipped


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
        # Drop files or whole folders anywhere on this page.
        self.setAcceptDrops(True)
        self.drop = QLabel(
            "⬇  Drop files or folders here, or use Add files… / Add a folder…  "
            "Folders are searched all the way down; you check each document before it is taken in."
        )
        self.drop.setWordWrap(True)
        self.drop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop.setMinimumHeight(54)
        self._drop_style(False)
        self.root.addWidget(
            card(
                "Take documents into this matter",
                self.drop,
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
        fit(self.docs, [44, 0, 120, 150, 190, 66, 140, 90])
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

    # ── dropping files and folders ───────────────────────────────────────────
    def _drop_style(self, active: bool) -> None:
        colour = theme.ACCENT if active else theme.BORDER
        self.drop.setStyleSheet(
            f"QLabel {{ border: 2px dashed {colour}; border-radius: 10px; padding: 10px; "
            f"color: {theme.ACCENT if active else theme.MUTED}; }}"
        )

    @staticmethod
    def _local(event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> list[str]:
        mime = event.mimeData()
        if not mime.hasUrls():
            return []
        return [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - Qt's name
        if self._local(event) and self.session.matter is not None:
            event.acceptProposedAction()
            self._drop_style(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802 - Qt's name
        if self._local(event):
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802 - Qt's name
        self._drop_style(False)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - Qt's name
        self._drop_style(False)
        paths = self._local(event)
        if paths:
            event.acceptProposedAction()
            self._ingest(paths)

    def _ingest(self, paths: list[str]) -> None:
        """Ask, file by file, what each document is, who filed it and who may see it, then
        take them in, in the background, and say plainly what happened to each."""
        matter = self.session.matter
        if matter is None or not paths:
            if matter is None and paths:
                QMessageBox.information(self, "No matter open", "Open a matter first.")
            return
        if self.session.working:
            QMessageBox.information(
                self, "Still reading", "Documents are still being taken in; add these after."
            )
            return
        files, skipped = collect(paths)
        if not files:
            QMessageBox.information(
                self,
                "Nothing to add",
                "There was no document to take in."
                + ("\n\nLeft out:\n" + "\n".join(skipped[:30]) if skipped else ""),
            )
            return
        intake = IntakeDialog(
            self,
            files,
            parties=[(p.party_id, f"{p.name} ({p.role})") for p in matter.parties],
            kind=self.kind.currentData() or "",
            party=self.party.currentData() or "",
            scope=self.scope.currentData(),
            custodian=self.custodian.text().strip(),
            skipped=skipped,
        )
        if intake.exec() != QDialog.DialogCode.Accepted:
            return
        plan = intake.plan()
        if not plan:
            return
        busy = self.session.busy

        def work() -> list[Document]:
            out: list[Document] = []
            for n, item in enumerate(plan, start=1):
                busy.emit(f"Reading {n} of {len(plan)}: {Path(item['path']).name}")
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

        def done(taken: object) -> None:
            self.session.notify()
            if isinstance(taken, list) and taken:
                QMessageBox.information(self, "Documents taken in", _outcome(taken))

        def failed(exc: Exception) -> None:
            self.session.notify()
            QMessageBox.warning(
                self, "Could not take them all in", f"{type(exc).__name__}\n\n{exc}"
            )

        # Reading a long scan by OCR takes a while: it runs off the window's thread, as the
        # person who filed it, and the status line counts the documents as they are read.
        self.session.background(
            f"Reading {plain.count(len(plan), 'document')}…", work, done, failed
        )

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
        skipped: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add documents")
        self.setMinimumSize(1040, 480)
        layout = QVBoxLayout(self)
        size = sum(f.stat().st_size for f in files)
        layout.addWidget(
            label(
                f"<b>{plain.count(len(files), 'document')}, {size / 1_048_576:.1f} MB.</b> "
                "Check each before it is taken in. Who may see it decides who on the matter can "
                "read it and whether it can ever appear in a shared report; hover over a choice "
                "for what it means. Originals are stored once, read-only; the same file filed "
                "twice is one document.",
                wrap=True,
            )
        )
        if skipped:
            note = label(
                f"Left out ({len(skipped)}): "
                + "; ".join(skipped[:8])
                + (" …" if len(skipped) > 8 else ""),
                "muted",
                wrap=True,
            )
            note.setToolTip("\n".join(skipped))
            layout.addWidget(note)
        self._parties = parties
        # Set one choice for every row, or for the rows selected.
        self.all_kind = self._kinds(kind)
        self.all_filer = self._filers(party)
        self.all_scope = self._scopes(scope)
        self.all_where = QLineEdit(custodian)
        self.all_where.setPlaceholderText("Where it came from")
        apply = QPushButton("Set for all (or the selected rows)")
        apply.clicked.connect(self._apply)
        remove = QPushButton("Leave the selected rows out")
        remove.clicked.connect(self._remove)
        bar = QHBoxLayout()
        for text, widget in (
            ("What it is", self.all_kind),
            ("Filed by", self.all_filer),
            ("Who may see it", self.all_scope),
        ):
            bar.addWidget(label(text))
            bar.addWidget(widget)
        bar.addWidget(self.all_where, 1)
        bar.addWidget(apply)
        bar.addWidget(remove)
        layout.addLayout(bar)
        self.files = files
        self.grid = QTableWidget(len(files), 5)
        self.grid.setHorizontalHeaderLabels(
            ["File", "What it is", "Filed by", "Who may see it", "Where it came from"]
        )
        self.grid.verticalHeader().setVisible(False)
        self.grid.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for r, path in enumerate(files):
            name = QTableWidgetItem(str(path.name))
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name.setToolTip(str(path))
            name.setData(Qt.ItemDataRole.UserRole, str(path))
            self.grid.setItem(r, 0, name)
            self.grid.setCellWidget(r, 1, self._kinds(kind))
            self.grid.setCellWidget(r, 2, self._filers(party))
            self.grid.setCellWidget(r, 3, self._scopes(scope))
            self.grid.setItem(r, 4, QTableWidgetItem(custodian))
        self.grid.resizeColumnsToContents()
        layout.addWidget(self.grid, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._count()
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── the choices ──────────────────────────────────────────────────────────
    @staticmethod
    def _kinds(value: str) -> QComboBox:
        box = QComboBox()
        box.addItem("Work it out from the document", "")
        for doc_type in DocumentType:
            box.addItem(plain.kind(doc_type), doc_type.value)
        box.setCurrentIndex(max(0, box.findData(value)))
        return box

    def _filers(self, value: str) -> QComboBox:
        box = QComboBox()
        box.addItem("(nobody in particular)", "")
        for party_id, text in self._parties:
            box.addItem(text, party_id)
        box.setCurrentIndex(max(0, box.findData(value)))
        return box

    @staticmethod
    def _scopes(value: str) -> QComboBox:
        box = QComboBox()
        for access_scope in AccessScope:
            box.addItem(plain.scope(access_scope), access_scope.value)
            box.setItemData(
                box.count() - 1, plain.scope_meaning(access_scope), Qt.ItemDataRole.ToolTipRole
            )
        box.setCurrentIndex(max(0, box.findData(value)))
        return box

    def _rows(self) -> list[int]:
        chosen = sorted({i.row() for i in self.grid.selectionModel().selectedRows()})
        return chosen or list(range(self.grid.rowCount()))

    def _apply(self) -> None:
        for r in self._rows():
            for column, source in ((1, self.all_kind), (2, self.all_filer), (3, self.all_scope)):
                box = self.grid.cellWidget(r, column)
                if isinstance(box, QComboBox):
                    box.setCurrentIndex(max(0, box.findData(source.currentData())))
            self.grid.setItem(r, 4, QTableWidgetItem(self.all_where.text().strip()))

    def _remove(self) -> None:
        for r in sorted({i.row() for i in self.grid.selectionModel().selectedRows()}, reverse=True):
            self.grid.removeRow(r)
        self._count()

    def _count(self) -> None:
        n = self.grid.rowCount()
        self.ok.setText(f"Take in {plain.count(n, 'document')}")
        self.ok.setEnabled(n > 0)

    def plan(self) -> list[dict[str, str]]:
        out = []
        for r in range(self.grid.rowCount()):
            name = self.grid.item(r, 0)
            path = name.data(Qt.ItemDataRole.UserRole) if name else ""
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
