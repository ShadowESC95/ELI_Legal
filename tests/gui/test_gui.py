"""The desktop application, driven headlessly. No test harness: the window is signed in to as a
real person would, so every action is checked exactly as it is in use."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", reason="the desktop application needs PySide6")

from PySide6.QtWidgets import QInputDialog, QMessageBox  # noqa: E402

from eli_legal.application.matter_service import hash_passphrase  # noqa: E402
from eli_legal.application.services import build_services  # noqa: E402
from eli_legal.demo import build_demo_workspace  # noqa: E402
from eli_legal.demo_run import ADMIN, ARBITRATOR, SECRETARY, demo_settings, setup_demo  # noqa: E402
from eli_legal.domain.enums import ReviewDecision  # noqa: E402
from eli_legal.domain.errors import AuthenticationFailed, SecondFactorRequired  # noqa: E402
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
    sv = build_services(demo_settings(tmp_path, workspace), install_network_guard=False)
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
    ):
        assert any(wanted in t for t in titles), wanted
    assert len(titles) == 12
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
    assert "Audit verified" in chips and "Aoife Keane" in chips and "arbitrator" in chips


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
    assert dag.dag.nodes["human_review"].status == "pending" and "hold(s) open" in dag.state.text()
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
    assert "DRAFT — NOT FOR RELIANCE" in review.report.toPlainText() and review.limits.count() >= 4
    audit = d.page(AuditTab)
    assert audit.events.rowCount() > 40 and "chain verified" in audit.chain.text()
    proofs = {audit.events.item(r, 4).text() for r in range(audit.events.rowCount())}
    assert "gui-passphrase" in proofs, "the ledger shows the run was done by a signed-in person"
    governance = d.page(GovernanceTab)
    assert governance.requirements.rowCount() == 35 and governance.controls.rowCount() >= 33
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
    assert "verification_failed" in chat.transcript.toPlainText()


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
