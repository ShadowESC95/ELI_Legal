import pytest

from eli_legal.application.matter_service import hash_passphrase, verify_passphrase
from eli_legal.application.services import build_services
from eli_legal.demo import build_demo_workspace
from eli_legal.demo_run import ARBITRATOR, SECRETARY, demo_settings, setup_demo
from eli_legal.domain.errors import (
    AuthenticationFailed,
    InvalidInput,
    MatterAccessDenied,
    PolicyDenied,
)
from eli_legal.workflows.agents import (
    AGENTS,
    DETERMINISTIC,
    HUMAN,
    MODEL_ASSISTED,
    agent_for,
    layers,
)
from tests.conftest import FakeInference

A = ARBITRATOR


def test_chat_answers_from_the_matter_with_locators_and_flags_what_cannot_be_relied_on(held_run):
    sv, mid, rid = held_run
    answer = sv.chat.ask(
        mid, actor_id=A, question="When did the Respondent receive the notice of termination?"
    )
    assert answer.mode == "passages" and not answer.lines, "no model: the sources are the answer"
    documents = [s for s in answer.sources if s.kind == "document"]
    assert any(
        "did not receive the notice of 28 April 2023 until 2 May 2023" in s.text for s in documents
    )
    assert all(s.locator and s.title for s in documents)
    law = sv.chat.ask(
        mid, actor_id=A, question="Is time for delivery of the essence of a commercial contract?"
    )
    authorities = {s.title.split(" — ")[0]: s for s in law.sources if s.kind == "authority"}
    assert authorities["[2011] XXSC 14"].usable is False
    assert (
        authorities["[2011] XXSC 14"].note.startswith("NOT TO BE RELIED ON")
        and "overruled" in authorities["[2011] XXSC 14"].note
    )
    assert authorities["[2022] XXSC 7"].usable is True
    held = [s for s in law.sources if s.kind == "finding" and s.note.startswith("HELD")]
    assert held and not any(s.usable for s in held)


def test_chat_will_not_give_the_decision_but_still_shows_the_material(held_run):
    sv, mid, _rid = held_run
    for question in (
        "Who should win on the termination issue?",
        "Should the tribunal find for the Claimant?",
        "What should the outcome be?",
        "Draft the award for me",
    ):
        answer = sv.chat.ask(mid, actor_id=A, question=question)
        assert answer.mode == "refused", question
        assert "do not say who should succeed" in answer.notes[0]
    assert sv.chat.ask(mid, actor_id=A, question="Who should win on the termination issue?").sources


def test_chat_commands_report_state_and_chat_is_access_controlled_and_logged(held_run):
    sv, mid, rid = held_run
    status = sv.chat.ask(mid, actor_id=A, question="/status")
    assert status.mode == "command" and "is held" in status.notes[0]
    assert any(
        "verification_failed" in n for n in sv.chat.ask(mid, actor_id=A, question="/holds").notes
    )
    assert any("current_law" in n for n in sv.chat.ask(mid, actor_id=A, question="/tasks").notes)
    assert any(
        "jurisdiction_pack_unvalidated" in n
        for n in sv.chat.ask(mid, actor_id=A, question="/limits").notes
    )
    assert (
        "no hold, verification, approval or release"
        in sv.chat.ask(mid, actor_id=A, question="/help").notes[0]
    )
    with pytest.raises(MatterAccessDenied):
        sv.chat.ask(mid, actor_id="admin", question="/status")
    events = [e for e in sv.ctx.audit.events(matter_id=mid) if e["event_type"] == "chat_query"]
    assert len(events) == 5 and all(
        e["input_hash"] and "question" not in e["payload"] for e in events
    )


