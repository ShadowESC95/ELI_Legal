from __future__ import annotations

import threading
from typing import Any

from PySide6.QtCore import QByteArray, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from eli_legal import __version__
from eli_legal.adapters.local.usage import Usage, UsageMeter
from eli_legal.adapters.local.usage import details as usage_details
from eli_legal.adapters.local.usage import summary as usage_summary
from eli_legal.domain import glossary, how_to, plain
from eli_legal.domain.enums import MatterStatus
from eli_legal.domain.profiles import profile_spec
from eli_legal.gui import theme, zoom
from eli_legal.gui.closed_cases import ClosedCasesDialog
from eli_legal.gui.journey import JourneyBar
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
from eli_legal.gui.tabs.new_case_tab import NewCaseTab
from eli_legal.gui.tabs.released_tab import ReleasedTab
from eli_legal.gui.tabs.review_tab import ReviewTab
from eli_legal.gui.tabs.settings_tab import SettingsTab
from eli_legal.gui.tabs.sources_tab import SourcesTab
from eli_legal.gui.tabs.workflow_tab import WorkflowTab
from eli_legal.gui.widgets import FlowLayout, chip, label, set_chip

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


_CLOSED = "__closed_cases__"  # the case list's last entry: the closed cases


# Pages that only show the case: redrawn when someone else changes it.
_LIVE_PAGES = (
    HomeTab,
    WorkflowTab,
    AgentsTab,
    FindingsTab,
    ReviewTab,
    AuditTab,
    ReleasedTab,
    DocumentsTab,
)


class _UsageReader(QObject):
    """Carries a reading from the thread that took it to the interface thread."""

    ready = Signal(object)


class Pages(QTabWidget):
    """The pages, each in its own scrolling area. A page bigger than the window scrolls instead
    of forcing the window bigger than the screen. Callers still deal in the pages themselves."""

    def add_page(self, page: QWidget, title: str) -> None:
        holder = QScrollArea()
        holder.setWidget(page)
        holder.setWidgetResizable(True)
        holder.setFrameShape(QFrame.Shape.NoFrame)
        self.addTab(holder, title)

    def page_at(self, index: int) -> QWidget | None:
        holder = super().widget(index)
        return holder.widget() if isinstance(holder, QScrollArea) else holder

    def currentWidget(self) -> QWidget:  # noqa: N802 - Qt's name
        page = self.page_at(self.currentIndex())
        return page if page is not None else super().currentWidget()

    def setCurrentWidget(self, page: QWidget) -> None:  # noqa: N802 - Qt's name
        for index in range(self.count()):
            if self.page_at(index) is page:
                self.setCurrentIndex(index)
                return


