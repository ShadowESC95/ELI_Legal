"""Home: where the open matter stands, what to do next, and what is waiting for you.

The first page a person sees after signing in. It answers three questions without their having
to look anywhere else: what stage is this matter at, what should I do now (and can I, or who
can), and is anything about the system itself in need of attention.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from eli_legal.domain import plain
from eli_legal.gui import theme
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import button, card, label, row

_STAGE_COLOUR = {
    "done": theme.GOOD,
    "current": theme.ACCENT,
    "waiting": theme.WARN,
    "later": theme.IDLE,
}
_CHECK_MARK = {"ok": "✓", "attention": "!", "failed": "✗", "could_not_run": "?"}


class HomeTab(Tab):
    title = "🏠 Home"

    def __init__(self, session, go: Callable[[str], None]) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self._go = go
        self.heading = label("", "title", wrap=True)
        self.headline = label("", wrap=True)
        self.role = label("", "muted", wrap=True)
        self.stages_host = QWidget()
        self.stages = QHBoxLayout(self.stages_host)
        self.stages.setContentsMargins(0, 0, 0, 0)
        self.stages.setSpacing(6)
        self.steps_host = QWidget()
        self.steps = QVBoxLayout(self.steps_host)
        self.steps.setContentsMargins(0, 0, 0, 0)
        self.steps.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.work = QListWidget()
        self.work.setWordWrap(True)
        self.work.itemActivated.connect(self._open_work)
        self.checks = label("", wrap=True)
        self.checks_list = QListWidget()
        self.checks_list.setWordWrap(True)
        self.compliance = label("", wrap=True)
        self.run_checks = button("Run the checks now", self._run_checks)

        left = QWidget()
        column = QVBoxLayout(left)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(card("This matter", self.heading, self.headline, self.role))
        column.addWidget(card("Where it stands", self.stages_host))
        steps_scroll = QScrollArea()
        steps_scroll.setWidgetResizable(True)
        steps_scroll.setFrameShape(QFrame.Shape.NoFrame)
        steps_scroll.setWidget(self.steps_host)
        column.addWidget(card("What to do next", steps_scroll), 1)

        right = QWidget()
        side = QVBoxLayout(right)
        side.setContentsMargins(0, 0, 0, 0)
        side.addWidget(
            card(
                "Waiting for you on your matters",
                label("Double-click one to open it.", "muted"),
                self.work,
            ),
            1,
        )
        side.addWidget(
            card(
                "Routine checks",
                self.checks,
                self.checks_list,
                row(self.run_checks, button("Details…", lambda: self._go("governance")), None),
            ),
            1,
        )
        side.addWidget(
            card(
                "The organisation's compliance",
                self.compliance,
                row(button("Open compliance…", lambda: self._go("governance")), None),
            )
        )
        grid = QGridLayout()
        grid.addWidget(left, 0, 0)
        grid.addWidget(right, 0, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        self.root.addLayout(grid, 1)

    # ── filling ──────────────────────────────────────────────────────────────
    def refresh(self) -> None:
        if not self.actor:
            return
        self._matter()
        self._work()
        self._checks()
        overview = self.session.attempt(
            self, lambda: self.sv.compliance.overview(actor_id=self.actor), quiet=True
        )
        self.compliance.setText(overview.headline if overview else "")

    def _clear(self, layout: QHBoxLayout | QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()

    def _matter(self) -> None:
        self._clear(self.stages)
        self._clear(self.steps)
        if not self.mid:
            self.heading.setText("No matter is open")
            self.headline.setText(
                "Open a matter to begin: the wizard asks who it is for, the legal system, the "
                "parties and issues, the team and their roles, the sources and the laws."
            )
            self.role.setText("")
            self.steps.addWidget(
                row(button("Open a matter…", lambda: self._go("new_matter"), kind="primary"), None)
            )
            return
        guide = self.session.attempt(
            self,
            lambda: self.sv.guidance.for_matter(self.mid, actor_id=self.actor),
            quiet=True,
        )
        if guide is None:
            return
        self.heading.setText(guide.matter_name)
        self.headline.setText(guide.headline)
        self.role.setText(
            f"<b>Your role on this matter: {guide.role}.</b> {guide.role_summary}<br>{guide.reads}"
        )
        for number, stage in enumerate(guide.stages, start=1):
            box = QLabel(
                f"<b>{number}. {stage.title}</b><br><span style='font-size:9pt'>"
                f"{plain.state(stage.state) if stage.state != 'current' else 'Now'}</span>"
            )
            box.setToolTip(stage.detail)
            box.setAlignment(Qt.AlignmentFlag.AlignCenter)
            box.setMinimumHeight(48)
            colour = _STAGE_COLOUR.get(stage.state, theme.IDLE)
            weight = "2px" if stage.state == "current" else "1px"
            box.setStyleSheet(
                f"border: {weight} solid {colour}; border-radius: 8px; color: {colour};"
                " padding: 4px;"
            )
            self.stages.addWidget(box, 1)
        if not guide.steps:
            self.steps.addWidget(label("Nothing is waiting on this matter.", "muted"))
        for index, step in enumerate(guide.steps):
            self.steps.addWidget(self._step(step, primary=index == 0))

    def _step(self, step, *, primary: bool) -> QWidget:  # type: ignore[no-untyped-def]
        holder = QFrame()
        holder.setProperty("role", "step")
        holder.setStyleSheet(
            f"QFrame[role='step'] {{ border: 1px solid {theme.BORDER}; border-radius: 8px; }}"
        )
        line = QHBoxLayout(holder)
        text = label(
            f"<b>{step.title}</b><br><span style='color:{theme.MUTED}'>{step.why}</span>"
            + (
                ""
                if step.can_do
                else f"<br><span style='color:{theme.WARN}'>You cannot do this. {step.who}</span>"
            ),
            wrap=True,
        )
        line.addWidget(text, 1)
        go = QPushButton(f"Go to {_PAGE_NAMES.get(step.page, step.page)} →")
        if primary and step.can_do:
            go.setProperty("kind", "primary")
        go.clicked.connect(lambda _checked=False, page=step.page: self._go(page))
        line.addWidget(go, 0, Qt.AlignmentFlag.AlignVCenter)
        return holder

    def _work(self) -> None:
        self.work.clear()
        items = self.session.attempt(
            self, lambda: self.sv.guidance.my_work(actor_id=self.actor), quiet=True
        )
        for w in items or []:
            entry = QListWidgetItem(f"{w.matter_name}\n    {w.text}")
            entry.setData(Qt.ItemDataRole.UserRole, (w.matter_id, w.page))
            self.work.addItem(entry)
        if not items:
            self.work.addItem("Nothing is waiting for you.")

    def _checks(self) -> None:
        self.checks_list.clear()
        latest = self.sv.checks.latest()
        allowed = self.session.may("checks.run")
        self.run_checks.setEnabled(allowed)
        self.run_checks.setToolTip(
            "" if allowed else "Running them by hand needs an administrator or governance role."
        )
        if latest is None:
            self.checks.setText("The routine checks have not run yet.")
            return
        when = latest.finished_at or latest.started_at
        colour = theme.colour_for(latest.state)
        self.checks.setText(
            f"<span style='color:{colour}'><b>{latest.headline}</b></span><br>"
            f"<span style='color:{theme.MUTED}'>Last run {when:%d %b %Y %H:%M} UTC by "
            f"{latest.actor_id}. {_schedule(self.sv.ctx.settings.checks_every_hours)}</span>"
        )
        results = self.session.attempt(
            self, lambda: self.sv.checks.for_viewer(latest, actor_id=self.actor), quiet=True
        )
        for result in results or []:
            entry = QListWidgetItem(
                f"{_CHECK_MARK.get(result.state, '?')}  {result.title}: {result.summary}"
            )
            entry.setForeground(QBrush(QColor(theme.colour_for(result.state))))
            entry.setToolTip(
                "\n".join([result.what_to_do, *(i.text for i in result.items[:8])]).strip()
            )
            self.checks_list.addItem(entry)

    # ── acting ───────────────────────────────────────────────────────────────
    def _open_work(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        matter_id, page = data
        if matter_id != self.mid:
            self.session.set_matter(matter_id)
        self._go(page)

    def _run_checks(self) -> None:
        self.session.background(
            "Running the routine checks…",
            lambda: self.sv.checks.run(actor_id=self.actor),
            lambda _run: self.session.notify(),
            lambda exc: self.checks.setText(f"The checks could not run: {exc}"),
        )


def _schedule(hours: float) -> str:
    if hours <= 0:
        return "They run only when someone asks: the schedule is switched off."
    return f"They run on their own every {hours:g} hours."


_PAGE_NAMES = {
    "matter": "Matter",
    "evidence": "Evidence",
    "workflow": "Workflow",
    "review": "Review",
    "findings": "Findings",
    "governance": "Governance",
    "settings": "Settings",
    "new_matter": "the wizard",
}
