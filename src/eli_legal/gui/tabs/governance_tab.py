"""Governance: where every legal requirement stands, the organisation's own compliance work,
the routine checks, oversight of every matter, monitoring and incidents.

A requirement reads as met by the software, met, waiting for the organisation or due for
review. What the organisation must do is a list of actions, each recorded here in a named
person's name (with their passphrase again) and reviewed on time.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from PySide6.QtCore import QDate, QDateTime, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from eli_legal.application.incident_service import REPORTING_DAYS, reporting_deadline
from eli_legal.domain import glossary, plain
from eli_legal.domain.enums import IncidentSeverity
from eli_legal.governance.compliance import (
    MIN_AUDIT_RETENTION_DAYS,
    OrganisationAction,
    template_title,
)
from eli_legal.governance.registers import check_registers, load_register
from eli_legal.gui import theme
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import (
    ReasonDialog,
    button,
    card,
    fill,
    fit,
    label,
    row,
    selected_id,
    table,
)
from eli_legal.security import authn

_WHO = {"provider": "Provider", "deployer": "Deployer", "both": "Both"}
# Who does what, in words rather than the letters of a RACI chart.
_DUTY = {
    "R": "Does it",
    "A": "Answers for it",
    "C": "Is asked first",
    "I": "Is kept informed",
}
_DUTY_KEY = (
    "<b>Provider</b> is whoever makes ELI Legal and puts it on the market. <b>Deployer</b> is "
    "your organisation, which uses it. For each thing that has to be done: <b>Does it</b> means "
    "that party does the work; <b>Answers for it</b>, it is answerable for it being done; "
    "<b>Is asked first</b>, it is consulted before it is done; <b>Is kept informed</b>, it is "
    "told once it is done."
)
_ACTION_STATE = {
    "done": "Done",
    "waiting": plain.state("to_do"),
    "review_due": "Review due",
    "not_applicable": "Does not apply",
}


def _utc(widget: QDateTimeEdit) -> datetime:
    moment = widget.dateTime().toPython()
    assert isinstance(moment, datetime)
    return moment.astimezone(timezone.utc)


def _pydate(widget: QDateEdit) -> date:
    d = widget.date()
    return date(d.year(), d.month(), d.day())


class _Dialog(QDialog):
    """A form with OK and Cancel, scrolling when it is long."""

    def __init__(self, parent: QWidget, title: str, intro: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(640)
        outer = QVBoxLayout(self)
        outer.addWidget(label(intro, wrap=True))
        inner = QWidget()
        self.form = QFormLayout(inner)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def ok(self) -> bool:
        return self.exec() == QDialog.DialogCode.Accepted


class GovernanceTab(Tab):
    title = "🛡 Governance"

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.inner = QTabWidget()
        self.headline = label("", wrap=True)
        self.root.addWidget(self.headline)
        self.waiting_note = label("", wrap=True)
        self.to_record = button("Show what to record", self._show_actions, kind="primary")
        waiting_line = QHBoxLayout()
        waiting_line.addWidget(self.waiting_note, 1)
        waiting_line.addWidget(self.to_record, 0)
        self.root.addLayout(waiting_line)
        self.root.addWidget(
            label(
                "Working aids to check against the official texts: not legal advice, and not a "
                "conformity assessment.",
                "muted",
                wrap=True,
            )
        )
        self.root.addWidget(self.inner, 1)
        self._actions: dict[str, OrganisationAction] = {}
        self._last_document: dict[str, str] = {}

        # requirements, with where each stands now
        self.requirements = table(
            [
                "Ref",
                "Law or standard",
                "Article or section",
                "What it requires, in plain words",
                "Who does it",
                "Status",
                "What your organisation still has to record",
                "How the software meets it",
            ]  # fmt: skip
        )
        self.requirements.itemSelectionChanged.connect(self._requirement_chosen)
        self.requirement_detail = label("", wrap=True, selectable=True)
        self.record_needed = button("Go to what it needs", self._record_needed, kind="primary")
        detail = QScrollArea()
        detail.setWidget(self.requirement_detail)
        detail.setWidgetResizable(True)
        detail.setFrameShape(QFrame.Shape.NoFrame)
        self.requirement_detail.setAlignment(Qt.AlignmentFlag.AlignTop)
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.requirements)
        split.addWidget(card("What this requirement needs", detail, row(self.record_needed, None)))
        split.setSizes([420, 320])
        self.inner.addTab(split, "Requirements")

        # the organisation's actions
        self.org_actions = table(
            ["Action", "What to do", "Covers", "For", "Status", "Where it stands"], stretch=1
        )
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(
            label(
                "What the software cannot do for you. Record each one when it is done, or why "
                "it does not apply; each is reviewed again when its date comes.",
                "muted",
                wrap=True,
            )
        )
        box.addWidget(self.org_actions, 1)
        box.addWidget(
            row(
                button("Record it…", self._record, kind="primary"),
                button("It does not apply…", self._not_applicable),
                button("Record training…", self._training),
                button("Run the evaluation", self._evaluate),
                button("Draft the document…", self._generate),
                None,
            )
        )
        self._actions_page = page
        self.inner.addTab(page, "Organisation actions")

        # routine checks
        self.check_state = label("", wrap=True)
        self.check_results = table(["Check", "State", "What it found"], stretch=2)
        self.check_results.itemSelectionChanged.connect(self._check_chosen)
        self.check_detail = label("", wrap=True, selectable=True)
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(self.check_state)
        box.addWidget(self.check_results, 1)
        box.addWidget(card("Details", self.check_detail))
        box.addWidget(row(button("Run the checks now", self._run_checks, kind="primary"), None))
        self.inner.addTab(page, "Routine checks")

        # every matter, for oversight
        self.register = table(
            ["Matter", "For", "Legal system", "State", "People", "Last run", "Open holds"],
            stretch=0,
        )
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(
            label(
                "Every matter on this system, for those who oversee it. A matter you are not on "
                "shows no name, party or content.",
                "muted",
                wrap=True,
            )
        )
        box.addWidget(self.register, 1)
        self.inner.addTab(page, "All matters")

        self.controls = table(
            [
                "Control",
                "Part of",
                "What it does",
                "Type",
                "Code",
                "Tests",
                "Evidence it produces",
                "Owner",
                "Stage",
                "Formerly",
            ]
        )
        # The five RAIMS controls (Week 5 control map): what each needs, its minimum evidence,
        # who owns it, when it must exist, and how many of the system's controls are its parts.
        self.families = table(
            [
                "RAIMS control",
                "What it needs",
                "Minimum evidence fields",
                "Evidence owner",
                "When",
                "Parts",
            ]
        )
        # The RAIMS lifecycle (Week 7): each stage, its main control, owner and evidence, and
        # which of the system's controls operate there.
        self.lifecycle = table(
            ["Stage", "Main control / action", "Owner", "Evidence", "Controls at this stage"]
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
            ]  # fmt: skip
        )
        self.matrix = table(
            [
                "What has to be done",
                "Provider (the maker of ELI Legal)",
                "Deployer (your organisation)",
                "Your IT and security staff",
            ],
            stretch=0,
        )
        for widget, name in (
            (self.families, "RAIMS controls"),
            (self.controls, "Controls"),
            (self.lifecycle, "Lifecycle"),
            (self.risks, "Risks"),
        ):
            self.inner.addTab(widget, name)
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(label(_DUTY_KEY, "muted", wrap=True))
        box.addWidget(self.matrix, 1)
        self.inner.addTab(page, "Who is responsible")

        self.alerts = table(["What needs attention"])
        self.metrics = table(["Measure", "Value"], stretch=1)
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(
            label(
                "Computed from control evidence across every matter: failed checks, overrides, "
                "unchallenged approvals, open incidents, version changes.",
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
            ["Incident", "State", "Severity", "Category", "Detail", "Reporting (Art. 73)"],
            stretch=4,
        )
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(
            label(
                "The system opens an incident itself for a flagged file, an audit failure, an "
                "altered original, or an authority that stopped being good law after approval. "
                "A serious incident shows its reporting deadline until a person decides.",
                "muted",
                wrap=True,
            )
        )
        box.addWidget(self.incidents, 1)
        box.addWidget(
            row(
                button("Open an incident…", self._open_incident),
                button("When it became known…", self._aware),
                button("Owner and stand-in…", self._assign),
                button("Decide on reporting…", self._decide_reporting),
                button("Close the selected incident…", self._close_incident),
                None,
            )
        )
        self._incidents_page = page
        self.inner.addTab(page, "Incidents")

        # deployment authorisations: the approval to use ELI Legal on real matters
        self.deployments = table(
            ["Authorisation", "State", "In force", "Legal systems", "Kinds of matter",
             "Provider lead", "Deployer lead", "Intended use"],
            stretch=7,
        )  # fmt: skip
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(
            label(
                "A real matter's work starts, is approved and leaves only under an authorisation "
                "in force that covers its legal system and kind. It rests on the evidence "
                "documents themselves, is signed by a provider lead and a different deployer "
                "lead, and is pinned to this version, policy, models, workflow, legal-system "
                "packs and sources: a change to any voids it. Practice matters need none.",
                "muted",
                wrap=True,
            )
        )
        box.addWidget(self.deployments, 1)
        box.addWidget(
            row(
                button("Propose…", self._propose_deployment, kind="primary"),
                button("Sign as the provider lead…", lambda: self._sign_deployment("provider")),
                button("Sign as the deployer lead…", lambda: self._sign_deployment("deployer")),
                button("Revoke…", self._revoke_deployment, kind="danger"),
                None,
            )
        )
        self.inner.addTab(page, "Deployment")
        self._registers_loaded = False

    # ── filling ──────────────────────────────────────────────────────────────
    def refresh(self) -> None:
        if not self.actor:
            return
        if not self._registers_loaded:
            self._registers_loaded = True
            self._fill_registers()
        self._fill_compliance()
        self._fill_checks()
        self._fill_register_of_matters()
        self._fill_incidents()
        self._fill_deployments()

    def _fill_registers(self) -> None:
        controls = load_register("controls")
        families = {f["family_id"]: f["name"] for f in load_register("families")}
        fill(
            self.controls,
            [
                [
                    c["control_id"],
                    families.get(c["control_id"].split(".", 1)[0], ""),
                    c["control"],
                    c["type"],
                    c["implementation"].replace(";", ", "),
                    str(len(c["tests"].split(";"))) + " test(s)",
                    c["evidence"],
                    c["owner_role"].replace("_", " "),
                    c.get("stage", ""),
                    c.get("formerly", ""),
                ]
                for c in controls
            ],
        )
        fit(self.controls, [70, 200, 480, 70, 260, 70, 260, 90, 100, 0])
        parts: dict[str, int] = {}
        for c in controls:
            key = c["control_id"].split(".", 1)[0]
            parts[key] = parts.get(key, 0) + 1
        fill(
            self.families,
            [
                [
                    f"{f['family_id']} {f['name']}",
                    f["what_it_needs"],
                    f["minimum_evidence_fields"],
                    f["evidence_owner"],
                    f["when"],
                    str(parts.get(f["family_id"], 0)),
                ]
                for f in load_register("families")
            ],
        )
        fit(self.families, [260, 260, 340, 150, 140, 0])
        at_stage: dict[str, list[str]] = {}
        for c in controls:
            at_stage.setdefault(c.get("stage", ""), []).append(c["control_id"])
        stages = load_register("lifecycle")
        fill(
            self.lifecycle,
            [
                [
                    s["stage"],
                    s["main_control"],
                    s["owner"],
                    s["evidence"],
                    ", ".join(at_stage.get(s["stage"], [])),
                ]
                for s in stages
            ],
        )
        fit(self.lifecycle, [110, 300, 220, 220, 0])
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
        fill(
            self.matrix,
            [
                [
                    m["responsibility"],
                    *(
                        _DUTY.get(m[k].strip(), m[k])
                        for k in ("provider", "deployer", "technical_security_owner")
                    ),
                ]
                for m in load_register("responsibilities")
            ],
        )
        fit(self.matrix, [0, 250, 230, 210])
        self.inner.setTabText(self.inner.indexOf(self.controls), f"Controls ({len(controls)})")
        self.inner.setTabText(self.inner.indexOf(self.risks), f"Risks ({len(risks)})")

    def _fill_compliance(self) -> None:
        overview = self.session.attempt(
            self, lambda: self.sv.compliance.overview(actor_id=self.actor), quiet=True
        )
        if overview is None:
            return
        self._overview = overview
        total = len(overview.requirements)
        met = overview.count("met") + overview.count("software")
        waiting = overview.count("waiting") + overview.count("review_due")
        records = sum(1 for a in overview.actions if a.state in ("waiting", "review_due"))
        self.headline.setText(f"<b>{met} of {total} requirements are met.</b>")
        self.waiting_note.setText(
            f"The other {waiting} need something only your organisation can do, as well as what "
            f"the software does: {records} record(s) in all, such as a classification, an "
            "assessment or training. Each requirement turns to met once its records are made."
            if waiting
            else "Nothing is waiting for your organisation."
        )
        self.to_record.setVisible(bool(waiting))
        fill(
            self.requirements,
            [
                [
                    r.requirement_id,
                    r.instrument,
                    r.reference,
                    r.requirement,
                    r.who,
                    plain.state(r.state),
                    "; ".join(a.action.title for a in r.outstanding) or "Nothing",
                    r.how_met,
                ]
                for r in overview.requirements
            ],
            ids=[r.requirement_id for r in overview.requirements],
            state_columns=[5],
        )
        fit(self.requirements, [72, 140, 170, 340, 220, 210, 340, 0])
        for r in range(self.requirements.rowCount()):
            item = self.requirements.item(r, 5)
            if item is not None:
                item.setToolTip(glossary.tooltip(item.text()))
        if not self.requirements.selectedItems() and self.requirements.rowCount():
            first_waiting = next(
                (i for i, r in enumerate(overview.requirements) if r.outstanding), 0
            )
            self.requirements.selectRow(first_waiting)
        self._actions = {a.action.action_id: a.action for a in overview.actions}
        fill(
            self.org_actions,
            [
                [
                    f"{a.action.action_id} {a.action.title}",
                    a.action.what_to_do,
                    ", ".join(a.action.requirement_ids),
                    _WHO.get(a.action.owner, a.action.owner),
                    _ACTION_STATE.get(a.state, plain.state(a.state)),
                    a.detail,
                ]
                for a in overview.actions
            ],
            ids=[a.action.action_id for a in overview.actions],
            state_columns=[4],
        )
        fit(self.org_actions, [300, 360, 150, 75, 95, 0])
        waiting = sum(1 for a in overview.actions if a.state in ("waiting", "review_due"))
        self.inner.setTabText(
            self.inner.indexOf(self._actions_page),
            f"Organisation actions ({waiting} to do)",
        )
        self.inner.setTabText(
            0,
            f"Requirements ({overview.count('met') + overview.count('software')} of "
            f"{len(overview.requirements)} met)",
        )

    def _requirement_chosen(self) -> None:
        rid = selected_id(self.requirements)
        overview = getattr(self, "_overview", None)
        found = next(
            (r for r in (overview.requirements if overview else []) if r.requirement_id == rid),
            None,
        )
        self._needed = ""
        if found is None:
            self.requirement_detail.setText(
                "Click a requirement above to see what it asks for, what the software already "
                "does about it, and what your organisation still has to record."
            )
            self.record_needed.setVisible(False)
            return
        outstanding = found.outstanding
        self._needed = outstanding[0].action.action_id if outstanding else ""
        self.record_needed.setVisible(bool(outstanding))
        to_do = "".join(
            f"<li><b>{a.action.title}</b> ({a.action.action_id}): {a.action.what_to_do}</li>"
            for a in outstanding
        )
        done = "".join(
            f"<li>{a.action.title}: {a.detail}</li>" for a in found.actions if a not in outstanding
        )
        self.requirement_detail.setText(
            f"<b>{found.instrument}, {found.reference}.</b> {found.requirement}<br><br>"
            f"<b>What the software does:</b> {found.how_met}"
            + (
                f"<br><br><b>Still to be recorded by your organisation:</b><ul>{to_do}</ul>"
                if to_do
                else "<br><br><b>Nothing more is needed from your organisation.</b>"
            )
            + (f"<b>Already recorded:</b><ul>{done}</ul>" if done else "")
        )

    def _show_actions(self) -> None:
        self.inner.setCurrentWidget(self._actions_page)

    def _record_needed(self) -> None:
        """Take the person to the record this requirement is waiting for, selected."""
        if not getattr(self, "_needed", ""):
            return
        self._show_actions()
        for r in range(self.org_actions.rowCount()):
            item = self.org_actions.item(r, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == self._needed:
                self.org_actions.selectRow(r)
                self.org_actions.scrollToItem(item)
                return

    def _fill_checks(self) -> None:
        latest = self.sv.checks.latest()
        if latest is None:
            self.check_state.setText("The routine checks have not run yet.")
            fill(self.check_results, [])
            self._results = []
            return
        results = (
            self.session.attempt(
                self, lambda: self.sv.checks.for_viewer(latest, actor_id=self.actor), quiet=True
            )
            or []
        )
        self._results = results
        when = latest.finished_at or latest.started_at
        self.check_state.setText(
            f"<b style='color:{theme.colour_for(latest.state)}'>{latest.headline}</b> "
            f"<span style='color:{theme.MUTED}'>Last run {when:%d %b %Y %H:%M} UTC by "
            f"{latest.actor_id}.</span>"
        )
        fill(
            self.check_results,
            [[r.title, plain.check_state(r.state), r.summary] for r in results],
            ids=[r.check_id for r in results],
            state_columns=[1],
        )
        fit(self.check_results, [240, 140, 0])

    def _check_chosen(self) -> None:
        chosen = selected_id(self.check_results)
        result = next((r for r in getattr(self, "_results", []) if r.check_id == chosen), None)
        if result is None:
            self.check_detail.setText("")
            return
        items = "".join(f"<li>{i.text}</li>" for i in result.items[:40])
        acted = "".join(f"<li>{a}</li>" for a in result.acted)
        self.check_detail.setText(
            f"{result.summary}"
            + (f"<br><b>What to do:</b> {result.what_to_do}" if result.what_to_do else "")
            + (f"<ul>{items}</ul>" if items else "")
            + (f"<b>What the check did:</b><ul>{acted}</ul>" if acted else "")
        )

    def _fill_register_of_matters(self) -> None:
        if not self.sv.ctx.authorizer().bindings.can(self.actor, "audit.read"):
            fill(self.register, [["Overseeing every matter needs the auditor, governance or "
                                  "legal administrator role.", "", "", "", "", "", ""]])  # fmt: skip
            return
        rows = (
            self.session.attempt(self, lambda: self.sv.matters.register(self.actor), quiet=True)
            or []
        )
        fill(
            self.register,
            [
                [
                    r["name"],
                    str(r["profile"]).replace("_", " "),
                    r["jurisdiction"],
                    plain.state(str(r["status"])),
                    r["people"],
                    plain.state(str(r["last_run"])) if r["last_run"] else "none",
                    r["open_holds"],
                ]
                for r in rows
            ],
            state_columns=[3, 5],
        )
        fit(self.register, [0, 160, 100, 90, 70, 170, 90])

    def _fill_incidents(self) -> None:
        incidents = (
            self.session.attempt(
                self,
                lambda: self.sv.incidents.list(self.mid, actor_id=self.actor),
                quiet=True,
            )
            if self.mid and self.session.may("matter.read")
            else []
        ) or []
        now = datetime.now(timezone.utc)

        def reporting(i) -> str:  # type: ignore[no-untyped-def]
            if i.reported_at:
                return f"reported {i.reported_at:%Y-%m-%d} ({i.report_reference})"
            if i.reportable is False:
                return f"not reportable ({i.report_decided_by})"
            deadline = reporting_deadline(i)
            if deadline is None:
                return "—"
            days = (deadline - now).days
            return (
                f"OVERDUE since {deadline:%Y-%m-%d}"
                if days < 0
                else f"decide by {deadline:%Y-%m-%d} ({days} days)"
            )

        fill(
            self.incidents,
            [
                [
                    plain.short_id(i.incident_id),
                    plain.state(i.status),
                    i.severity.value,
                    i.category.replace("_", " "),
                    i.detail,
                    reporting(i),
                ]
                for i in incidents
            ],
            ids=[i.incident_id for i in incidents],
            state_columns=[1, 2],
        )
        fit(self.incidents, [80, 70, 80, 220, 0, 230])
        self.inner.setTabText(
            self.inner.indexOf(self._incidents_page),
            f"Incidents ({sum(1 for i in incidents if i.status == 'open')} open)",
        )

    # ── recording the organisation's work ────────────────────────────────────
    def _chosen_action(self) -> OrganisationAction | None:
        return self._actions.get(selected_id(self.org_actions))

    def _record(self) -> None:
        action = self._chosen_action()
        if action is None:
            QMessageBox.information(self, "Organisation actions", "Choose an action first.")
            return
        kind = action.evidence
        if kind == "training":
            self._training()
        elif kind == "evaluation":
            self._evaluate()
        elif kind == "document":
            self._sign_off(action)
        elif kind == "retention":
            self._retention()
        elif kind == "form":
            self._form(action)
        elif kind == "attestation":
            self._attest(action)
        elif kind == "registration":
            self._registration(action)

    def _form(self, action: OrganisationAction) -> None:
        dialog = _Dialog(
            self,
            template_title(action.template),
            f"<b>{action.action_id} {action.title}</b><br>{action.what_to_do}<br>"
            "Every question must be answered. Who recorded it and when is added for you.",
        )
        answers: dict[str, QPlainTextEdit] = {}
        for field_ in action.form:
            box = QPlainTextEdit()
            box.setMaximumHeight(70)
            answers[field_.key] = box
            caption = label(field_.label, wrap=True)
            caption.setMaximumWidth(260)
            dialog.form.addRow(caption, box)
        notes = QLineEdit()
        notes.setPlaceholderText("Where the signed copy is kept, if anywhere else")
        dialog.form.addRow("Reference", notes)
        if dialog.ok():
            self.session.decide(
                self,
                f"record '{action.title}'",
                lambda: self.sv.compliance.record(
                    action.action_id,
                    actor_id=self.actor,
                    answers={k: w.toPlainText() for k, w in answers.items()},
                    reference=notes.text(),
                ),
            )

    def _attest(self, action: OrganisationAction) -> None:
        dialog = _Dialog(
            self,
            action.title,
            f"<b>{action.action_id} {action.title}</b><br>{action.what_to_do}",
        )
        confirm = QCheckBox("I confirm this statement")
        statement = label(f"“{action.statement}”", wrap=True)
        notes = QPlainTextEdit()
        notes.setMaximumHeight(90)
        reference = QLineEdit()
        dialog.form.addRow(statement)
        dialog.form.addRow(confirm)
        dialog.form.addRow("Notes", notes)
        dialog.form.addRow("Reference", reference)
        if dialog.ok():
            self.session.decide(
                self,
                f"confirm '{action.title}'",
                lambda: self.sv.compliance.record(
                    action.action_id,
                    actor_id=self.actor,
                    confirmed=confirm.isChecked(),
                    notes=notes.toPlainText(),
                    reference=reference.text(),
                ),
            )

    def _registration(self, action: OrganisationAction) -> None:
        number = QLineEdit()
        notes = ReasonDialog.ask(
            self,
            action.title,
            f"{action.what_to_do} Give the registration number and when it was registered.",
            extra=[("Registration number", number)],
            minimum=0,
            placeholder="Notes (optional)",
        )
        if notes is not None:
            self.session.decide(
                self,
                "record the registration",
                lambda: self.sv.compliance.record(
                    action.action_id, actor_id=self.actor, reference=number.text(), notes=notes
                ),
            )

    def _not_applicable(self) -> None:
        action = self._chosen_action()
        if action is None:
            return
        reason = ReasonDialog.ask(
            self,
            "It does not apply",
            f"Why does “{action.title}” not apply to this deployment? This is recorded in your "
            "name and reviewed again when its date comes.",
        )
        if reason:
            self.session.decide(
                self,
                f"record that '{action.title}' does not apply",
                lambda: self.sv.compliance.record(
                    action.action_id, actor_id=self.actor, not_applicable=True, notes=reason
                ),
            )

    def _training(self) -> None:
        people = QComboBox()
        for user in self.sv.users.directory(self.actor):
            if user.active:
                people.addItem(f"{user.display_name} ({user.user_id})", user.user_id)
        course = QLineEdit("AI literacy and the instructions for use")
        done = QDateEdit(QDate.currentDate())
        done.setCalendarPopup(True)
        expires = QDateEdit(QDate.currentDate().addYears(1))
        expires.setCalendarPopup(True)
        dialog = _Dialog(
            self,
            "Record training",
            "Record training a person has completed. Someone who works on matters without a "
            "current record is reported by the routine checks.",
        )
        for caption, widget in (
            ("Person", people),
            ("Training", course),
            ("Completed on", done),
            ("Valid until", expires),
        ):
            dialog.form.addRow(caption, widget)
        if dialog.ok():
            self.session.decide(
                self,
                "record this training",
                lambda: self.sv.compliance.record_training(
                    actor_id=self.actor,
                    user_id=str(people.currentData()),
                    course=course.text(),
                    completed_on=_pydate(done),
                    expires_on=_pydate(expires),
                ),
            )

    def _retention(self) -> None:
        current = self.sv.compliance.retention()
        audit = QSpinBox()
        audit.setRange(MIN_AUDIT_RETENTION_DAYS, 36500)
        audit.setValue(current.audit_days if current else 3653)
        closed = QSpinBox()
        closed.setRange(0, 36500)
        closed.setValue(current.closed_matter_days if current else 2190)

        def kind(value: int | None, suggested: int | None, unset: str) -> QSpinBox:
            box = QSpinBox()
            box.setRange(-1, 36500)
            box.setSpecialValueText(unset)  # shown at -1: not set
            chosen = value if value is not None else suggested
            box.setValue(-1 if chosen is None else chosen)
            return box

        same = "as long as the papers"
        analysis = kind(current.analysis_days if current else None, None, same)
        reports = kind(current.reports_days if current else None, None, same)
        evidence = kind(current.evidence_days if current else None, 3650, same)
        record = kind(current.record_days if current else None, 3650, "no end")
        idle = QSpinBox()
        idle.setRange(0, 36500)
        idle.setSpecialValueText("never")
        idle.setValue(current.inactive_matter_days if current else 365)
        dialog = _Dialog(
            self,
            "Retention",
            "How long each kind of information is kept. The audit trail is kept at least six "
            "months and is never shortened. From a case's closing, each kind of its content is "
            "kept for its own period, archived under its own key, and deleted (its key destroyed) "
            "by the routine checks when that period ends, unless a preservation hold keeps it. "
            "The decision record is kept at least as long as anything it accounts for.",
        )
        dialog.form.addRow("Keep the audit trail (days)", audit)
        dialog.form.addRow("A closed case's papers (days)", closed)
        dialog.form.addRow("Its analysis (days)", analysis)
        dialog.form.addRow("Its reports (days)", reports)
        dialog.form.addRow("Its evidence packs (days)", evidence)
        dialog.form.addRow("Its decision record (days)", record)
        dialog.form.addRow("Report an open matter idle for (days)", idle)

        def given(box: QSpinBox) -> int | None:
            return None if box.value() < 0 else box.value()

        if dialog.ok():
            self.session.decide(
                self,
                "set the retention periods",
                lambda: self.sv.compliance.set_retention(
                    actor_id=self.actor,
                    audit_days=audit.value(),
                    closed_matter_days=closed.value(),
                    inactive_matter_days=idle.value(),
                    analysis_days=given(analysis),
                    reports_days=given(reports),
                    evidence_days=given(evidence),
                    record_days=given(record),
                ),
            )

    def _evaluate(self) -> None:
        phrase = self.session.ask_passphrase(self, "run the accuracy evaluation in your name")
        if phrase is None:
            return

        def work() -> object:
            self.sv.users.confirm(self.actor, phrase)
            with authn.stepped_up():
                return self.sv.compliance.run_evaluation(actor_id=self.actor)

        self.session.background(
            "Running the accuracy evaluation…",
            work,
            self._evaluated,
            self._failed,
        )

    def _failed(self, exc: Exception) -> None:
        QMessageBox.warning(self, "Could not complete", str(exc))

    def _evaluated(self, record: object) -> None:
        QMessageBox.information(self, "Evaluation", str(getattr(record, "summary", record)))
        self.session.notify()

    def _generate(self) -> None:
        kind = QComboBox()
        kind.addItem("Technical documentation (Annex IV)", "annex_iv")
        kind.addItem("EU declaration of conformity", "declaration")
        dialog = _Dialog(
            self,
            "Draft a document",
            "The system drafts it from its own records and marks what only the provider can "
            "state. Complete it, then sign it off by its fingerprint with “Record it…”.",
        )
        dialog.form.addRow("Document", kind)
        if not dialog.ok():
            return
        made = self.session.attempt(
            self,
            lambda: self.sv.compliance.generate(kind.currentData(), actor_id=self.actor),
            quiet=True,
        )
        if made:
            path, digest = made
            self._last_document["OA-05" if kind.currentData() == "annex_iv" else "OA-12"] = digest
            QMessageBox.information(
                self,
                "Drafted",
                f"Saved to:\n{path}\n\nSHA-256 fingerprint:\n{digest}",
            )

    def _sign_off(self, action: OrganisationAction) -> None:
        digest = QLineEdit(self._last_document.get(action.action_id, ""))
        digest.setPlaceholderText("The SHA-256 fingerprint of the completed document")
        notes = ReasonDialog.ask(
            self,
            f"Sign off: {action.title}",
            f"“{action.statement}” Give the fingerprint of the document you are signing off "
            "(draft it first with “Draft the document…”).",
            extra=[("SHA-256", digest)],
            minimum=0,
            placeholder="Notes (optional)",
        )
        if notes is not None:
            self.session.decide(
                self,
                f"sign off '{action.title}'",
                lambda: self.sv.compliance.sign_off(
                    action.action_id, actor_id=self.actor, sha256=digest.text(), notes=notes
                ),
            )

    # ── checks, monitoring, incidents ────────────────────────────────────────
    def _run_checks(self) -> None:
        self.session.background(
            "Running the routine checks…",
            lambda: self.sv.checks.run(actor_id=self.actor),
            lambda _run: self.session.notify(),
            self._failed,
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
            [f"Runs — {plain.state(k).lower()}", v]
            for k, v in sorted(snapshot.runs_by_status.items())
        ]
        rows += [
            [f"Reviews — {plain.state(k).lower()}", v] for k, v in sorted(snapshot.reviews.items())
        ]
        rows += [
            [f"Holds raised — {plain.hold_reason(k).lower()}", v]
            for k, v in sorted(snapshot.holds_by_reason.items())
        ]
        rows += [
            [
                f"Checks — {plain.check_name(k.split(':')[0])} → {plain.state(k.split(':')[-1]).lower()}",
                v,
            ]
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

    # ── deployment authorisations ────────────────────────────────────────────
    def _fill_deployments(self) -> None:
        found = self.session.attempt(
            self, lambda: self.sv.deployment.list(actor_id=self.actor), quiet=True
        )
        rows = found or []
        today = date.today()
        fill(
            self.deployments,
            [
                [
                    a.authorisation_id[-8:],
                    a.status,
                    "yes"
                    if a.status == "approved" and a.effective_from <= today <= a.expires_on
                    else f"{a.effective_from} → {a.expires_on}",
                    ", ".join(a.jurisdictions),
                    ", ".join(a.profiles),
                    a.provider_signed_by or "—",
                    a.deployer_signed_by or "—",
                    a.intended_use,
                ]
                for a in rows
            ],
            ids=[a.authorisation_id for a in rows],
        )

    def _propose_deployment(self) -> None:
        dialog = _DeploymentDialog(self, self.sv.ctx.jurisdictions.codes())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.session.decide(
            self,
            "propose a deployment authorisation",
            lambda: self.sv.deployment.propose(actor_id=self.actor, **values),
        )
        self._fill_deployments()

    def _sign_deployment(self, as_lead: str) -> None:
        authorisation_id = selected_id(self.deployments)
        if not authorisation_id:
            return
        self.session.decide(
            self,
            f"sign this deployment authorisation as the {as_lead} lead",
            lambda: self.sv.deployment.sign(authorisation_id, actor_id=self.actor, as_lead=as_lead),
        )
        self._fill_deployments()

    def _revoke_deployment(self) -> None:
        authorisation_id = selected_id(self.deployments)
        if not authorisation_id:
            return
        reason = ReasonDialog.ask(
            self,
            "Revoke the authorisation",
            "Real matters' work stops at once until another is approved. Why is it revoked?",
        )
        if reason:
            self.session.decide(
                self,
                "revoke this deployment authorisation",
                lambda: self.sv.deployment.revoke(
                    authorisation_id, actor_id=self.actor, reason=reason
                ),
            )
            self._fill_deployments()

    # ── incidents: when known, who owns it ───────────────────────────────────
    def _aware(self) -> None:
        incident_id = selected_id(self.incidents)
        if not incident_id:
            return
        when = QDateTimeEdit(QDateTime.currentDateTime())
        when.setCalendarPopup(True)
        happened = QDateTimeEdit(QDateTime.currentDateTime())
        happened.setCalendarPopup(True)
        known_happened = QCheckBox("I know when it happened")
        basis = ReasonDialog.ask(
            self,
            "When it became known",
            "The reporting deadline (Art. 73) counts from when the provider or deployer became "
            "aware, which may be before it was entered here. It may be moved earlier later, "
            "never later. How did it become known?",
            extra=[("Became known on", when), ("", known_happened), ("It happened on", happened)],
        )
        if basis:
            aware = _utc(when)
            occurred = _utc(happened) if known_happened.isChecked() else None
            self.session.decide(
                self,
                "record when the incident became known",
                lambda: self.sv.incidents.record_awareness(
                    self.mid, incident_id, actor_id=self.actor, aware_at=aware, basis=basis,
                    occurred_at=occurred,
                ),
            )  # fmt: skip

    def _assign(self) -> None:
        incident_id = selected_id(self.incidents)
        matter = self.session.matter
        if not incident_id or matter is None:
            return
        people = sorted({matter.owner_user_id, *matter.authorised_user_ids})
        owner, backup = QComboBox(), QComboBox()
        owner.addItems(people)
        backup.addItems(people)
        if len(people) > 1:
            backup.setCurrentIndex(1)
        dialog = QDialog(self)
        dialog.setWindowTitle("Owner and stand-in")
        form = QFormLayout(dialog)
        form.addRow(label(
            "The owner decides on the incident; the stand-in is told when half the time to "
            "report is gone undecided. Two different people who may manage incidents.",
            wrap=True,
        ))  # fmt: skip
        form.addRow("Owner", owner)
        form.addRow("Stand-in", backup)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.session.attempt(
                self,
                lambda: self.sv.incidents.assign(
                    self.mid, incident_id, actor_id=self.actor,
                    owner=owner.currentText(), backup=backup.currentText(),
                ),
            )  # fmt: skip

    def _decide_reporting(self) -> None:
        incident_id = selected_id(self.incidents)
        if not incident_id:
            return
        reportable = QComboBox()
        reportable.addItem("Reportable to the market surveillance authority", True)
        reportable.addItem("Not reportable", False)
        kind = QComboBox()
        for code, days in REPORTING_DAYS.items():
            kind.addItem(
                {
                    "general": "A serious incident",
                    "death": "A person's death",
                    "widespread": "A widespread infringement or critical-infrastructure disruption",
                }[code]
                + f" ({days} days)",
                code,
            )
        reported = QCheckBox("It has been reported")
        when = QDateEdit(QDate.currentDate())
        when.setCalendarPopup(True)
        reference = QLineEdit()
        reason = ReasonDialog.ask(
            self,
            "Decide on reporting (EU AI Act Art. 73)",
            "Is this a serious incident that must be reported? Your decision and reasons are "
            "recorded in your name.",
            extra=[
                ("Decision", reportable),
                ("Kind", kind),
                ("", reported),
                ("Reported on", when),
                ("Authority's reference", reference),
            ],
        )
        if reason:
            on = _pydate(when)
            self.session.decide(
                self,
                "record the reporting decision",
                lambda: self.sv.incidents.decide_reporting(
                    self.mid,
                    incident_id,
                    actor_id=self.actor,
                    reportable=bool(reportable.currentData()),
                    reason=reason,
                    serious_kind=str(kind.currentData()),
                    reported_on=datetime(on.year, on.month, on.day, tzinfo=timezone.utc)
                    if reported.isChecked()
                    else None,
                    reference=reference.text(),
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


class _DeploymentDialog(QDialog):
    """What a deployment authorisation is to approve, and the evidence documents it rests on."""

    def __init__(self, parent: QWidget, codes: list[str]) -> None:
        from eli_legal.application.deployment_service import EVIDENCE

        super().__init__(parent)
        self.setWindowTitle("Propose a deployment authorisation")
        self.setMinimumWidth(720)
        form = QFormLayout(self)
        self.use = QPlainTextEdit()
        self.use.setPlaceholderText("What it is to be used for, by whom, on which matters")
        self.use.setMaximumHeight(80)
        self.provider, self.deployer = QLineEdit(), QLineEdit()
        self.codes = QLineEdit(", ".join(codes))
        self.kinds = {
            code: QCheckBox(label_)
            for code, label_ in (
                ("adjudicator", "Court, tribunal or arbitral tribunal"),
                ("neutral_facilitator", "Mediator or conciliator"),
                ("party_representative", "Party's legal representative"),
            )
        }
        self.start, self.end = (
            QDateEdit(QDate.currentDate()),
            QDateEdit(QDate.currentDate().addYears(1)),
        )
        for widget in (self.start, self.end):
            widget.setCalendarPopup(True)
        form.addRow("Intended use", self.use)
        form.addRow("Provider", self.provider)
        form.addRow("Deployer", self.deployer)
        form.addRow("Legal systems", self.codes)
        kinds = QWidget()
        line = QHBoxLayout(kinds)
        for box in self.kinds.values():
            line.addWidget(box)
        form.addRow("Kinds of matter", kinds)
        form.addRow("In force from", self.start)
        form.addRow("Expires on", self.end)
        form.addRow(label("<b>Evidence</b>: each the document itself, copied and recorded by its "
                          "fingerprint when proposed.", wrap=True))  # fmt: skip
        self.evidence: dict[str, QLineEdit] = {}
        for key, what in EVIDENCE.items():
            path = QLineEdit()
            path.setPlaceholderText(what)
            choose = button("Choose…", lambda _=False, p=path: self._choose(p))
            holder = QWidget()
            line = QHBoxLayout(holder)
            line.setContentsMargins(0, 0, 0, 0)
            line.addWidget(path, 1)
            line.addWidget(choose)
            self.evidence[key] = path
            form.addRow(what.capitalize(), holder)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _choose(self, target: QLineEdit) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(self, "The evidence document")
        if path:
            target.setText(path)

    def values(self) -> dict[str, Any]:
        return {
            "intended_use": self.use.toPlainText(),
            "provider": self.provider.text(),
            "deployer": self.deployer.text(),
            "jurisdictions": [c.strip() for c in self.codes.text().split(",") if c.strip()],
            "profiles": [k for k, box in self.kinds.items() if box.isChecked()],
            "effective_from": _pydate(self.start),
            "expires_on": _pydate(self.end),
            "evidence": {k: w.text().strip() for k, w in self.evidence.items()},
        }
