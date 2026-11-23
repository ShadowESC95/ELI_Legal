"""Telling the right people that work is waiting for them.

When a run stops for a person (holds to clear, a report ready for review, a report returned, an
approved report suspended), each person on the matter who is able to act on it gets a
notification: on the Home page and the bell in the browser, and on the header of the desktop
application, wherever they are signed in. Who can act is decided by the same rules that will
let or refuse the action itself, so nobody is told to do what they may not do.

Notifications are recomputed from the state of the work, never kept by hand: when the work moves
on (a hold cleared, a decision made, a new run started) the ones it answered are marked done.
Each new notification is written to the audit trail, so the record shows who was told what and
when, which is part of showing that human oversight was possible (AI Act Art. 14, 26(2)).
Nothing is ever sent outside ELI Legal: no e-mail, no message to any other system.
"""

from __future__ import annotations

import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from eli_legal.application.container import AppContext
from eli_legal.domain import plain
from eli_legal.domain.enums import HoldScope, MatterStatus, RunStatus
from eli_legal.domain.errors import NotFound
from eli_legal.domain.models import (
    AuditEvent,
    Document,
    Hold,
    Matter,
    Notification,
    RelianceBlock,
    Run,
    utcnow,
)
from eli_legal.domain.release import ReleasePackage
from eli_legal.security import access, authn

# Events after which the work waiting for someone may have changed.
TRIGGERS = frozenset(
    {
        "run_started",
        "run_settled",
        "run_stopped",
        "run_restarted",
        "hold_raised",
        "hold_resolved",
        "hold_answered",
        "access_granted",
        "access_revoked",
        "member_role_set",
        "human_verification",
        "review_decision",
        "release_prepared",
        "release_approval",
        "reliance_block_opened",
        "reliance_block_extended",
        "reliance_block_resolved",
        "delivery_receipt",
        "report_collected",
        "matter_updated",
        "matter_closed",
    }
)

_Wanted = dict[tuple[str, str], tuple[str, str, str, list[str]]]


