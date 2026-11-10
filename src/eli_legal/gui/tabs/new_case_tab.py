"""Start a new case: how a case is built, and a walkthrough of every part, in order.

The map shows the eleven parts as boxes; choosing one shows what it is, each question asked with
what it means and an example, tips, and who does it, with a button that does it now. With a case
open, each part already done is ticked.
"""

from __future__ import annotations

from collections.abc import Callable
from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from eli_legal.domain.how_to import NEW_CASE, NEW_CASE_INTRO, Part
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import button, card, label, row

_PER_ROW = 4
# The guidance stages (application/guidance_service.py) that say a later part is done.
_STAGE_OF = {
    "documents": "documents",
    "analysis": "analysis",
    "holds": "holds",
    "review": "review",
    "release": "release",
}


class _PartBox(QFrame):
    """One part on the map: its number and title, and a line saying what it is. Its words wrap,
    so the map fits any window and any zoom."""

    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("role", "partcard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        inner = QVBoxLayout(self)
        inner.setContentsMargins(10, 8, 10, 8)
        inner.setSpacing(2)
        self.name = label("", wrap=True)
        self.about = label("", "muted", wrap=True)
        inner.addWidget(self.name)
        inner.addWidget(self.about)

    def show_part(self, text: str, about: str, *, done: bool, chosen: bool) -> None:
        self.name.setText(f"<b>{text}</b>")
        self.about.setText(about)
        for prop, value in (("done", done), ("chosen", chosen)):
            self.setProperty(prop, value)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
        else:
            super().keyPressEvent(event)


class NewCaseTab(Tab):
    title = "🧭 Start a new case"

    def __init__(self, session, go: Callable[[str], None]) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self._go = go
        self.index = 0
        self.done: set[str] = set()
        page = QWidget()
        column = QVBoxLayout(page)
        column.addWidget(label("Start a new case: a guided walkthrough", "title", wrap=True))
        column.addWidget(label(NEW_CASE_INTRO, wrap=True))
        self.status = label("", wrap=True)
        self.start = button("Start a new case", lambda: self._go("new_matter"), kind="primary")
        self.start.setMinimumHeight(40)
        line = QHBoxLayout()
        line.addWidget(self.status, 1)
        line.addWidget(self.start, 0)
        column.addLayout(line)

        # the map: every part as a box, in order
        grid_holder = QWidget()
        grid = QGridLayout(grid_holder)
        grid.setSpacing(8)
        self.cards: list[_PartBox] = []
        for number, part in enumerate(NEW_CASE):
            box = _PartBox()
            box.setToolTip(part.what)
            box.clicked.connect(lambda i=number: self.choose(i))
            self.cards.append(box)
            grid.addWidget(box, number // _PER_ROW, number % _PER_ROW)
        for col in range(_PER_ROW):
            grid.setColumnStretch(col, 1)
        column.addWidget(card("How a case is built — the eleven parts, in order", grid_holder))

        # the chosen part, in full
        self.part_title = label("", "title", wrap=True)
        self.part_text = label("", wrap=True, selectable=True)
        self.questions = QTableWidget(0, 3)
        self.questions.setHorizontalHeaderLabels(["You are asked", "What it means", "For example"])
        self.questions.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.questions.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.questions.setWordWrap(True)
        self.questions.verticalHeader().setVisible(False)
        header = self.questions.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tips = label("", wrap=True, selectable=True)
        self.back = button("◀ Previous part", lambda: self.choose(self.index - 1))
        self.forward = button("Next part ▶", lambda: self.choose(self.index + 1))
        self.do_it = button("", self._do, kind="primary")
        column.addWidget(
            card(
                "This part",
                self.part_title,
                self.part_text,
                self.questions,
                self.tips,
                row(self.back, self.forward, None, self.do_it),
            )
        )
        column.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.root.addWidget(scroll)
        self.choose(0)

    # ── what is done for the open case ───────────────────────────────────────
    def refresh(self) -> None:
        matter = self.session.matter
        done: set[str] = set()
        if matter is not None:
            done |= {"for", "open"}
            if matter.name and matter.purpose:
                done.add("case")
            if matter.parties and matter.stated_issues:
                done.add("parties")
            if matter.reviewer_user_ids:
                done.add("team")
            if matter.approved_source_ids:
                done.add("law")
            guide = self.session.attempt(
                self,
                lambda: self.sv.guidance.for_matter(matter.matter_id, actor_id=self.actor),
                quiet=True,
            )
            stages = {s.key: s.state for s in guide.stages} if guide else {}
            done |= {part for part, stage in _STAGE_OF.items() if stages.get(stage) == "done"}
            self.status.setText(
                f"<b>Your open case: {escape(matter.name)}</b> — {len(done)} of {len(NEW_CASE)} "
                "parts done. A tick marks each; choose any part to see what it needs."
            )
        else:
            self.status.setText(
                "<b>No case is open.</b> Press Start a new case, or read each part first: choose "
                "one below."
            )
        self.done = done
        self._paint()
        self.choose(self.index)

    def _paint(self) -> None:
        for number, (box, part) in enumerate(zip(self.cards, NEW_CASE, strict=True)):
            mark = "✓ " if part.key in self.done else ""
            box.show_part(
                f"{mark}{number + 1}. {part.title}",
                part.summary,
                done=part.key in self.done,
                chosen=number == self.index,
            )

    # ── the chosen part ──────────────────────────────────────────────────────
    def choose(self, index: int) -> None:
        self.index = max(0, min(len(NEW_CASE) - 1, index))
        part: Part = NEW_CASE[self.index]
        self._paint()
        state = " — done for your open case" if part.key in self.done else ""
        self.part_title.setText(f"{self.index + 1}. {part.title}{state}")
        self.part_text.setText(
            f"<b>Who:</b> {escape(part.who)}<br><br>{escape(part.what)}"
            + (
                "<br><br>On the form this is one page of <i>Start a new case</i>."
                if part.page == "new_matter"
                else ""
            )
        )
        self.questions.setVisible(bool(part.questions))
        self.questions.setRowCount(len(part.questions))
        for r, values in enumerate(part.questions):
            for c, text in enumerate(values):
                item = QTableWidgetItem(text)
                if c == 0:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.questions.setItem(r, c, item)
        self.questions.resizeRowsToContents()
        height = self.questions.horizontalHeader().height() + sum(
            self.questions.rowHeight(r) for r in range(self.questions.rowCount())
        )
        self.questions.setFixedHeight(height + 6)
        self.tips.setText(
            "<b>Good to know</b><ul>"
            + "".join(f"<li>{escape(t)}</li>" for t in part.tips)
            + "</ul>"
            if part.tips
            else ""
        )
        self.back.setEnabled(self.index > 0)
        self.forward.setEnabled(self.index < len(NEW_CASE) - 1)
        self.do_it.setText(part.button)

    def _do(self) -> None:
        self._go(NEW_CASE[self.index].page)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        self.questions.resizeRowsToContents()
