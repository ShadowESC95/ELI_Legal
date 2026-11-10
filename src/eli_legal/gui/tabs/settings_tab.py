from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from eli_legal import __version__
from eli_legal.domain import plain
from eli_legal.gui import theme
from eli_legal.gui.model_picker import ModelPicker
from eli_legal.gui.people import UserDialog as _UserDialog
from eli_legal.gui.people import new_passphrase
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import button, card, fill, fit, label, row, selected_id, table
from eli_legal.security import access
from eli_legal.security.rbac import DEFAULT_ROLE_ACTIONS
from eli_legal.settings import ENV_FILE


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
                    button("Second factor…", self._second_factor),
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
                button("Unlock", self._unlock),
                button("Reset second factor", self._reset_second_factor),
                button("Deactivate", self._deactivate, kind="danger"),
                None,
            )
        )
        self.inner.addTab(page, "Users and roles")

        # what every role may do, for anyone deciding who gets which
        self.matrix = QTextBrowser()
        self.matrix.setOpenLinks(False)
        cell = "padding:4px 10px 4px 0; vertical-align:top; border-bottom:1px solid #2b3647"
        account = "".join(
            f"<tr><td style='{cell}'><b>{plain.role(code)}</b></td>"
            f"<td style='{cell}'>{plain.role_summary(code)}</td>"
            f"<td style='{cell}; color:{theme.MUTED}'>"
            + "; ".join(sorted(plain.action(a) for a in DEFAULT_ROLE_ACTIONS[code]))
            + "</td></tr>"
            for code in sorted(DEFAULT_ROLE_ACTIONS, key=plain.role)
        )
        on_matter = "".join(
            f"<tr><td style='{cell}'><b>{r.label}</b></td><td style='{cell}'>{r.summary}</td>"
            f"<td style='{cell}'>"
            + (
                "Everything"
                if r.clearance == access.ALL_SCOPES
                else ", ".join(plain.scope(c) for c in sorted(r.clearance)) or "Nothing"
            )
            + "</td></tr>"
            for r in access.MATTER_ROLES.values()
        )
        self.matrix.setHtml(
            "<p>Three things decide what a person may do on a matter, and all three must agree: "
            "their <b>account role</b>, their <b>role on that matter</b>, and the material they "
            "are <b>cleared to read</b>. A role on a matter narrows the account role; it never "
            "adds to it.</p>"
            "<h3>Roles on a matter</h3><table width='100%' cellspacing='0'>"
            "<tr><th align='left'>Role</th><th align='left'>What it is for</th>"
            f"<th align='left'>Reads</th></tr>{on_matter}</table>"
            "<h3>Account roles</h3><table width='100%' cellspacing='0'>"
            "<tr><th align='left'>Role</th><th align='left'>What it is for</th>"
            f"<th align='left'>What it may do</th></tr>{account}</table>"
        )
        self.inner.addTab(self.matrix, "What each role can do")

        self.picker = ModelPicker(self.sv)
        self.model_state = label("", wrap=True)
        holder = self.picker
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(
            card(
                "Model",
                self.model_state,
                holder,
                row(
                    button("Apply…", self._apply_model, kind="primary"),
                    button("Install a graphics pack from a file…", self._install_gpu),
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
        self.blocked = table(["Blocked connection attempts (this session)", "Outcome"], stretch=0)
        self.offline_state = label("", wrap=True)
        self.offline_now = button("Go hard offline now…", self._go_offline, kind="danger")
        self.at_start = QCheckBox("Start hard offline every time")
        self.at_start.clicked.connect(self._at_start)
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(card("This installation", self.system))
        box.addWidget(
            card(
                "Hard offline",
                label(
                    "Hard offline makes the computer's own kernel refuse every network "
                    "connection from ELI Legal: Python code, native code such as llama.cpp, and "
                    "any program ELI Legal starts. Unlike a switch inside the program, nothing "
                    "running in it can undo it: it lasts until ELI Legal is closed. Local models "
                    "(GGUF files) keep working; live legal sources and a model server do not.",
                    "muted",
                    wrap=True,
                ),
                self.offline_state,
                row(self.offline_now, self.at_start, None),
            )
        )
        box.addWidget(card("Network", self.blocked), 1)
        self.inner.addTab(page, "System")

    def refresh(self) -> None:
        ctx = self.sv.ctx
        user = self.session.user
        if user is not None:
            self.me.setText(
                f"<b>{user.display_name}</b> ({user.user_id})<br>Roles: {plain.roles(user.roles)}<br>Second factor: {'set up' if self.sv.users.has_second_factor(user.user_id) else 'not set up'}<br><span style='color:{theme.MUTED}'>Decisions you record ask for your passphrase again and are logged under your name.</span>"
            )
        users = self.sv.users.directory(self.actor) if self.actor else []
        fill(
            self.users,
            [
                [
                    u.user_id,
                    u.display_name,
                    plain.roles(u.roles),
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
        self.picker.load(current)
        loaded = current["loaded"]["model"]
        self.model_state.setText(
            f"In use now — drafting: <b>{current['active_model_id']}</b>; verifying: <b>{current['active_verifier_id']}</b>"
            + (
                f"<br>Loaded with {loaded['summary']}."
                if loaded
                else (
                    "<br>The model loads at its first use; how it loaded is then shown here."
                    if current["backend"] == "gguf"
                    else ""
                )
            )
        )
        self.picker.show_placement()
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
        fill(
            self.blocked,
            [[a["host"], a.get("outcome", "blocked")] for a in ctx.guard.blocked_attempts()]
            or [["none", ""]],
        )
        status = self.sv.network.status()
        self.offline_state.setText(
            f"<b style='color:{theme.GOOD}'>ON</b>, enforced by {status['enforced_by']}. "
            f"{status['detail']}"
            + (" Checked: a native connection attempt was refused." if status["verified"] else "")
            if status["hard_offline"]
            else "<b>Off.</b> The network guard denies connections by default and opens one "
            "approved host at a time for an approved legal source."
        )
        self.offline_now.setEnabled(not status["hard_offline"])
        self.at_start.blockSignals(True)
        self.at_start.setChecked(status["at_every_start"])
        self.at_start.blockSignals(False)
        self.at_start.setEnabled(self.session.may("config.manage"))

    # ── hard offline ─────────────────────────────────────────────────────────
    def _go_offline(self) -> None:
        answer = QMessageBox.question(
            self,
            "Go hard offline",
            "From now until ELI Legal is closed, the kernel will refuse every network connection "
            "it makes. This cannot be undone while ELI Legal is running. Live legal sources and "
            "a model server will stop working; local GGUF models will not.\n\nGo hard offline?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.session.attempt(self, lambda: self.sv.network.go_offline(actor_id=self.actor))

    def _at_start(self, on: bool) -> None:
        what = (
            "start ELI Legal hard offline every time"
            if on
            else "stop starting ELI Legal hard offline (from the next start)"
        )
        done = self.session.decide(
            self,
            what,
            lambda: self.sv.network.set_at_every_start(
                actor_id=self.actor, on=on, persist_to=ENV_FILE
            ),
        )
        if done is None:
            self.refresh()

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

    # ── second factor and locks ──────────────────────────────────────────────
    def _second_factor(self) -> None:
        """Set up an authenticator code for yourself, or remove the one you have."""
        users = self.sv.users
        if users.has_second_factor(self.actor):
            asked = QMessageBox.question(
                self,
                "Second factor",
                "You have a second factor set up.\n\nRemove it? You would then sign in with your "
                "passphrase alone, and your other sessions will be ended.",
            )
            if asked != QMessageBox.StandardButton.Yes:
                return

            def remove() -> bool:
                users.second_factor_remove(actor_id=self.actor, user_id=self.actor)
                return True

            if self.session.decide(self, "remove your second factor", remove):
                self.refresh()
            return
        started = self.session.decide(
            self, "set up a second factor", lambda: users.second_factor_begin(actor_id=self.actor)
        )
        if started is None:
            return
        secret, _uri = started
        code, ok = QInputDialog.getText(
            self,
            "Set up your authenticator",
            "Add this key to an authenticator app on your phone:\n\n"
            f"    {secret}\n\nThen enter the six-digit code the app shows:",
        )
        if not ok:
            return

        def confirm() -> bool:
            users.second_factor_confirm(actor_id=self.actor, code=code.strip())
            return True

        if self.session.attempt(self, confirm):
            QMessageBox.information(
                self,
                "Second factor",
                "Set up. From now on you will be asked for a code at every sign-in, here, in the "
                "browser and on the command line.",
            )
            self.refresh()

    def _unlock(self) -> None:
        uid = selected_id(self.users)
        if not uid:
            return

        def unlock() -> bool:
            self.sv.users.unlock(actor_id=self.actor, user_id=uid)
            return True

        if self.session.decide(self, f"unlock {uid}", unlock):
            QMessageBox.information(self, "Unlocked", f"{uid} can sign in again.")

    def _reset_second_factor(self) -> None:
        uid = selected_id(self.users)
        if not uid or uid == self.actor:
            return

        def reset() -> bool:
            self.sv.users.second_factor_remove(actor_id=self.actor, user_id=uid)
            return True

        if self.session.decide(self, f"remove the second factor of {uid}", reset):
            QMessageBox.information(
                self, "Second factor", f"Removed for {uid}. Their sessions have been ended."
            )

    # ── model ────────────────────────────────────────────────────────────────
    def _install_gpu(self) -> None:
        """A graphics pack is the llama.cpp that uses the card: installing one changes the code
        that runs the model, so it is a decision like changing the model."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a graphics pack", str(Path.home()), "Graphics packs (*.whl)"
        )
        if not path:
            return

        def install() -> dict[str, object]:
            return self.sv.config.install_gpu_runtime(actor_id=self.actor, wheel=Path(path))

        done = self.session.decide(self, "install a graphics runtime", install)
        if done is not None:
            said = str(done["summary"])
            QMessageBox.information(self, "Graphics runtime", said[:1].upper() + said[1:] + ".")
            self.refresh()

    def _apply_model(self) -> None:
        values = self.picker.values()
        if values["backend"] in ("gguf", "openai_compat") and not values["model"]:
            QMessageBox.warning(self, "Model", "Choose a model first.")
            return

        def change() -> dict[str, object]:
            result = self.sv.config.set_model(actor_id=self.actor, persist_to=ENV_FILE, **values)
            return result

        done = self.session.decide(self, "change the model the system uses", change)
        if done is not None:
            self.refresh()
            self.session.changed.emit()

    def export_policy(self) -> str:
        return json.dumps(json.loads(self.policy.toPlainText() or "{}"), indent=2)
