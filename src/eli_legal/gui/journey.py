"""The case from A to Z, on every page: where it stands, and the next thing to do.

A bar under the header shows the open matter's eight stages (set up, documents, analysis,
holds and checks, review, release, collected, close), each done, now or later; a click on one
opens the page where it is worked on. Beside them, the next step: a button that takes the person
straight there if it is theirs to do, or who is being waited for if it is not. It is worked out
by the same guidance, and the same permission rules, as Home, so it never asks anyone to do what
they may not do.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from eli_legal.application.guidance_service import STAGE_PAGES
from eli_legal.gui import theme

_COLOUR = {"done": theme.GOOD, "current": theme.ACCENT, "waiting": theme.WARN, "later": theme.IDLE}
_MARK = {"done": "✓", "current": "●", "waiting": "…", "later": ""}


class JourneyBar(QFrame):
    def __init__(self, session: Any, go: Callable[[str], None]) -> None:
        super().__init__()
        self.session, self.go = session, go
        self.setObjectName("journey")
        self.setStyleSheet(
            f"QFrame#journey {{ border-bottom: 1px solid {theme.BORDER}; background: {theme.PANEL}; }}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 6, 12, 6)
        outer.setSpacing(4)
        top = QHBoxLayout()
        self.where = QLabel("")
        self.where.setWordWrap(True)
        self.where.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(self.where, 1)
        self.next = QPushButton("")
        self.next.setProperty("kind", "primary")
        self.next.clicked.connect(self._next)
        self.waiting = QLabel("")
        self.waiting.setWordWrap(True)
        self.waiting.setStyleSheet(f"color: {theme.WARN};")
        top.addWidget(self.waiting, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.next, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(top)
        self.track = QHBoxLayout()
        self.track.setSpacing(4)
        self.track.addStretch(1)  # the stage buttons go before it
        holder = QWidget()
        holder.setLayout(self.track)
        outer.addWidget(holder)
        # Eight stage buttons, made once and kept: refreshing changes their words and colour, and
        # never destroys and rebuilds widgets while the window may be closing.
        self.stage_buttons: list[QPushButton] = []
        self._keys: list[str] = []
        self._page = ""
        self.hide()

    def _button(self, index: int) -> QPushButton:
        while len(self.stage_buttons) <= index:
            b = QPushButton("")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            position = len(self.stage_buttons)
            b.clicked.connect(lambda _c=False, i=position: self._open(i))
            self.track.insertWidget(position, b)
            self.stage_buttons.append(b)
            self._keys.append("")
        return self.stage_buttons[index]

    def _open(self, index: int) -> None:
        if index < len(self._keys) and self._keys[index]:
            self.go(STAGE_PAGES.get(self._keys[index], "home"))

    def refresh(self) -> None:
        sv, mid, actor = self.session.sv, self.session.matter_id, self.session.user_id
        guide = None
        if mid and actor:
            try:
                guide = sv.guidance.for_matter(mid, actor_id=actor)
            except Exception:  # noqa: BLE001 - someone who may not read the matter sees no bar
                guide = None
        if guide is None:
            self.hide()
            return
        current = next((s for s in guide.stages if s.state == "current"), None)
        for index, stage in enumerate(guide.stages):
            colour = _COLOUR.get(stage.state, theme.IDLE)
            b = self._button(index)
            self._keys[index] = stage.key
            b.setText(f"{index + 1}. {stage.title} {_MARK.get(stage.state, '')}".strip())
            b.setToolTip(stage.detail or stage.title)
            weight = "2px" if stage is current else "1px"
            b.setStyleSheet(
                f"QPushButton {{ border: {weight} solid {colour}; border-radius: 12px; "
                f"color: {colour}; padding: 3px 10px; background: transparent; }}"
            )
            b.show()
        for extra in self.stage_buttons[len(guide.stages) :]:
            extra.hide()
        stage_text = (
            f"Stage {guide.stages.index(current) + 1} of {len(guide.stages)}: {current.title}"
            if current
            else ("Closed" if "closed" in guide.headline.lower() else "Everything is done")
        )
        self.where.setText(
            f"<b>{guide.matter_name}</b> · <b>{stage_text}</b>"
            + (f" — {current.detail}" if current and current.detail else "")
        )
        mine = next((s for s in guide.steps if s.can_do), None)
        theirs = next((s for s in guide.steps if not s.can_do), None)
        if mine is not None:
            self._page = mine.page
            self.next.setText(f"Next: {mine.title} →")
            self.next.setToolTip(mine.why)
            self.next.show()
            self.waiting.hide()
        else:
            self._page = ""
            self.next.hide()
            if theirs is not None:
                self.waiting.setText(f"Next: {theirs.title}. {theirs.who}")
                self.waiting.show()
            else:
                self.waiting.hide()
        self.show()

    def _next(self) -> None:
        if self._page:
            self.go(self._page)