def _model_chat(tmp_path, reply):
    model = FakeInference(
        {
            "chat_answer": reply,
            "fact_select": {"selected": []},
            "issue_propose": {"issues": []},
            "fact_issue_link": {"links": []},
            "arguments": {"arguments": []},
        }
    )
    workspace = build_demo_workspace(tmp_path / "demo")
    sv = build_services(
        demo_settings(tmp_path, workspace), inference=model, install_network_guard=False
    )
    mid = setup_demo(sv, workspace)
    sv.runs.start(mid, actor_id=SECRETARY)
    return sv, mid, model


def test_a_model_summary_keeps_only_sentences_grounded_in_the_cited_sources(tmp_path):
    reply = {
        "sentences": [
            {"text": "The Respondent says it received the notice on 2 May 2023.", "cites": ["D1"]},
            {"text": "The notice was in fact received on 9 June 2023.", "cites": ["D1"]},
            {"text": "The Claimant should therefore succeed.", "cites": ["D1"]},
            {"text": "See also Zeta v Omega [2020] XXSC 55.", "cites": ["D1"]},
            {"text": "A sentence citing nothing.", "cites": []},
        ]
    }
    sv, mid, model = _model_chat(tmp_path, reply)
    answer = sv.chat.ask(
        mid, actor_id=A, question="When did the Respondent receive the notice of 28 April 2023?"
    )
    assert answer.mode == "model" and answer.model_id == "fake-model"
    assert [text for text, _ in answer.lines] == [
        "The Respondent says it received the notice on 2 May 2023."
    ]
    assert answer.dropped == 4 and "discarded" in answer.notes[-1]
    prompt = next(p for p in model.prompts if "Task chat_answer/" in p)
    assert "ignore all previous instructions" not in prompt.lower(), (
        "a flagged file is not given to the model"
    )
    assert "[2011] XXSC 14" not in prompt, (
        "an overruled authority is not offered to the model as a source"
    )
    plain = sv.chat.ask(
        mid, actor_id=A, question="When did the Respondent receive the notice?", use_model=False
    )
    assert plain.mode == "passages" and not plain.lines


def test_every_workflow_step_has_an_agent_with_a_bounded_mandate(services):
    workflow = services.ctx.workflow
    assert [a.step_id for a in AGENTS] == [s.id for s in workflow.steps]
    for agent in AGENTS:
        assert agent.role and agent.reads and agent.writes and agent.may_not, agent.step_id
        assert agent.kind in {DETERMINISTIC, MODEL_ASSISTED, HUMAN}
        assert (agent.kind == HUMAN) == workflow.step(agent.step_id).manual
    assert {a.step_id for a in AGENTS if a.kind == MODEL_ASSISTED} == {
        "facts",
        "issues",
        "analysis",
    }
    assert "state or imply an outcome" in agent_for("analysis").may_not
    from eli_legal.governance.registers import load_register

    known = {c["control_id"] for c in load_register("controls")}
    assert all(set(a.controls) <= known for a in AGENTS)


def test_the_graph_layers_respect_every_dependency(services):
    workflow = services.ctx.workflow
    grouped = layers(workflow)
    position = {step: i for i, layer in enumerate(grouped) for step in layer}
    assert grouped[0] == ["scope"] and sorted(position) == sorted(s.id for s in workflow.steps)
    for step in workflow.steps:
        assert all(position[d] < position[step.id] for d in step.depends_on)
    assert position["legal_research"] == position["evidence_mapping"], (
        "research and mapping are parallel"
    )


