"""One hold, decided on the evidence: what it means, the exact words that caused it (marked in
the document's full text), or the original itself (an image or PDF, shown here without writing
it anywhere), who filed it and when, what the filing party answered, and what can be done
about this kind of hold. Every action is recorded in the name of the person who takes it."""

from __future__ import annotations

from collections.abc import Callable
from html import escape
from pathlib import Path
from typing import Any

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from eli_legal.domain import plain
from eli_legal.gui import theme
from eli_legal.gui.widgets import ReasonDialog, button, card, label, row

_LABELS = {
    "accept_evidence": ("Accept it as ordinary evidence…", "", "You read the marked words: "
                        "they are part of the evidence, not an attempt to steer the analysis."),
    "exclude_document": ("Take the document out of the analysis…", "danger", "Nothing in it is "
                         "used; it stays on the case's record, with your reason."),
    "describe": ("Describe it by hand…", "primary", "Look at the original and type what it "
                 "shows or says; your words become its text, marked as yours."),
    "readable_copy": ("File a readable copy…", "", "A clearer scan, the native file, or a "
                      "written description from the party; the hold closes once it is read."),
    "accept_gap": ("Accept the gap…", "", "Go on without it; the report states the gap as a "
                   "limit of the analysis."),
    "save_original": ("Save a copy of the original…", "", "A hand-over: it is plain where you "
                      "put it, and recorded."),
    "record_check": ("Record a check by hand…", "primary", "You checked the authority or the "
                     "evidence yourself, and say where."),
    "exclude_finding": ("Take the finding out of reliance…", "danger", "It stays in the report "
                        "under 'Findings not to be relied on', with your reason."),
    "lift": ("Lift the hold…", "primary", "The run carries on from where it was held."),
}  # fmt: skip


# What each kind of match means, in words (security/prompt_injection.py).
FOUND = {
    "instruction_override": "an instruction to ignore or replace earlier instructions",
    "role_reassignment": "an attempt to give the reader a new role",
    "addressed_to_model": "words addressed to an AI model",
    "chat_template_marker": "a chat-system marker",
    "boundary_spoofing": "a forged boundary of the material",
    "concealment_request": "a request to keep something from the reviewer",
    "verification_tampering": "an attempt to change how things are checked",
    "exfiltration_request": "a request to send information somewhere",
    "hidden_characters": "invisible characters",
    "the finding's source": "the words the finding rests on",
}


def found(name: str) -> str:
    return FOUND.get(name, name.replace("_", " "))


def _marked(text: str, marks: list[list[Any]], first: list[int]) -> str:
    """The passage as HTML, each marked span highlighted and anchored for jumping to it."""
    out, at = [], 0
    for name, start, end in sorted(marks, key=lambda m: (m[1], -m[2])):
        if start < at:
            continue
        out.append(escape(text[at:start]))
        n = first[0]
        first[0] += 1
        out.append(
            f"<a name='m{n}'></a><span style='background:#f2c14e;color:#111;' "
            f"title='{escape(found(str(name)))}'>{escape(text[start:end])}</span>"
        )
        at = end
    out.append(escape(text[at:]))
    return "".join(out).replace("\n", "<br>")


