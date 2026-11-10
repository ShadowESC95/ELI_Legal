"""People and their accounts: adding a person, changing what their account may do, and setting a
passphrase. Used by Settings → Users and by the team page of Open a matter, so a matter's team
can be completed where it is chosen. Every change is made in the name of the person signed in,
after they confirm their passphrase, and is refused unless their account manages users.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QWidget,
)

from eli_legal.domain import plain
from eli_legal.gui.widgets import label
from eli_legal.security.rbac import DEFAULT_ROLE_ACTIONS

MANAGES_USERS = "user.manage"


def new_passphrase(parent: QWidget, who: str, *, later: bool = False) -> str | None:
    """A new passphrase typed twice, or None. With ``later``, Cancel means "set it later"."""
    hint = " Cancel to set it later in Settings → Users." if later else ""
    first, ok = QInputDialog.getText(
        parent,
        "New passphrase",
        f"New passphrase for {who} (at least 10 characters), so they can sign in.{hint}",
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
        QMessageBox.warning(
            parent,
            "Passphrase",
            "The two entries differ. No passphrase was set"
            + ("; set one later in Settings → Users." if later else ". Nothing was changed."),
        )
        return None
    return first


class UserDialog(QDialog):
    """A person's user id, name and account roles. ``approve`` stars the roles that may approve
    a report on the kind of matter being set up, so it is plain which one a reviewer needs."""

    def __init__(
        self,
        parent: QWidget,
        user_id: str = "",
        name: str = "",
        roles: set[str] | None = None,
        *,
        approve: Iterable[str] = (),
        matter_label: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Person and account")
        self.setMinimumWidth(640)
        approve = set(approve)
        form = QFormLayout(self)
        self.user_id = QLineEdit(user_id)
        self.user_id.setReadOnly(bool(user_id))
        self.user_id.setPlaceholderText("what they sign in with, for example j.murphy")
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("their name as it appears on the record")
        self.roles = QListWidget()
        self.roles.setWordWrap(True)
        ordered = sorted(DEFAULT_ROLE_ACTIONS, key=lambda r: (r not in approve, plain.role(r)))
        for role in ordered:
            star = "★ " if role in approve else ""
            item = QListWidgetItem(f"{star}{plain.role(role)} — {plain.role_summary(role)}")
            item.setData(Qt.ItemDataRole.UserRole, role)
            item.setCheckState(
                Qt.CheckState.Checked if roles and role in roles else Qt.CheckState.Unchecked
            )
            self.roles.addItem(item)
        form.addRow("User id", self.user_id)
        form.addRow("Name", self.name)
        form.addRow("What their account may do", self.roles)
        if approve and matter_label:
            form.addRow(
                label(
                    f"★ may approve the report on a matter for: {matter_label.lower()}. A "
                    "reviewer needs one of these, and to be decision-maker on the matter.",
                    wrap=True,
                )
            )
        form.addRow(
            label(
                "An account's roles say what someone may do. They never give access to a "
                "matter: that is given matter by matter, with a role on that matter that can "
                "only narrow it.",
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


class People:
    """What a page needs to add people and change accounts, in the signed-in person's name."""

    def __init__(self, session: Any, actor_id: str) -> None:
        self.session = session
        self.actor_id = actor_id

    @property
    def sv(self) -> Any:
        return self.session.sv

    @property
    def can_manage(self) -> bool:
        return bool(self.sv.ctx.authorizer().bindings.can(self.actor_id, MANAGES_USERS))

    def directory(self) -> list[Any]:
        return list(self.sv.users.directory(self.actor_id))

    def add(self, parent: QWidget, *, approve: Iterable[str] = (), matter_label: str = "") -> str:
        """Add a person, with a passphrase if one is given; their user id, or "" if not added."""
        dialog = UserDialog(parent, approve=approve, matter_label=matter_label)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return ""
        uid, name, roles = (
            dialog.user_id.text().strip(),
            dialog.name.text().strip(),
            dialog.chosen(),
        )
        if not uid:
            return ""
        phrase = new_passphrase(parent, uid, later=True)

        def work() -> str:
            self.sv.users.add_user(
                actor_id=self.actor_id, user_id=uid, display_name=name, roles=roles
            )
            if phrase:
                self.sv.users.set_passphrase(actor_id=self.actor_id, user_id=uid, new=phrase)
            return uid

        return (
            self.session.decide(parent, f"add {uid} and set what their account may do", work) or ""
        )

    def change(
        self, parent: QWidget, user: Any, *, approve: Iterable[str] = (), matter_label: str = ""
    ) -> bool:
        """Change what a person's account may do; whether it was changed."""
        dialog = UserDialog(
            parent,
            user.user_id,
            user.display_name,
            set(user.roles),
            approve=approve,
            matter_label=matter_label,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        roles = dialog.chosen()
        keeps = any(MANAGES_USERS in DEFAULT_ROLE_ACTIONS.get(r, set()) for r in roles)
        if user.user_id == self.actor_id and not keeps:
            answer = QMessageBox.question(
                parent,
                "Your own account",
                "With these roles you could no longer add people or change accounts. Go on?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        done = self.session.decide(
            parent,
            f"change what the account of {user.user_id} may do",
            lambda: self.sv.users.add_user(
                actor_id=self.actor_id,
                user_id=user.user_id,
                display_name=dialog.name.text().strip(),
                roles=roles,
            ),
        )
        return done is not None