def test_sign_in_needs_the_passphrase_and_every_attempt_is_recorded(services):
    sv = services
    sv.users.bootstrap_admin("admin", "Admin", passphrase="correct horse battery")
    assert sv.users.authenticate("admin", "correct horse battery").user_id == "admin"
    for user, phrase in (("admin", "wrong passphrase!"), ("nobody", "correct horse battery")):
        with pytest.raises(AuthenticationFailed):
            sv.users.authenticate(user, phrase)
    sv.users.add_user(
        actor_id="admin", user_id="j.okoro", display_name="Judge Okoro", roles=["judge"]
    )
    assert sv.users.needs_passphrase("j.okoro")
    with pytest.raises(AuthenticationFailed):
        sv.users.authenticate("j.okoro", "")  # no passphrase set means no sign-in, not open access
    with pytest.raises(AuthenticationFailed, match="administrator must set the first one"):
        # an account with no passphrase cannot be claimed by whoever asks first
        sv.users.set_passphrase(actor_id="j.okoro", user_id="j.okoro", new="claiming this account")
    with pytest.raises(InvalidInput):
        sv.users.set_passphrase(actor_id="admin", user_id="j.okoro", new="short")
    sv.users.set_passphrase(actor_id="admin", user_id="j.okoro", new="set by administrator")
    with pytest.raises(AuthenticationFailed):
        sv.users.set_passphrase(
            actor_id="j.okoro", user_id="j.okoro", new="another long phrase", current="wrong"
        )
    with pytest.raises(PolicyDenied):
        sv.users.set_passphrase(actor_id="j.okoro", user_id="admin", new="taking over the admin")
    sv.users.set_passphrase(
        actor_id="j.okoro",
        user_id="j.okoro",
        new="chosen by the judge",
        current="set by administrator",
    )
    assert sv.users.authenticate("j.okoro", "chosen by the judge")
    outcomes = [e["outcome"] for e in sv.ctx.audit.events() if e["event_type"] == "sign_in"]
    assert outcomes.count("sign_in_refused") == 3 and outcomes.count("signed_in") == 2
    stored = sv.ctx.user("admin").passphrase_hash
    assert stored.startswith("pbkdf2_sha256$") and "correct horse" not in stored
    assert verify_passphrase("x" * 12, hash_passphrase("x" * 12)) and not verify_passphrase(
        "y" * 12, hash_passphrase("x" * 12)
    )


def test_changing_the_model_is_a_governed_recorded_change(services, tmp_path):
    sv = services
    sv.users.bootstrap_admin("admin")
    sv.users.add_user(actor_id="admin", user_id="j.okoro", display_name="Judge", roles=["judge"])
    with pytest.raises(PolicyDenied):
        sv.config.set_model(
            actor_id="j.okoro", backend="openai_compat", url="http://127.0.0.1:11434/v1", model="m"
        )
    with pytest.raises(InvalidInput, match="different model"):
        sv.config.set_model(
            actor_id="admin",
            backend="openai_compat",
            url="http://127.0.0.1:11434/v1",
            model="m",
            verifier_model="m",
        )
    env = tmp_path / ".env"
    env.write_text("ELI_LEGAL_ENV=development\nELI_LEGAL_INFERENCE=none\n")
    now = sv.config.set_model(
        actor_id="admin",
        backend="openai_compat",
        url="http://127.0.0.1:11434/v1",
        model="m",
        verifier_model="v",
        persist_to=env,
    )
    assert now["active_model_id"] == "m@127.0.0.1" and now["active_verifier_id"] == "v@127.0.0.1"
    assert sv.ctx.model.available and sv.ctx.model.model_id == "m@127.0.0.1"
    text = env.read_text()
    assert (
        "ELI_LEGAL_ENV=development" in text
        and "ELI_LEGAL_INFERENCE=openai_compat" in text
        and "ELI_LEGAL_INFERENCE_MODEL=m" in text
    )
    event = [e for e in sv.ctx.audit.events() if e["event_type"] == "configuration_changed"][-1]
    assert event["payload"] == {
        "auth": "test-harness+step-up",
        "from": "none",
        "to": "m@127.0.0.1",
        "verifier": "v@127.0.0.1",
    }
    from eli_legal.domain.errors import NetworkDenied

    with pytest.raises(NetworkDenied):
        sv.config.set_model(
            actor_id="admin", backend="openai_compat", url="https://api.example.com/v1", model="m"
        )
    assert (
        sv.config.set_model(actor_id="admin", backend="none", url="", model="")["active_model_id"]
        == "none"
    )
