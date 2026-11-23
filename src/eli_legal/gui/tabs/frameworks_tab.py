from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QWidget,
)

from eli_legal.domain import plain
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import (
    ReasonDialog,
    button,
    card,
    fill,
    fit,
    label,
    row,
    selected_id,
    table,
)
from eli_legal.legal.framework_library import PackState

FILES = (
    "Packages and documents (*.json *.csv *.pdf *.docx *.odt *.rtf *.txt *.md *.html *.htm *.eml)"
)


class _ImportDialog(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import a law or standards package")
        self.setMinimumWidth(620)
        form = QFormLayout(self)
        form.addRow(
            label(
                "A JSON package (the format the Export button writes), a CSV requirements register "
                "(columns: id, reference, title, text, effect), or your organisation's rules as a "
                "document (PDF, Word, ODT, text). Each clause of a document becomes a rule given to "
                "the model, and a reviewer confirms the work meets the document as a whole. It "
                "cannot be used on a matter until it is approved.",
                "muted",
                wrap=True,
            )
        )
        self.path = QLineEdit()
        self.title = QLineEdit()
        self.title.setPlaceholderText(
            "e.g. Firm policy on AI-assisted work (taken from the file if blank)"
        )
        self.pack_id = QLineEdit()
        self.pack_id.setPlaceholderText("optional, e.g. org-ai-policy")
        self.issuer = QLineEdit()
        self.version = QLineEdit("1")
        form.addRow("File", row(self.path, button("Browse…", self._browse)))
        form.addRow("Title", self.title)
        form.addRow("Identifier", self.pack_id)
        form.addRow("Issued by", self.issuer)
        form.addRow("Version", self.version)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a package or document", str(Path.home()), FILES
        )
        if path:
            self.path.setText(path)


