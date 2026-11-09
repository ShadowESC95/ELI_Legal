from __future__ import annotations

import contextvars
from collections.abc import Callable
from typing import TypeVar

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox, QWidget

from eli_legal.application.services import Services
from eli_legal.domain.errors import EliLegalError
from eli_legal.domain.models import Matter, Run, User
from eli_legal.security import access, authn

T = TypeVar("T")
AUTH_METHOD = "gui-passphrase"


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)


class _Job(QRunnable):
    """Work run off the interface thread, carrying the signed-in identity with it."""

    def __init__(self, work: Callable[[], object]) -> None:
        super().__init__()
        self.work = work
        self.signals = _Signals()
        self._context = contextvars.copy_context()

    def run(self) -> None:
        try:
            result = self._context.run(self.work)
        except Exception as exc:  # delivered to the interface thread, where it is shown
            self.signals.failed.emit(exc)
        else:
            self.signals.done.emit(result)


class Session(QObject):
    """Who is signed in and which matter and run are open. Tabs listen for ``changed``."""

    changed = Signal()
    busy = Signal(str)

    def __init__(self, services: Services) -> None:
        super().__init__()
        self.sv = services
        self.user_id: str = ""
        self.matter_id: str = ""
        self.run_id: str = ""
        self._pool = QThreadPool.globalInstance()
        self._jobs: list[_Job] = []

    # ── identity ─────────────────────────────────────────────────────────────
    def sign_in(self, user_id: str, passphrase: str, code: str = "") -> User:
        user = self.sv.users.authenticate(user_id, passphrase, code=code or None)
        authn.establish(user.user_id, AUTH_METHOD)
        self.user_id, self.matter_id, self.run_id = user.user_id, "", ""
        matters = self.sv.matters.list_for(self.user_id)
        if matters:
            self.set_matter(matters[-1].matter_id, announce=False)
        self.changed.emit()
        return user

    def sign_out(self) -> None:
        authn.clear()
        self.user_id = self.matter_id = self.run_id = ""
        self.changed.emit()

    @property
    def user(self) -> User | None:
        return self.sv.ctx.store.get_user(self.user_id) if self.user_id else None

    def may(self, action: str) -> bool:
        """Whether the signed-in user holds a role that permits the action here."""
        if not self.user_id:
            return False
        authz = self.sv.ctx.authorizer()
        matter = self.matter
        if action in access.MATTER_ACTIONS:
            return matter is not None and authz.can_matter(matter, self.user_id, action)
        return authz.bindings.can(self.user_id, action)

    # ── what is open ─────────────────────────────────────────────────────────
    @property
    def matter(self) -> Matter | None:
        return self.sv.ctx.store.get_matter(self.matter_id) if self.matter_id else None

    @property
    def run(self) -> Run | None:
        if not (self.matter_id and self.run_id):
            return None
        return self.sv.ctx.store.get(Run, self.matter_id, self.run_id)

    def set_matter(self, matter_id: str, *, announce: bool = True) -> None:
        self.matter_id = matter_id
        runs = self.sv.ctx.store.list(Run, matter_id) if matter_id else []
        self.run_id = runs[-1].run_id if runs else ""
        if announce:
            self.changed.emit()

    def set_run(self, run_id: str) -> None:
        self.run_id = run_id
        self.changed.emit()

    def notify(self) -> None:
        self.changed.emit()

    # ── doing things ─────────────────────────────────────────────────────────
    def attempt(self, parent: QWidget, work: Callable[[], T], *, quiet: bool = False) -> T | None:
        """Run a service call. A refusal is shown to the user in the system's own words."""
        try:
            result = work()
        except EliLegalError as exc:
            QMessageBox.warning(parent, "Refused", f"{type(exc).__name__}\n\n{exc}")
            return None
        except (OSError, ValueError) as exc:
            QMessageBox.warning(parent, "Could not complete", str(exc))
            return None
        if not quiet:
            self.changed.emit()
        return result

    def ask_passphrase(self, parent: QWidget, what: str) -> str | None:
        phrase, ok = QInputDialog.getText(
            parent,
            "Confirm it is you",
            f"You are about to {what}.\n\nThis will be recorded under your name "
            f"({self.user_id}). Enter your passphrase to confirm.",
            QLineEdit.EchoMode.Password,
        )
        return phrase if ok else None

    def decide(self, parent: QWidget, what: str, work: Callable[[], T]) -> T | None:
        """A decision: confirm the passphrase, then act with identity freshly confirmed."""
        phrase = self.ask_passphrase(parent, what)
        if phrase is None:
            return None
        return self.decide_with(parent, phrase, work)

    def decide_with(self, parent: QWidget, phrase: str, work: Callable[[], T]) -> T | None:
        try:
            self.sv.users.confirm(self.user_id, phrase)
        except EliLegalError:
            QMessageBox.warning(
                parent, "Refused", "That passphrase is not correct. Nothing was recorded."
            )
            return None

        def confirmed() -> T:
            with authn.stepped_up():
                return work()

        return self.attempt(parent, confirmed)

    def background(
        self,
        label: str,
        work: Callable[[], object],
        on_done: Callable[[object], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        """Run long work (a workflow run, a model call) off the interface thread."""
        job = _Job(work)
        self._jobs.append(job)

        def finish(handler: Callable[..., None], value: object) -> None:
            if job in self._jobs:
                self._jobs.remove(job)
            self.busy.emit("")
            handler(value)

        job.signals.done.connect(lambda value: finish(on_done, value))
        job.signals.failed.connect(lambda exc: finish(on_error, exc))
        self.busy.emit(label)
        self._pool.start(job)

    @property
    def working(self) -> bool:
        return bool(self._jobs)

    def wait_for_background(self, timeout_ms: int = 120000) -> bool:
        return bool(self._pool.waitForDone(timeout_ms))
