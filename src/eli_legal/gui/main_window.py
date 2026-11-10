from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from eli_legal import __version__
from eli_legal.domain import glossary, how_to, plain
from eli_legal.domain.profiles import profile_spec
from eli_legal.gui import theme, zoom
from eli_legal.gui.session import Session
from eli_legal.gui.tabs.agents_tab import AgentsTab
from eli_legal.gui.tabs.audit_tab import AuditTab
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.tabs.chat_tab import ChatTab
from eli_legal.gui.tabs.documents_tab import DocumentsTab
from eli_legal.gui.tabs.findings_tab import FindingsTab
from eli_legal.gui.tabs.frameworks_tab import FrameworksTab
from eli_legal.gui.tabs.governance_tab import GovernanceTab
from eli_legal.gui.tabs.help_tab import HelpTab
from eli_legal.gui.tabs.home_tab import HomeTab
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
        self.matter_box.setToolTip(glossary.tooltip("Matter", "Choose the case to work on."))
        self.profile = label("", "muted")
        self.chips = {name: chip("") for name in ("checks", "audit", "network", "model", "user")}
        header = QFrame()
        header.setProperty("role", "header")
        line = QHBoxLayout(header)
        line.setContentsMargins(12, 8, 12, 8)
        title = label("ELI Legal", "title")
        line.addWidget(title)
        line.addSpacing(14)
        line.addWidget(label("Case"))
        line.addWidget(self.matter_box)
        line.addWidget(self.profile)
        line.addStretch(1)
        for widget in self.chips.values():
            line.addWidget(widget)

        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()  # the sidebar chooses the page
        self.pages: list[Tab] = [
            HomeTab(session, self.go),
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
            HelpTab(session, self.go),
        ]
        for page in self.pages:
            self.tabs.addTab(page, page.title)
        self.tabs.currentChanged.connect(lambda _index: self._refresh_page())
        self.nav = self._sidebar()

        central = QWidget()
        column = QVBoxLayout(central)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(header)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.nav)
        body.addWidget(self.tabs, 1)
        column.addLayout(body, 1)
        self.setCentralWidget(central)
        self._menus()
        self.statusBar().showMessage(
            "Decision support only. Nothing here may be relied on until a named reviewer has approved it."
        )
        session.changed.connect(self.refresh)
        session.busy.connect(self._busy)
        self.refresh()
        # Routine checks run on their own: once soon after sign-in if they are due, then
        # whenever they fall due. An interval of 0 hours switches the schedule off.
        self.checks_timer = QTimer(self)
        self.checks_timer.timeout.connect(self.scheduled_checks)
        if session.sv.ctx.settings.checks_every_hours > 0:
            self.checks_timer.start(30 * 60 * 1000)
            QTimer.singleShot(3000, self.scheduled_checks)

    # ── navigation ───────────────────────────────────────────────────────────
    # Each page in plain words: its name in the sidebar and what it is for.
    _SECTIONS = (
        ("START HERE", ("HelpTab", "HomeTab")),
        (
            "THIS CASE",
            ("MatterTab", "DocumentsTab", "ChatTab", "WorkflowTab", "AgentsTab", "FindingsTab",
             "ReviewTab"),
        ),
        ("CHECKING AND RECORDS", ("AuditTab", "GovernanceTab")),
        ("SET-UP", ("SourcesTab", "FrameworksTab", "SettingsTab")),
    )  # fmt: skip
    _PAGE_KEYS = {
        "help": "HelpTab",
        "home": "HomeTab",
        "matter": "MatterTab",
        "evidence": "DocumentsTab",
        "chat": "ChatTab",
        "workflow": "WorkflowTab",
        "agents": "AgentsTab",
        "findings": "FindingsTab",
        "review": "ReviewTab",
        "audit": "AuditTab",
        "governance": "GovernanceTab",
        "sources": "SourcesTab",
        "laws": "FrameworksTab",
        "settings": "SettingsTab",
    }
    _NAV_WIDTH = 270

    @property
    def _NAV(self) -> dict[str, tuple[str, str]]:  # noqa: N802 - read as a table
        """Each page in plain words, by its class: its name and what it is for."""
        return {cls: how_to.PAGES[key] for key, cls in self._PAGE_KEYS.items()}

    def page_name(self, page: Tab) -> str:
        """A page's name as the sidebar shows it."""
        return self._NAV.get(type(page).__name__, (page.title, ""))[0]

    def _sidebar(self) -> QListWidget:
        nav = QListWidget()
        nav.setObjectName("nav")
        nav.setFixedWidth(round(self._NAV_WIDTH * zoom.level()))
        nav.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        by_class = {type(page).__name__: i for i, page in enumerate(self.pages)}
        for heading, classes in self._SECTIONS:
            head = QListWidgetItem(heading)
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            head.setForeground(Qt.GlobalColor.gray)
            nav.addItem(head)
            for name in classes:
                index = by_class[name]
                title, about = self._NAV[name]
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, index)
                item.setToolTip(glossary.tooltip(title, about))
                nav.addItem(item)
                holder = QWidget()
                holder.setObjectName("navitem")
                inner = QVBoxLayout(holder)
                inner.setContentsMargins(8, 3, 8, 4)
                inner.setSpacing(1)
                inner.addWidget(label(title, "navname"))
                inner.addWidget(label(about, "navabout", wrap=True))
                nav.setItemWidget(item, holder)
        nav.currentItemChanged.connect(self._nav_chosen)
        self.tabs.currentChanged.connect(self._sync_nav)
        zoom_control = zoom.current()
        if zoom_control is not None:
            zoom_control.changed.connect(self._nav_zoomed)
        QTimer.singleShot(0, lambda: self._nav_zoomed(zoom.level()))
        self._size_nav_items(nav)
        return nav

    def _size_nav_items(self, nav: QListWidget) -> None:
        """Each entry as tall as its words need at the sidebar's width, so none is cut off."""
        width = nav.width() - nav.verticalScrollBar().sizeHint().width() - 12
        for row in range(nav.count()):
            item = nav.item(row)
            holder = nav.itemWidget(item)
            layout = holder.layout() if holder is not None else None
            if holder is not None and layout is not None:
                holder.setFixedWidth(width)
                item.setSizeHint(QSize(width, layout.totalHeightForWidth(width)))

    def _nav_zoomed(self, level: float) -> None:
        self.nav.setFixedWidth(round(self._NAV_WIDTH * level))
        self._size_nav_items(self.nav)

    def _nav_chosen(self, item: QListWidgetItem | None, _old: QListWidgetItem | None) -> None:
        index = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if index is not None:
            self.tabs.setCurrentIndex(int(index))

    def _sync_nav(self, index: int) -> None:
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == index:
                self.nav.blockSignals(True)
                self.nav.setCurrentRow(row)
                self.nav.blockSignals(False)
                return

    def go(self, page: str) -> None:
        """Open a page by its key; ``new_matter`` opens the wizard for a new matter."""
        if page == "new_matter":
            matter_tab = self.show_page(MatterTab)
            assert isinstance(matter_tab, MatterTab)
            matter_tab._new()
            return
        name = self._PAGE_KEYS.get(page)
        target = next((p for p in self.pages if type(p).__name__ == name), None)
        if target is not None:
            self.tabs.setCurrentWidget(target)

    def scheduled_checks(self) -> None:
        """Run the routine checks in the background if they are due and nothing else is."""
        if not self.session.user_id or self.session.working or not self.session.sv.checks.due():
            return
        self.session.background(
            "Running the routine checks…",
            lambda: self.session.sv.checks.run(),
            lambda _run: self.session.notify(),
            lambda exc: self.statusBar().showMessage(f"The routine checks could not run: {exc}"),
        )

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
        control = zoom.current()
        if control is not None:
            # Shortcuts are the zoom's own, so they work in every window; the menu shows them.
            control.keys(self)
            add(view, "Larger (Ctrl and +)", control.zoom_in)
            add(view, "Smaller (Ctrl and −)", control.zoom_out)
            add(view, "Normal size (Ctrl and 0)", control.reset)
        view.addSeparator()
        for index, page in enumerate(self.pages):
            add(
                view,
                self.page_name(page),
                lambda i=index: self.tabs.setCurrentIndex(i),
                f"Ctrl+{index + 1}" if index < 9 else "",
            )
        help_menu = self.menuBar().addMenu("&Help")
        add(help_menu, "How to use ELI Legal", lambda: self.go("help"), "F1")
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
        control = zoom.current()
        if control is not None:
            control.watch_new()  # what the page just built answers to Ctrl and the wheel too

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
            self.matter_box.addItem(
                f"{listed.name}  ·  {plain.state(listed.status).lower()}", listed.matter_id
            )
            if listed.matter_id == session.matter_id:
                self.matter_box.setCurrentIndex(self.matter_box.count() - 1)
        self.matter_box.blockSignals(False)
        matter = session.matter
        self.profile.setText(profile_spec(matter.profile).label if matter else "")
        latest = sv.checks.latest()
        if latest is None:
            set_chip(self.chips["checks"], "● Checks not run yet", theme.IDLE)
        else:
            bad = sum(1 for r in latest.results if r.state != "ok")
            set_chip(
                self.chips["checks"],
                "● Checks clear" if not bad else f"● Checks: {bad} need attention",
                theme.colour_for(latest.state),
            )
        chain = sv.ctx.audit.report()
        set_chip(
            self.chips["audit"],
            f"● Audit {'verified' if chain.ok else 'INVALID'} · {chain.count} events",
            theme.GOOD if chain.ok else theme.BAD,
        )
        offline = sv.network.status()
        if offline["hard_offline"]:
            enforced = "kernel" in offline["enforced_by"] or "Firewall" in offline["enforced_by"]
            set_chip(
                self.chips["network"],
                "● Hard offline" + (" (kernel-enforced)" if enforced else " (this program only)"),
                theme.GOOD if enforced else theme.WARN,
            )
        else:
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
        roles = plain.roles(user.roles) if user else ""
        set_chip(
            self.chips["user"], f"👤 {user.display_name if user else ''} · {roles}", theme.TEXT
        )
        # What each indicator means, for the pointer to rest on.
        self.chips["checks"].setToolTip(
            glossary.tooltip(
                "Checks",
                "The Compliance page, under Routine checks, says what "
                "needs attention and what to do.",
            )
        )
        self.chips["audit"].setToolTip(
            glossary.tooltip(
                "Audit verified" if chain.ok else "Audit trail",
                f"{chain.count} entries so far. The Record of actions page shows them.",
            )
        )
        self.chips["network"].setToolTip(
            glossary.tooltip(
                "Hard offline" if offline["hard_offline"] else "Network denied by default"
            )
        )
        self.chips["model"].setToolTip(
            glossary.tooltip(
                "Model",
                f"In use: {model.model_id}."
                if model.available
                else "None is in use; choose one in Settings if you want drafting.",
            )
        )
        self.chips["user"].setToolTip(
            glossary.tooltip("Role", f"You are signed in as {user.display_name if user else ''}. "
                             f"Your account's roles: {roles}.")
        )  # fmt: skip
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
                "Work is in progress (a run, or the routine checks). Stop a run on the Progress page, or wait for it to finish.",
            )
            event.ignore()
            self.signing_out = False
            return
        self.session.sign_out()
        event.accept()
