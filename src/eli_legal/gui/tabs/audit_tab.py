from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
)

from eli_legal.adapters.local.hmac_audit import Checkpoint
from eli_legal.gui import theme
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import (
    button,
    card,
    chip,
    fill,
    fit,
    label,
    row,
    selected_id,
    set_chip,
    table,
)


class AuditTab(Tab):
    title = "🧾 Audit Trail"

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.chain = chip("not checked")
        self.record = chip("")
        self.whole = QCheckBox("Events outside any matter (sign-ins, users, sources, settings)")
        self.whole.toggled.connect(self.refresh)
        self.record.hide()  # shown once this run's record has been checked
        self.kind = QComboBox()
        self.kind.setMinimumWidth(230)
        self.kind.currentIndexChanged.connect(self._filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by actor, action, subject or outcome")
        self.search.textChanged.connect(self._filter)
        self.events = table(
            [
                "#",
                "When (UTC)",
                "Event",
                "Who",
                "How identity was proved",
                "Action",
                "Outcome",
                "Subject",
            ],
            stretch=7,
        )
        self.events.itemSelectionChanged.connect(self._show)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self._events: list[dict[str, Any]] = []
        self.root.addWidget(
            card(
                "Ledger",
                row(
                    self.chain,
                    self.record,
                    None,
                    button("Verify the chain", self._verify, kind="primary"),
                    button("Check this run's record", self._completeness),
                    button(
                        "Export a checkpoint…",
                        self._checkpoint,
                        tip="A signed statement of the chain's length and end. Keep it off this machine.",
                    ),
                    button("Verify against a checkpoint…", self._against),
                    button("Export the evidence pack…", self._pack),
                ),
                label(
                    "Each event is signed over the one before it. Editing, removing or truncating events breaks the chain. The ledger holds identifiers and hashes, never document text.",
                    "muted",
                    wrap=True,
                ),
            )
        )
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(
            card("Events", row(self.kind, self.search, self.whole, stretch_last=False), self.events)
        )
        split.addWidget(card("Selected event", self.detail))
        split.setSizes([460, 180])
        self.root.addWidget(split, 1)

    def refresh(self) -> None:
        events: list[dict[str, Any]] = []
        if self.whole.isChecked():
            events = (
                self.session.attempt(
                    self, lambda: self.sv.audit_trail(actor_id=self.actor), quiet=True
                )
                or []
            )
        elif self.mid:
            events = (
                self.session.attempt(
                    self,
                    lambda: self.sv.audit_trail(actor_id=self.actor, matter_id=self.mid),
                    quiet=True,
                )
                or []
            )
        self._events = events
        current = self.kind.currentData()
        self.kind.blockSignals(True)
        self.kind.clear()
        self.kind.addItem(f"Every event ({len(events)})", "")
        for name in sorted({e["event_type"] for e in events}):
            self.kind.addItem(name.replace("_", " "), name)
        self.kind.setCurrentIndex(max(0, self.kind.findData(current)))
        self.kind.blockSignals(False)
        report = self.sv.ctx.audit.report()
        set_chip(
            self.chain,
            f"● chain {'verified' if report.ok else 'INVALID: ' + report.error} · {report.count} events",
            theme.GOOD if report.ok else theme.BAD,
        )
        self._filter()

    def _filter(self) -> None:
        kind, words = self.kind.currentData(), self.search.text().lower().split()
        shown = [
            e
            for e in self._events
            if (not kind or e["event_type"] == kind)
            and all(
                w in f"{e['actor_id']} {e['action']} {e['subject_id']} {e['outcome']}".lower()
                for w in words
            )
        ]
        fill(
            self.events,
            [
                [
                    e["seq"],
                    e["created_at"][:19].replace("T", " "),
                    e["event_type"].replace("_", " "),
                    e["actor_id"],
                    e["payload"].get("auth", ""),
                    e["action"],
                    e["outcome"],
                    e["subject_id"],
                ]
                for e in shown
            ],
            ids=[str(e["seq"]) for e in shown],
            state_columns=[6],
        )
        fit(self.events, [56, 150, 170, 120, 190, 190, 150, 0])

    def _show(self) -> None:
        wanted = selected_id(self.events)
        for event in self._events:
            if str(event["seq"]) == wanted:
                self.detail.setPlainText(json.dumps(event, indent=2, sort_keys=True))

    def _verify(self) -> None:
        def allowed() -> bool:
            self.sv.ctx.authorizer().require_global(self.actor, "audit.verify")
            return True

        if not self.session.attempt(self, allowed, quiet=True):
            return
        self.refresh()
        report = self.sv.ctx.audit.report()
        QMessageBox.information(
            self,
            "Audit chain",
            f"The chain is valid: {report.count} events, every signature and link checks out."
            if report.ok
            else f"THE CHAIN IS INVALID: {report.error}.\n\nStop, preserve both database files "
            "and the anchor, and open an incident.",
        )

    def _completeness(self) -> None:
        if not (self.mid and self.rid):
            return
        result = self.session.attempt(
            self, lambda: self.sv.run_record(self.mid, self.rid, actor_id=self.actor), quiet=True
        )
        if result is not None:
            self.record.show()
            set_chip(
                self.record,
                f"● run record {'complete' if result.ok else 'HAS GAPS'} · {result.events_checked} events",
                theme.GOOD if result.ok else theme.BAD,
            )
            if not result.ok:
                QMessageBox.warning(
                    self,
                    "Run record",
                    "The store and the ledger disagree:\n\n" + "\n".join(result.gaps),
                )

    def _checkpoint(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save checkpoint", "eli_legal_audit_checkpoint.json", "JSON (*.json)"
        )
        if not path:
            return

        def save() -> bool:
            self.sv.ctx.authorizer().require_global(self.actor, "audit.verify")
            Path(path).write_text(self.sv.ctx.audit.checkpoint().to_json() + "\n", encoding="utf-8")
            return True

        if self.session.attempt(self, save, quiet=True):
            QMessageBox.information(
                self,
                "Checkpoint saved",
                f"{path}\n\nKeep a copy off this machine. Verifying against it later detects a rollback.",
            )

    def _against(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Checkpoint to verify against", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            report = self.sv.ctx.audit.report(
                expected=Checkpoint.from_json(Path(path).read_text(encoding="utf-8"))
            )
        except (ValueError, KeyError, OSError) as exc:
            QMessageBox.warning(self, "Checkpoint", f"That file is not a checkpoint: {exc}")
            return
        QMessageBox.information(
            self,
            "Checkpoint",
            "The chain matches the checkpoint." if report.ok else f"MISMATCH: {report.error}",
        )

    def _pack(self) -> None:
        if not (self.mid and self.rid):
            return
        folder = QFileDialog.getExistingDirectory(self, "Where to write the evidence pack")
        if folder:
            path = self.session.attempt(
                self,
                lambda: self.sv.evidence_pack(
                    self.mid, self.rid, actor_id=self.actor, out_dir=folder
                ),
            )
            if path is not None:
                QMessageBox.information(self, "Evidence pack", f"Written to:\n{path}")
