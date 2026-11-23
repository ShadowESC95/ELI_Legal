"""Closed cases: off the case list, still here. Look at one, reopen it, archive its content
(encrypted, out of the working database) or delete it for good once it may go."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QCheckBox, QDialog, QMessageBox, QVBoxLayout, QWidget

from eli_legal.gui.session import Session
from eli_legal.gui.widgets import ReasonDialog, button, fill, fit, label, row, selected_id, table

_STATE = {"archived": "Archived, encrypted", "kept": "Kept", "deleted": "Deleted"}
_KINDS = ("papers", "analysis", "reports", "evidence", "record")


def _cell(entry: dict[str, Any], code: str) -> str:
    """Where one kind of a closed case's content is, and until when it is kept."""
    kind = entry["kinds"][code]
    state = _STATE[kind["state"]]
    if kind["state"] == "deleted":
        return state
    if entry["held"]:
        return f"{state} · held"
    until = kind["until"]
    end = "no end" if code == "record" else "no period set"
    return f"{state} · to {until}" if until else f"{state} · {end}"


class ClosedCasesDialog(QDialog):
    def __init__(self, parent: QWidget, session: Session) -> None:
        super().__init__(parent)
        self.session = session
        self.setWindowTitle("Closed cases")
        self.setMinimumSize(900, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(
            label(
                "Closed cases are off the case list but not gone. Each kind of a case's content "
                "(papers, analysis, reports, evidence packs) is kept, archived (encrypted under "
                "its own key, out of the working database, restored if the case is reopened) or "
                "deleted, and is kept for its own period (Compliance → OA-09). When a kind's "
                "period ends the routine checks delete it, or destroy its archive's key, unless a "
                "preservation hold keeps it. The decision record goes last.",
                wrap=True,
            )
        )
        self.table = table(
            [
                "Case",
                "Closed on",
                "Papers",
                "Analysis",
                "Reports",
                "Evidence packs",
                "Decision record",
                "Team",
            ],
            stretch=0,
        )
        fit(self.table, [220, 95, 190, 190, 190, 190, 170, 50])
        self.table.itemSelectionChanged.connect(self._enable)
        self.table.doubleClicked.connect(lambda _index: self._view())
        layout.addWidget(self.table, 1)
        self.view_button = button("View (read only)", self._view)
        self.reopen_button = button("Reopen…", self._reopen, kind="primary")
        self.archive_button = button("Archive, encrypted…", self._archive)
        self.delete_button = button("Delete its content for good…", self._delete, kind="danger")
        layout.addWidget(
            row(
                self.view_button,
                self.reopen_button,
                self.archive_button,
                self.delete_button,
                button("Close", self.reject),
                stretch_last=False,
            )
        )
        self.entries: dict[str, dict[str, Any]] = {}
        self.refresh()

    def refresh(self) -> None:
        listed = self.session.sv.matters.closed_overview(self.session.user_id)
        self.entries = {str(e["matter_id"]): e for e in listed}
        fill(
            self.table,
            [
                [
                    e["name"],
                    e["closed_on"] or "",
                    *(_cell(e, code) for code in _KINDS),
                    e["team"] or "",
                ]
                for e in listed
            ],
            ids=[str(e["matter_id"]) for e in listed],
        )
        if listed and not selected_id(self.table):
            self.table.selectRow(0)
        self._enable()

    def _chosen(self) -> dict[str, Any] | None:
        return self.entries.get(selected_id(self.table))

    def _enable(self) -> None:
        entry = self._chosen()
        self.view_button.setEnabled(entry is not None)
        self.reopen_button.setEnabled(entry is not None)
        self.archive_button.setEnabled(
            entry is not None
            and any(entry["kinds"][c]["state"] == "kept" for c in _KINDS if c != "record")
        )
        self.delete_button.setEnabled(
            entry is not None and entry["content"] != "deleted" and not entry["held"]
        )

    def _view(self) -> None:
        entry = self._chosen()
        if entry is None:
            return
        self.session.set_matter(str(entry["matter_id"]))
        self.accept()

    def _reopen(self) -> None:
        entry = self._chosen()
        if entry is None:
            return
        team = QCheckBox(
            "Give its team access again (anyone suspended or removed since is left out)"
        )
        team.setChecked(True)
        where = {
            "archived": "Its archived content is checked, fingerprint by fingerprint, and put back.",
            "kept": "Its content was kept, and is there as it was.",
            "deleted": "Its content was deleted: it reopens with its record and history only.",
        }[str(entry["content"])]
        reason = ReasonDialog.ask(
            self,
            f"Reopen {entry['name']}",
            f"Reopening makes the case active again. {where} Why is it being reopened?",
            extra=[("", team)],
        )
        if not reason:
            return
        mid = str(entry["matter_id"])
        done = self.session.decide(
            self,
            "reopen this matter",
            lambda: self.session.sv.matters.reopen(
                mid, actor_id=self.session.user_id, reason=reason, restore_team=team.isChecked()
            ),
        )
        if done is None:
            return
        lines = [f"Reopened. Its content was {done['content']}."]
        if done["team"]:
            lines.append(f"Access given back to: {', '.join(done['team'])}.")
        if done["left_out"]:
            lines.append(
                f"Left out (suspended or removed since): {', '.join(done['left_out'])}. "
                "Case details → Team can add them again."
            )
        QMessageBox.information(self, "Reopened", "\n\n".join(lines))
        self.session.set_matter(mid)
        self.accept()

    def _archive(self) -> None:
        entry = self._chosen()
        if entry is None:
            return
        reason = ReasonDialog.ask(
            self,
            f"Archive {entry['name']}",
            "Its documents, text, findings and reports are sealed into an encrypted archive "
            "(AES-256-GCM, a key of its own), read back to prove it opens, then removed from "
            "the working database and folders, overwritten. Reopening the case restores them. "
            "Why now?",
        )
        if not reason:
            return
        mid = str(entry["matter_id"])
        if (
            self.session.decide(
                self,
                "archive this matter",
                lambda: self.session.sv.matters.archive(
                    mid, actor_id=self.session.user_id, reason=reason
                ),
            )
            is not None
        ):
            self.refresh()

    def _delete(self) -> None:
        entry = self._chosen()
        if entry is None:
            return
        if (
            QMessageBox.question(
                self,
                "Delete for good",
                f"Delete the content of {entry['name']} for good? Its documents, text, findings "
                "and reports (or its archive's key) are destroyed and cannot be brought back. "
                "Its record and history are kept.",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        reason = ReasonDialog.ask(
            self,
            "Delete for good",
            "Why may its content go now: its retention ended, a data-protection request, an order?",
        )
        if not reason:
            return
        mid = str(entry["matter_id"])
        if (
            self.session.decide(
                self,
                "delete this matter's content for good",
                lambda: self.session.sv.matters.delete_content(
                    mid, actor_id=self.session.user_id, reason=reason
                ),
            )
            is not None
        ):
            self.refresh()
