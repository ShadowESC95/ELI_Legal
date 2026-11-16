"""A person's controls over the human stages of a run, shared by the DAG and Review pages.

While a run waits for review, or once it is approved, anyone who may hold work can put it on
hold with reasons; nothing goes further until someone who may resolve holds lifts it, or the run
is stopped. Each is a decision: the passphrase is asked again and the reasons are recorded.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QComboBox, QMessageBox

from eli_legal.application.verification_service import HELD_BY_PERSON
from eli_legal.domain import plain
from eli_legal.domain.enums import RunStatus
from eli_legal.domain.models import Hold
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import ReasonDialog
from eli_legal.workflows.agents import agent_for


def person_hold(tab: Tab) -> Hold | None:
    """The open hold a person put on the run that is open, if there is one."""
    if not (tab.mid and tab.rid):
        return None
    holds = tab.session.attempt(
        tab, lambda: tab.sv.holds.list(tab.mid, tab.rid, actor_id=tab.actor), quiet=True
    )
    return next((h for h in holds or [] if h.reason_code == HELD_BY_PERSON), None)


def hold_run(tab: Tab) -> None:
    run = tab.session.run
    if run is None:
        return
    if run.status not in (RunStatus.AWAITING_HUMAN_REVIEW, RunStatus.APPROVED_FOR_RELIANCE):
        QMessageBox.information(
            tab,
            "Put on hold",
            "A run can be put on hold while it waits for review or once it is approved. "
            "A run that is still running is stopped instead.",
        )
        return
    approved = run.status is RunStatus.APPROVED_FOR_RELIANCE
    reason = ReasonDialog.ask(
        tab,
        "Suspend reliance" if approved else "Put the run on hold",
        (
            "The report is approved. Putting it on hold suspends reliance on it and stops its "
            "release until a decision-maker lifts the hold or the run is stopped."
            if approved
            else "Nothing will be approved or released until a decision-maker lifts the hold "
            "or the run is stopped."
        )
        + " Why are you holding it?",
    )
    if reason:
        tab.session.decide(
            tab,
            "suspend reliance on this report" if approved else "put this run on hold",
            lambda: tab.sv.holds.place(tab.mid, tab.rid, actor_id=tab.actor, reason=reason),
        )


def lift_hold(tab: Tab) -> None:
    hold = person_hold(tab)
    if hold is None:
        QMessageBox.information(tab, "Lift the hold", "Nobody has put this run on hold.")
        return
    why = hold.detail.split(";", 1)[-1].strip()
    reason = ReasonDialog.ask(
        tab,
        "Lift the hold",
        f"It was put on hold because: “{why}”. The run returns to where it was. Why can the "
        "hold be lifted?",
    )
    if reason:
        tab.session.decide(
            tab,
            "lift the hold on this run",
            lambda: tab.sv.holds.resolve(
                tab.mid, hold.hold_id, actor_id=tab.actor, action="lift", reason=reason
            ),
        )


RESUMABLE = (
    RunStatus.HELD,
    RunStatus.BLOCKED,
    RunStatus.STOPPED,
    RunStatus.RETURNED_FOR_CORRECTION,
)


def restart_run(
    tab: Tab,
    on_done: Callable[[object], None],
    on_failed: Callable[[Exception], None],
) -> bool:
    """Ask which step to restart from, and why, then restart the open run in the background.
    A report returned for correction starts again from the papers by default: its steps all
    finished cleanly, so "the first step that did not finish" would be the verification gate
    and the corrections would never be read. Whether anything was started."""
    run = tab.session.run
    if run is None or not tab.rid:
        return False
    if run.status not in RESUMABLE:
        QMessageBox.information(
            tab,
            "Restart",
            f"The run is {plain.state(run.status.value).lower()}; only a run that is held, "
            "stopped or returned for correction is restarted.",
        )
        return False
    returned = run.status is RunStatus.RETURNED_FOR_CORRECTION
    automated = tab.sv.ctx.workflow.automated
    steps = QComboBox()
    if returned:
        steps.addItem(f"the beginning: {agent_for(automated[0].id).name}", automated[0].id)
    else:
        steps.addItem("the first step that did not finish cleanly", "")
    for step in automated:
        steps.addItem(agent_for(step.id).name, step.id)
    reason = ReasonDialog.ask(
        tab,
        "Restart to make the corrections" if returned else "Restart this run",
        (
            "The report was returned for correction. Make the corrections first (add or replace "
            "a document, record a check on a finding), then restart. Starting from the beginning "
            "reads everything again, the corrections included. "
            if returned
            else ""
        )
        + "A restart is recorded under your name. The step you choose and everything after it "
        "runs again; earlier decisions about findings are kept. What was corrected?",
        extra=[("Restart from", steps)],
    )
    if not reason:
        return False
    phrase = tab.session.ask_passphrase(tab, "restart this run")
    if phrase is None:
        return False
    try:
        tab.sv.users.confirm(tab.actor, phrase)
    except Exception:
        tab.session.decide_with(tab, "", lambda: None)
        return False
    mid, rid, actor, from_step = tab.mid, tab.rid, tab.actor, steps.currentData() or None

    def work() -> object:
        from eli_legal.security import authn

        with authn.stepped_up():
            return tab.sv.runs.resume(mid, rid, actor_id=actor, reason=reason, from_step=from_step)

    tab.session.background("Restarting the run…", work, on_done, on_failed)
    tab.session.notify()
    return True