class HoldWindow(QDialog):
    def __init__(
        self,
        parent: QWidget,
        session: Any,
        matter_id: str,
        hold_id: str,
        *,
        record_check: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.session, self.sv, self.mid, self.hold_id = session, session.sv, matter_id, hold_id
        self.actor = session.user_id
        self._record_check = record_check
        self._keep: list[Any] = []  # what Qt reads from while the window is open
        seen = self.sv.holds.evidence(matter_id, hold_id, actor_id=self.actor)
        self.seen = seen
        hold = seen["hold"]
        said = plain.hold_explanation(hold.reason_code)
        self.setWindowTitle(f"Hold: {said.headline}")
        self.resize(1180, 820)
        layout = QVBoxLayout(self)
        document = seen["document"]
        facts = [f"<b>{escape(said.headline)}.</b> {escape(said.why)}"]
        if hold.detail:
            facts.append(f"<b>What the system found:</b> {escape(hold.detail)}")
        if document:
            facts.append(
                f"<b>{escape(document['ref'])} {escape(document['filename'])}</b> · filed by "
                f"{escape(document['filed_by'])} · received {document['received']:%d %b %Y %H:%M}"
                f" · {escape(document['type'])} · {document['bytes']:,} bytes"
                + (f" · read with {escape(document['read_with'])}" if document["read_with"] else "")
            )
            if document["error"]:
                facts.append(f"<b>Why it was not read:</b> {escape(document['error'])}")
            facts.append(
                f"<span style='color:{theme.MUTED}'>Fingerprint (SHA-256): "
                f"{document['sha256']}</span>"
            )
        claim = seen["claim"]
        if claim:
            facts.append(f"<b>The finding:</b> {escape(claim['text'])}")
            if claim["citation"]:
                facts.append(f"<b>Authority:</b> {escape(claim['citation'])}")
            if claim["why"]:
                facts.append(f"<b>Where it stands:</b> {escape(claim['why'])}")
        if hold.answers:
            facts.append(
                "<b>The party that filed it answered:</b> "
                + "; ".join(
                    f"{escape(a.by)}, {a.at:%d %b %H:%M}: {escape(a.reasons)}" for a in hold.answers
                )
            )
        if hold.status.value != "open":
            facts.append(
                f"<b>Resolved</b> by {escape(hold.resolved_by or '')}: "
                f"{escape(hold.resolution_reason)}"
            )
        header = label("<br>".join(facts), wrap=True, selectable=True)
        layout.addWidget(header)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.views = QTabWidget()
        self.text = QTextBrowser()
        self.text.setOpenLinks(False)
        counter = [0]
        blocks = [
            f"<p><span style='color:{theme.MUTED}'>[{escape(p['locator'])}]</span> "
            f"{_marked(p['text'], p['marks'], counter)}</p>"
            for p in seen["passages"]
        ]
        self.text.setHtml(
            "".join(blocks)
            or f"<p style='color:{theme.MUTED}'>No text was read from this document.</p>"
        )
        self.views.addTab(self.text, "The text, marked" if counter[0] else "The text")
        if document and document["original"]:
            self.views.addTab(self._original_view(document), "The original")
            if not counter[0] and hold.scope.value == "document":
                self.views.setCurrentIndex(1)
        split.addWidget(self.views)

        side = QWidget()
        side_box = QVBoxLayout(side)
        side_box.setContentsMargins(0, 0, 0, 0)
        if counter[0]:
            self.found = QListWidget()
            n = 0
            for p in seen["passages"]:
                for name, start, end in sorted(p["marks"], key=lambda m: m[1]):
                    item = QListWidgetItem(
                        f"{p['locator']}: {found(str(name))} — “{p['text'][start:end][:80]}”"
                    )
                    item.setData(Qt.ItemDataRole.UserRole, f"m{n}")
                    self.found.addItem(item)
                    n += 1
            self.found.itemClicked.connect(self._jump)
            side_box.addWidget(card(f"What was found ({n})", self.found), 1)
        actions = seen["actions"]
        buttons = []
        for code in actions:
            text, kind, tip = _LABELS[code]
            buttons.append(button(text, lambda _c=False, c=code: self._act(c), kind=kind, tip=tip))
        if actions:
            box = QVBoxLayout()
            holder = QWidget()
            holder.setLayout(box)
            for b in buttons:
                box.addWidget(b)
            box.addStretch(1)
            side_box.addWidget(card("What you can do", holder))
        else:
            side_box.addWidget(label("Nothing to decide here.", "muted"))
        split.addWidget(side)
        split.setSizes([820, 340])
        layout.addWidget(split, 1)
        layout.addWidget(row(None, button("Close", self.reject)))
        if counter[0]:
            self.text.scrollToAnchor("m0")

    def _jump(self, item: QListWidgetItem) -> None:
        """Show the marked words a match in the list stands for."""
        self.views.setCurrentIndex(0)
        self.text.scrollToAnchor(str(item.data(Qt.ItemDataRole.UserRole)))

    # ── the original, shown here ─────────────────────────────────────────────
    def _original_view(self, document: dict[str, Any]) -> QWidget:
        try:
            _doc, raw = self.sv.matters.original(self.mid, document["document_id"], self.actor)
        except Exception as exc:  # noqa: BLE001 - said in the window, not raised
            return label(f"The original cannot be shown: {exc}", wrap=True)
        media = document["media_type"]
        if media == "application/pdf":
            try:
                from PySide6.QtPdf import QPdfDocument
                from PySide6.QtPdfWidgets import QPdfView
            except ImportError:
                return label("Showing PDFs needs Qt's PDF module, which is not installed.")
            data = QByteArray(raw)
            buffer = QBuffer()
            buffer.setData(data)
            buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            pdf = QPdfDocument(self)
            pdf.load(buffer)
            view = QPdfView(self)
            view.setDocument(pdf)
            view.setPageMode(QPdfView.PageMode.MultiPage)
            view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            self._keep += [data, buffer, pdf]
            return view
        image = QImage.fromData(raw)
        if image.isNull():
            head = " ".join(raw[:16].hex()[i : i + 4] for i in range(0, 32, 4))
            return label(
                "<b>This file cannot be opened as an image.</b> It is damaged, or not the kind of "
                f"file its name says. Its first bytes: <code>{head}</code><br>Ask the party who "
                "filed it for a readable copy, or accept the gap.",
                wrap=True,
                selectable=True,
            )
        shown = QLabel()
        shown.setPixmap(QPixmap.fromImage(image))
        shown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(shown)
        scroll.setWidgetResizable(False)
        return scroll

    # ── actions ──────────────────────────────────────────────────────────────
    def _done(self, result: object, message: str = "") -> None:
        if result is None:
            return
        if message:
            QMessageBox.information(self, "Recorded", message)
        self.accept()

    def _act(self, code: str) -> None:
        hold = self.seen["hold"]
        holds = self.sv.holds
        if code in ("accept_evidence", "accept_gap", "exclude_document", "exclude_finding", "lift"):
            action = {"accept_evidence": "waive", "accept_gap": "waive", "lift": "lift"}.get(
                code, "exclude"
            )
            title, _kind, tip = _LABELS[code]
            reason = ReasonDialog.ask(self, title.rstrip("…"), tip + " Why?")
            if reason:
                self._done(
                    self.session.decide(
                        self,
                        f"{title.rstrip('…').lower()}",
                        lambda: holds.resolve(
                            self.mid,
                            hold.hold_id,
                            actor_id=self.actor,
                            action=action,
                            reason=reason,
                        ),
                    )  # fmt: skip
                )
        elif code == "describe":
            words = QPlainTextEdit()
            words.setPlaceholderText(
                "What the original shows or says, as exactly as you can: the words on it, or what "
                "the photograph shows."
            )
            words.setMinimumHeight(160)
            reason = ReasonDialog.ask(
                self,
                "Describe it by hand",
                "Your words become this document's text, marked as described by you, and the "
                "analysis uses them once it is restarted. Where did you see the original?",
                extra=[("What it shows or says", words)],
            )
            if reason:
                text = words.toPlainText()
                self._done(
                    self.session.decide(
                        self,
                        "describe this document by hand",
                        lambda: holds.describe(
                            self.mid, hold.hold_id, actor_id=self.actor, text=text, reason=reason
                        ),
                    ),
                    "Recorded. Restart the analysis (Progress) so it reads your description.",
                )
        elif code == "readable_copy":
            path, _ = QFileDialog.getOpenFileName(self, "The readable copy")
            if not path:
                return
            reason = ReasonDialog.ask(
                self,
                "File a readable copy",
                "It is filed for the same party, of the same kind, seen as widely as the original. "
                "Where does it come from?",
            )
            if reason:
                raw = Path(path).read_bytes()
                name = Path(path).name
                got = self.session.decide(
                    self,
                    "file a readable copy",
                    lambda: holds.replace_with_copy(
                        self.mid, hold.hold_id, actor_id=self.actor, filename=name, raw=raw,
                        reason=reason,
                    ),
                )  # fmt: skip
                if got is None:
                    return
                done, copy = got
                if done is None:
                    QMessageBox.warning(
                        self,
                        "Not read either",
                        f"{copy.filename} could not be read either ({copy.error or 'unread'}). "
                        "It is on the case and held too; the original's hold stays.",
                    )
                    self.accept()
                    return
                self._done(done, "Filed and read. Restart the analysis (Progress) to use it.")
        elif code == "save_original":
            document = self.seen["document"]
            path, _ = QFileDialog.getSaveFileName(
                self, "Save a copy of the original", document["filename"]
            )
            if not path:
                return
            got = self.session.attempt(
                self,
                lambda: self.sv.matters.original(
                    self.mid, document["document_id"], self.actor, purpose="saved"
                ),
                quiet=True,
            )
            if got is not None:
                Path(path).write_bytes(got[1])
                QMessageBox.information(
                    self, "Saved", f"Saved to {path}. It is plain there; the hand-over is recorded."
                )
        elif code == "record_check" and self._record_check is not None:
            self.accept()
            self._record_check(hold.subject_id, hold.detail.split(":", 1)[0].strip())