@dataclass(slots=True)
class NotificationService:
    ctx: AppContext
    _lock: threading.RLock = field(default_factory=threading.RLock)

    # ── keeping them in step with the work ───────────────────────────────────
    def on_event(self, event: AuditEvent) -> None:
        """Called by the audit ledger after each event is signed into the chain."""
        if event.event_type not in TRIGGERS or not event.matter_id or event.matter_id == "-":
            return
        self.refresh_matter(event.matter_id)

    def refresh_matter(self, matter_id: str) -> list[Notification]:
        """Bring every notification on a matter into line with where its work stands. Returns
        the notifications opened now."""
        with self._lock:
            matter = self.ctx.store.get_matter(matter_id)
            if matter is None:
                return []
            runs = self.ctx.store.list(Run, matter_id)
            latest = max(runs, key=lambda r: r.created_at).run_id if runs else None
            opened: list[Notification] = []
            for run in runs:
                opened += self._refresh_run(matter, run, latest=run.run_id == latest)
            return opened

    def _refresh_run(self, matter: Matter, run: Run, *, latest: bool) -> list[Notification]:
        store, mid, rid = self.ctx.store, matter.matter_id, run.run_id
        wanted = self._wanted(matter, run, latest=latest)
        now = utcnow()
        for note in store.list(Notification, mid, run_id=rid):
            if note.status == "done":
                continue
            key = (note.user_id, note.kind)
            if key in wanted:
                title, detail, _page, actions = wanted.pop(key)
                if (note.title, note.detail, note.actions) != (title, detail, actions):
                    note.title, note.detail, note.actions, note.updated_at = (
                        title,
                        detail,
                        actions,
                        now,
                    )
                    store.put(note)
            else:
                note.status, note.done_at, note.updated_at = "done", now, now
                store.put(note)
        opened: list[Notification] = []
        for (user_id, kind), (title, detail, page, actions) in wanted.items():
            note = Notification(
                matter_id=mid,
                user_id=user_id,
                kind=kind,
                subject_id=rid,
                run_id=rid,
                title=title,
                detail=detail,
                page=page,
                actions=actions,
            )
            store.put(note)
            opened.append(note)
            self.ctx.log(
                "notification_sent",
                actor_id="system",
                matter_id=mid,
                run_id=rid,
                action="notify",
                subject_id=note.notification_id,
                outcome="shown",
                object_type=f"notification:{kind}",
                payload={"recipient": user_id, "kind": kind},
            )
        return opened

    def _wanted(self, matter: Matter, run: Run, *, latest: bool) -> _Wanted:
        """Who must act on this run now, and on what: from the state of the work and the same
        permission rules that will allow or refuse the action."""
        if matter.status is MatterStatus.CLOSED:
            return {}
        ctx, mid, rid = self.ctx, matter.matter_id, run.run_id
        authorizer = ctx.authorizer()
        people = sorted({matter.owner_user_id, *matter.authorised_user_ids})

        def able(action: str, among: list[str] | None = None) -> list[str]:
            out = []
            for user_id in among if among is not None else people:
                user = ctx.store.get_user(user_id)
                if user is None or not user.active:
                    continue
                if authorizer.can_matter(matter, user_id, action):
                    out.append(user_id)
            return out

        name = matter.name[:120]
        wanted: _Wanted = {}
        if latest and run.status is RunStatus.HELD:
            holds = ctx.holds.open_holds(mid, rid)
            if holds:
                why = Counter(h.reason_code for h in holds)
                detail = "; ".join(
                    f"{count} × {plain.hold_reason(code)}" for code, count in why.most_common(4)
                )
                title = f"{name}: the run is held, {plain.count(len(holds), 'hold')} to clear"
                actions = ["verify by hand", "take out of reliance", "accept the gap", "stop",
                           "restart"]  # fmt: skip
                for user_id in able("hold.resolve"):
                    wanted[(user_id, "holds_open")] = (title, detail[:280], "review", actions)
            else:
                title = f"{name}: every hold is cleared; restart the run to continue"
                for user_id in able("workflow.restart"):
                    wanted[(user_id, "restart_needed")] = (title, "", "workflow", ["restart"])
        elif latest and run.status is RunStatus.AWAITING_HUMAN_REVIEW:
            title = f"{name}: the report is ready for your review"
            detail = "Read it with its limits, then approve, return for correction, or reject."
            actions = ["approve", "return for correction", "reject", "put on hold"]
            for user_id in able("report.approve", sorted(matter.reviewer_user_ids)):
                wanted[(user_id, "review_required")] = (title, detail, "review", actions)
        elif latest and run.status is RunStatus.RETURNED_FOR_CORRECTION:
            title = f"{name}: the report was returned for correction"
            for user_id in able("workflow.restart"):
                wanted[(user_id, "returned")] = (title, "Correct it, then restart.", "workflow",
                                                 ["restart"])  # fmt: skip
        if latest:
            self._party_holds(matter, run, able, wanted)
        for package in ctx.store.list(ReleasePackage, mid, run_id=rid):
            if package.status != "delivery_attempted":
                continue
            for recipient in package.recipients:
                uid = recipient.recipient_id
                user = ctx.store.get_user(uid)
                if user is None or not user.active or uid in package.collected:
                    continue
                if uid != matter.owner_user_id and uid not in matter.authorised_user_ids:
                    continue
                wanted[(uid, "report_released")] = (
                    f"{name}: a report was released to you",
                    f"Approved version {package.report_version}. Read it, or take a copy as PDF, "
                    "Word or Markdown, in Released to me.",
                    "released",
                    ["read", "save as PDF", "save as Word"],
                )
        blocks = [b for b in ctx.store.list(RelianceBlock, mid, run_id=rid) if b.status == "active"]
        if blocks:
            title = f"{name}: an approved report is suspended from reliance"
            detail = (
                f"{plain.count(len(blocks), 'authority problem')} found after approval; nothing "
                "may leave until a named reviewer deals with it."
            )
            for user_id in able("report.approve", sorted(matter.reviewer_user_ids)):
                wanted[(user_id, "reliance_suspended")] = (
                    title,
                    detail,
                    "review",
                    ["end the suspension", "keep it suspended"],
                )
        return wanted

    def _party_holds(self, matter: Matter, run: Run, able: Any, wanted: _Wanted) -> None:
        """Holds on a party's own filings: that party's people are asked for their answer, on
        their own screen; once a party has answered, the tribunal's people who decide holds are
        told the answer is in."""
        ctx, mid = self.ctx, matter.matter_id
        docs = {d.document_id: d for d in ctx.store.list(Document, mid)}
        waiting: dict[str, list[Hold]] = {}
        answered: list[Hold] = []
        for hold in ctx.holds.open_holds(mid, run.run_id):
            doc = docs.get(hold.subject_id) if hold.scope is HoldScope.DOCUMENT else None
            if doc is None or not doc.party_id:
                continue
            if hold.answers:
                answered.append(hold)
            else:
                waiting.setdefault(doc.party_id, []).append(hold)
        name = matter.name[:120]
        party_name = {p.party_id: p.name for p in matter.parties}

        def paper(h: Hold) -> str:
            d = docs[h.subject_id]
            return f"{d.title or d.filename}: {plain.hold_reason(h.reason_code)}"

        for party_id, held in waiting.items():
            members = sorted(
                u
                for u, p in matter.member_parties.items()
                if p == party_id and access.is_party_member(matter, u)
            )
            title = f"{name}: the tribunal needs your answer on {plain.count(len(held), 'filing')}"
            detail = "; ".join(paper(h) for h in held)[:280]
            actions = ["file a readable copy", "ask to withdraw it", "explain"]
            for user_id in able("hold.respond", members):
                wanted[(user_id, "answer_needed")] = (title, detail, "filings", actions)
        if answered:
            sides = sorted({party_name.get(h.answers[-1].party_id, "a party") for h in answered})
            title = (
                f"{name}: {', '.join(sides)} answered {plain.count(len(answered), 'hold')} on "
                "their filings; decide them"
            )
            detail = "; ".join(
                f"{paper(h)} — {h.answers[-1].kind}: {h.answers[-1].reasons}" for h in answered
            )[:280]
            for user_id in able("hold.resolve"):
                wanted[(user_id, "party_answered")] = (
                    title,
                    detail,
                    "review",
                    ["accept the gap", "take it out of the analysis", "restart once re-filed"],
                )

    # ── what a person sees ───────────────────────────────────────────────────
    def inbox(self, actor_id: str, *, include_read: bool = True) -> list[dict[str, Any]]:
        """The signed-in person's notifications that still need them, newest first, across every
        matter they work on. Brought up to date first, so none is missed or stale."""
        authn.require(actor_id)
        authorizer = self.ctx.authorizer()
        out: list[dict[str, Any]] = []
        for matter in self.ctx.store.list_matters():
            if not (
                authorizer.can_matter(matter, actor_id, "matter.read")
                or authorizer.can_matter(matter, actor_id, "filing.read")
            ):
                continue
            self.refresh_matter(matter.matter_id)
            for note in self.ctx.store.list(Notification, matter.matter_id):
                if note.user_id != actor_id or note.status == "done":
                    continue
                if note.status == "read" and not include_read:
                    continue
                out.append(_row(note, matter))
        out.sort(key=lambda r: r["created_at"], reverse=True)
        out.sort(key=lambda r: r["status"] != "open")  # unseen first, each group newest first
        return out

    def unread(self, actor_id: str) -> int:
        return sum(1 for r in self.inbox(actor_id) if r["status"] == "open")

    def mark_read(self, matter_id: str, notification_id: str, *, actor_id: str) -> dict[str, Any]:
        authn.require(actor_id)
        with self._lock:
            note = self.ctx.store.get(Notification, matter_id, notification_id)
            if note is None or note.user_id != actor_id:
                raise NotFound("no such notification")  # another person's is not revealed
            if note.status == "open":
                note.status, note.read_at = "read", utcnow()
                self.ctx.store.put(note)
            matter = self.ctx.store.get_matter(matter_id)
            return _row(note, matter)

    def mark_all_read(self, actor_id: str) -> int:
        count = 0
        for row in self.inbox(actor_id):
            if row["status"] == "open":
                self.mark_read(row["matter_id"], row["notification_id"], actor_id=actor_id)
                count += 1
        return count


def _row(note: Notification, matter: Matter | None) -> dict[str, Any]:
    return {
        "notification_id": note.notification_id,
        "matter_id": note.matter_id,
        "matter_name": matter.name if matter else "",
        "run_id": note.run_id,
        "kind": note.kind,
        "title": note.title,
        "detail": note.detail,
        "page": note.page,
        "actions": list(note.actions),
        "status": note.status,
        "created_at": note.created_at.isoformat(),
        "updated_at": note.updated_at.isoformat(),
    }