class MainWindow(QMainWindow):
    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session
        self.signing_out = False
        self.setWindowTitle(f"ELI Legal {__version__}")
        self._fit_to_screen()

        # header: what is open, and the state of the things that must never be in doubt
        self.matter_box = QComboBox()
        self.matter_box.setMinimumWidth(220)
        self.matter_box.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.matter_box.setMinimumContentsLength(24)
        self.matter_box.activated.connect(self._matter_chosen)
        self.matter_box.setToolTip(glossary.tooltip("Matter", "Choose the case to work on."))
        self.profile = label("", "muted")
        self.chips = {name: chip("") for name in ("checks", "audit", "network", "model", "user")}
        header = QFrame()
        header.setProperty("role", "header")
        line = QHBoxLayout(header)
        line.setContentsMargins(12, 8, 12, 8)
        title = label("ELI Legal", "title")
        middle = Qt.AlignmentFlag.AlignVCenter
        line.addWidget(title, 0, middle)
        line.addSpacing(14)
        line.addWidget(label("Case"), 0, middle)
        line.addWidget(self.matter_box, 0, middle)
        line.addWidget(self.profile, 0, middle)
        # The state chips sit at the right and wrap onto a second line in a narrow window,
        # rather than widen it.
        chips = QWidget()
        flow = FlowLayout(chips, align_right=True)
        # Work waiting for this person on any matter: holds to clear, a report to review.
        self.bell = QPushButton("Nothing waiting")
        self.bell.setObjectName("bell")
        self.bell.setToolTip("Work on your matters that only a person can do, and that you can do")
        self.bell.clicked.connect(self._show_waiting)
        self._waiting: list[dict[str, Any]] = []
        self._told: set[str] = set()
        for name, widget in self.chips.items():
            if name == "user":
                flow.addWidget(self.bell)
            flow.addWidget(widget)
        policy = chips.sizePolicy()
        policy.setHeightForWidth(True)
        chips.setSizePolicy(policy)
        line.addWidget(chips, 1)

        self.tabs = Pages()
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
            ReleasedTab(session),
            SourcesTab(session),
            FrameworksTab(session),
            SettingsTab(session, self.sign_out),
            HelpTab(session, self.go),
            NewCaseTab(session, self.go),
        ]
        for page in self.pages:
            self.tabs.add_page(page, page.title)
        self.tabs.currentChanged.connect(lambda _index: self._refresh_page())
        self.nav = self._sidebar()

        central = QWidget()
        column = QVBoxLayout(central)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(header)
        # The open case from A to Z: its stages, and the next thing to do, on every page.
        self.journey = JourneyBar(session, self.go)
        column.addWidget(self.journey)
        # The sidebar and the page share a divider that can be dragged; where it was left is
        # remembered, as is the window's size and place.
        self.body = QSplitter(Qt.Orientation.Horizontal)
        self.body.setObjectName("body")
        self.body.setChildrenCollapsible(False)
        self.body.setHandleWidth(6)
        self.body.addWidget(self.nav)
        self.body.addWidget(self.tabs)
        self.body.setStretchFactor(1, 1)
        self.body.setSizes([round(self._NAV_WIDTH * zoom.level()), 1200])
        self.body.splitterMoved.connect(lambda _pos, _index: self._size_nav_items(self.nav))
        column.addWidget(self.body, 1)
        self._restore_layout()
        self.setCentralWidget(central)
        self._menus()
        self.statusBar().showMessage(
            "Decision support only. Nothing here may be relied on until a named reviewer has approved it."
        )
        # How busy the machine is, and how much of it ELI Legal uses: read every few seconds off
        # the interface thread (a graphics driver can take a moment to answer).
        self.usage = QLabel("")
        self.usage.setProperty("class", "muted")
        self.statusBar().addPermanentWidget(self.usage)
        self._meter = UsageMeter()
        self._reader = _UsageReader(self)
        self._reader.ready.connect(self._show_usage)
        self._reading = False
        self._seen_event: int | None = None
        self.usage_timer = QTimer(self)
        self.usage_timer.timeout.connect(self._read_usage)
        self.usage_timer.start(3000)
        QTimer.singleShot(1000, self._read_usage)
        session.changed.connect(self.refresh)
        session.busy.connect(self._busy)
        self.refresh()
        # Routine checks run on their own: once soon after sign-in if they are due, then
        # whenever they fall due. An interval of 0 hours switches the schedule off.
        # Notifications: checked every few seconds, so when a run stops for this person (on this
        # machine or on another signed in to the same data) they are told.
        self.waiting_timer = QTimer(self)
        self.waiting_timer.timeout.connect(self.check_waiting)
        self.waiting_timer.start(5_000)  # others' work shows here within seconds
        QTimer.singleShot(1500, self.check_waiting)
        self.checks_timer = QTimer(self)
        self.checks_timer.timeout.connect(self.scheduled_checks)
        if session.sv.ctx.settings.checks_every_hours > 0:
            self.checks_timer.start(30 * 60 * 1000)
            QTimer.singleShot(3000, self.scheduled_checks)

    # ── navigation ───────────────────────────────────────────────────────────
    # Each page in plain words: its name in the sidebar and what it is for.
    _SECTIONS = (
        ("START HERE", ("NewCaseTab", "HelpTab", "HomeTab")),
        (
            "THIS CASE",
            ("MatterTab", "DocumentsTab", "ChatTab", "WorkflowTab", "AgentsTab", "FindingsTab",
             "ReviewTab"),
        ),
        ("CHECKING AND RECORDS", ("AuditTab", "GovernanceTab", "ReleasedTab")),
        ("SET-UP", ("SourcesTab", "FrameworksTab", "SettingsTab")),
    )  # fmt: skip
    _PAGE_KEYS = {
        "start": "NewCaseTab",
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
        "released": "ReleasedTab",
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
        nav.setMinimumWidth(150)
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
                holder.setProperty("accent", name == "NewCaseTab")  # the way in stands out
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
        # inside each entry's box: the list's margins and the box's own (gui/theme.py)
        width = nav.width() - nav.verticalScrollBar().sizeHint().width() - 30
        for row in range(nav.count()):
            item = nav.item(row)
            holder = nav.itemWidget(item)
            layout = holder.layout() if holder is not None else None
            if holder is not None and layout is not None:
                holder.setFixedWidth(width)
                # the box around it: its margin, border and padding above and below
                item.setSizeHint(QSize(width, layout.totalHeightForWidth(width) + 14))
            elif holder is None:  # a group's heading, with room above it
                item.setSizeHint(QSize(width, nav.fontMetrics().height() + 22))

    def _nav_zoomed(self, level: float) -> None:
        """Larger text, wider sidebar: scaled from wherever the person dragged its divider."""
        if hasattr(self, "body"):
            sizes = self.body.sizes()
            total = sum(sizes) or self.width()
            current = sizes[0] if sizes and sizes[0] > 0 else round(self._NAV_WIDTH * level)
            before = self._nav_level or level
            wanted = round(current * level / before) if self._nav_level else current
            self.body.setSizes([wanted, max(200, total - wanted)])
            self.nav.resize(wanted, self.nav.height())
            self._nav_level = level
        self._size_nav_items(self.nav)

    # ── size: fit the screen, remember what the person chose ─────────────────
    _layout_restored = False
    _nav_level = 0.0

    def _fit_to_screen(self) -> None:
        """Open no bigger than the screen: most of it on a laptop, 1440 by 900 on a large one."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1440, 900)
            return
        free = screen.availableGeometry()
        self.resize(min(1440, round(free.width() * 0.94)), min(900, round(free.height() * 0.92)))
        self.setMinimumSize(640, 420)

    def _restore_layout(self) -> None:
        store = zoom.remembered()
        geometry = store.value("window/geometry")
        if isinstance(geometry, QByteArray) and not geometry.isEmpty():
            self.restoreGeometry(geometry)
        divider = store.value("window/divider")
        if isinstance(divider, QByteArray) and not divider.isEmpty():
            self._layout_restored = self.body.restoreState(divider)

    def _save_layout(self) -> None:
        store = zoom.remembered()
        store.setValue("window/geometry", self.saveGeometry())
        store.setValue("window/divider", self.body.saveState())
        store.sync()

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
        page, _, spot = page.partition("#")
        name = self._PAGE_KEYS.get(page)
        target = next((p for p in self.pages if type(p).__name__ == name), None)
        if target is not None:
            self.tabs.setCurrentWidget(target)
        if spot == "issues" and isinstance(target, MatterTab):
            target.edit_details(focus="issues")

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
        add(file_menu, "Closed cases…", self.closed_cases)
        file_menu.addSeparator()
        add(file_menu, "Sign out", self.sign_out)
        add(file_menu, "Quit", self.close, "Ctrl+Q")
        view = self.menuBar().addMenu("&View")
        add(view, "Refresh", self.refresh, "F5")
        add(view, "Show or hide processor, memory and graphics card use", self._toggle_usage)
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
        self._refresh_header()
        if self.session.user_id:
            self._refresh_page()

    def _refresh_header(self) -> None:
        """The case list, the stage bar and the header's chips; not the page."""
        session = self.session
        if not session.user_id:
            return
        sv = session.sv
        matters = sv.matters.list_for(session.user_id)
        self.matter_box.blockSignals(True)
        self.matter_box.clear()
        self.matter_box.addItem("— no matter open —", "")
        closed = 0
        for listed in matters:
            if listed.status is MatterStatus.CLOSED and listed.matter_id != session.matter_id:
                closed += 1  # off the list, not gone: File → Closed cases
                continue
            self.matter_box.addItem(
                f"{listed.name}  ·  {plain.state(listed.status).lower()}", listed.matter_id
            )
            if listed.matter_id == session.matter_id:
                self.matter_box.setCurrentIndex(self.matter_box.count() - 1)
        if closed:
            self.matter_box.addItem(f"Closed cases ({closed})…", _CLOSED)
        self.matter_box.blockSignals(False)
        matter = session.matter
        self.profile.setText(profile_spec(matter.profile).label if matter else "")
        self.journey.refresh()
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

    def _matter_chosen(self) -> None:
        chosen = self.matter_box.currentData() or ""
        if chosen == _CLOSED:
            self.refresh()  # back to the case that was open, then the list of closed ones
            self.closed_cases()
            return
        if chosen != self.session.matter_id:
            self.session.set_matter(chosen)

    def _follow_others(self) -> None:
        """What others did on this case (in the browser, or on another machine signed in to the
        same data) shows here without anyone pressing F5: the stage bar, the header and the page
        in front of you, if it is one that only shows the case. Never while a dialog is open or
        work is running, so nothing being typed or chosen is lost."""
        audit = self.session.sv.ctx.audit
        try:
            head = audit.head()
        except Exception:  # noqa: BLE001 - tried again on the next tick
            return
        if self._seen_event is None or head <= self._seen_event:
            self._seen_event = head
            return
        fresh = audit.since(self._seen_event)
        self._seen_event = head
        mid, me = self.session.matter_id, self.session.user_id
        if not mid or not any(e.get("matter_id") == mid and e.get("actor_id") != me for e in fresh):
            return
        if QApplication.activeModalWidget() is not None or self.session.working:
            self._seen_event = min(e["seq"] for e in fresh) - 1  # caught up with next time
            return
        self._refresh_header()
        page = self.tabs.currentWidget()
        if isinstance(page, _LIVE_PAGES):
            page.refresh()
        self.statusBar().showMessage("Updated: someone else has worked on this case.", 6000)

    def closed_cases(self) -> None:
        if not self.session.user_id:
            return
        ClosedCasesDialog(self, self.session).exec()
        self.refresh()

    # ── resource use ─────────────────────────────────────────────────────────
    def _read_usage(self) -> None:
        if self._reading or not self.usage.isVisible():
            return
        self._reading = True
        meter, reader = self._meter, self._reader

        def work() -> None:
            try:
                reading = meter.read()
            except Exception:  # noqa: BLE001 - a failed reading is tried again on the next tick
                reading = None
            try:
                reader.ready.emit(reading)
            except RuntimeError:  # the window closed meanwhile
                pass

        threading.Thread(target=work, name="eli-legal-usage", daemon=True).start()

    def _show_usage(self, reading: object) -> None:
        self._reading = False
        if isinstance(reading, Usage):
            self.usage.setText(usage_summary(reading))
            self.usage.setToolTip(usage_details(reading))

    def _toggle_usage(self) -> None:
        self.usage.setVisible(not self.usage.isVisible())
        if self.usage.isVisible():
            self._read_usage()

    # ── work waiting for this person ─────────────────────────────────────────
    def check_waiting(self) -> None:
        if not self.session.user_id or self.signing_out:
            return
        self._follow_others()
        try:
            items = self.session.sv.notifications.inbox(self.session.user_id)
        except Exception:  # noqa: BLE001 - a failed check is tried again on the next tick
            return
        self._waiting = items
        unread = [n for n in items if n["status"] == "open"]
        self.bell.setText(f"🔔 {len(unread)} waiting for you" if unread else "Nothing waiting")
        self.bell.setProperty("kind", "primary" if unread else "")
        self.bell.style().unpolish(self.bell)
        self.bell.style().polish(self.bell)
        fresh = [n for n in unread if n["notification_id"] not in self._told]
        self._told.update(n["notification_id"] for n in fresh)
        if fresh:
            latest = fresh[0]
            more = f" (and {len(fresh) - 1} more)" if len(fresh) > 1 else ""
            self.statusBar().showMessage(f"For you: {latest['title']}{more}", 15000)
            QApplication.alert(self, 0)  # the task bar entry asks for attention

    def _show_waiting(self) -> None:
        menu = QMenu(self)
        if not self._waiting:
            menu.addAction("Nothing is waiting for you.").setEnabled(False)
        for note in self._waiting[:12]:
            mark = "● " if note["status"] == "open" else ""
            action = menu.addAction(f"{mark}{note['title']}")
            action.setToolTip(note["detail"])
            action.triggered.connect(lambda _c=False, n=note: self._open_waiting(n))
        if any(n["status"] == "open" for n in self._waiting):
            menu.addSeparator()
            menu.addAction("Mark all as seen").triggered.connect(self._seen_all)
        menu.exec(self.bell.mapToGlobal(self.bell.rect().bottomLeft()))

    def _open_waiting(self, note: dict[str, Any]) -> None:
        sv, user = self.session.sv, self.session.user_id
        self.session.attempt(
            self,
            lambda: sv.notifications.mark_read(
                note["matter_id"], note["notification_id"], actor_id=user
            ),
            quiet=True,
        )
        if note["matter_id"] != self.session.matter_id:
            self.session.set_matter(note["matter_id"], announce=False)
        if note.get("run_id"):
            self.session.set_run(note["run_id"])
        else:
            self.session.notify()
        self.go(note["page"])
        self.check_waiting()

    def _seen_all(self) -> None:
        self.session.attempt(
            self, lambda: self.session.sv.notifications.mark_all_read(self.session.user_id)
        )
        self.check_waiting()

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
        self._save_layout()
        self.session.stop_server()
        self.session.sign_out()
        event.accept()
