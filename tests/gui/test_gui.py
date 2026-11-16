"""The desktop application, driven headlessly. No test harness: the window is signed in to as a
real person would, so every action is checked exactly as it is in use."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", reason="the desktop application needs PySide6")
from PySide6 import QtCore  # noqa: E402
from PySide6.QtWidgets import QInputDialog, QMessageBox  # noqa: E402

from eli_legal.application.matter_service import hash_passphrase  # noqa: E402
from eli_legal.application.services import build_services  # noqa: E402
from eli_legal.demo import build_demo_workspace  # noqa: E402
from eli_legal.demo_run import ADMIN, ARBITRATOR, SECRETARY, demo_settings, setup_demo  # noqa: E402
from eli_legal.domain.enums import ReviewDecision  # noqa: E402
from eli_legal.domain.errors import AuthenticationFailed, SecondFactorRequired  # noqa: E402
from eli_legal.governance.registers import load_register  # noqa: E402
from eli_legal.gui.app import (  # noqa: E402
    FirstRunDialog,
    SignInDialog,
    _ensure_key,
    create_application,
)
from eli_legal.gui.main_window import MainWindow  # noqa: E402
from eli_legal.gui.session import Session  # noqa: E402
from eli_legal.gui.tabs.agents_tab import AgentsTab  # noqa: E402
from eli_legal.gui.tabs.audit_tab import AuditTab  # noqa: E402
from eli_legal.gui.tabs.chat_tab import ChatTab  # noqa: E402
from eli_legal.gui.tabs.documents_tab import DocumentsTab  # noqa: E402
from eli_legal.gui.tabs.findings_tab import FindingsTab  # noqa: E402
from eli_legal.gui.tabs.governance_tab import GovernanceTab  # noqa: E402
from eli_legal.gui.tabs.review_tab import ReviewTab  # noqa: E402
from eli_legal.gui.tabs.settings_tab import SettingsTab  # noqa: E402
from eli_legal.gui.tabs.workflow_tab import WorkflowTab  # noqa: E402
from eli_legal.gui.widgets import ReasonDialog  # noqa: E402
from eli_legal.security import authn, totp  # noqa: E402

PHRASE = {
    ARBITRATOR: "arbitrator passphrase",
    SECRETARY: "secretary passphrase",
    ADMIN: "administrator passphrase",
}


@pytest.fixture(scope="module")
def qt():
    return create_application([])


class Desk:
    """A signed-in window plus the dialogs it would have shown."""

    def __init__(self, qt, sv, mid, user):
        self.qt, self.sv, self.mid = qt, sv, mid
        self.warnings: list[str] = []
        self.passphrase = PHRASE[user]
        self.session = Session(sv)
        self.session.sign_in(user, PHRASE[user])
        self.window = MainWindow(self.session)
        self.window.resize(1400, 900)
        self.window.show()
        qt.processEvents()

    def page(self, kind):
        page = self.window.show_page(kind)
        self.qt.processEvents()
        return page

    def settle(self):
        assert self.session.wait_for_background()
        for _ in range(5):
            self.qt.processEvents()


@pytest.fixture
def desk(qt, tmp_path, monkeypatch):
    workspace = build_demo_workspace(tmp_path / "demo")
    # The schedule is driven by hand in tests, so nothing runs behind a test's back.
    settings = demo_settings(tmp_path, workspace, checks_every_hours=0)
    sv = build_services(settings, install_network_guard=False)
    mid = setup_demo(sv, workspace)
    for user, phrase in PHRASE.items():
        if user == ADMIN:  # the first administrator's passphrase comes from set-up, not from anyone
            admin = sv.ctx.user(ADMIN)
            admin.passphrase_hash = hash_passphrase(phrase)
            sv.ctx.store.put_user(admin)
        else:
            sv.users.set_passphrase(actor_id=ADMIN, user_id=user, new=phrase)
    authn.remove_harness()  # from here on, only a real sign-in counts
    authn.clear()
    made: list[Desk] = []

    def open_as(user=ARBITRATOR) -> Desk:
        desk = Desk(qt, sv, mid, user)
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: desk.warnings.append(str(a[2])))
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: (desk.passphrase, True))
        monkeypatch.setattr(
            ReasonDialog,
            "ask",
            classmethod(lambda cls, *a, **k: "Decided for the purposes of this test."),
        )
        made.append(desk)
        return desk

    yield open_as
    for desk in made:
        desk.session._jobs.clear()
        desk.window.close()
    qt.processEvents()


def test_the_application_has_the_specialised_tabs_and_nothing_else(desk):
    d = desk()
    titles = [d.window.tabs.tabText(i) for i in range(d.window.tabs.count())]
    for wanted in (
        "Home",
        "Matter",
        "Evidence",
        "Chat",
        "DAG",
        "Agents",
        "Findings",
        "Review",
        "Audit Trail",
        "Governance",
        "Sources",
        "Laws & Standards",
        "Settings",
        "How to use",
        "Start a new case",
    ):
        assert any(wanted in t for t in titles), wanted
    assert len(titles) == 15
    for unwanted in (
        "Images",
        "Screen",
        "IDE",
        "Coding",
        "Proactive",
        "Habits",
        "Self-Improve",
        "World",
        "Files",
    ):
        assert not any(unwanted in t for t in titles), "no general-assistant tab belongs here"
    chips = " ".join(c.text() for c in d.window.chips.values())
    assert "Audit verified" in chips and "Aoife Keane" in chips and "Arbitrator" in chips
    assert "Checks not run yet" in chips


def test_sign_in_needs_the_passphrase_and_signing_out_ends_the_identity(desk, qt):
    d = desk()
    with pytest.raises(AuthenticationFailed):
        Session(d.sv).sign_in(ARBITRATOR, "not the passphrase")
    assert authn.current().user_id == ARBITRATOR and authn.current().method == "gui-passphrase"
    dialog = SignInDialog(d.sv)
    assert ARBITRATOR in [dialog.user.itemText(i) for i in range(dialog.user.count())]
    d.window.close()
    qt.processEvents()
    assert authn.current() is None
    with pytest.raises(AuthenticationFailed):
        d.sv.matters.get(d.mid, ARBITRATOR)


def test_a_run_started_from_the_dag_tab_executes_in_the_background_and_every_tab_fills(desk):
    d = desk()
    assert d.page(DocumentsTab).docs.rowCount() == 7
    dag = d.page(WorkflowTab)
    assert set(dag.dag.nodes) == {s.id for s in d.sv.ctx.workflow.steps}
    dag._start()
    d.settle()
    assert d.session.run.status.value == "held"
    assert dag.dag.nodes["current_law_check"].status == "ok"
    assert dag.dag.nodes["human_review"].status == "pending" and "6 holds open" in dag.state.text()
    dag._show_step("current_law_check")
    assert (
        "Current-law citator" in dag.step_title.text()
        and '"failed": 2' in dag.outputs.toPlainText()
    )
    agents = d.page(AgentsTab)
    agents._show("analysis")
    assert "state or imply an outcome" in agents.body.text() and "C-13" in agents.body.text()
    findings = d.page(FindingsTab)
    assert findings.list.rowCount() > 25
    findings.status.setCurrentIndex(findings.status.findData("held"))
    assert findings.list.rowCount() == 4
    findings.list.selectRow(0)
    assert (
        "overruled" in findings.why.text()
        or "not found" in findings.why.text()
        or "last confirmed" in findings.why.text()
    )
    review = d.page(ReviewTab)
    assert review.holds.rowCount() == 6 and review.tasks.rowCount() == 5
    assert "PRACTICE MATTER — DRAFT, NOT FOR RELIANCE" in review.report.toPlainText()
    assert review.limits.count() >= 4
    audit = d.page(AuditTab)
    assert audit.events.rowCount() > 40 and "chain verified" in audit.chain.text()
    proofs = {audit.events.item(r, 4).text() for r in range(audit.events.rowCount())}
    assert any("desktop sign-in with passphrase · gui-passphrase" in p for p in proofs), (
        "the ledger shows the run was done by a signed-in person"
    )
    governance = d.page(GovernanceTab)
    assert governance.requirements.rowCount() == len(load_register("requirements"))
    assert governance.controls.rowCount() == len(load_register("controls"))
    assert not d.warnings, d.warnings


def test_chat_answers_from_the_matter_and_refuses_to_decide(desk):
    d = desk()
    d.sv.runs.start(d.mid, actor_id=ARBITRATOR)
    d.session.set_matter(d.mid)
    chat = d.page(ChatTab)
    chat._ask("When did the Respondent receive the notice of termination?")
    text = chat.transcript.toPlainText()
    assert (
        "did not receive the notice of 28 April 2023 until 2 May 2023" in text
        and "02_defence.txt" in text
    )
    assert chat.sources.rowCount() >= 3
    chat._ask("Who should win this case?")
    assert "do not say who should succeed" in chat.transcript.toPlainText()
    chat._ask("/holds")
    assert "A check failed" in chat.transcript.toPlainText()


def test_the_administrator_sees_the_machine_and_how_a_model_would_be_placed_before_choosing(
    desk, tmp_path, monkeypatch
):
    import sys
    import types
    from dataclasses import replace

    from eli_legal.adapters.inference import gguf, gpu_runtime, hardware
    from tests.gguf_files import dense_model

    card = hardware.Hardware(
        cpu_threads=12,
        ram_gb=32.0,
        available_ram_gb=20.0,
        has_gpu=True,
        gpu_name="Test Card 8G",
        gpu_vendor="nvidia",
        total_vram_mb=8192,
        free_vram_mb=7000,
        vram_measured=True,
    )
    monkeypatch.setattr(hardware, "detect", lambda force=False: replace(card))

    class Llama:
        def __init__(self, **kw):
            self.kw = kw

        def n_ctx(self):
            return self.kw["n_ctx"]

        def create_chat_completion(self, **kw):
            return {"choices": [{"message": {"content": '{"sentences": []}'}}]}

    fake = types.SimpleNamespace(
        Llama=Llama, llama_supports_gpu_offload=lambda: True, __version__="0.0-test"
    )
    monkeypatch.setitem(sys.modules, "llama_cpp", fake)
    monkeypatch.setattr(gguf, "_LOADED", {})
    monkeypatch.setattr(gpu_runtime, "_state", None)
    model = dense_model(tmp_path / "models" / "Seven-B.gguf")

    d = desk(ADMIN)
    d.sv.ctx.settings.models_dirs = str(model.parent)
    settings = d.page(SettingsTab)
    picker = settings.picker
    picker.backend.setCurrentIndex(picker.backend.findData("gguf"))
    picker.refresh_gguf()
    assert (picker.context.text(), picker.gpu.text(), picker.threads.text()) == (
        "automatic",
        "automatic",
        "automatic",
    )
    assert "Test Card 8G: 7000 of 8192 MB free" in picker.machine.text()
    assert "llama.cpp 0.0-test" in picker.machine.text()
    assert "all 29 layers on the graphics card" in picker.placement.text()
    picker.gpu.setValue(0)
    assert picker.placement.text().endswith("processor only.")
    picker.gpu.setValue(-1)
    values = picker.values()
    assert (values["gguf_context"], values["gguf_gpu_layers"]) == (0, -1)

    settings._apply_model()
    assert not d.warnings, d.warnings
    assert d.sv.config.current()["backend"] == "gguf"
    assert "loads at its first use" in settings.model_state.text()
    d.sv.ctx.model.inference.warm()
    settings.refresh()
    assert "all 29 layers on the graphics card" in settings.model_state.text()


def test_a_decision_in_the_application_needs_the_passphrase_again(desk):
    d = desk()
    d.sv.runs.start(d.mid, actor_id=ARBITRATOR)
    d.session.set_matter(d.mid)
    review = d.page(ReviewTab)
    review.holds.selectRow(2)
    d.passphrase = "not my passphrase"
    review._resolve("exclude")
    assert d.warnings == ["That passphrase is not correct. Nothing was recorded."]
    assert len(d.sv.holds.list(d.mid, d.session.run_id, actor_id=ARBITRATOR)) == 6
    d.passphrase = PHRASE[ARBITRATOR]
    review.holds.selectRow(2)
    review._resolve("exclude")
    assert len(d.sv.holds.list(d.mid, d.session.run_id, actor_id=ARBITRATOR)) == 5
    resolved = [
        e for e in d.sv.ctx.audit.events(matter_id=d.mid) if e["event_type"] == "hold_resolved"
    ][-1]
    assert (
        resolved["actor_id"] == ARBITRATOR
        and resolved["payload"]["auth"] == "gui-passphrase+step-up"
    )
    review.reasons.setPlainText("Approving for the hearing bundle.")
    review._decide(ReviewDecision.APPROVE)
    assert "only a run awaiting review can be approved" in d.warnings[-1]


def test_the_application_cannot_do_what_the_signed_in_role_cannot(desk):
    d = desk(SECRETARY)
    d.sv.runs.start(d.mid, actor_id=SECRETARY)
    d.session.set_matter(d.mid)
    review = d.page(ReviewTab)
    review.holds.selectRow(0)
    review._resolve("exclude")
    assert "not permitted to perform 'hold.resolve'" in d.warnings[-1]
    settings = d.page(SettingsTab)
    settings._apply_model()
    assert "not permitted to perform 'config.manage'" in d.warnings[-1]
    assert len(d.sv.holds.list(d.mid, d.session.run_id, actor_id=SECRETARY)) == 6


def test_a_second_factor_can_be_set_up_in_the_application_and_is_then_needed(desk, monkeypatch):
    d = desk()
    settings = d.page(SettingsTab)
    assert "Second factor: not set up" in settings.me.text()

    def answer(parent, title, label, *args, **kwargs):
        if "six-digit" in label:  # the code the authenticator would show for the key just issued
            pending = d.sv.ctx.store.auth_state(ARBITRATOR)["totp_pending"]
            assert pending in label
            return totp.code_at(pending, totp.step_at()), True
        return d.passphrase, True

    monkeypatch.setattr(QInputDialog, "getText", answer)
    settings._second_factor()
    assert d.sv.users.has_second_factor(ARBITRATOR) and not d.warnings
    assert "Second factor: set up" in settings.me.text()
    with pytest.raises(SecondFactorRequired):
        Session(d.sv).sign_in(ARBITRATOR, PHRASE[ARBITRATOR])
    fresh = totp.code_at(d.sv.ctx.store.auth_state(ARBITRATOR)["totp_secret"], totp.step_at() + 1)
    assert Session(d.sv).sign_in(ARBITRATOR, PHRASE[ARBITRATOR], fresh).user_id == ARBITRATOR
    outcomes = [e["outcome"] for e in d.sv.ctx.audit.events(matter_id="-")]
    assert "second_factor_enabled" in outcomes and "signed_in_two_factor" in outcomes


def test_first_run_creates_the_key_and_insists_on_a_real_passphrase(qt, tmp_path, monkeypatch):
    from eli_legal.settings import Settings

    settings = Settings(
        _env_file=None,
        audit_key_file=tmp_path / "secrets" / "audit.key",
        db_path=tmp_path / "d" / "x.db",
        data_dir=tmp_path / "m",
        artifacts_dir=tmp_path / "a",
    )
    assert _ensure_key(settings) is True and _ensure_key(settings) is False
    if os.name != "nt":
        assert oct(settings.audit_key_file.stat().st_mode & 0o777) == "0o600"
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(str(a[2])))
    dialog = FirstRunDialog()
    dialog.first.setText("short")
    dialog.second.setText("short")
    dialog._check()
    dialog.first.setText("a long enough passphrase")
    dialog.second.setText("a different passphrase")
    dialog._check()
    assert len(shown) == 2 and dialog.result() == 0
    dialog.second.setText("a long enough passphrase")
    dialog._check()
    assert dialog.result() == 1


def test_home_shows_where_the_matter_stands_and_takes_you_to_the_next_step(desk):
    from eli_legal.gui.tabs.home_tab import HomeTab

    d = desk()
    home = d.page(HomeTab)
    assert home.heading.text() == "Harbour Freight Ltd v Northwind Logistics Ltd"
    assert "Your role on this matter: Lead" in home.role.text()
    assert home.stages.count() == 6
    d.sv.runs.start(d.mid, actor_id=ARBITRATOR)
    d.session.notify()
    d.qt.processEvents()
    first = home.steps.itemAt(0).widget()
    assert "Resolve" in first.findChild(QtWidgets.QLabel).text()
    first.findChild(QtWidgets.QPushButton).click()
    assert isinstance(d.window.tabs.currentWidget(), ReviewTab)
    assert home.work.count() >= 1 and "Harbour Freight" in home.work.item(0).text()


def test_the_wizard_opens_a_matter_with_its_team_reviewers_and_sources(desk):
    from eli_legal.gui.matter_wizard import MatterWizard

    d = desk()
    wizard = MatterWizard(
        d.window,
        actor_id=ARBITRATOR,
        jurisdictions=d.sv.ctx.jurisdictions.codes(),
        default_jurisdiction="XX",
        users=d.sv.users.directory(ARBITRATOR),
        sources=[s for s in d.sv.sources.list() if s.approved],
        frameworks=[s for s in d.sv.frameworks.list(actor_id=ARBITRATOR) if s.usable],
        recommend=lambda profile, code: d.sv.frameworks.recommended(
            profile, code, actor_id=ARBITRATOR
        ),
    )
    wizard.show()
    wizard.next()
    wizard.name.setText("Gantry Marine v Holloway")
    wizard.purpose.setText("Bench memorandum on acceptance of late delivery")
    wizard.jurisdiction.setCurrentText("XX")
    wizard.next()
    wizard.parties.item(0, 0).setText("Gantry Marine Ltd")
    wizard.parties.item(1, 0).setText("Holloway plc")
    wizard.issues.setPlainText("Whether acceptance waived the delay")
    wizard.next()
    secretary = next(
        r for r in range(wizard.team.rowCount()) if SECRETARY in wizard.team.item(r, 0).text()
    )
    wizard.team.item(secretary, 0).setCheckState(QtCore.Qt.CheckState.Checked)
    wizard.next()
    assert wizard.source_list.count() and wizard.law_list.count()
    wizard.next()
    assert "Gantry Marine v Holloway" in wizard.summary.text()
    values = wizard.values()
    assert values["team"][0].matter_role == "case_worker" and values["reviewers"] == [ARBITRATOR]
    matter = d.sv.matters.create(actor_id=ARBITRATOR, **values)
    assert matter.member_roles == {SECRETARY: "case_worker"}
    assert matter.reviewer_user_ids == {ARBITRATOR} and matter.approved_source_ids
    assert [p.name for p in matter.parties] == ["Gantry Marine Ltd", "Holloway plc"]
    wizard.close()


def test_routine_checks_run_on_their_schedule_in_the_application(desk):
    d = desk()
    assert not d.sv.checks.due(), "switched off in these tests: nothing is due on its own"
    d.sv.ctx.settings.checks_every_hours = 24
    assert d.sv.checks.latest() is None and d.sv.checks.due()
    d.window.scheduled_checks()
    d.settle()
    latest = d.sv.checks.latest()
    assert latest is not None and latest.actor_id == "system"
    d.window.refresh()
    assert "Checks" in d.window.chips["checks"].text()
    d.window.scheduled_checks()  # not due again yet: nothing more runs
    d.settle()
    assert d.sv.checks.latest().run_id == latest.run_id


def test_compliance_is_recorded_from_the_governance_page_in_the_persons_name(desk, monkeypatch):
    d = desk()
    d.window.close()  # signs out: the administrator sets up the new person
    with authn.harness("test-harness"):
        d.sv.users.add_user(
            actor_id=ADMIN, user_id="gov.x", display_name="Gov", roles=["governance_officer"]
        )
        d.sv.users.set_passphrase(actor_id=ADMIN, user_id="gov.x", new="governance passphrase")
    monkeypatch.setitem(PHRASE, "gov.x", "governance passphrase")
    g = desk("gov.x")
    governance = g.page(GovernanceTab)
    rows = [
        governance.org_actions.item(r, 0).text() for r in range(governance.org_actions.rowCount())
    ]
    governance.org_actions.selectRow(next(i for i, t in enumerate(rows) if t.startswith("OA-19")))
    governance._not_applicable()
    governance.refresh()
    assert not g.warnings, g.warnings
    record = g.sv.compliance.records("OA-19")[-1]
    assert record.recorded_by == "gov.x" and record.not_applicable
    statuses = {
        r.requirement_id: r.state for r in g.sv.compliance.overview(actor_id="gov.x").requirements
    }
    assert statuses["AIA-22"] == "met"


def test_documents_are_taken_in_file_by_file_and_the_outcome_is_said_plainly(
    desk, tmp_path, monkeypatch
):
    from eli_legal.domain.enums import AccessScope
    from eli_legal.gui.tabs import documents_tab
    from eli_legal.gui.tabs.documents_tab import IntakeDialog

    d = desk()
    letter = tmp_path / "without_prejudice.txt"
    letter.write_text("On 3 May 2023 the Respondent offered €40,000 to settle.\n")
    photo = tmp_path / "scan.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0 not really a photograph")
    told: list[str] = []
    monkeypatch.setattr(documents_tab.QMessageBox, "information", lambda *a, **k: told.append(a[2]))

    def accept(dialog):
        scopes = dialog.grid.cellWidget(0, 3)
        scopes.setCurrentIndex(scopes.findData(AccessScope.PARTY_CONFIDENTIAL.value))
        assert [row["path"] for row in dialog.plan()] == [str(letter), str(photo)]
        return QtWidgets.QDialog.DialogCode.Accepted

    monkeypatch.setattr(IntakeDialog, "exec", accept)
    tab = d.page(DocumentsTab)
    tab._ingest([str(letter), str(photo)])
    assert told and "1 document read." in told[0] and "could not be read" in told[0]
    stored = {doc.filename: doc for doc in d.sv.matters.documents(d.mid, ARBITRATOR)}
    assert stored["without_prejudice.txt"].access_scope is AccessScope.PARTY_CONFIDENTIAL
    assert stored["scan.jpg"].access_scope is AccessScope.ALL_PARTIES


def test_everyone_can_make_everything_larger_and_back(desk, qt):
    """Ctrl and + or -, or Ctrl and the mouse wheel, anywhere: text, tables, sidebar, the map."""
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent

    from eli_legal.gui import zoom

    d = desk()
    control = zoom.current()
    assert control is not None and control.level == 1.0
    findings = d.page(FindingsTab)
    table = findings.findChildren(QtWidgets.QTableWidget)[0]
    row_before = table.verticalHeader().defaultSectionSize()
    nav_before = d.window.nav.width()
    try:
        control.zoom_in()
        control.zoom_in()
        qt.processEvents()
        assert control.level == 1.2
        assert qt.font().pointSizeF() == pytest.approx(12.0), "every widget's text"
        assert table.font().pointSizeF() == pytest.approx(12.0), "in windows already open"
        assert d.window.statusBar().font().pointSizeF() == pytest.approx(12.0)
        title = next(w for w in qt.allWidgets() if w.property("role") == "title")
        assert title.font().pointSizeF() == pytest.approx(18.0), "titles stay larger"
        assert table.verticalHeader().defaultSectionSize() > row_before, "table rows"
        assert d.window.nav.width() > nav_before, "the sidebar"
        dag = d.page(WorkflowTab).findChild(QtWidgets.QGraphicsView)
        assert dag.transform().m11() == pytest.approx(1.2), "the map of the steps"
        wheel = QWheelEvent(
            QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120),
            QtCore.Qt.MouseButton.NoButton, QtCore.Qt.KeyboardModifier.ControlModifier,
            QtCore.Qt.ScrollPhase.NoScrollPhase, False,
        )  # fmt: skip
        qt.sendEvent(table.viewport(), wheel)
        assert control.level == 1.1, "Ctrl and the wheel, over a table"
        assert QtCore.QSettings("ELI", "ELI Legal").value("view/zoom") in (1.1, "1.1")
        control.set(9.0)
        assert control.level == 2.5, "never larger than this"
    finally:
        control.reset()
    assert control.level == 1.0 and qt.font().pointSizeF() == pytest.approx(10.0)


def test_pages_have_plain_names_and_the_words_explain_themselves(desk):
    d = desk()
    names = [d.window.page_name(p) for p in d.window.pages]
    for wanted in ("How to use", "Case details", "Documents", "Progress", "Compliance",
                   "Record of actions", "Legal sources"):  # fmt: skip
        assert wanted in names, wanted
    tips = [d.window.nav.item(i).toolTip() for i in range(d.window.nav.count())]
    assert any("analysis" in t for t in tips), "each page says what it is for"
    assert "cannot reach the internet" in d.window.chips["network"].toolTip()
    table = d.page(FindingsTab).list
    headings = [table.horizontalHeaderItem(i) for i in range(table.columnCount())]
    assert any(h is not None and h.toolTip() for h in headings), "column headings explain terms"
    from eli_legal.gui.tabs.help_tab import HelpTab

    help_page = d.page(HelpTab)
    help_page.search.setText("deployer")
    assert "your organisation" in help_page.words.toPlainText()
    starts = [
        b for b in help_page.findChildren(QtWidgets.QPushButton) if b.text() == "Start a new case"
    ]
    assert starts, "the guide starts a case"


def test_compliance_says_what_your_organisation_must_record_and_who_does_what_in_words(desk):
    d = desk(ADMIN)
    governance = d.page(GovernanceTab)
    governance.refresh()
    assert "need something only your organisation can do" in governance.waiting_note.text()
    headers = [
        governance.requirements.horizontalHeaderItem(i).text()
        for i in range(governance.requirements.columnCount())
    ]
    column = headers.index("What your organisation still has to record")
    row = governance.requirements.currentRow()
    assert row >= 0, "a requirement is selected, so the panel below is never empty"
    assert governance.requirements.item(row, column).text() not in ("", "Nothing")
    assert "Still to be recorded by your organisation" in governance.requirement_detail.text()
    governance._record_needed()
    assert governance.inner.currentWidget() is governance._actions_page
    assert governance.org_actions.selectedItems(), "the action it needs is selected"
    cells = {
        governance.matrix.item(r, c).text()
        for r in range(governance.matrix.rowCount())
        for c in range(1, governance.matrix.columnCount())
    }
    assert cells <= {"Does it", "Answers for it", "Is asked first", "Is kept informed"}, cells


def test_an_official_database_is_added_by_reading_its_licence(desk, monkeypatch):
    from eli_legal.gui.tabs import sources_tab

    d = desk(ADMIN)
    page = d.page(sources_tab.SourcesTab)

    def accept(dialog):
        dialog.choice.setCurrentIndex(dialog.choice.findData("uk_open"))
        assert "Open Government Licence" in dialog.about.text()
        dialog.read.setChecked(True)
        return QtWidgets.QDialog.DialogCode.Accepted

    monkeypatch.setattr(sources_tab._OfficialDialog, "exec", accept)
    page._official()
    d.settle()
    source = d.sv.ctx.sources.get("uk_open")
    assert source is not None and source.terms_reviewed and not source.approved


def test_the_walkthrough_of_a_new_case_comes_first_and_shows_what_is_done(desk, monkeypatch):
    from eli_legal.domain.how_to import NEW_CASE
    from eli_legal.gui.tabs.matter_tab import MatterTab
    from eli_legal.gui.tabs.new_case_tab import NewCaseTab

    d = desk()
    nav = d.window.nav
    first = next(
        nav.item(i)
        for i in range(nav.count())
        if nav.item(i).flags() & QtCore.Qt.ItemFlag.ItemIsEnabled
    )
    assert d.window.pages[first.data(QtCore.Qt.ItemDataRole.UserRole)].__class__ is NewCaseTab
    page = d.page(NewCaseTab)
    page.refresh()
    assert len(page.cards) == len(NEW_CASE) == 11
    ticked = {part.key for part in NEW_CASE if part.key in page.done}
    assert {"for", "case", "parties", "team", "law", "open", "documents"} <= ticked
    assert "of 11 parts done" in page.status.text()
    page.choose(3)
    assert page.part_title.text().startswith("4. The team and the reviewer")
    assert page.questions.rowCount() == len(NEW_CASE[3].questions)
    page.forward.click()
    assert page.index == 4
    opened = []
    monkeypatch.setattr(MatterTab, "_new", lambda self: opened.append(True))
    page.do_it.click()
    assert opened, "Do this now opens Start a new case"


def test_stop_says_at_once_that_the_run_is_stopping(desk):
    d = desk()
    dag = d.page(WorkflowTab)
    run = d.sv.runs.create(d.mid, actor_id=ARBITRATOR)
    d.session.run_id = run.run_id
    dag._stop()
    assert d.sv.ctx.store.get(type(run), d.mid, run.run_id).status.value == "stopped"
    assert "stop" in dag.state.text().lower()


def _wizard(d, actor, people):
    from eli_legal.gui.matter_wizard import MatterWizard

    wizard = MatterWizard(
        d.window,
        actor_id=actor,
        jurisdictions=d.sv.ctx.jurisdictions.codes(),
        default_jurisdiction="XX",
        users=d.sv.users.directory(actor),
        sources=[s for s in d.sv.sources.list() if s.approved],
        frameworks=[s for s in d.sv.frameworks.list(actor_id=actor) if s.usable],
        recommend=lambda profile, code: d.sv.frameworks.recommended(profile, code, actor_id=actor),
        people=people,
    )
    wizard.show()
    wizard.next()
    wizard.name.setText("Gantry Marine v Holloway")
    wizard.purpose.setText("Bench memorandum on acceptance of late delivery")
    wizard.jurisdiction.setCurrentText("XX")
    wizard.next()
    wizard.parties.item(0, 0).setText("Gantry Marine Ltd")
    wizard.parties.item(1, 0).setText("Holloway plc")
    wizard.issues.setPlainText("Whether acceptance waived the delay")
    wizard.next()
    return wizard


class _Confirmed:
    """A session whose person has just confirmed their passphrase."""

    def __init__(self, sv):
        self.sv = sv

    def decide(self, parent, what, work):
        from eli_legal.security import authn

        with authn.stepped_up():
            return work()


def test_the_team_page_says_who_can_approve_and_people_are_added_and_changed_there(
    desk, monkeypatch
):
    """A person whose account cannot approve on this kind of matter is told why, in words, and
    an administrator adds a person, or changes an account, without leaving the page."""
    from PySide6.QtWidgets import QCheckBox, QLabel

    from eli_legal.gui import people as people_mod

    d = desk(ADMIN)
    wizard = _wizard(d, ADMIN, people_mod.People(_Confirmed(d.sv), ADMIN))
    rows = {wizard.team.item(r, 0).data(QtCore.Qt.ItemDataRole.UserRole): r
            for r in range(wizard.team.rowCount())}  # fmt: skip
    cannot = wizard.team.cellWidget(rows[SECRETARY], 4)
    assert isinstance(cannot, QLabel) and cannot.text() == "cannot approve"
    assert "Arbitrator" in cannot.toolTip() and "Change their account" in cannot.toolTip()
    assert isinstance(wizard.team.cellWidget(rows[ARBITRATOR], 4), QCheckBox)
    assert not wizard.reviewer_self.isEnabled()
    assert "your account (Legal administrator, Technical administrator) cannot approve" in (
        wizard.reviewer_self.text()
    )
    assert "Who can approve the report" in wizard.review_note.text()
    assert all(b.isEnabled() for b in (wizard.add_person, wizard.change_person, wizard.change_me))

    def filled(user_id, roles):
        def run(dialog):
            if not dialog.user_id.isReadOnly():
                dialog.user_id.setText(user_id)
                dialog.name.setText("J Brennan")
            for i in range(dialog.roles.count()):
                item = dialog.roles.item(i)
                if item.data(QtCore.Qt.ItemDataRole.UserRole) in roles:
                    item.setCheckState(QtCore.Qt.CheckState.Checked)
            assert any(dialog.roles.item(i).text().startswith("★ Arbitrator")
                       for i in range(dialog.roles.count())), "the roles that may approve"  # fmt: skip
            return people_mod.QDialog.DialogCode.Accepted

        return run

    monkeypatch.setattr(people_mod.UserDialog, "exec", filled("j.brennan", {"arbitrator"}))
    monkeypatch.setattr(people_mod, "new_passphrase", lambda *a, **k: "harbour lights at dawn")
    wizard.add_person.click()
    rows = {wizard.team.item(r, 0).data(QtCore.Qt.ItemDataRole.UserRole): r
            for r in range(wizard.team.rowCount())}  # fmt: skip
    new = rows["j.brennan"]
    assert wizard.team.item(new, 0).checkState() == QtCore.Qt.CheckState.Checked, "added: on it"
    d.sv.users.confirm("j.brennan", "harbour lights at dawn")  # they can sign in
    reviews = wizard.team.cellWidget(new, 4)
    reviews.setChecked(True)
    assert wizard.team.cellWidget(new, 2).currentData() == "decision_maker"

    monkeypatch.setattr(people_mod.UserDialog, "exec", filled(ADMIN, {"arbitrator"}))
    wizard.change_me.click()
    assert wizard.reviewer_self.isEnabled(), "an arbitrator's account may approve"
    assert d.sv.ctx.store.get_user(ADMIN).roles >= {"legal_admin", "arbitrator"}
    wizard.reviewer_self.setChecked(True)
    assert wizard.team.cellWidget(new, 4).isChecked(), "what was chosen is kept"
    wizard.next()
    wizard.next()
    values = wizard.values()
    assert set(values["reviewers"]) == {ADMIN, "j.brennan"}
    matter = d.sv.matters.create(actor_id=ADMIN, **values)
    assert matter.reviewer_user_ids == {ADMIN, "j.brennan"}
    assert matter.member_roles["j.brennan"] == "decision_maker"
    events = [e["event_type"] for e in d.sv.ctx.audit.events(matter_id="-")]
    assert "user_created" in events and "user_updated" in events
    wizard.close()


def test_only_an_account_that_manages_users_can_add_people_from_the_team_page(desk):
    from eli_legal.gui import people as people_mod

    d = desk()
    for people in (None, people_mod.People(_Confirmed(d.sv), ARBITRATOR)):
        wizard = _wizard(d, ARBITRATOR, people)
        assert wizard.reviewer_self.isEnabled() and wizard.reviewer_self.isChecked()
        assert not wizard.add_person.isEnabled()
        assert "Settings → Users" in wizard.add_person.toolTip()
        wizard.close()


def test_named_reviewers_says_why_nobody_can_approve_and_an_account_is_changed_there(
    desk, monkeypatch
):
    """With nobody on the matter able to approve, the page says which accounts can and what
    each person's account is, and an administrator changes one without leaving the page."""
    from eli_legal.gui import people as people_mod
    from eli_legal.gui.tabs import matter_tab
    from eli_legal.gui.tabs.matter_tab import MatterTab

    d = desk(ADMIN)
    wizard = _wizard(d, ADMIN, None)
    rows = {wizard.team.item(r, 0).data(QtCore.Qt.ItemDataRole.UserRole): r
            for r in range(wizard.team.rowCount())}  # fmt: skip
    wizard.team.item(rows[SECRETARY], 0).setCheckState(QtCore.Qt.CheckState.Checked)
    wizard.next()
    wizard.next()
    values = wizard.values()
    wizard.close()
    assert values["reviewers"] == []
    matter = d.sv.matters.create(actor_id=ADMIN, **values)
    d.session.set_matter(matter.matter_id)
    page = d.page(MatterTab)
    said = []

    def answer(reply):
        def ask(parent, title, text, *a, **k):
            said.append(text)
            return reply

        return ask

    monkeypatch.setattr(matter_tab.QMessageBox, "question", answer(QMessageBox.StandardButton.No))
    page._reviewers()
    assert "Nobody on this matter can approve" in said[-1]
    assert "Arbitrator, Judge or Tribunal member" in said[-1]
    assert f"Tom Byrne ({SECRETARY}): Tribunal secretary" in said[-1]

    monkeypatch.setattr(matter_tab.QMessageBox, "question", answer(QMessageBox.StandardButton.Yes))
    opened = []

    def pick(dialog):
        opened.append(dialog.windowTitle())
        if dialog.windowTitle() != "Whose account?":
            return matter_tab.QDialog.DialogCode.Rejected
        for i in range(dialog.list.count()):
            if dialog.list.item(i).data(QtCore.Qt.ItemDataRole.UserRole) == SECRETARY:
                dialog.list.item(i).setCheckState(QtCore.Qt.CheckState.Checked)
        return matter_tab.QDialog.DialogCode.Accepted

    def give_arbitrator(dialog):
        for i in range(dialog.roles.count()):
            if dialog.roles.item(i).data(QtCore.Qt.ItemDataRole.UserRole) == "arbitrator":
                dialog.roles.item(i).setCheckState(QtCore.Qt.CheckState.Checked)
        return people_mod.QDialog.DialogCode.Accepted

    monkeypatch.setattr(matter_tab.PickDialog, "exec", pick)
    monkeypatch.setattr(people_mod.UserDialog, "exec", give_arbitrator)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: (PHRASE[ADMIN], True))
    page._reviewers()
    assert "arbitrator" in d.sv.ctx.store.get_user(SECRETARY).roles
    assert opened == ["Whose account?", "Named reviewers"], "then the reviewers can be named"


