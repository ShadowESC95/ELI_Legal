"""A person's controls over the human stages of a run, shared by the DAG and Review pages.

While a run waits for review, or once it is approved, anyone who may hold work can put it on
hold with reasons; nothing goes further until someone who may resolve holds lifts it, or the run
is stopped. Each is a decision: the passphrase is asked again and the reasons are recorded.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from eli_legal.application.verification_service import HELD_BY_PERSON
from eli_legal.domain.enums import RunStatus
from eli_legal.domain.models import Hold
from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import ReasonDialog


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
