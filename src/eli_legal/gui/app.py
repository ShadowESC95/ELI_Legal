"""Entry point of the desktop application: first-run set-up, sign-in, then the main window."""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QWidget,
)

from eli_legal import __version__
from eli_legal.application.services import Services, build_services
from eli_legal.domain.errors import AccountLocked, EliLegalError, SecondFactorRequired
from eli_legal.gui import theme
from eli_legal.gui.main_window import MainWindow
from eli_legal.gui.session import Session
from eli_legal.gui.widgets import label
from eli_legal.settings import Settings


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
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._check)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

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
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    assert isinstance(app, QApplication)
    app.setApplicationName("ELI Legal")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.STYLESHEET)
    icon = Path(__file__).resolve().parent / "assets" / "eli_legal_256.png"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    return app


def main(argv: list[str] | None = None) -> int:
    app = create_application(argv)
    settings = Settings()
    try:
        _ensure_key(settings)
        services = build_services(settings)
    except (EliLegalError, OSError) as exc:
        QMessageBox.critical(None, "ELI Legal cannot start", f"{type(exc).__name__}\n\n{exc}")
        return 2
    if not services.ctx.store.list_users():
        first = FirstRunDialog()
        if first.exec() != QDialog.DialogCode.Accepted:
            return 0
        services.users.bootstrap_admin(
            first.user_id.text().strip(), first.name.text().strip(), passphrase=first.first.text()
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
        window = MainWindow(session)
        window.show()
        app.exec()
        if not window.signing_out:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
