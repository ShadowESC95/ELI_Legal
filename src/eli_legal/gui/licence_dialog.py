"""The licence window: where this copy stands (licensed, on trial, or neither), and the two ways
to a licence: **Buy a licence…**, which opens the store (the key is emailed when payment completes,
and activated here by itself where the store can do so), and **Enter a key…** for any key. A key
bought to be activated is activated with the store the first time it is entered on a computer
(that computer takes one of the licence's seats); **Deactivate this computer** gives the seat back
so the licence can move to another computer. The computer's activation code is shown for
activating it from another device when this one cannot go online.

Opening the store is the only time ELI Legal reaches the licence store, and only when a person
asks: the address is let through the network guard for that request alone, and recorded. With
hard offline on, nothing is sent: the store's address is shown to open on another device, and
the key emailed is entered here.
"""

from __future__ import annotations

import threading
from contextlib import AbstractContextManager, nullcontext
from typing import Any
from urllib.parse import urlparse

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
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

POLL_MS = 5000
WAIT_POLLS = 360  # thirty minutes


class _Collected(QObject):
    done = Signal(object)  # list of licences, or an error string


class LicenceDialog(QDialog):
    """``blocking``: shown at start because this copy may not run; closing it ends the program."""

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
        self.setMinimumWidth(520)
        self.network = network
        self.offline = offline
        self.blocking = blocking
        self.claim = ""
        self._polls = 0
        self._busy = False
        self.licensed = False

        self.state = QLabel()
        self.state.setWordWrap(True)
        self.waiting = QLabel()
        self.waiting.setWordWrap(True)
        self.waiting.setProperty("class", "muted")
        self.buy = QPushButton("Buy a licence…")
        self.buy.setToolTip(
            "Opens the store in your browser. When payment completes, the key is emailed to "
            "you, and activated here by itself where the store can do so."
        )
        self.enter = QPushButton("Enter a key…")
        self.deactivate_button = QPushButton("Deactivate this computer")
        self.deactivate_button.setToolTip(
            "Give this computer's seat back, so the licence can be activated on another computer"
        )
        self.code = QLabel()
        self.code.setWordWrap(True)
        self.code.setProperty("class", "muted")
        self.code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
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
        layout.addWidget(self.waiting)
        layout.addWidget(self.code)
        layout.addLayout(buttons)

        self._collected = _Collected()
        self._collected.done.connect(self._on_collected)
        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self._poll)
        self.refresh()

    # ── what is shown ───────────────────────────────────────────────────────
    def refresh(self) -> None:
        st = licensing.standing()
        lines = [f"<b>{st.describe()}</b>"]
        if st.on_trial or not st.granted:
            lines.append(
                f"The trial covers {licensing.TRIAL_SCOPE}: a real matter needs a paid "
                "licence. A key can be entered at any time."
            )
        if self.offline:
            lines.append(
                f"Hard offline is on, so nothing is sent from here. Buy on another "
                f"device at {licensing.BUY}, then enter the key you receive."
            )
        self.state.setText("<br><br>".join(lines))
        self.buy.setEnabled(not self.offline and not self.timer.isActive())
        paid = st.granted and not st.on_trial and st.licence is not None
        self.deactivate_button.setVisible(paid and licensing.required())
        from eli_sdk.store import activate_page

        self.code.setText(
            f"This computer's activation code: <code>{licensing.activation_code()}</code><br>"
            f"A key is activated with the licence store the first time it is entered on a computer "
            f"(the internet, once). If this computer cannot go online, activate it at "
            f"{activate_page(licensing.STORE_URL)} from any other device."
        )

    # ── buying ──────────────────────────────────────────────────────────────
    def _allowed(self, reason: str = "licence purchase, asked for by the user") -> AbstractContextManager[Any]:
        host = urlparse(licensing.STORE_URL).hostname or ""
        if self.network is None or not host:
            return nullcontext()
        window: AbstractContextManager[Any] = self.network.allow(host=host, reason=reason)
        return window

    def _through_store(self, act: Any, reason: str) -> Any:
        """Run ``act`` with the store's address let through the network guard for it alone. Under
        hard offline (or with the store not approved) it runs anyway with nothing let through: a key
        already made for this computer needs no network, and one to be activated is refused with
        how to activate this computer from another device."""
        try:
            window = self._allowed(reason)
            window.__enter__()
        except Exception:
            return act()
        try:
            return act()
        finally:
            window.__exit__(None, None, None)

    def _buy(self) -> None:
        from eli_sdk import store as eli_store

        self.claim = eli_store.new_claim()
        url = licensing.buy_link(self.claim)
        QDesktopServices.openUrl(QUrl(url))
        self._polls = 0
        self.waiting.setText(
            "Complete the payment in your browser. Your key is emailed to you; if the store can "
            "tell this program, it is activated here by itself as well. Otherwise press Enter a "
            f"key… when the email arrives.<br><small>{url}</small>"
        )
        self.timer.start()
        self.refresh()

    def _poll(self) -> None:
        if self._busy:
            return
        self._polls += 1
        if self._polls > WAIT_POLLS:
            self.timer.stop()
            self.waiting.setText(
                "No payment was seen. When the email with your key arrives, press Enter a key…."
            )
            self.refresh()
            return
        self._busy = True
        claim = self.claim

        def work() -> None:
            try:
                with self._allowed():
                    result: object = licensing.collect(claim)
            except Exception as exc:  # the store unreachable: keep trying until the time is up
                result = str(exc)
            self._collected.done.emit(result)

        threading.Thread(target=work, name="licence-collect", daemon=True).start()

    def _on_collected(self, result: object) -> None:
        self._busy = False
        if isinstance(result, list) and result:
            self.timer.stop()
            lic = result[0]
            self.waiting.setText(f"Activated: {lic.label} {lic.major_version}.x, {lic.tier}.")
            self._licensed_now()
        elif isinstance(result, str):
            self.waiting.setText(
                "Waiting. Your key is emailed to you when payment completes: press Enter a key… "
                "when it arrives."
            )

    # ── entering a key ──────────────────────────────────────────────────────
    def _enter(self) -> None:
        from eli_sdk import InvalidKey

        key, ok = QInputDialog.getMultiLineText(
            self,
            "Enter a licence key",
            "Paste your ELI Legal key, or an ELI v3 key that includes ELI Legal:",
        )
        if not ok or not key.strip():
            return
        try:
            lic = self._through_store(lambda: licensing.activate(key),
                                      "licence activation, asked for by the user")
        except InvalidKey as exc:
            QMessageBox.warning(self, "Key not activated", f"That key was not activated: {exc}")
            return
        self.waiting.setText(
            f"Activated: {lic.label} {lic.major_version}.x, {lic.tier}, {lic.seats} seat(s)."
        )
        self._licensed_now()

    def _deactivate(self) -> None:
        from eli_sdk import InvalidKey

        answer = QMessageBox.question(
            self,
            "Deactivate this computer",
            "Give this computer's seat back to the licence? ELI Legal will need a key, or the "
            "licence activated again, to run here.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            done = self._through_store(licensing.deactivate, "licence deactivation, asked for by the user")
        except InvalidKey as exc:
            QMessageBox.warning(self, "Not deactivated", str(exc))
            return
        self.waiting.setText("Deactivated: this computer's seat is free for another computer."
                             if done else "There was no key on this computer to deactivate.")
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

    def reject(self) -> None:
        self.timer.stop()
        super().reject()


def trial_notice(parent: QWidget | None, days: int) -> None:
    QMessageBox.information(
        parent,
        "ELI Legal trial",
        f"Your {days}-day ELI Legal trial has started. It covers {licensing.TRIAL_SCOPE}: opening "
        "a real matter needs a paid licence.\n\nYou can buy a licence or enter a key at any time: "
        "Help → Licence….",
    )
