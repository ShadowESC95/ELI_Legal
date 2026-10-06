from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from eli_legal.gui.session import Session


class Tab(QWidget):
    """A page of the application. ``refresh`` re-reads everything it shows from the services."""

    title = ""

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session
        self.sv = session.sv
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(10, 10, 10, 10)
        self.root.setSpacing(8)

    @property
    def actor(self) -> str:
        return self.session.user_id

    @property
    def mid(self) -> str:
        return self.session.matter_id

    @property
    def rid(self) -> str:
        return self.session.run_id

    def refresh(self) -> None:  # pragma: no cover - overridden
        """Re-read what this page shows."""
