from __future__ import annotations

from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from eli_legal import __version__
from eli_legal.domain.profiles import profile_spec
from eli_legal.gui import theme
from eli_legal.gui.session import Session
from eli_legal.gui.tabs.agents_tab import AgentsTab
from eli_legal.gui.tabs.audit_tab import AuditTab
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.tabs.chat_tab import ChatTab
from eli_legal.gui.tabs.documents_tab import DocumentsTab
from eli_legal.gui.tabs.findings_tab import FindingsTab
from eli_legal.gui.tabs.frameworks_tab import FrameworksTab
from eli_legal.gui.tabs.governance_tab import GovernanceTab
from eli_legal.gui.tabs.matter_tab import MatterTab
from eli_legal.gui.tabs.review_tab import ReviewTab
from eli_legal.gui.tabs.settings_tab import SettingsTab
from eli_legal.gui.tabs.sources_tab import SourcesTab
from eli_legal.gui.tabs.workflow_tab import WorkflowTab
from eli_legal.gui.widgets import chip, label, set_chip

BOUNDARIES = (
    "ELI Legal prepares; a named person decides.\n\n"
    "It renders no verdict, award, order or recommendation on the merits, and proposes no "
    "settlement terms. It contacts no party and sends nothing: an approved report is staged for "
    "collection. It reads only the legal sources approved for the matter, with the network "
    "denied by default. Text inside documents is evidence, never an instruction.\n\n"
    "A finding is shown as verified only when every check its kind requires has passed. "
    "“Verified” means the words appear in an unaltered source, and an authority exists and was "
    "in good standing when the source last said so. It does not mean the statement is true or "
    "that the authority governs the case."
)


class MainWindow(QMainWindow):
    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session
        self.signing_out = False
        self.setWindowTitle(f"ELI Legal {__version__}")
        self.resize(1440, 900)

        # header: what is open, and the state of the things that must never be in doubt
        self.matter_box = QComboBox()
        self.matter_box.setMinimumWidth(360)
        self.matter_box.activated.connect(self._matter_chosen)
        self.profile = label("", "muted")
        self.chips = {name: chip("") for name in ("audit", "network", "model", "user")}
        header = QFrame()
        header.setProperty("role", "header")
        line = QHBoxLayout(header)
        line.setContentsMargins(12, 8, 12, 8)
        title = label("ELI Legal", "title")
        line.addWidget(title)
        line.addSpacing(14)
        line.addWidget(label("Matter"))
        line.addWidget(self.matter_box)
        line.addWidget(self.profile)
        line.addStretch(1)
        for widget in self.chips.values():
            line.addWidget(widget)

        self.tabs = QTabWidget()
        self.pages: list[Tab] = [
            MatterTab(session),
            DocumentsTab(session),
            ChatTab(session),
            WorkflowTab(session),
            AgentsTab(session),
            FindingsTab(session),
            ReviewTab(session),
            AuditTab(session),
            GovernanceTab(session),
            SourcesTab(session),
            FrameworksTab(session),
            SettingsTab(session, self.sign_out),
        ]
        for page in self.pages:
            self.tabs.addTab(page, page.title)
        self.tabs.currentChanged.connect(lambda _index: self._refresh_page())

        central = QWidget()
        column = QVBoxLayout(central)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(header)
        column.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self._menus()
        self.statusBar().showMessage(
            "Decision support only. Nothing here may be relied on until a named reviewer has approved it."
        )
        session.changed.connect(self.refresh)
        session.busy.connect(self._busy)
        self.refresh()

    def _menus(self) -> None:
        def add(menu, text: str, slot, shortcut: str = "") -> None:  # type: ignore[no-untyped-def]
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(lambda _checked=False: slot())
            menu.addAction(action)

        file_menu = self.menuBar().addMenu("&File")
        add(file_menu, "Sign out", self.sign_out)
        add(file_menu, "Quit", self.close, "Ctrl+Q")
        view = self.menuBar().addMenu("&View")
        add(view, "Refresh", self.refresh, "F5")
        for index, page in enumerate(self.pages):
            add(
                view,
                page.title,
                lambda i=index: self.tabs.setCurrentIndex(i),
                f"Ctrl+{index + 1}" if index < 9 else "",
            )
        help_menu = self.menuBar().addMenu("&Help")
        add(
            help_menu,
            "What this system does and does not do",
            lambda: QMessageBox.information(self, "Boundaries", BOUNDARIES),
        )
        add(
            help_menu,
            "About",
            lambda: QMessageBox.about(
                self,
                "ELI Legal",
                f"<h2>ELI Legal {__version__}</h2><p>Governed legal case preparation.</p><p>Decision support only: it renders no verdict and gives no legal advice.</p>",
            ),
        )

    def page(self, kind: type) -> Tab:
        return next(p for p in self.pages if isinstance(p, kind))

    def show_page(self, kind: type) -> Tab:
        page = self.page(kind)
        self.tabs.setCurrentWidget(page)
        return page

    def _refresh_page(self) -> None:
        page = self.tabs.currentWidget()
        if isinstance(page, Tab) and self.session.user_id:
            page.refresh()

    def refresh(self) -> None:
        session = self.session
        if not session.user_id:
            return
        sv = session.sv
        matters = sv.matters.list_for(session.user_id)
        self.matter_box.blockSignals(True)
        self.matter_box.clear()
        self.matter_box.addItem("— no matter open —", "")
        for listed in matters:
            self.matter_box.addItem(f"{listed.name}  ·  {listed.status.value}", listed.matter_id)
            if listed.matter_id == session.matter_id:
                self.matter_box.setCurrentIndex(self.matter_box.count() - 1)
        self.matter_box.blockSignals(False)
        matter = session.matter
        self.profile.setText(profile_spec(matter.profile).label if matter else "")
        chain = sv.ctx.audit.report()
        set_chip(
            self.chips["audit"],
            f"● Audit {'verified' if chain.ok else 'INVALID'} · {chain.count} events",
            theme.GOOD if chain.ok else theme.BAD,
        )
        set_chip(
            self.chips["network"],
            "● Network denied by default"
            if sv.ctx.guard.installed
            else "● Network guard not installed",
            theme.GOOD if sv.ctx.guard.installed else theme.WARN,
        )
        model = sv.ctx.model
        set_chip(
            self.chips["model"],
            f"● Model: {model.model_id}"
            if model.available
            else (
                "● Model unavailable" if getattr(model.inference, "reason", "") else "● No model"
            ),
            theme.ACCENT
            if model.available
            else (theme.WARN if getattr(model.inference, "reason", "") else theme.IDLE),
        )
        user = session.user
        roles = ", ".join(sorted(r.replace("_", " ") for r in user.roles)) if user else ""
        set_chip(
            self.chips["user"], f"👤 {user.display_name if user else ''} · {roles}", theme.TEXT
        )
        self._refresh_page()

    def _matter_chosen(self) -> None:
        chosen = self.matter_box.currentData() or ""
        if chosen != self.session.matter_id:
            self.session.set_matter(chosen)

    def _busy(self, what: str) -> None:
        self.statusBar().showMessage(
            what
            or "Decision support only. Nothing here may be relied on until a named reviewer has approved it."
        )

    def sign_out(self) -> None:
        self.signing_out = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.session.working:
            QMessageBox.information(
                self,
                "Still working",
                "A run is in progress. Stop it from the DAG tab, or wait for it to finish.",
            )
            event.ignore()
            self.signing_out = False
            return
        self.session.sign_out()
        event.accept()
