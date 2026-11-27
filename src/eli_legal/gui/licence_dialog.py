"""The licence window: where this copy stands (licensed, on trial, or neither); **Buy a licence…**,
which opens geteli.tech in the browser; **Enter a key…**, for this computer's key; and **Deactivate
this computer**. A licence covers a number of computers, each with its own key, made by the seller
from the computer's activation code, which this window shows. Nothing is ever sent from here.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from eli_legal import licensing

TRIAL_LINE = "The trial covers practice matters only: a real matter needs a paid licence. A key can be entered at any time."


class LicenceDialog(QDialog):
    """``blocking``: shown at start because this copy may not run; closing it ends the program.
    ``network`` is accepted for callers that pass one; nothing here goes online. ``offline``: hard
    offline is on, so even the website is to be opened on another device."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        blocking: bool = False,
        network: Any = None,
        offline: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ELI Legal licence")
        self.setMinimumWidth(560)
        self.offline = offline
        self.blocking = blocking
        self.licensed = False

        self.state = QLabel()
        self.state.setWordWrap(True)
        self.waiting = QLabel()
        self.waiting.setWordWrap(True)
        self.waiting.setProperty("class", "muted")
        self.code = QLabel()
        self.code.setWordWrap(True)
        self.code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.buy = QPushButton("Buy a licence…")
        self.buy.setToolTip(f"Opens {licensing.BUY} in your browser")
        self.enter = QPushButton("Enter a key…")
        self.deactivate_button = QPushButton("Deactivate this computer")
        self.deactivate_button.setToolTip(
            "Remove the key from this computer; then tell the seller, so its seat can be used on another"
        )
        self.close_button = QPushButton("Quit" if blocking else "Close")
        self.buy.clicked.connect(self._buy)
        self.enter.clicked.connect(self._enter)
        self.deactivate_button.clicked.connect(self._deactivate)
        self.close_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addWidget(self.buy)
        buttons.addWidget(self.enter)
        buttons.addWidget(self.deactivate_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.state)
        layout.addWidget(self.code)
        layout.addWidget(self.waiting)
        layout.addLayout(buttons)
        self.refresh()

    # ── what is shown ───────────────────────────────────────────────────────
    def refresh(self) -> None:
        st = licensing.standing()
        lines = [f"<b>{st.describe()}</b>"]
        if st.on_trial or not st.granted:
            lines.append(TRIAL_LINE)
        if self.offline:
            lines.append(
                f"Hard offline is on: buy on another device at {licensing.BUY}, then enter this "
                "computer's key."
            )
        self.state.setText("<br><br>".join(lines))
        self.buy.setEnabled(not self.offline)
        paid = st.granted and not st.on_trial and st.licence is not None
        self.deactivate_button.setVisible(paid and licensing.required())
        self.code.setText(
            "Each computer has its own key. To get this computer's, send the seller your licence "
            f"number and this computer's activation code:<br><code>{licensing.activation_code()}</code>"
        )

    # ── buying ──────────────────────────────────────────────────────────────
    def _buy(self) -> None:
        QDesktopServices.openUrl(QUrl(licensing.BUY))
        self.waiting.setText(
            "The website is open in your browser. Once you have bought a licence, send the seller "
            "this computer's activation code (above) and enter the key you get back."
        )

    # ── a key ───────────────────────────────────────────────────────────────
    def _enter(self) -> None:
        from eli_sdk import InvalidKey

        key, ok = QInputDialog.getMultiLineText(
            self,
            "Enter this computer's key",
            "Paste this computer's ELI Legal key, or an ELI v3 key sold with ELI Legal included:",
        )
        if not ok or not key.strip():
            return
        try:
            lic = licensing.activate(key)
        except InvalidKey as exc:
            QMessageBox.warning(self, "Key not taken", str(exc))
            return
        self.waiting.setText(
            f"Activated: {lic.label} {lic.major_version}.x, {lic.tier}, on this computer."
        )
        self._licensed_now()

    def _deactivate(self) -> None:
        answer = QMessageBox.question(
            self,
            "Deactivate this computer",
            "Remove ELI Legal's key from this computer? It will need a key again to run here.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        done = licensing.deactivate()
        self.waiting.setText(
            "Removed from this computer. Tell the seller, so its seat can be used on another computer."
            if done
            else "There was no key on this computer."
        )
        self.licensed = False
        self.refresh()

    def _licensed_now(self) -> None:
        self.refresh()
        st = licensing.standing()
        if st.granted and not st.on_trial:
            self.licensed = True
            self.close_button.setText("Continue" if self.blocking else "Close")
            if self.blocking:
                self.accept()


def trial_notice(parent: QWidget | None, days: int) -> None:
    QMessageBox.information(
        parent,
        "ELI Legal trial",
        f"Your {days}-day ELI Legal trial has started. It covers practice matters only: opening a real matter needs a paid licence.\n\nYou can buy a licence or "
        "enter a key at any time: Help → Licence….",
    )
