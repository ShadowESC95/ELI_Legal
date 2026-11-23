"""Released to me: the reports released to the signed-in person, to read on screen or save as a
PDF, a Word document or Markdown. Every reading and copy is recorded, and each copy carries the
name of the person who took it. See ``CollectionService``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QSplitter, QTextBrowser

from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import button, card, fill, label, row, selected_id, table

_FILTERS = {
    "pdf": "PDF document (*.pdf)",
    "docx": "Word document (*.docx)",
    "md": "Markdown (*.md)",
}


class ReleasedTab(Tab):
    title = "📬 Released to me"

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.list = table(["Case", "Version", "Released", "Approved by", "State"], stretch=0)
        self.list.itemSelectionChanged.connect(self._picked)
        self.reader = QTextBrowser()
        self.reader.setOpenExternalLinks(False)
        self.note = label("", "muted", wrap=True)
        self.open_btn = button("Read it", self._read, kind="go")
        self.pdf_btn = button("Save as PDF…", lambda: self._save("pdf"))
        self.docx_btn = button("Save as Word…", lambda: self._save("docx"))
        self.md_btn = button("Save as Markdown…", lambda: self._save("md"))
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(
            card(
                "Reports released to you",
                label(
                    "An approved report reaches you here once a named person has released it to "
                    "you. Nothing is e-mailed. Each reading and each copy is recorded under your "
                    "name, and each copy is stamped with it; do not pass a copy to anyone the "
                    "release does not name.",
                    "muted",
                    wrap=True,
                ),
                self.list,
                self.note,
                row(self.open_btn, self.pdf_btn, self.docx_btn, self.md_btn, None),
            )
        )
        split.addWidget(card("The report", self.reader))
        split.setStretchFactor(1, 2)
        self.root.addWidget(split)
        self._rows: dict[str, dict[str, Any]] = {}

    def refresh(self) -> None:
        rows = self.sv.released.mine(self.actor) if self.actor else []
        self._rows = {r["release_id"]: r for r in rows}
        fill(
            self.list,
            [
                [
                    r["matter_name"],
                    r["report_version"],
                    r["released_at"][:16].replace("T", " "),
                    r["approved_by"] or "",
                    ("collected" if r["collected"] else "new")
                    if r["can_open"]
                    else "cannot be opened",
                ]
                for r in rows
            ],
            ids=[r["release_id"] for r in rows],
        )
        if not rows:
            self.note.setText("Nothing has been released to you.")
        self._picked()

    def _current(self) -> dict[str, Any] | None:
        return self._rows.get(selected_id(self.list) or "")

    def _picked(self) -> None:
        r = self._current()
        ok = bool(r and r["can_open"])
        for widget in (self.open_btn, self.docx_btn, self.md_btn):
            widget.setEnabled(ok)
        self.pdf_btn.setEnabled(ok and r is not None and "pdf" in r["formats"])
        if r is not None:
            self.note.setText(
                f"Report SHA-256 {r['report_hash']} · {r['classification']}"
                if r["can_open"]
                else f"It cannot be opened now: {r['why_not']}."
            )

    def _read(self) -> None:
        r = self._current()
        if r is None:
            return
        text = self.session.attempt(
            self,
            lambda: self.sv.released.read(r["matter_id"], r["release_id"], self.actor),
            quiet=True,
        )
        if text is not None:
            self.reader.setMarkdown(text)
            self.refresh()

    def _save(self, fmt: str) -> None:
        r = self._current()
        if r is None:
            return
        got = self.session.attempt(
            self,
            lambda: self.sv.released.collect(r["matter_id"], r["release_id"], self.actor, fmt),
            quiet=True,
        )
        if got is None:
            return
        name, data, _media = got
        path, _ = QFileDialog.getSaveFileName(self, "Save the report", name, _FILTERS[fmt])
        if path:
            Path(path).write_bytes(data)
            self.note.setText(f"Saved to {path}. The copy carries your name.")
        self.refresh()
