from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from eli_legal import __version__
from eli_legal.domain.errors import EliLegalError
from eli_legal.gui import theme
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import button, card, fill, fit, label, row, selected_id, table
from eli_legal.security.rbac import DEFAULT_ROLE_ACTIONS
from eli_legal.settings import ENV_FILE


def new_passphrase(parent: QWidget, who: str) -> str | None:
    first, ok = QInputDialog.getText(
        parent,
        "New passphrase",
        f"New passphrase for {who} (at least 10 characters):",
        QLineEdit.EchoMode.Password,
    )
    if not ok:
        return None
    second, ok = QInputDialog.getText(
        parent, "New passphrase", "Repeat it:", QLineEdit.EchoMode.Password
    )
    if not ok:
        return None
    if first != second:
        QMessageBox.warning(parent, "Passphrase", "The two entries differ. Nothing was changed.")
        return None
    return first


class _UserDialog(QDialog):
    def __init__(
        self, parent: QWidget, user_id: str = "", name: str = "", roles: set[str] | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("User and roles")
        self.setMinimumWidth(460)
        form = QFormLayout(self)
        self.user_id = QLineEdit(user_id)
        self.user_id.setReadOnly(bool(user_id))
        self.name = QLineEdit(name)
        self.roles = QListWidget()
        for role in sorted(DEFAULT_ROLE_ACTIONS):
            item = QListWidgetItem(role.replace("_", " "))
            item.setData(Qt.ItemDataRole.UserRole, role)
            item.setCheckState(
                Qt.CheckState.Checked if roles and role in roles else Qt.CheckState.Unchecked
            )
            self.roles.addItem(item)
        form.addRow("User id", self.user_id)
        form.addRow("Name", self.name)
        form.addRow("Roles", self.roles)
        form.addRow(
            label(
                "A role says what someone may do. It never gives access to a matter: that is granted matter by matter.",
                "muted",
                wrap=True,
            )
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def chosen(self) -> list[str]:
        return [
            str(self.roles.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(self.roles.count())
            if self.roles.item(i).checkState() == Qt.CheckState.Checked
        ]


class SettingsTab(Tab):
    title = "⚙ Settings"

    def __init__(self, session, on_sign_out) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.inner = QTabWidget()
        self.root.addWidget(self.inner)

        self.me = label("", wrap=True, selectable=True)
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(
            card(
                "Signed in",
                self.me,
                row(
                    button("Change my passphrase…", self._my_passphrase),
                    button("Sign out", on_sign_out),
                    None,
                ),
            )
        )
        box.addStretch(1)
        self.inner.addTab(page, "You")

        self.users = table(["User", "Name", "Roles", "State", "Passphrase"], stretch=2)
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(self.users, 1)
        box.addWidget(
            row(
                button("Add a user…", self._add_user, kind="primary"),
                button("Change roles…", self._edit_user),
                button("Set a passphrase…", self._set_passphrase),
                button("Issue an API token…", self._token),
                button("Deactivate", self._deactivate, kind="danger"),
                None,
            )
        )
        self.inner.addTab(page, "Users and roles")

        self.backend = QComboBox()
        self.backend.addItem("No model — every step that needs none still runs", "none")
        self.backend.addItem(
            "A model server on this machine (Ollama, llama.cpp, LM Studio)", "openai_compat"
        )
        self.url = QLineEdit()
        self.model = QComboBox()
        self.model.setEditable(True)
        self.verifier = QComboBox()
        self.verifier.setEditable(True)
        self.model_state = label("", wrap=True)
        form = QFormLayout()
        form.addRow("Use", self.backend)
        form.addRow("Server address", self.url)
        form.addRow("Model", self.model)
        form.addRow("Verifier (a different model)", self.verifier)
        holder = QWidget()
        holder.setLayout(form)
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(
            card(
                "Model",
                self.model_state,
                holder,
                row(
                    button("List the models on this machine", self._list_models),
                    button("Apply…", self._apply_model, kind="primary"),
                    None,
                ),
            )
        )
        box.addWidget(
            label(
                "A model may only select sentences, link items and draft attributed arguments from what the system hands it. The verifier can only make a check stricter. Changing the model changes what every later run can produce, so it is recorded and should be followed by a change assessment.",
                "muted",
                wrap=True,
            )
        )
        box.addStretch(1)
        self.inner.addTab(page, "Model")

        self.packs = table(
            ["Code", "Legal system", "Family", "Pack", "Validated by", "Citation forms", "Notes"],
            stretch=6,
        )
        self.inner.addTab(self.packs, "Legal systems")

        self.policy = QPlainTextEdit()
        self.policy.setReadOnly(True)
        self.inner.addTab(self.policy, "Policy")

        self.system = label("", wrap=True, selectable=True)
        self.blocked = table(["Blocked connection attempts (this session)"])
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(card("This installation", self.system))
        box.addWidget(card("Network", self.blocked), 1)
        self.inner.addTab(page, "System")

    def refresh(self) -> None:
        ctx = self.sv.ctx
        user = self.session.user
        if user is not None:
            self.me.setText(
                f"<b>{user.display_name}</b> ({user.user_id})<br>Roles: {', '.join(sorted(r.replace('_', ' ') for r in user.roles)) or 'none'}<br><span style='color:{theme.MUTED}'>Decisions you record ask for your passphrase again and are logged under your name.</span>"
            )
        users = self.sv.users.directory(self.actor) if self.actor else []
        fill(
            self.users,
            [
                [
                    u.user_id,
                    u.display_name,
                    ", ".join(sorted(r.replace("_", " ") for r in u.roles)),
                    "active" if u.active else "inactive",
                    "set" if u.passphrase_hash else "NOT SET — cannot sign in",
                ]
                for u in users
            ],
            ids=[u.user_id for u in users],
            state_columns=[3],
        )
        fit(self.users, [150, 190, 0, 80, 200])
        self._users = {u.user_id: u for u in users}
        current = self.sv.config.current()
        self.backend.setCurrentIndex(max(0, self.backend.findData(current["backend"])))
        self.url.setText(current["url"])
        self.model.setEditText(current["model"])
        self.verifier.setEditText(current["verifier_model"])
        self.model_state.setText(
            f"In use now — drafting: <b>{current['active_model_id']}</b>; verifying: <b>{current['active_verifier_id']}</b>"
        )
        packs = [ctx.jurisdictions.get(code) for code in ctx.jurisdictions.codes()]
        fill(
            self.packs,
            [
                [
                    p.code,
                    p.name,
                    p.legal_family.replace("_", " "),
                    p.pack_status,
                    p.validated_by or "NOT VALIDATED",
                    ", ".join(c.example for c in p.citation_patterns),
                    p.notes,
                ]
                for p in packs
            ],
        )
        fit(self.packs, [80, 220, 110, 90, 130, 420, 0])
        self.policy.setPlainText(Path(ctx.settings.policy_file).read_text(encoding="utf-8"))
        chain = ctx.audit.report()
        s = ctx.settings
        self.system.setText(
            f"ELI Legal {__version__} · workflow {ctx.workflow.workflow_id} {ctx.workflow.version} · policy {ctx.policy.version}<br>"
            f"Store: {s.db_path}<br>Audit ledger: {s.audit_db_path} ({chain.count} events, {'valid' if chain.ok else 'INVALID'})<br>"
            f"Audit key: {s.audit_key_file} (id {ctx.audit.key_id})<br>Evidence vault: {s.data_dir}<br>Reports and evidence packs: {s.artifacts_dir}<br>"
            f"Network: denied by default; guard installed: {ctx.guard.installed}; approved hosts: {', '.join(sorted(ctx.guard.approved_hosts())) or 'none'}"
        )
        fill(self.blocked, [[a["host"]] for a in ctx.guard.blocked_attempts()] or [["none"]])

    # ── you ──────────────────────────────────────────────────────────────────
    def _my_passphrase(self) -> None:
        current, ok = QInputDialog.getText(
            self, "Change passphrase", "Current passphrase:", QLineEdit.EchoMode.Password
        )
        if not ok:
            return
        new = new_passphrase(self, "you")
        if new is None:
            return

        def change() -> bool:
            self.sv.users.set_passphrase(
                actor_id=self.actor, user_id=self.actor, new=new, current=current
            )
            return True

        if self.session.attempt(self, change):
            QMessageBox.information(
                self, "Passphrase", "Changed. Other open sessions of yours have been ended."
            )

    # ── users ────────────────────────────────────────────────────────────────
    def _add_user(self) -> None:
        dialog = _UserDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.user_id.text().strip():
            uid = dialog.user_id.text().strip()
            self.session.decide(
                self,
                f"create the user {uid}",
                lambda: self.sv.users.add_user(
                    actor_id=self.actor,
                    user_id=uid,
                    display_name=dialog.name.text().strip(),
                    roles=dialog.chosen(),
                ),
            )

    def _edit_user(self) -> None:
        user = getattr(self, "_users", {}).get(selected_id(self.users))
        if user is None:
            return
        dialog = _UserDialog(self, user.user_id, user.display_name, set(user.roles))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.session.decide(
                self,
                f"change the roles of {user.user_id}",
                lambda: self.sv.users.add_user(
                    actor_id=self.actor,
                    user_id=user.user_id,
                    display_name=dialog.name.text().strip(),
                    roles=dialog.chosen(),
                ),
            )

    def _set_passphrase(self) -> None:
        uid = selected_id(self.users)
        if not uid or uid == self.actor:
            return
        new = new_passphrase(self, uid)
        if new is not None:
            self.session.decide(
                self,
                f"set the passphrase of {uid}",
                lambda: self.sv.users.set_passphrase(actor_id=self.actor, user_id=uid, new=new),
            )

    def _token(self) -> None:
        uid = selected_id(self.users)
        if not uid:
            return
        token = self.session.decide(
            self,
            f"issue an API token for {uid}",
            lambda: self.sv.users.issue_token(
                actor_id=self.actor, user_id=uid, label="issued from the desktop application"
            ),
        )
        if token:
            QInputDialog.getText(
                self,
                "API token",
                "Copy this token now. It cannot be shown again.",
                QLineEdit.EchoMode.Normal,
                token,
            )

    def _deactivate(self) -> None:
        uid = selected_id(self.users)
        if uid and uid != self.actor:
            self.session.attempt(
                self, lambda: self.sv.users.deactivate(actor_id=self.actor, user_id=uid)
            )

    # ── model ────────────────────────────────────────────────────────────────
    def _list_models(self) -> None:
        try:
            models = self.sv.config.available_models(self.url.text().strip())
        except EliLegalError as exc:
            QMessageBox.warning(self, "Models", str(exc))
            return
        for combo in (self.model, self.verifier):
            text = combo.currentText()
            combo.clear()
            combo.addItems(["", *models])
            combo.setEditText(text)
        QMessageBox.information(self, "Models", f"{len(models)} model(s) found on this machine.")

    def _apply_model(self) -> None:
        backend, url = self.backend.currentData(), self.url.text().strip()
        model, verifier = self.model.currentText().strip(), self.verifier.currentText().strip()
        self.session.decide(
            self,
            "change the model the system uses",
            lambda: self.sv.config.set_model(
                actor_id=self.actor,
                backend=backend,
                url=url,
                model=model if backend != "none" else "",
                verifier_model=verifier if backend != "none" else "",
                persist_to=ENV_FILE,
            ),
        )

    def export_policy(self) -> str:
        return json.dumps(json.loads(self.policy.toPlainText() or "{}"), indent=2)