class FrameworksTab(Tab):
    title = "📜 Laws & Standards"

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.library = table(
            [
                "Package",
                "Instrument",
                "Scope",
                "Applies in",
                "Version",
                "Standing",
                "Checked against the official text",
                "Requirements",
            ],
            stretch=1,
        )
        self.library.itemSelectionChanged.connect(self._show)
        self.requirements = table(
            ["Provision", "Requirement", "How it is met", "For", "Only for"], stretch=1
        )
        self.requirements.itemSelectionChanged.connect(self._requirement)
        self.reader = QPlainTextEdit()
        self.reader.setReadOnly(True)
        self.applied = QListWidget()
        self.matter_note = label("", "muted", wrap=True)
        self.root.addWidget(
            card(
                "Law and standards packages: international, regional, national, professional and your organisation's own",
                label(
                    "The packages a matter applies are given to the model as rules in every call, "
                    "tighten the system where they say so, become confirmations the reviewer must give "
                    "before approval, and are listed in the report. Shipped packages are summaries "
                    "until a qualified lawyer's validation is recorded; your own must be approved.",
                    "muted",
                    wrap=True,
                ),
                self.library,
                row(
                    button("Import a package or document…", self._import, kind="primary"),
                    button("Approve…", self._approve),
                    button("Record a lawyer's validation…", self._validate),
                    button("Confirm checked against the official text…", self._confirm_current),
                    button("Withdraw", self._withdraw, kind="danger"),
                    button("Reinstate…", self._reinstate),
                    button("Remove", self._remove),
                    button("Export…", self._export),
                    None,
                ),
            ),
            2,
        )
        split = QSplitter()
        split.addWidget(card("Requirements of the selected package", self.requirements))
        split.addWidget(card("Detail", self.reader))
        split.setSizes([820, 420])
        self.root.addWidget(split, 3)
        self.root.addWidget(
            card(
                "Packages applied to the open matter",
                self.matter_note,
                self.applied,
                row(
                    button("Tick the recommended set", self._recommend),
                    button("Save for this matter", self._save, kind="primary"),
                    button("What the model is told…", self._preview),
                    None,
                ),
            ),
            2,
        )
        self._states: dict[str, PackState] = {}

    # ── library ──────────────────────────────────────────────────────────────
    def refresh(self) -> None:
        if not self.actor:
            return
        states = (
            self.session.attempt(
                self, lambda: self.sv.frameworks.list(actor_id=self.actor), quiet=True
            )
            or []
        )
        self._states = {s.pack.pack_id: s for s in states}
        fill(
            self.library,
            [
                [
                    s.pack.short_title + ("  (example)" if s.pack.example else ""),
                    s.pack.instrument or s.pack.title,
                    s.pack.scope,
                    ", ".join(s.pack.jurisdictions).replace("*", "anywhere"),
                    s.pack.version,
                    s.why,
                    self._checked(s.pack.pack_id),
                    str(len(s.pack.requirements)),
                ]
                for s in states
            ],
            ids=[s.pack.pack_id for s in states],
        )
        fit(self.library, [190, 0, 100, 110, 140, 260, 220, 60])
        self._show()
        self._matter()

    def _selected(self) -> PackState | None:
        return self._states.get(selected_id(self.library))

    def _show(self) -> None:
        state = self._selected()
        if state is None:
            fill(self.requirements, [])
            self.reader.clear()
            return
        p = state.pack
        fill(
            self.requirements,
            [
                [
                    r.reference or r.req_id,
                    r.title,
                    plain.effect(r.effect) + (f" ({', '.join(r.controls)})" if r.controls else ""),
                    ", ".join(r.addressed_to),
                    ", ".join(x.replace("_", " ") for x in r.profiles) or "every kind of matter",
                ]
                for r in p.requirements
            ],
            ids=[r.req_id for r in p.requirements],
        )
        fit(self.requirements, [150, 0, 230, 120, 170])
        rules = []
        if p.rules.status_max_age_days:
            rules.append(f"authority status confirmed within {p.rules.status_max_age_days} days")
        if p.rules.forbidden_terms:
            rules.append(
                "model-drafted text may not contain: " + ", ".join(p.rules.forbidden_terms)
            )
        self.reader.setPlainText(
            "\n\n".join(
                x
                for x in (
                    p.title,
                    p.instrument,
                    f"Issued by {p.issuer}. Version {p.version}. Checked against its source as at {p.as_at or 'not recorded'}.",
                    f"Standing: {state.why}",
                    p.description,
                    "Tightens the system: " + "; ".join(rules) if rules else "",
                    p.status_note,
                    p.licence_note,
                    p.source_url,
                    ("Flagged requirements: " + ", ".join(state.flags)) if state.flags else "",
                )
                if x
            )
        )

    def _requirement(self) -> None:
        state = self._selected()
        req_id = selected_id(self.requirements)
        if state is None or not req_id:
            return
        r = next(x for x in state.pack.requirements if x.req_id == req_id)
        parts = [
            f"{state.pack.short_title} — {r.reference}",
            r.title,
            r.text,
            f"How it is met: {plain.effect(r.effect)}",
        ]
        if r.effect == "instruction":
            parts.append(f"The model is told: {r.model_rule}")
        if r.effect in ("attestation", "disclosure"):
            parts.append(
                ("The reviewer confirms: " if r.effect == "attestation" else "The report says: ")
                + r.confirmation
            )
        if r.controls:
            parts.append("Controls: " + ", ".join(r.controls))
        self.reader.setPlainText("\n\n".join(parts))

    # ── changing the library ─────────────────────────────────────────────────
    def _import(self) -> None:
        dialog = _ImportDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.path.text().strip():
            return
        path = Path(dialog.path.text().strip())
        try:
            raw = path.read_bytes()
        except OSError as exc:
            QMessageBox.warning(self, "Import", str(exc))
            return
        state = self.session.attempt(
            self,
            lambda: self.sv.frameworks.import_file(
                path.name,
                raw,
                actor_id=self.actor,
                title=dialog.title.text(),
                pack_id=dialog.pack_id.text(),
                issuer=dialog.issuer.text(),
                version=dialog.version.text() or "1",
            ),
        )
        if state is not None:
            QMessageBox.information(
                self,
                "Imported",
                f"{state.pack.title}: {len(state.pack.requirements)} requirement(s). {state.why[:1].upper() + state.why[1:]}.",
            )
            self.refresh()

    def _approve(self) -> None:
        state = self._selected()
        if state and state.pack.origin == "shipped":
            # Said before the passphrase is asked for, so a refusal costs no sign-in attempt.
            QMessageBox.information(
                self,
                "Approve",
                f"{state.pack.title} came with ELI Legal and is used as shipped; it needs no "
                "approval. Record a qualified lawyer's validation of it instead.",
            )
            return
        if state and self.session.decide(
            self,
            f"approve {state.pack.title}",
            lambda: self.sv.frameworks.approve(state.pack.pack_id, actor_id=self.actor),
        ):
            self.refresh()

    def _validate(self) -> None:
        state = self._selected()
        if state is None:
            return
        lawyer, ok = QInputDialog.getText(
            self,
            "Record a validation",
            f"Name of the lawyer, qualified in {', '.join(state.pack.jurisdictions).replace('*', 'the relevant system')}, who checked\n“{state.pack.title}”, version {state.pack.version}, against its official text:",
        )
        if not ok or not lawyer.strip():
            return
        done = self.session.decide(
            self,
            "record a lawyer's validation",
            lambda: self.sv.frameworks.validate(
                state.pack.pack_id, actor_id=self.actor, lawyer=lawyer
            ),
        )
        if done is not None:
            self.refresh()

    def _checked(self, pack_id: str) -> str:
        on, by = self.sv.checks.law_checked_on(pack_id)
        if on is None:
            return "never recorded"
        age = (date.today() - on).days
        due = age > self.sv.ctx.settings.law_review_days
        return f"{on.isoformat()} ({by})" + (" — due again" if due else "")

    def _confirm_current(self) -> None:
        state = self._selected()
        if state is None:
            return
        note = ReasonDialog.ask(
            self,
            "Confirm checked against the official text",
            f"You checked “{state.pack.title}” (version {state.pack.version}) against the "
            "official text today and it still states the law correctly. Say which text you "
            "checked it against (for example the consolidated version and its date). The "
            "routine checks then count its review from today.",
        )
        if note:
            self.session.decide(
                self,
                "confirm this package is current",
                lambda: self.sv.checks.confirm_law_current(
                    state.pack.pack_id, actor_id=self.actor, checked_on=date.today(), note=note
                ),
            )

    def _withdraw(self) -> None:
        state = self._selected()
        if state and self.session.attempt(
            self, lambda: self.sv.frameworks.withdraw(state.pack.pack_id, actor_id=self.actor)
        ):
            self.refresh()

    def _reinstate(self) -> None:
        state = self._selected()
        if state and self.session.decide(
            self,
            f"reinstate {state.pack.title}",
            lambda: self.sv.frameworks.reinstate(state.pack.pack_id, actor_id=self.actor),
        ):
            self.refresh()

    def _remove(self) -> None:
        state = self._selected()
        if state is None:
            return
        if (
            QMessageBox.question(self, "Remove", f"Delete {state.pack.title} from the library?")
            != QMessageBox.StandardButton.Yes
        ):
            return

        def remove() -> bool:
            self.sv.frameworks.remove(state.pack.pack_id, actor_id=self.actor)
            return True

        if self.session.attempt(self, remove):
            self.refresh()

    def _export(self) -> None:
        state = self._selected()
        if state is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export package", str(Path.home() / f"{state.pack.pack_id}.json"), "JSON (*.json)"
        )
        if not path:
            return
        text = self.session.attempt(
            self, lambda: self.sv.frameworks.export(state.pack.pack_id, actor_id=self.actor)
        )
        if text:
            Path(path).write_text(text, encoding="utf-8")

    # ── the open matter ──────────────────────────────────────────────────────
    def _matter(self) -> None:
        self.applied.clear()
        if not self.mid:
            self.matter_note.setText("Open a matter to choose its packages.")
            return
        matter = self.session.attempt(
            self, lambda: self.sv.matters.get(self.mid, self.actor), quiet=True
        )
        if matter is None:
            return
        recommended = set(
            self.sv.frameworks.recommended(
                matter.profile.value, matter.jurisdiction, actor_id=self.actor
            )
        )
        self.matter_note.setText(
            f"“{matter.name}” — {matter.profile.value.replace('_', ' ')}, {matter.jurisdiction}. Ticked packages apply "
            "from the next run. ★ marks those recommended for this kind of matter and legal system."
        )
        for state in self._states.values():
            if not state.usable:
                continue
            item = QListWidgetItem(
                f"{'★ ' if state.pack.pack_id in recommended else '   '}{state.pack.title}  ({state.why})"
            )
            item.setData(Qt.ItemDataRole.UserRole, state.pack.pack_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if state.pack.pack_id in matter.framework_ids
                else Qt.CheckState.Unchecked
            )
            self.applied.addItem(item)

    def _ticked(self) -> list[str]:
        return [
            str(self.applied.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(self.applied.count())
            if self.applied.item(i).checkState() == Qt.CheckState.Checked
        ]

    def _recommend(self) -> None:
        matter = self.sv.ctx.store.get_matter(self.mid) if self.mid else None
        if matter is None:
            return
        wanted = set(
            self.sv.frameworks.recommended(
                matter.profile.value, matter.jurisdiction, actor_id=self.actor
            )
        )
        for i in range(self.applied.count()):
            item = self.applied.item(i)
            item.setCheckState(
                Qt.CheckState.Checked
                if item.data(Qt.ItemDataRole.UserRole) in wanted
                else Qt.CheckState.Unchecked
            )

    def _save(self) -> None:
        if not self.mid:
            return
        chosen = self._ticked()
        if self.session.attempt(
            self,
            lambda: self.sv.frameworks.set_for_matter(
                self.mid, actor_id=self.actor, pack_ids=chosen
            ),
        ):
            QMessageBox.information(
                self, "Saved", f"{len(chosen)} package(s) apply to this matter from the next run."
            )
            self.refresh()

    def _preview(self) -> None:
        if not self.mid:
            return
        text = self.session.attempt(
            self, lambda: self.sv.frameworks.context_for(self.mid, actor_id=self.actor)
        )
        dialog = QDialog(self)
        dialog.setWindowTitle("What the model is told about the law and standards")
        dialog.resize(820, 560)
        view = QPlainTextEdit(
            text or "No package applies, so the model is given only the system's own rules."
        )
        view.setReadOnly(True)
        layout = QFormLayout(dialog)
        layout.addRow(view)
        dialog.exec()