def test_review_says_what_a_returned_report_needs_and_keeps_what_was_ticked(desk, monkeypatch):
    """A returned report cannot be decided, and the page says so and offers the restart, which
    starts from the papers; a refresh keeps the limits ticked; a suspension is shown."""
    from eli_legal.demo_run import resolve_demo_holds
    from eli_legal.domain.models import RelianceBlock
    from eli_legal.gui import run_controls

    d = desk()
    d.page(WorkflowTab)._start()
    d.settle()
    mid, rid = d.mid, d.session.run_id
    with authn.stepped_up():
        resolve_demo_holds(d.sv, mid, rid)
        d.sv.runs.resume(mid, rid, actor_id=ARBITRATOR, reason="All holds resolved.")
    review = d.page(ReviewTab)
    review.refresh()
    assert review.approve.isEnabled() and review.restart.isHidden()
    review.limits.item(0).setCheckState(QtCore.Qt.CheckState.Checked)
    review.refresh()
    assert review.limits.item(0).checkState() == QtCore.Qt.CheckState.Checked, "kept"

    with authn.stepped_up():
        d.sv.reviews.decide(
            mid, rid, actor_id=ARBITRATOR, decision=ReviewDecision.RETURN_FOR_CORRECTION,
            reasons="The reply to the defence is missing; file it and run again.",
        )  # fmt: skip
    review.refresh()
    assert not any(b.isEnabled() for b in (review.approve, review.send_back, review.reject))
    assert not review.restart.isHidden()
    assert "Restart to make the corrections" in review.decision_note.text()
    assert "lifting a hold does not change that" in review.decision_note.text()
    offered = {}

    def ask(cls, parent, title, prompt, **kw):
        combo = kw["extra"][0][1]
        offered.update(title=title, start=combo.currentData())
        return None

    monkeypatch.setattr(run_controls.ReasonDialog, "ask", classmethod(ask))
    review.restart.click()
    first = d.sv.ctx.workflow.automated[0].id
    assert offered == {"title": "Restart to make the corrections", "start": first}

    d.sv.ctx.store.put(
        RelianceBlock(matter_id=mid, run_id=rid, report_id="r", report_hash="h",
                      cause="authority_changed_after_approval", recipient_ids=[ARBITRATOR])
    )  # fmt: skip
    review.refresh()
    assert "Reliance on this report is suspended" in review.release_note.text()
    assert "1 recipient(s)" in review.release_note.text()
    assert not review.end_suspension.isHidden()
