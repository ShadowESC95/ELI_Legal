"""Entry point of the desktop application: first-run set-up, sign-in, then the main window."""

from __future__ import annotations

import os
import secrets
import signal
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from eli_legal import __version__
from eli_legal.application.services import Services, build_services
from eli_legal.domain.errors import AccountLocked, EliLegalError, SecondFactorRequired
from eli_legal.gui import theme
from eli_legal.gui.main_window import MainWindow
from eli_legal.gui.session import Session
from eli_legal.gui.widgets import label
from eli_legal.security import authn, hard_offline
from eli_legal.security.files import private_process
from eli_legal.settings import ENV_FILE, Settings


def _ensure_key(settings: Settings) -> bool:
    """Create the audit key on first run. Returns True if it was just created."""
    key = Path(settings.audit_key_file)
    if key.exists():
        return False
    for directory in (
        key.parent,
        Path(settings.db_path).parent,
        Path(settings.data_dir),
        Path(settings.artifacts_dir),
    ):
        directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(secrets.token_hex(32))
    return True


class FirstRunDialog(QDialog):
    """Nobody exists yet: create the first administrator."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set up ELI Legal")
        self.setMinimumWidth(480)
        form = QFormLayout(self)
        form.addRow(label("Welcome to ELI Legal", "title"))
        form.addRow(
            label(
                "Create the first administrator. The administrator creates the other users and approves legal sources, but has no access to any matter unless someone grants it.",
                "muted",
                wrap=True,
            )
        )
        self.user_id = QLineEdit("admin")
        self.name = QLineEdit()
        self.name.setPlaceholderText("Your name")
        self.first = QLineEdit()
        self.first.setEchoMode(QLineEdit.EchoMode.Password)
        self.second = QLineEdit()
        self.second.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("User id", self.user_id)
        form.addRow("Name", self.name)
        form.addRow("Passphrase (10+ characters)", self.first)
        form.addRow("Repeat it", self.second)
        # Chosen now, not left unset: until it is chosen nothing is deleted on time. Suggested:
        # six years (a common limitation period); the audit trail at least six months.
        form.addRow(
            label(
                "How long is the record kept? Check these against your own rules; you can change "
                "them later in Compliance (OA-09).",
                "muted",
                wrap=True,
            )
        )
        self.audit_days = self._days(2190, minimum=183)
        self.closed_days = self._days(2190)
        self.evidence_days = self._days(3650)
        self.record_days = self._days(3650)
        self.idle_days = self._days(365)
        self.idle_days.setSpecialValueText("never")
        form.addRow("Keep the audit trail", self.audit_days)
        form.addRow("Keep a closed case's papers", self.closed_days)
        form.addRow("Keep its evidence packs", self.evidence_days)
        form.addRow("Keep its decision record", self.record_days)
        form.addRow("Report an open matter idle for", self.idle_days)
        form.addRow(
            "",
            label(
                "A case's analysis and reports are kept as long as its papers unless Compliance "
                "says otherwise; each kind is archived under its own key and goes on its own day.",
                "muted",
                wrap=True,
            ),
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._check)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @staticmethod
    def _days(value: int, *, minimum: int = 0) -> QSpinBox:
        box = QSpinBox()
        box.setRange(minimum, 36_500)
        box.setSuffix(" days")
        box.setValue(value)
        return box

    def retention(self) -> dict[str, int]:
        return {
            "audit_days": self.audit_days.value(),
            "closed_matter_days": self.closed_days.value(),
            "evidence_days": self.evidence_days.value(),
            "record_days": max(
                self.record_days.value(), self.closed_days.value(), self.evidence_days.value()
            ),
            "inactive_matter_days": self.idle_days.value(),
        }

    def _check(self) -> None:
        if self.first.text() != self.second.text():
            QMessageBox.warning(self, "Passphrase", "The two entries differ.")
        elif len(self.first.text()) < 10 or not self.user_id.text().strip():
            QMessageBox.warning(
                self, "Set-up", "A user id and a passphrase of at least 10 characters are needed."
            )
        else:
            self.accept()


class SignInDialog(QDialog):
    def __init__(self, services: Services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"ELI Legal {__version__} — sign in")
        self.setMinimumWidth(440)
        form = QFormLayout(self)
        form.addRow(label("ELI Legal", "title"))
        form.addRow(label("Governed legal case preparation. Decision support only.", "muted"))
        self.user = QComboBox()
        self.user.setEditable(True)
        for user in services.ctx.store.list_users():
            if user.active:
                self.user.addItem(user.user_id)
        self.phrase = QLineEdit()
        self.phrase.setEchoMode(QLineEdit.EchoMode.Password)
        self.code = QLineEdit()
        self.code.setPlaceholderText("only if you have set up an authenticator")
        self.code.setMaxLength(8)
        form.addRow("User", self.user)
        form.addRow("Passphrase", self.phrase)
        form.addRow("Code", self.code)
        form.addRow(
            label(
                "Everything you do is recorded under your name. A decision will ask for your passphrase again.",
                "muted",
                wrap=True,
            )
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Sign in")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.phrase.setFocus()


def create_application(argv: list[str] | None = None) -> QApplication:
    if QApplication.instance() is None:
        # Let a font set on a window reach every widget in it, as it does without a stylesheet:
        # zooming (gui/zoom.py) relies on it. Only possible before the application exists.
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseStyleSheetPropagationInWidgetStyles)
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    assert isinstance(app, QApplication)
    app.setApplicationName("ELI Legal")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.STYLESHEET)
    from eli_legal.gui import zoom

    zoom.install(app)  # Ctrl and + or - make everything larger or smaller
    icon = Path(__file__).resolve().parent / "assets" / "eli_legal_256.png"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    return app


class ModelChoiceDialog(QDialog):
    """Shown when an administrator signs in and no model is set: choose one now, or later."""

    def __init__(self, services: Services) -> None:
        super().__init__()
        self.setWindowTitle("ELI Legal: choose a model")
        self.resize(760, 420)
        from eli_legal.gui.model_picker import ModelPicker

        self.picker = ModelPicker(services)
        if self.picker.backend.findData("gguf") >= 0 and services.config.gguf_models():
            self.picker.backend.setCurrentIndex(self.picker.backend.findData("gguf"))
        self.never = QCheckBox("Do not ask again (choose one later in Settings, Model)")
        buttons = QDialogButtonBox()
        buttons.addButton("Use this model", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Not now", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(
            label(
                "No model is set. ELI Legal works without one, but a model lets it select facts more fully, "
                "link them to issues and draft the arguments open to each party. Every model runs on this "
                "machine; nothing is sent anywhere. Choosing one is recorded under your name.",
                "muted",
                wrap=True,
            )
        )
        layout.addWidget(self.picker)
        layout.addWidget(self.never)
        layout.addWidget(buttons)


def _model_at_start(session: Session, phrase: str) -> None:
    """Say if the configured model cannot be used, and offer an administrator the choice of
    one if none is set. The passphrase just given confirms the choice."""
    sv = session.sv
    current = sv.config.current()
    reason = getattr(sv.ctx.model.inference, "reason", "")
    if reason:
        QMessageBox.warning(
            None,
            "Model",
            reason[:1].upper()
            + reason[1:]
            + ".\n\nELI Legal will run without a model until this is put right in Settings, Model.",
        )
        return
    if current["backend"] != "none" or not sv.ctx.settings.model_prompt:
        return
    if not sv.ctx.authorizer().bindings.can(session.user_id, "config.manage"):
        return
    dialog = ModelChoiceDialog(sv)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    if dialog.never.isChecked():
        from eli_legal.application.config_service import _update_env_file

        _update_env_file(ENV_FILE, {"ELI_LEGAL_MODEL_PROMPT": "false"})
        sv.ctx.settings.model_prompt = False
    if accepted:
        values = dialog.picker.values()
        session.decide_with(
            dialog,
            phrase,
            lambda: sv.config.set_model(actor_id=session.user_id, persist_to=ENV_FILE, **values),
        )


def _licensed() -> bool:
    """Ask for a key until one licenses this copy, or the user stops."""
    from eli_sdk import InvalidKey

    from eli_legal import licensing

    if licensing.allowed():
        return True
    reason = licensing.status().reason
    while True:
        key, ok = QInputDialog.getText(
            None,
            "ELI Legal licence",
            f"ELI Legal needs a licence: {reason}.\n\n"
            "Paste your ELI Legal key, or an ELI v3 key that includes ELI Legal.\n"
            f"Buy one: {licensing.BUY}",
        )
        if not ok or not key.strip():
            return False
        try:
            licensing.activate(key)
            return True
        except InvalidKey as exc:
            reason = str(exc)


def main(argv: list[str] | None = None) -> int:
    # Ctrl+C in the terminal that started it closes the program, as it does any other. Qt's
    # event loop otherwise keeps Python from acting on it, and each press only prints an error.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    private_process()  # files and folders this program creates are its user's alone
    if Settings().hard_offline:
        hard_offline.relaunch_sandboxed_if_needed()  # macOS only; returns elsewhere
    app = create_application(argv)
    if not _licensed():
        return 0
    from eli_legal import bundle

    bundle.refresh_registration()  # ELI v3 opens the newest copy on this machine
    settings = Settings()
    try:
        _ensure_key(settings)
        services = build_services(settings)
    except (EliLegalError, OSError) as exc:
        QMessageBox.critical(None, "ELI Legal cannot start", f"{type(exc).__name__}\n\n{exc}")
        return 2
    if settings.hard_offline:
        services.network.go_offline(actor_id="system")
    if not services.ctx.store.list_users():
        first = FirstRunDialog()
        if first.exec() != QDialog.DialogCode.Accepted:
            return 0
        admin = first.user_id.text().strip()
        services.users.bootstrap_admin(
            admin, first.name.text().strip(), passphrase=first.first.text()
        )
        # The administrator has just chosen the passphrase: this is that person, confirmed.
        with authn.established(admin, "gui-passphrase", step_up=True):
            r = first.retention()
            services.compliance.set_retention(
                actor_id=admin,
                audit_days=r["audit_days"],
                closed_matter_days=r["closed_matter_days"],
                inactive_matter_days=r["inactive_matter_days"],
                evidence_days=r["evidence_days"],
                record_days=r["record_days"],
            )
    session = Session(services)
    while True:
        dialog = SignInDialog(services)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return 0
        try:
            session.sign_in(
                dialog.user.currentText().strip(), dialog.phrase.text(), dialog.code.text().strip()
            )
        except (AccountLocked, SecondFactorRequired) as exc:
            QMessageBox.warning(None, "Sign in", str(exc)[:1].upper() + str(exc)[1:] + ".")
            continue
        except EliLegalError:
            QMessageBox.warning(
                None,
                "Sign in",
                "Unknown user, wrong passphrase or wrong code.\n\nIf you have no passphrase yet, an administrator must set your first one.",
            )
            continue
        _model_at_start(session, dialog.phrase.text())
        window = MainWindow(session)
        window.show()
        app.exec()
        if not window.signing_out:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
