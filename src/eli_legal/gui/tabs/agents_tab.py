from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QPushButton, QScrollArea, QSplitter, QWidget

from eli_legal.domain.models import RunStep
from eli_legal.governance.registers import load_register
from eli_legal.gui import theme
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import card, label
from eli_legal.workflows.agents import (
    AGENTS,
    DETERMINISTIC,
    HUMAN,
    MODEL_ASSISTED,
    agent_for,
    layers,
)

_KIND_TEXT = {
    DETERMINISTIC: "Rule-based: it follows fixed rules and uses no model.",
    MODEL_ASSISTED: "Model-assisted: a model may select or draft, only from numbered items the system gives it, and every answer is checked against those items before anything is stored.",
    HUMAN: "A person. The system cannot perform this step.",
}


class AgentsTab(Tab):
    title = "🤖 Agents"

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.facts = label("", wrap=True)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.buttons: dict[str, QPushButton] = {}
        grouped = layers(self.sv.ctx.workflow)
        per_band = 6  # layers per band, so the mesh wraps instead of running off the edge
        top = 0
        for start in range(0, len(grouped), per_band):
            band = grouped[start : start + per_band]
            for column, layer in enumerate(band):
                self.grid.addWidget(
                    label(f"L{start + column + 1}", "muted"),
                    top,
                    column,
                    Qt.AlignmentFlag.AlignHCenter,
                )
                for index, step_id in enumerate(layer, start=1):
                    pill = QPushButton(agent_for(step_id).name)
                    pill.setCheckable(True)
                    pill.clicked.connect(lambda _checked=False, s=step_id: self._show(s))
                    self.grid.addWidget(pill, top + index, column)
                    self.buttons[step_id] = pill
            top += 2 + max(len(layer) for layer in band)
            self.grid.setRowMinimumHeight(top - 1, 18)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid_host)
        self.name = label("Select an agent", "title")
        self.body = label("", wrap=True, selectable=True)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop)
        detail = QScrollArea()
        detail.setWidgetResizable(True)
        detail.setWidget(self.body)
        self._controls = {c["control_id"]: c["control"] for c in load_register("controls")}
        self._picked = AGENTS[0].step_id
        split = QSplitter()
        split.addWidget(card("Agent mesh", self.facts, scroll))
        split.addWidget(card("Mandate", self.name, detail))
        split.setSizes([760, 460])
        self.root.addWidget(split)

    def _records(self) -> dict[str, RunStep]:
        if not (self.mid and self.rid):
            return {}
        return {s.step_id: s for s in self.sv.ctx.store.list(RunStep, self.mid, run_id=self.rid)}

    def refresh(self) -> None:
        records = self._records()
        automated = [a for a in AGENTS if a.kind != HUMAN]
        model = self.sv.ctx.model
        self.facts.setText(
            f"<b>Engine</b> &nbsp; ELI Legal workflow runner &nbsp;·&nbsp; "
            f"<b>Agents</b> &nbsp; {len(automated)} automated, {len(AGENTS) - len(automated)} people &nbsp;·&nbsp; "
            f"<b>Layers</b> &nbsp; {len(layers(self.sv.ctx.workflow))} &nbsp;·&nbsp; "
            f"<b>Model</b> &nbsp; {model.model_id if model.available else 'none'}"
            "<br><span style='color:#94a8c6'>Each agent has a fixed mandate: what it reads, what it writes, "
            "and what it may never do. Only three may use a model. None can approve its own work.</span>"
        )
        for step_id, pill in self.buttons.items():
            agent = agent_for(step_id)
            status = records[step_id].status.value if step_id in records else "pending"
            colour = (
                theme.HUMAN
                if agent.kind == HUMAN and status == "pending"
                else theme.colour_for(status)
            )
            border = "dashed" if agent.kind == HUMAN else "solid"
            mark = " ✦" if agent.kind == MODEL_ASSISTED else ""
            pill.setText(f"{agent.name}{mark}")
            pill.setChecked(step_id == self._picked)
            pill.setStyleSheet(
                f"QPushButton {{ border: 1.5px {border} {colour}; color: {colour}; background: #0f1620;"
                " border-radius: 12px; padding: 6px 12px; text-align: left; }"
                "QPushButton:checked { background: #1f2a3a; color: #ffffff; }"
            )
            pill.setToolTip(f"{status} — {agent.role}")
        self._show(self._picked)

    def _show(self, step_id: str) -> None:
        self._picked = step_id
        for key, pill in self.buttons.items():
            pill.setChecked(key == step_id)
        agent = agent_for(step_id)
        record = self._records().get(step_id)
        run = self.session.run
        self.name.setText(agent.name)

        def items(values: tuple[str, ...]) -> str:
            return "".join(f"<li>{v}</li>" for v in values)

        last = "It has not run in the selected run."
        if record is not None:
            colour = theme.colour_for(record.status.value)
            last = f"<span style='color:{colour}'>{record.status.value}</span>" + (
                f" — {record.detail}" if record.detail else ""
            )
            if record.outputs:
                last += "<br>" + ", ".join(
                    f"{k}: {v}"
                    for k, v in record.outputs.items()
                    if not isinstance(v, (list, dict))
                )
        versions = ""
        if run is not None and agent.kind == MODEL_ASSISTED:
            versions = (
                f"<p><b>Model in this run:</b> {run.model_versions.get('generator', 'none')}</p>"
            )
        controls = "".join(
            f"<li><b>{c}</b> — {self._controls.get(c, '')}</li>" for c in agent.controls
        )
        self.body.setText(
            f"<p>{agent.role}</p><p style='color:{theme.MUTED}'>{_KIND_TEXT[agent.kind]}</p>"
            f"<p><b>Reads</b></p><ul>{items(agent.reads)}</ul>"
            f"<p><b>Writes</b></p><ul>{items(agent.writes)}</ul>"
            f"<p><b style='color:{theme.BAD}'>May never</b></p><ul>{items(agent.may_not)}</ul>"
            f"<p><b>Controls it carries out</b></p><ul>{controls or '<li>none of its own</li>'}</ul>"
            f"{versions}<p><b>In the selected run:</b> {last}</p>"
        )
