"""A run a person stops stops promptly: the step at work ends at its next model answer, document
or issue, no later step starts, and nothing a step saves afterwards undoes the stop."""

import pytest

from eli_legal.domain import stopping
from eli_legal.domain.enums import RunStatus, StepStatus
from eli_legal.domain.errors import RunStopped
from eli_legal.domain.models import Run, RunStep
from eli_legal.legal.llm import LegalModel
from eli_legal.workflows.case_preparation import CasePreparation

A = "arb.keane"


def test_a_stop_during_a_step_ends_that_step_and_no_later_one_starts(demo, monkeypatch):
    sv, mid = demo
    run = sv.runs.create(mid, actor_id=A)
    original = CasePreparation.facts

    def facts_stopped_halfway(self, c):
        # A person presses Stop while facts are being taken; the step reaches its next
        # checkpoint (here, the next document) and ends there.
        sv.runs.stop(mid, run.run_id, actor_id=A, reason="Wrong papers were filed; stop it.")
        stopping.check_stop()
        return original(self, c)

    monkeypatch.setattr(CasePreparation, "facts", facts_stopped_halfway)
    finished = sv.runs.execute(mid, run.run_id, actor_id=A)
    assert finished.status is RunStatus.STOPPED
    steps = {s.step_id: s for s in sv.ctx.store.list(RunStep, mid, run_id=run.run_id)}
    assert steps["ingest"].status is StepStatus.OK
    assert steps["facts"].status is StepStatus.SKIPPED
    assert steps["facts"].detail == "stopped by a person while this step was working"
    later = [s for s in steps.values() if s.step_id in ("issues", "legal_research", "draft_report")]
    assert later and all(s.detail == "run was stopped" for s in later)
    holds = sv.ctx.holds.open_holds(mid, run.run_id)
    assert not [h for h in holds if h.subject_id == "facts"], "a stop is no failure to hold"


def test_a_step_saving_the_run_cannot_undo_a_stop(demo):
    sv, mid = demo
    run = sv.runs.create(mid, actor_id=A)
    working_copy = sv.ctx.store.get(Run, mid, run.run_id)  # what a step holds in memory
    sv.runs.stop(mid, run.run_id, actor_id=A, reason="Stopped while a step was at work.")
    working_copy.tool_versions["retrieval"] = "recorded by the step"
    CasePreparation.for_run(sv.ctx)._save_run(working_copy)
    stored = sv.ctx.store.get(Run, mid, run.run_id)
    assert stored.status is RunStatus.STOPPED, "the person's stop stands"
    assert stored.tool_versions["retrieval"] == "recorded by the step", "what the step recorded too"


def test_no_model_answer_is_waited_for_once_the_run_is_stopped():
    class Inference:
        model_id, available = "stand-in", True

        def generate(self, **_kwargs):
            raise AssertionError("the model was asked after the run was stopped")

    model = LegalModel(Inference())
    with stopping.watching(lambda: True), pytest.raises(RunStopped):
        model.ask("facts", "Which statements are facts?")
    stopping.check_stop()  # outside a run it does nothing


def test_a_run_held_for_want_of_a_reviewer_says_in_words_who_may_approve(demo):
    """The hold names the accounts that may approve this kind of matter and where to name one,
    and stays within what the step and the ledger keep."""
    sv, mid = demo
    sv.matters.set_reviewers(mid, actor_id=A, reviewer_ids=[])
    run = sv.runs.start(mid, actor_id=A)
    intake = next(
        s for s in sv.ctx.store.list(RunStep, mid, run_id=run.run_id) if s.step_id == "scope"
    )
    assert intake.detail.startswith("missing_reviewer: nobody named on this matter may approve")
    assert "Arbitrator, Judge or Tribunal member" in intake.detail
    assert intake.detail.endswith("named under Named reviewers on the Case page")
