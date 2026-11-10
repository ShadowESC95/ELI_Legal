from __future__ import annotations

import json

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QPlainTextEdit,
    QSplitter,
    QStyleOptionGraphicsItem,
    QWidget,
)

from eli_legal.domain import plain
from eli_legal.domain.enums import RunStatus
from eli_legal.domain.models import RunStep
from eli_legal.gui import theme
from eli_legal.gui.run_controls import hold_run, lift_hold, person_hold
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import ReasonDialog, button, card, chip, label, row, set_chip
from eli_legal.workflows.agents import HUMAN, MODEL_ASSISTED, agent_for, layers

NODE_W, NODE_H, GAP_X, GAP_Y, ROW_GAP = 168.0, 50.0, 46.0, 16.0, 44.0


class _Node(QGraphicsItem):
    """One step of the workflow, drawn as a pill coloured by what happened to it."""

    def __init__(self, step_id: str, name: str, kind: str) -> None:
        super().__init__()
        self.step_id, self.name, self.kind = step_id, name, kind
        self.status = "pending"
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setToolTip(f"{name} — {step_id}")

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, NODE_W, NODE_H)

    def paint(
        self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None
    ) -> None:
        colour = QColor(
            theme.HUMAN
            if self.kind == HUMAN and self.status == "pending"
            else theme.colour_for(self.status)
        )
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fill_colour = QColor(colour)
        fill_colour.setAlpha(70 if self.status in ("pending", "skipped") else 110)
        painter.setBrush(QBrush(fill_colour))
        pen = QPen(
            QColor("#ffffff") if self.isSelected() else colour, 2.4 if self.isSelected() else 1.4
        )
        if self.kind == HUMAN:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRoundedRect(self.boundingRect().adjusted(1, 1, -1, -1), 12, 12)
        painter.setPen(QPen(QColor("#f2f6fb")))
        font = QFont(painter.font())
        font.setBold(True)
        font.setPointSizeF(8.6)
        painter.setFont(font)
        painter.drawText(
            QRectF(8, 5, NODE_W - 16, 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.name,
        )
        font.setBold(False)
        font.setPointSizeF(7.6)
        painter.setFont(font)
        painter.setPen(QPen(colour.lighter(140)))
        tag = {HUMAN: "person", MODEL_ASSISTED: "model-assisted"}.get(self.kind, "rule-based")
        painter.drawText(
            QRectF(8, 26, NODE_W - 16, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{self.status.replace('_', ' ')} · {tag}",
        )


class DagView(QGraphicsView):
    """The workflow as a graph, left to right in dependency order."""

    picked = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        # The map grows and shrinks with the rest of the application (gui/zoom.py).
        self.setProperty("zooms", True)
        from eli_legal.gui import zoom

        self.setTransform(QTransform.fromScale(zoom.level(), zoom.level()))
        self.nodes: dict[str, _Node] = {}
        self._scene.selectionChanged.connect(self._selection)

    def build(self, workflow, per_row: int | None = None) -> None:  # type: ignore[no-untyped-def]
        """Lay the layers out left to right, wrapping onto further rows so that the whole graph
        is readable at the width available instead of running off the edge."""
        self._workflow = workflow
        statuses = {step_id: node.status for step_id, node in self.nodes.items()}
        chosen = next((s for s, n in self.nodes.items() if n.isSelected()), "")
        self._scene.blockSignals(True)
        self._scene.clear()
        self.nodes.clear()
        grouped = layers(workflow)
        if per_row is None:
            per_row = max(3, int((self.viewport().width() - 30) // (NODE_W + GAP_X)))
        self._per_row = per_row
        bands = [grouped[i : i + per_row] for i in range(0, len(grouped), per_row)]
        column_of: dict[str, int] = {}
        top = 0.0
        for band in bands:
            tallest = max(len(layer) for layer in band)
            height = tallest * (NODE_H + GAP_Y)
            for column, layer in enumerate(band):
                offset = (height - len(layer) * (NODE_H + GAP_Y)) / 2
                for index, step_id in enumerate(layer):
                    agent = agent_for(step_id)
                    node = _Node(step_id, agent.name, agent.kind)
                    node.status = statuses.get(step_id, "pending")
                    node.setPos(column * (NODE_W + GAP_X), top + offset + index * (NODE_H + GAP_Y))
                    self._scene.addItem(node)
                    self.nodes[step_id] = node
                    column_of[step_id] = column
            top += height + ROW_GAP
        pen = QPen(QColor("#4c5d78"), 1.3)
        for step in workflow.steps:
            target = self.nodes[step.id]
            for dependency in step.depends_on:
                source = self.nodes[dependency]
                if (
                    source.pos().y() + NODE_H < target.pos().y()
                    and column_of[dependency] >= column_of[step.id]
                ):
                    # the dependency is on the row above: come out of its foot, into this one's head
                    start = source.pos() + QPointF(NODE_W / 2, NODE_H)
                    finish = target.pos() + QPointF(NODE_W / 2, 0)
                    drop = (finish.y() - start.y()) / 2
                    path = QPainterPath(start)
                    path.cubicTo(start + QPointF(0, drop), finish - QPointF(0, drop), finish)
                else:
                    start = source.pos() + QPointF(NODE_W, NODE_H / 2)
                    finish = target.pos() + QPointF(0, NODE_H / 2)
                    bend = (finish.x() - start.x()) / 2
                    path = QPainterPath(start)
                    path.cubicTo(start + QPointF(bend, 0), finish - QPointF(bend, 0), finish)
                edge = QGraphicsPathItem(path)
                edge.setPen(pen)
                edge.setZValue(-1)
                self._scene.addItem(edge)
        self._scene.setSceneRect(self._scene.itemsBoundingRect().adjusted(-16, -16, 16, 16))
        self._scene.blockSignals(False)
        if chosen in self.nodes:
            self.nodes[chosen].setSelected(True)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        wanted = max(3, int((self.viewport().width() - 30) // (NODE_W + GAP_X)))
        if getattr(self, "_workflow", None) is not None and wanted != getattr(self, "_per_row", 0):
            self.build(self._workflow, wanted)

    def set_statuses(self, statuses: dict[str, str]) -> None:
        for step_id, node in self.nodes.items():
            status = statuses.get(step_id, "pending")
            if node.status != status:
                node.status = status
                node.update()

    def _selection(self) -> None:
        chosen = [i for i in self._scene.selectedItems() if isinstance(i, _Node)]
        if chosen:
            self.picked.emit(chosen[0].step_id)


class WorkflowTab(Tab):
    title = "🕸 DAG"

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.runs = QComboBox()
        self.runs.setMinimumWidth(330)
        self.runs.activated.connect(self._run_chosen)
        self.state = chip("no run")
        self.dag = DagView()
        self.dag.build(self.sv.ctx.workflow)
        self.dag.picked.connect(self._show_step)
        self.step_title = label("Select a step", "title")
        self.step_text = label("", wrap=True)
        self.outputs = QPlainTextEdit()
        self.outputs.setReadOnly(True)
        self._picked = ""
        self.start = button("▶ Start a run", self._start, kind="primary")
        self.stop = button("■ Stop", self._stop, kind="danger")
        self.restart = button("↻ Restart…", self._restart)
        self.root.addWidget(
            row(label("Run"), self.runs, self.state, None, self.start, self.restart, self.stop)
        )
        legend = label(
            f"<span style='color:{theme.GOOD}'>■</span> done &nbsp; "
            f"<span style='color:{theme.ACCENT}'>■</span> running &nbsp; "
            f"<span style='color:{theme.WARN}'>■</span> held &nbsp; "
            f"<span style='color:{theme.BAD}'>■</span> failed &nbsp; "
            f"<span style='color:{theme.IDLE}'>■</span> not run &nbsp; "
            f"<span style='color:{theme.HUMAN}'>▭</span> a person's step (dashed). "
            "A step that does not finish cleanly stops everything after it.",
            "muted",
        )
        # A person's step: what it waits for, and what can be done about it from here.
        self.person_text = label("", wrap=True)
        self.to_decision = button(
            "Open the decision…", lambda: self._open_review(3), kind="primary"
        )
        self.to_release = button("Open the release…", lambda: self._open_review(4), kind="primary")
        self.hold_button = button("Put on hold…", lambda: hold_run(self))
        self.lift_button = button("Lift the hold…", lambda: lift_hold(self))
        self.person_box = card(
            "What this step needs",
            self.person_text,
            row(self.to_decision, self.to_release, None),
            row(self.hold_button, self.lift_button, None),
        )
        self.person_box.hide()
        side = card(
            "Step",
            self.step_title,
            self.step_text,
            self.person_box,
            label("What it recorded", "muted"),
            self.outputs,
        )
        split = QSplitter()
        split.addWidget(card("Case-preparation workflow", self.dag, legend))
        split.addWidget(side)
        split.setSizes([880, 340])
        self.root.addWidget(split, 1)
        self.timer = QTimer(self)
        self.timer.setInterval(700)
        self.timer.timeout.connect(self._tick)

    # ── reading ──────────────────────────────────────────────────────────────
    def _steps(self) -> dict[str, RunStep]:
        if not (self.mid and self.rid):
            return {}
        records = self.sv.ctx.store.list(RunStep, self.mid, run_id=self.rid)
        return {s.step_id: s for s in records}

    def refresh(self) -> None:
        runs = (
            self.session.attempt(
                self, lambda: self.sv.runs.list(self.mid, actor_id=self.actor), quiet=True
            )
            if self.mid
            else []
        )
        self.runs.blockSignals(True)
        self.runs.clear()
        for run in runs or []:
            self.runs.addItem(
                f"{run.created_at:%Y-%m-%d %H:%M}  ·  {run.status.value.replace('_', ' ')}  ·  {run.run_id[-8:]}",
                run.run_id,
            )
            if run.run_id == self.rid:
                self.runs.setCurrentIndex(self.runs.count() - 1)
        self.runs.blockSignals(False)
        self._tick()
        working = self.session.working
        self.start.setEnabled(bool(self.mid) and not working)
        self.restart.setEnabled(bool(self.rid) and not working)
        self.stop.setEnabled(bool(self.rid))

    def _tick(self) -> None:
        steps = self._steps()
        self.dag.set_statuses({k: v.status.value for k, v in steps.items()})
        run = self.session.run
        if run is None:
            set_chip(self.state, "no run yet", theme.IDLE)
        else:
            holds = len(self.sv.ctx.holds.open_holds(self.mid, self.rid))
            text = plain.state(run.status) + (
                f" · {plain.count(holds, 'hold')} open" if holds else ""
            )
            set_chip(self.state, text, theme.colour_for(run.status.value))
        if self._picked:
            self._show_step(self._picked)
        if not self.session.working and self.timer.isActive():
            self.timer.stop()

    def _show_step(self, step_id: str) -> None:
        self._picked = step_id
        agent = agent_for(step_id)
        definition = self.sv.ctx.workflow.step(step_id)
        record = self._steps().get(step_id)
        self.step_title.setText(agent.name)
        status = record.status.value if record else "pending"
        colour = theme.colour_for(status)
        self._person(step_id, definition.manual, record)
        after = (
            ", ".join(agent_for(d).name for d in definition.depends_on) or "nothing — it is first"
        )
        detail = f"<br><b>Why:</b> {record.detail}" if record and record.detail else ""
        self.step_text.setText(
            f"{definition.description}<br><br><b>Status:</b> <span style='color:{colour}'>{plain.state(status)}</span>"
            f"{detail}<br><b>Runs after:</b> {after}"
            f"<br><b>Attempts:</b> {record.attempt if record else 0}"
        )
        self.outputs.setPlainText(
            json.dumps(record.outputs, indent=2, default=str) if record and record.outputs else ""
        )

    def _person(self, step_id: str, manual: bool, record: RunStep | None) -> None:
        """For a person's step: say what it waits for, and offer what can be done now."""
        run = self.session.run
        self.person_box.setVisible(manual and run is not None)
        if not manual or run is None:
            return
        status = run.status
        held = person_hold(self)
        matter = self.session.matter
        reviewers = ", ".join(sorted(matter.reviewer_user_ids)) if matter else ""
        done = record is not None and record.status.value == "ok"
        if held is not None:
            why = held.detail.split(";", 1)[-1].strip()
            said = (
                f"<b>On hold</b>, put there by {self._raised_by(held)}: “{why}”. Nothing goes "
                "further until a decision-maker lifts the hold, or the run is stopped."
            )
        elif done:
            said = f"<b>Done.</b> {record.detail if record else ''}"
        elif step_id == "human_review" and status is RunStatus.AWAITING_HUMAN_REVIEW:
            said = (
                f"<b>Waiting for a named reviewer</b> ({reviewers}) to read the report, "
                "acknowledge each stated limit and approve it, return it for correction or "
                "reject it. Anyone working on the matter can put it on hold first."
            )
        elif step_id != "human_review" and status is RunStatus.APPROVED_FOR_RELIANCE:
            said = (
                "<b>Waiting for a person</b> to prepare the release, confirm each recipient "
                "and stage it in the outbox. The approved report can still be put on hold, "
                "which suspends reliance on it."
            )
        elif status is RunStatus.HELD:
            said = (
                "Not reached yet: the run is on hold until its holds are dealt with, on the "
                "Review page."
            )
        else:
            said = f"Not reached yet: the run is {plain.state(status).lower()}."
        self.person_text.setText(said)
        reviewing = step_id == "human_review"
        self.to_decision.setVisible(reviewing)
        self.to_release.setVisible(not reviewing)
        self.to_decision.setEnabled(status is RunStatus.AWAITING_HUMAN_REVIEW and held is None)
        self.to_release.setEnabled(status is RunStatus.APPROVED_FOR_RELIANCE and held is None)
        self.hold_button.setEnabled(
            held is None
            and status in (RunStatus.AWAITING_HUMAN_REVIEW, RunStatus.APPROVED_FOR_RELIANCE)
            and self.session.may("workflow.hold")
        )
        self.lift_button.setEnabled(held is not None and self.session.may("hold.resolve"))

    def _raised_by(self, hold) -> str:  # type: ignore[no-untyped-def]
        for event in self.sv.ctx.audit.events(matter_id=self.mid, run_id=self.rid):
            if event["event_type"] == "hold_raised" and event["subject_id"] == hold.hold_id:
                return str(event["actor_id"])
        return "a person"

    def _open_review(self, page: int) -> None:
        window = self.window()
        go = getattr(window, "go", None)
        if go is None:
            return
        go("review")
        review = getattr(window, "tabs", None)
        inner = getattr(review.currentWidget(), "inner", None) if review is not None else None
        if inner is not None:
            inner.setCurrentIndex(page)

    def _run_chosen(self) -> None:
        run_id = self.runs.currentData()
        if run_id and run_id != self.rid:
            self.session.set_run(run_id)

    # ── doing ────────────────────────────────────────────────────────────────
    def _finished(self, _result: object = None) -> None:
        self.timer.stop()
        self.session.notify()

    def _failed(self, exc: Exception) -> None:
        self.timer.stop()
        self.session.attempt(self, lambda: (_ for _ in ()).throw(exc))

    def _start(self) -> None:
        run = self.session.attempt(
            self, lambda: self.sv.runs.create(self.mid, actor_id=self.actor), quiet=True
        )
        if run is None:
            return
        self.session.run_id = run.run_id
        mid, rid, actor = self.mid, run.run_id, self.actor
        self.session.background(
            "Running the workflow…",
            lambda: self.sv.runs.execute(mid, rid, actor_id=actor),
            self._finished,
            self._failed,
        )
        self.timer.start()
        self.session.notify()

    def _stop(self) -> None:
        reason = ReasonDialog.ask(
            self,
            "Stop this run",
            "Stopping takes effect before the next step begins. Why are you stopping it?",
        )
        if reason:
            self.session.attempt(
                self,
                lambda: self.sv.runs.stop(self.mid, self.rid, actor_id=self.actor, reason=reason),
            )

    def _restart(self) -> None:
        steps = QComboBox()
        steps.addItem("the first step that did not finish cleanly", "")
        for step in self.sv.ctx.workflow.automated:
            steps.addItem(agent_for(step.id).name, step.id)
        reason = ReasonDialog.ask(
            self,
            "Restart this run",
            "A restart is recorded under your name. The step you choose and everything after it runs again; earlier decisions about findings are kept.",
            extra=[("Restart from", steps)],
        )
        if not reason:
            return
        phrase = self.session.ask_passphrase(self, "restart this run")
        if phrase is None:
            return
        try:
            self.sv.users.confirm(self.actor, phrase)
        except Exception:
            self.session.decide_with(self, "", lambda: None)
            return
        mid, rid, actor, from_step = self.mid, self.rid, self.actor, steps.currentData() or None

        def work() -> object:
            from eli_legal.security import authn

            with authn.stepped_up():
                return self.sv.runs.resume(
                    mid, rid, actor_id=actor, reason=reason, from_step=from_step
                )

        self.session.background("Restarting the run…", work, self._finished, self._failed)
        self.timer.start()
        self.session.notify()
