from __future__ import annotations

import html
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QCheckBox, QPlainTextEdit, QSplitter, QTextBrowser

from eli_legal.application.chat_service import ChatAnswer
from eli_legal.gui import theme
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import button, card, fill, fit, label, row, selected_id, table

_KIND = {"document": "Document", "finding": "Finding", "authority": "Authority"}


class _Input(QPlainTextEdit):
    """Enter sends; Shift+Enter starts a new line — as in the ELI chat."""

    def __init__(self, on_send) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self._send = on_send
        self.setPlaceholderText(
            "Ask about this matter…  (Enter to send, Shift+Enter for a new line; /help for commands)"
        )
        self.setMaximumHeight(96)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self._send()
            return
        super().keyPressEvent(event)


class ChatTab(Tab):
    title = "💬 Chat"

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.heading = label("ELI Legal", "title")
        self.status = label("", "muted")
        self.transcript = QTextBrowser()
        self.transcript.setOpenLinks(False)
        self.box = _Input(self._send)
        self.use_model = QCheckBox("Let the model summarise the sources")
        self.use_model.setChecked(True)
        self.sources = table(["Ref", "Kind", "From", "Where", "May it be relied on?"], stretch=2)
        self.sources.itemSelectionChanged.connect(self._show_source)
        self.reader = QPlainTextEdit()
        self.reader.setReadOnly(True)
        self._last: ChatAnswer | None = None
        self._turns: list[str] = []
        left = card(
            "Conversation about this matter",
            self.transcript,
        )
        ask = card(
            "Your question",
            self.box,
            row(
                button("Send", self._send, kind="primary"),
                button("Clear", self._clear),
                button("/status", lambda: self._ask("/status")),
                button("/holds", lambda: self._ask("/holds")),
                button("/tasks", lambda: self._ask("/tasks")),
                button("/limits", lambda: self._ask("/limits")),
                self.use_model,
                None,
            ),
        )
        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(card("Sources for the last answer", self.sources))
        right.addWidget(card("Passage, word for word", self.reader))
        right.setSizes([300, 300])
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([700, 480])
        self.root.addWidget(row(self.heading, self.status, None))
        self.root.addWidget(split, 1)
        self.root.addWidget(ask)
        self._say(
            "ELI Legal",
            "I answer from this matter's documents, this run's findings and the approved legal "
            "sources, and show where each passage comes from. I do not say who should succeed or "
            "how anything should be decided, and nothing can be approved, verified or released "
            "from here. Type /help for more.",
        )

    def refresh(self) -> None:
        matter = self.session.matter
        model = self.sv.ctx.model
        dot = f"<span style='color:{theme.GOOD if model.available else theme.IDLE}'>●</span>"
        where = matter.name if matter else "no matter open"
        self.status.setText(
            f"{dot} model: {model.model_id if model.available else 'none — answers are the sources themselves'}"
            f" &nbsp;·&nbsp; {html.escape(where)}"
        )
        self.use_model.setEnabled(model.available)

    def _say(self, who: str, body_html: str) -> None:
        colour = theme.ACCENT if who != "You" else "#8eaac8"
        stamp = datetime.now().strftime("%H:%M:%S")
        self._turns.append(
            f"<p><b style='color:{colour}'>{html.escape(who)} [{stamp}]:</b><br>{body_html}</p>"
        )
        self.transcript.setHtml("".join(self._turns))
        bar = self.transcript.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _clear(self) -> None:
        self._turns.clear()
        self.transcript.clear()
        fill(self.sources, [])
        self.reader.clear()

    def _send(self) -> None:
        text = " ".join(self.box.toPlainText().split())
        if text:
            self.box.clear()
            self._ask(text)

    def _ask(self, question: str) -> None:
        if not self.mid:
            self._say("ELI Legal", "Open a matter first.")
            return
        self._say("You", html.escape(question))
        use_model = self.use_model.isChecked() and self.sv.ctx.model.available

        def work() -> ChatAnswer:
            return self.sv.chat.ask(
                self.mid,
                actor_id=self.actor,
                question=question,
                run_id=self.rid or None,
                use_model=use_model,
            )

        if use_model and not question.startswith("/"):
            self.session.background("Reading the sources…", work, self._answered, self._failed)
        else:
            answer = self.session.attempt(self, work, quiet=True)
            if answer is not None:
                self._answered(answer)

    def _failed(self, exc: Exception) -> None:
        self._say(
            "ELI Legal", f"<span style='color:{theme.BAD}'>Refused: {html.escape(str(exc))}</span>"
        )

    def _answered(self, answer: object) -> None:
        assert isinstance(answer, ChatAnswer)
        self._last = answer
        parts: list[str] = []
        for note in answer.notes:
            parts.append(html.escape(note).replace("\n", "<br>"))
        if answer.lines:
            parts.append(
                f"<i style='color:{theme.MUTED}'>Summary written by {html.escape(answer.model_id)} from the "
                "sources cited. Check it against them.</i>"
            )
            for text, cites in answer.lines:
                refs = " ".join(f"<b style='color:{theme.ACCENT}'>[{c}]</b>" for c in cites)
                parts.append(f"{html.escape(text)} {refs}")
        if answer.sources:
            if not answer.lines:
                parts.append(
                    f"<i style='color:{theme.MUTED}'>These passages bear on your question:</i>"
                )
            for source in answer.sources:
                colour = theme.TEXT if source.usable else theme.WARN
                note = (
                    f" — <span style='color:{theme.WARN}'>{html.escape(source.note)}</span>"
                    if source.note
                    else ""
                )
                excerpt = html.escape(source.text[:260] + ("…" if len(source.text) > 260 else ""))
                parts.append(
                    f"<b style='color:{theme.ACCENT}'>[{source.label}]</b> "
                    f"<span style='color:{theme.MUTED}'>{html.escape(source.title)} {html.escape(source.locator)}</span>"
                    f"{note}<br><span style='color:{colour}'>“{excerpt}”</span>"
                )
        self._say("ELI Legal", "<br><br>".join(parts) or "Nothing to show.")
        fill(
            self.sources,
            [
                [
                    s.label,
                    _KIND[s.kind],
                    s.title,
                    s.locator,
                    "yes" if s.usable else f"NO — {s.note}",
                ]
                for s in answer.sources
            ],
            ids=[s.label for s in answer.sources],
            keep_selection=False,
        )
        fit(self.sources, [44, 80, 0, 80, 230])

    def _show_source(self) -> None:
        if self._last is None:
            return
        wanted = selected_id(self.sources)
        for source in self._last.sources:
            if source.label == wanted:
                note = f"\n\n{source.note}" if source.note else ""
                self.reader.setPlainText(
                    f"{source.title} — {source.locator}{note}\n\n{source.text}"
                )
