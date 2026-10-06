from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QLineEdit, QMessageBox, QTabWidget, QVBoxLayout, QWidget

from eli_legal.domain.enums import IncidentSeverity
from eli_legal.governance.registers import check_registers, load_register
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import ReasonDialog, button, fill, fit, label, row, selected_id, table


class GovernanceTab(Tab):
    title = "🛡 Governance"

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.inner = QTabWidget()
        self.root.addWidget(
            label(
                "How each legal and standards requirement is met, by which control, and what remains for the organisation. These are working aids to check against the official texts — not legal advice, and not a conformity assessment.",
                "muted",
                wrap=True,
            )
        )
        self.root.addWidget(self.inner, 1)

        self.requirements = table(
            [
                "Ref",
                "Instrument",
                "Provision",
                "For",
                "Requirement, in plain words",
                "Controls",
                "Status",
                "How it is met, and what remains",
            ]
        )
        self.controls = table(
            ["Control", "What it does", "Type", "Code", "Tests", "Evidence it produces", "Owner"]
        )
        self.risks = table(
            [
                "Risk",
                "What could go wrong",
                "Cause",
                "Impact",
                "Controls",
                "What remains",
                "Owner",
                "Status",
            ]
        )
        self.matrix = table(
            ["Responsibility", "Provider", "Deployer", "Technical / security owner"], stretch=0
        )
        for widget, name in (
            (self.requirements, "Requirements"),
            (self.controls, "Controls"),
            (self.risks, "Risks"),
            (self.matrix, "Who is responsible"),
        ):
            self.inner.addTab(widget, name)

        self.alerts = table(["What needs attention"])
        self.metrics = table(["Measure", "Value"], stretch=1)
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(
            label(
                "Computed from control evidence across every matter: failed checks, overrides, unchallenged approvals, open incidents, version changes.",
                "muted",
                wrap=True,
            )
        )
        box.addWidget(
            row(
                button("Refresh monitoring", self._monitor, kind="primary"),
                button("Check the registers against the code", self._check),
                None,
            )
        )
        box.addWidget(self.alerts)
        box.addWidget(self.metrics, 1)
        self.inner.addTab(page, "Monitoring")

        self.incidents = table(
            ["Incident", "State", "Severity", "Category", "Detail", "Containment"], stretch=4
        )
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(
            label(
                "The system opens an incident itself for a flagged file, an audit gap or an audit integrity failure.",
                "muted",
            )
        )
        box.addWidget(self.incidents, 1)
        box.addWidget(
            row(
                button("Open an incident…", self._open_incident),
                button("Close the selected incident…", self._close_incident),
                None,
            )
        )
        self.inner.addTab(page, "Incidents")
        self._loaded = False

    def refresh(self) -> None:
        if not self._loaded:
            self._loaded = True
            requirements = load_register("requirements")
            fill(
                self.requirements,
                [
                    [
                        r["requirement_id"],
                        r["instrument"].split(" (")[0],
                        r["reference"],
                        r["addressed_to"],
                        r["requirement_in_plain_words"],
                        r["control_ids"].replace(";", ", "),
                        r["status"],
                        r["how_met_and_what_remains"],
                    ]
                    for r in requirements
                ],
                state_columns=[6],
            )
            fit(self.requirements, [80, 110, 170, 80, 380, 150, 110, 0])
            controls = load_register("controls")
            fill(
                self.controls,
                [
                    [
                        c["control_id"],
                        c["control"],
                        c["type"],
                        c["implementation"].replace(";", ", "),
                        str(len(c["tests"].split(";"))) + " test(s)",
                        c["evidence"],
                        c["owner_role"].replace("_", " "),
                    ]
                    for c in controls
                ],
            )
            fit(self.controls, [60, 520, 70, 300, 70, 300, 0])
            risks = load_register("risks")
            fill(
                self.risks,
                [
                    [
                        r["risk_id"],
                        r["risk"],
                        r["cause"],
                        r["impact"],
                        r["control_ids"].replace(";", ", "),
                        r["residual_risk_and_limits"],
                        r["owner_role"].replace("_", " "),
                        r["status"],
                    ]
                    for r in risks
                ],
                state_columns=[7],
            )
            fit(self.risks, [50, 320, 240, 240, 150, 420, 150, 0])
            matrix = load_register("responsibilities")
            fill(
                self.matrix,
                [
                    [
                        m["responsibility"],
                        m["provider"],
                        m["deployer"],
                        m["technical_security_owner"],
                    ]
                    for m in matrix
                ],
            )
            done = sum(1 for r in requirements if r["status"] == "implemented")
            part = sum(1 for r in requirements if r["status"] == "partial")
            self.inner.setTabText(
                0,
                f"Requirements ({done} met, {part} partly, {len(requirements) - done - part} for the organisation)",
            )
            self.inner.setTabText(1, f"Controls ({len(controls)})")
            self.inner.setTabText(2, f"Risks ({len(risks)})")
        incidents = (
            self.sv.incidents.list(self.mid, actor_id=self.actor)
            if self.mid and self.session.may("matter.read")
            else []
        )
        fill(
            self.incidents,
            [
                [
                    i.incident_id[-8:],
                    i.status,
                    i.severity.value,
                    i.category.replace("_", " "),
                    i.detail,
                    i.containment,
                ]
                for i in incidents
            ],
            ids=[i.incident_id for i in incidents],
            state_columns=[1, 2],
        )
        fit(self.incidents, [90, 70, 80, 220, 0, 260])
        self.inner.setTabText(
            5, f"Incidents ({sum(1 for i in incidents if i.status == 'open')} open)"
        )

    def _monitor(self) -> None:
        snapshot = self.session.attempt(
            self, lambda: self.sv.monitoring.snapshot(actor_id=self.actor), quiet=True
        )
        if snapshot is None:
            return
        fill(self.alerts, [[a] for a in snapshot.alerts] or [["Nothing needs attention."]])
        rows = [
            ["Matters", snapshot.matters],
            ["Human check results", snapshot.human_results],
            ["… of which overrode the system", snapshot.overrides],
            ["Documents not read", snapshot.documents_not_read],
            ["Model answer items discarded", snapshot.model_items_rejected],
            ["Open incidents", snapshot.open_incidents],
        ]
        rows += [
            [f"Runs — {k.replace('_', ' ')}", v] for k, v in sorted(snapshot.runs_by_status.items())
        ]
        rows += [
            [f"Reviews — {k.replace('_', ' ')}", v] for k, v in sorted(snapshot.reviews.items())
        ]
        rows += [
            [f"Holds raised — {k.replace('_', ' ')}", v]
            for k, v in sorted(snapshot.holds_by_reason.items())
        ]
        rows += [
            [f"Checks — {k.replace(':', ' → ').replace('_', ' ')}", v]
            for k, v in sorted(snapshot.checks.items())
        ]
        fill(self.metrics, rows)

    def _check(self) -> None:
        problems = check_registers(None)
        QMessageBox.information(
            self,
            "Registers",
            "Every control points at code that exists and every cross-reference resolves."
            if not problems
            else "\n".join(problems),
        )

    def _open_incident(self) -> None:
        if not self.mid:
            return
        category = QLineEdit()
        severity = QComboBox()
        for level in IncidentSeverity:
            severity.addItem(level.value, level.value)
        severity.setCurrentText("medium")
        detail = ReasonDialog.ask(
            self,
            "Open an incident",
            "What happened?",
            extra=[("Category", category), ("Severity", severity)],
            placeholder="What happened, and what it affects",
        )
        if detail:
            self.session.attempt(
                self,
                lambda: self.sv.incidents.create(
                    self.mid,
                    actor_id=self.actor,
                    category=category.text().strip() or "other",
                    detail=detail,
                    severity=IncidentSeverity(severity.currentData()),
                    run_id=self.rid or None,
                ),
            )

    def _close_incident(self) -> None:
        incident_id = selected_id(self.incidents)
        if not incident_id:
            return
        containment = QLineEdit()
        containment.setPlaceholderText("What was stopped, removed or held")
        reason = ReasonDialog.ask(
            self,
            "Close the incident",
            "Why can it be closed?",
            extra=[("Containment", containment)],
        )
        if reason:
            self.session.attempt(
                self,
                lambda: self.sv.incidents.close(
                    self.mid,
                    incident_id,
                    actor_id=self.actor,
                    containment=containment.text().strip(),
                    reason=reason,
                ),
            )
