"""Where a matter is, and what to do next.

The lifecycle has six stages: set the matter up, add the documents, run the analysis, resolve
what is on hold, review and approve, release. For the open matter this says which stage it is
at, what each stage still needs, and the next things to do, each with the page it is done on
and whether the person looking can do it themselves or must wait for someone who can. Across
matters it lists the work waiting for that person.

It reads only: nothing here changes a matter. Every front end shows the same guidance.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from eli_legal.application.container import AppContext
from eli_legal.domain import plain
from eli_legal.domain.enums import DocumentStatus, MatterStatus, RunStatus, TaskStatus
from eli_legal.domain.models import Document, Matter, Run, VerificationTask
from eli_legal.domain.release import ReleasePackage
from eli_legal.security import access, authn

STAGES = (
    ("set_up", "Set up"),
    ("documents", "Documents"),
    ("analysis", "Analysis"),
    ("holds", "Holds and checks"),
    ("review", "Review"),
    ("release", "Release"),
    ("collect", "Collected"),
    ("close", "Close"),
)

# Where each stage is worked on, for a person who clicks it.
STAGE_PAGES = {
    "set_up": "matter",
    "documents": "evidence",
    "analysis": "workflow",
    "holds": "review",
    "review": "review",
    "release": "review",
    "collect": "released",
    "close": "matter",
}


@dataclass(frozen=True, slots=True)
class Stage:
    key: str
    title: str
    state: str  # done | current | waiting | later
    detail: str


@dataclass(frozen=True, slots=True)
class NextStep:
    title: str
    why: str
    page: str  # matter | evidence | workflow | review | findings | governance | settings
    action: str  # the permission it needs
    can_do: bool
    who: str = ""  # who can, when the viewer cannot


@dataclass(frozen=True, slots=True)
class Guide:
    matter_id: str
    matter_name: str
    headline: str
    role: str
    role_summary: str
    reads: str
    stages: tuple[Stage, ...]
    steps: tuple[NextStep, ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkItem:
    matter_id: str
    matter_name: str
    text: str
    page: str


@dataclass(slots=True)
class _Plan:
    stages: dict[str, tuple[str, str]] = field(default_factory=dict)
    steps: list[tuple[str, str, str, str]] = field(default_factory=list)  # title, why, page, action
    collectors: set[str] = field(default_factory=set)  # recipients yet to collect the report


class GuidanceService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def for_matter(self, matter_id: str, *, actor_id: str) -> Guide:
        ctx = self.ctx
        matter = ctx.matter_for(matter_id, actor_id, "matter.read")
        authz = ctx.authorizer()
        seen = authz.visibility(matter, actor_id)
        plan = self._plan(matter)
        stages = []
        current_found = False
        for key, title in STAGES:
            state, detail = plan.stages.get(key, ("later", ""))
            if state == "current":
                if current_found:
                    state = "later"
                current_found = True
            stages.append(Stage(key, title, state, detail))
        steps = []
        for title, why, page, action in plan.steps:
            can = (
                actor_id in plan.collectors
                if action == "report.collect"
                else authz.can_matter(matter, actor_id, action)
            )
            steps.append(
                NextStep(
                    title,
                    why,
                    page,
                    action,
                    can,
                    ""
                    if can
                    else (
                        "Waiting for: " + ", ".join(self._name(u) for u in sorted(plan.collectors))
                        if action == "report.collect"
                        else self._who_can(matter, action)
                    ),
                )
            )
        role = access.MATTER_ROLES.get(seen.role)
        reads = (
            "You read all of this matter's material."
            if seen.sees_everything
            else (
                "You read: "
                + ", ".join(plain.scope(s).lower() for s in sorted(seen.scopes))
                + ". Anything else is withheld from you, and marked as withheld."
                if seen.scopes
                else "You read none of this matter's documents or findings; they are withheld."
            )
            + (" Personal contact details are masked." if seen.masks else "")
            + (
                f" You act for {seen.party_name(seen.party_id)}: what another party gave in "
                "confidence is withheld."
                if seen.party_id
                else ""
            )
        )
        current = next((s for s in stages if s.state == "current"), None)
        if matter.status is MatterStatus.CLOSED:
            headline = "This matter is closed. Its record is kept; nothing more can be done on it."
        elif current is None:
            headline = "Everything is done: the approved report has been released and collected."
        else:
            headline = f"{current.title}: {current.detail}"
        return Guide(
            matter_id=matter.matter_id,
            matter_name=matter.name,
            headline=headline,
            role=role.label if role else "",
            role_summary=role.summary if role else "",
            reads=reads,
            stages=tuple(stages),
            steps=tuple(steps),
        )

    def _name(self, user_id: str) -> str:
        user = self.ctx.store.get_user(user_id)
        return user.display_name if user else user_id

    def _who_can(self, matter: Matter, action: str) -> str:
        authz = self.ctx.authorizer()
        names = [
            u.display_name
            for u in self.ctx.store.list_users()
            if u.active
            and u.user_id in {matter.owner_user_id, *matter.authorised_user_ids}
            and authz.can_matter(matter, u.user_id, action)
        ]
        return (
            "Someone on this matter who can: " + ", ".join(sorted(names))
            if names
            else f"Nobody on this matter can {plain.action(action)}; the lead must add someone."
        )

    def _plan(self, matter: Matter) -> _Plan:
        ctx, mid, plan = self.ctx, matter.matter_id, _Plan()
        stages, steps = plan.stages, plan.steps
        if matter.status is MatterStatus.CLOSED:
            for key, _title in STAGES:
                stages[key] = ("done", "")
            return plan

        # 1. set-up
        missing = []
        if not matter.reviewer_user_ids:
            missing.append("a named reviewer")
            steps.append(
                (
                    "Name at least one reviewer",
                    "Nothing can be relied on until a named reviewer approves it, so the analysis "
                    "will not start without one.",
                    "matter",
                    "matter.manage",
                )
            )
        if not matter.approved_source_ids:
            steps.append(
                (
                    "Choose the legal sources",
                    "Without an approved source no legal research is done and no authority a "
                    "party cites can be checked.",
                    "matter",
                    "matter.manage",
                )
            )
        if not matter.stated_issues:
            steps.append(
                (
                    "State the issues",
                    "Issues framed at the start make the analysis follow the questions you "
                    "need answered; without them they are taken from the papers.",
                    "matter",
                    "matter.manage",
                )
            )
        stages["set_up"] = (
            ("current", "needs " + " and ".join(missing) + ".")
            if missing
            else ("done", "Team, reviewers, sources and laws are chosen.")
        )

        # 2. documents
        documents = ctx.store.list(Document, mid)
        unread = [d for d in documents if d.status is DocumentStatus.REGISTERED]
        if not documents:
            stages["documents"] = ("current", "no documents have been added yet.")
            steps.append(
                (
                    "Add the documents",
                    "Add the pleadings, statements, contracts and correspondence, saying who "
                    "filed each one and who may see it.",
                    "evidence",
                    "document.ingest",
                )
            )
        elif unread:
            stages["documents"] = (
                "current",
                f"{plain.count(len(unread), 'document')} not read yet.",
            )
        else:
            read = sum(1 for d in documents if d.status is DocumentStatus.PROCESSED)
            failed = [
                d
                for d in documents
                if d.status not in (DocumentStatus.PROCESSED, DocumentStatus.WAIVED)
            ]
            stages["documents"] = (
                "done",
                f"{read} of {len(documents)} documents read"
                + (
                    f"; {plain.count(len(failed), 'could not be read', 'could not be read')}: add a "
                    "readable copy, or a person accepts the gap when the run holds."
                    if failed
                    else "."
                ),
            )

        # 3-6. the latest run
        runs = ctx.store.list(Run, mid)
        run = runs[-1] if runs else None
        if run is None:
            stages["analysis"] = ("current", "the analysis has not been run.")
            if documents and not missing:
                steps.append(
                    (
                        "Run the analysis",
                        "The system reads the papers, takes the facts word for word, finds and "
                        "checks the law, and drafts a report for review.",
                        "workflow",
                        "workflow.run",
                    )
                )
            return plan
        status = run.status
        stages["analysis"] = (
            ("current", "the analysis is running.")
            if status in (RunStatus.RUNNING, RunStatus.CREATED)
            else (
                "done",
                f"Run of {run.created_at:%d %b %Y}: "
                f"{plain.run_state(status, real=matter.real).lower()}.",
            )
        )
        holds = ctx.holds.open_holds(mid, run.run_id)
        tasks = ctx.store.list(
            VerificationTask, mid, run_id=run.run_id, status=TaskStatus.OPEN.value
        )
        if status in (RunStatus.HELD, RunStatus.BLOCKED, RunStatus.STOPPED):
            if holds or tasks:
                parts = []
                if holds:
                    parts.append(plain.count(len(holds), "hold"))
                if tasks:
                    parts.append(plain.count(len(tasks), "check") + " for a person")
                stages["holds"] = ("current", " and ".join(parts) + " open.")
                reasons: dict[str, int] = {}
                for h in holds:
                    reasons[h.reason_code] = reasons.get(h.reason_code, 0) + 1
                for code, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
                    explained = plain.hold_explanation(code)
                    steps.append(
                        (
                            f"Resolve {plain.count(n, 'hold')}: {plain.lower_first(explained.headline)}",
                            f"{explained.why} {explained.options[0]}",
                            "review",
                            "hold.resolve",
                        )
                    )
                if tasks:
                    steps.append(
                        (
                            f"Record {plain.count(len(tasks), 'check')} the system could not make",
                            "Each is a question about one finding, answered against its source "
                            "and recorded under your name.",
                            "review",
                            "citation.verify",
                        )
                    )
            else:
                stages["holds"] = ("current", "nothing is open; the run can resume.")
                steps.append(
                    (
                        "Resume the run" if status is not RunStatus.STOPPED else "Restart the run",
                        "Every hold is resolved, so the rest of the analysis can run and the "
                        "report be drafted for review.",
                        "workflow",
                        "workflow.restart",
                    )
                )
            return plan
        if status in (RunStatus.RUNNING, RunStatus.CREATED):
            return plan
        stages["holds"] = ("done", "Nothing is on hold.")

        if status in (RunStatus.REJECTED, RunStatus.RETURNED_FOR_CORRECTION):
            stages["review"] = (
                "current",
                f"the reviewer {plain.state(status).lower()} the report.",
            )
            steps.append(
                (
                    "Correct the matter and run the analysis again",
                    "Read the reviewer's reasons in the audit trail, correct what they point "
                    "to, and start a new run.",
                    "workflow",
                    "workflow.run",
                )
            )
            return plan
        if status is RunStatus.AWAITING_HUMAN_REVIEW:
            names = sorted(matter.reviewer_user_ids)
            stages["review"] = ("current", "the report is waiting for a named reviewer.")
            steps.append(
                (
                    "Review and approve the report",
                    "Read the report, acknowledge each stated limit, and approve it, return it "
                    "for correction or reject it, with reasons. Named reviewers: "
                    + ", ".join(names)
                    + ".",
                    "review",
                    "report.approve",
                )
            )
            return plan
        stages["review"] = (
            ("done", "The report is approved for reliance.")
            if matter.real
            else ("done", "The practice review is complete; a practice matter is not for reliance.")
        )
        packages = ctx.store.list(ReleasePackage, mid, run_id=run.run_id)
        sent = [p for p in packages if p.status == "delivery_attempted"]
        prepared = [p for p in packages if p.status in ("prepared", "approved_for_delivery")]
        if not sent:
            if prepared:
                stages["release"] = (
                    "current",
                    "a release is prepared; a person must confirm each recipient.",
                )
                steps.append(
                    (
                        "Confirm the recipients and release the report",
                        "Tick each recipient yourself: only people entitled to this matter can "
                        "receive it. Nothing is e-mailed; each recipient with an account is told "
                        "and collects it on Released to me.",
                        "review",
                        "report.send",
                    )
                )
            else:
                stages["release"] = ("current", "the approved report has not been released.")
                steps.append(
                    (
                        "Release the approved report",
                        "Choose who receives it; only people entitled to this matter can. Nothing "
                        "is e-mailed: each recipient with an account collects it on Released to "
                        "me.",
                        "review",
                        "report.prepare_release",
                    )
                )
            return plan
        people = {u.user_id for u in ctx.store.list_users() if u.active}
        on_matter = {matter.owner_user_id, *matter.authorised_user_ids}
        recipients = {
            r.recipient_id
            for p in sent
            for r in p.recipients
            if r.recipient_id in people and r.recipient_id in on_matter
        }
        collected = {uid for p in sent for uid in p.collected}
        stages["release"] = (
            "done",
            "Released to "
            + plain.count(len({r.recipient_id for p in sent for r in p.recipients}), "recipient")
            + ".",
        )
        plan.collectors = recipients - collected
        if plan.collectors:
            waiting = ", ".join(sorted(self._name(u) for u in plan.collectors))
            stages["collect"] = ("current", f"waiting for {waiting} to collect it.")
            steps.append(
                (
                    "Collect the report released to you",
                    "Read it, or save it as PDF, Word or Markdown on Released to me; each copy "
                    "carries your name and is recorded.",
                    "released",
                    "report.collect",
                )
            )
        else:
            stages["collect"] = (
                "done",
                "Every recipient with an account has collected it."
                if recipients
                else "Staged in the outbox for recipients without an account.",
            )
        stages["close"] = (
            "current",
            "close the matter when the case is finished; its record is kept.",
        )
        steps.append(
            (
                "Close the matter when the case is finished",
                "Closing ends everyone's access. The record (runs, reviews, releases and the "
                "audit trail) is kept; the papers are kept for the retention period, unless you "
                "delete them at closing. A preservation hold stops any deletion.",
                "matter",
                "matter.close",
            )
        )
        return plan

    # ── across matters ───────────────────────────────────────────────────────
    def my_work(self, *, actor_id: str) -> list[WorkItem]:
        """What is waiting for this person, on every matter they are on."""
        authn.require(actor_id)
        authz = self.ctx.authorizer()
        out: list[WorkItem] = []
        for matter in self.ctx.store.list_matters():
            if matter.status is MatterStatus.CLOSED or not authz.can_matter(
                matter, actor_id, "matter.read"
            ):
                continue
            plan = self._plan(matter)
            for title, _why, page, action in plan.steps:
                if action == "report.collect":
                    if actor_id in plan.collectors:
                        out.append(WorkItem(matter.matter_id, matter.name, title, page))
                    continue
                if authz.can_matter(matter, actor_id, action):
                    if action == "report.approve" and actor_id not in matter.reviewer_user_ids:
                        continue
                    out.append(WorkItem(matter.matter_id, matter.name, title, page))
        return out
