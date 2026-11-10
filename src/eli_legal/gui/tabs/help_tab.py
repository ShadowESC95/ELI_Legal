"""How to use ELI Legal: a case from start to finish, in plain words, and what each word means."""

from __future__ import annotations

from collections.abc import Callable
from html import escape

from PySide6.QtWidgets import QFrame, QLineEdit, QScrollArea, QTextBrowser, QVBoxLayout, QWidget

from eli_legal.domain import glossary
from eli_legal.domain.how_to import INTRO, READING, STEPS
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import button, card, label, row


class HelpTab(Tab):
    title = "❓ How to use"

    def __init__(self, session, go: Callable[[str], None]) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self._go = go
        page = QWidget()
        column = QVBoxLayout(page)
        column.addWidget(label("How to use ELI Legal", "title"))
        column.addWidget(label(INTRO, wrap=True))
        column.addWidget(label(READING, "muted", wrap=True))
        for number, (what, who, how, target, caption) in enumerate(STEPS, 1):
            body = label(f"<b>Who:</b> {escape(who)}<br>{escape(how)}", wrap=True)
            step = card(
                f"{number}. {what}",
                body,
                row(button(caption, lambda t=target: self._go(t), kind="primary"), None),
            )
            column.addWidget(step)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Look up a word: matter, authority, held, provider …")
        self.search.textChanged.connect(self._words)
        self.words = QTextBrowser()
        self.words.setMinimumHeight(360)
        column.addWidget(card("What the words mean", self.search, self.words))
        column.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.root.addWidget(scroll)
        self._words()

    def _words(self) -> None:
        wanted = self.search.text().strip().lower()
        shown = [
            (term, meaning)
            for term, meaning in glossary.items()
            if not wanted or wanted in term.lower() or wanted in meaning.lower()
        ]
        self.words.setHtml(
            "".join(f"<p><b>{escape(t)}</b>: {escape(m)}</p>" for t, m in shown)
            or "<p>No word matches. Try fewer letters.</p>"
        )

    def refresh(self) -> None:
        """Nothing here depends on the case."""
