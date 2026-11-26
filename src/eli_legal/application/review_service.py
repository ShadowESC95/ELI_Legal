from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eli_legal.application.container import AppContext
from eli_legal.application.deployment_service import require_deployment
from eli_legal.domain.enums import ActorType, ReviewDecision, RunStatus, StepStatus
from eli_legal.domain.errors import (
    AuditIntegrityError,
    InvalidInput,
    InvalidState,
    NotFound,
    PolicyDenied,
    VerificationGateFailed,
)
from eli_legal.domain.models import (
    Claim,
    Document,
    HumanReview,
    Report,
    Run,
    RunStep,
    VerificationResult,
    utcnow,
)
from eli_legal.domain.profiles import profile_spec
from eli_legal.governance.completeness import check_run_completeness
from eli_legal.legal.human_review_gate import HumanReviewGate
from eli_legal.security import authn
from eli_legal.security.redaction import content_hash
from eli_legal.workflows.case_preparation import build_report, warning_id, write_report
from eli_legal.workflows.runner import record_person_step

_BODY_MARK = "## 1. Matter"


def _body(markdown: str) -> str:
    """The report without its status banner; identical before and after approval."""
    return markdown.split(_BODY_MARK, 1)[-1]


@dataclass(slots=True)
class ReviewService:
    """The human review gate. Nothing is released for reliance except through here."""

    ctx: AppContext

    def deciders(self, matter_id: str, run_id: str, *, actor_id: str) -> dict[str, Any]:
        """Who may decide this run's report, by the same rules the decision itself applies: a
        named reviewer of the matter, whose role reviews this kind of matter, whose account is
        active, and (unless the policy allows it) not the person who ran the work. Says whether
        ``actor_id`` may, and if not, why, so nobody is left at a greyed-out button."""
        ctx = self.ctx
        matter = ctx.matter_for(matter_id, actor_id, "matter.read")
        run = ctx.store.get(Run, matter.matter_id, run_id)
        if run is None:
            raise NotFound(f"run not found in this matter: {run_id}")
        spec = profile_spec(matter.profile)
        distinct = ctx.policy.require_reviewer_distinct_from_operator

        def why_not(user_id: str) -> str:
            user = ctx.store.get_user(user_id)
            if user is None or not user.active:
                return "the account is suspended or removed"
            if user.actor_type is not ActorType.HUMAN:
                return "only a person reviews"
            if user_id not in matter.reviewer_user_ids:
                return "not a named reviewer of this matter"
            if not (user.roles & spec.reviewer_roles):
                return "the account's role does not review this kind of matter"
            if distinct and user_id == run.initiated_by:
                return "started this run, and nobody approves their own run"
            return ""

        names = {u.user_id: u.display_name for u in ctx.store.list_users()}
        who = [
            {"user_id": uid, "name": names.get(uid, uid)}
            for uid in sorted(matter.reviewer_user_ids)
            if not why_not(uid)
        ]
        reason = why_not(actor_id)
        return {
            "you_can": not reason,
            "why_not": reason,
            "who": who,
            "started_by": run.initiated_by,
            "started_by_name": names.get(run.initiated_by, run.initiated_by),
        }

    def release_for_reliance(self, run: Run, review: HumanReview | None) -> Run:
        return HumanReviewGate().release(run, review)

    def report_text(self, matter_id: str, run_id: str, *, actor_id: str) -> tuple[str, bool]:
        """The run's current report as this person may read it, and whether anything in it was
        withheld from them. A person cleared for all of the matter's material reads the file
        exactly as it was hashed and approved."""
        matter = self.ctx.matter_for(matter_id, actor_id, "document.read")
        run = self.ctx.store.require(Run, matter.matter_id, run_id)
        report = self.ctx.store.get(Report, matter.matter_id, run.report_id or "")
        if report is None:
            raise NotFound("no report has been drafted for this run")
        path = Path(report.artifact_ref)
        if not path.is_file():
            raise NotFound("the report file is missing")
        text = self.ctx.files.read(matter.matter_id, path).decode("utf-8")
        seen = self.ctx.authorizer().visibility(matter, actor_id)
        if seen.sees_everything:
            return text, False
        shown = seen.scrub(
            text,
            documents=self.ctx.store.list(Document, matter.matter_id),
            claims=self.ctx.store.list(Claim, matter.matter_id, run_id=run_id),
        )
        return shown, shown != text

    def pending_warnings(self, matter_id: str, run_id: str, *, actor_id: str) -> list[str]:
        matter = self.ctx.matter_for(matter_id, actor_id, "report.review")
        run = self.ctx.store.require(Run, matter.matter_id, run_id)
        report = self.ctx.store.get(Report, matter.matter_id, run.report_id or "")
        if report is None:
            return []
        seen = self.ctx.authorizer().visibility(matter, actor_id)
        if seen.sees_everything:
            return list(report.warnings)
        documents = self.ctx.store.list(Document, matter.matter_id)
        claims = self.ctx.store.list(Claim, matter.matter_id, run_id=run_id)
        # The id before ": " is what is acknowledged; only the description can name material.
        return [
            f"{warning_id(w)}: {seen.scrub(w.split(': ', 1)[1], documents=documents, claims=claims)}"
            if ": " in w
            else w
            for w in report.warnings
        ]

    def decide(
        self,
        matter_id: str,
        run_id: str,
        *,
        actor_id: str,
        decision: ReviewDecision,
        reasons: str,
        report_hash: str = "",
        acknowledged: Iterable[str] = (),
    ) -> HumanReview:
        ctx = self.ctx
        authn.require_step_up(actor_id, "record a review decision")
        approving = decision is ReviewDecision.APPROVE
        matter = ctx.matter_for(
            matter_id, actor_id, "report.approve" if approving else "report.review"
        )
        mid = matter.matter_id
        run = ctx.store.get(Run, mid, run_id)
        if run is None:
            raise NotFound(f"run not found in this matter: {run_id}")
        reviewer = ctx.user(actor_id)
        spec = profile_spec(matter.profile)
        # Identity comes from the user record, never from what the caller says about itself.
        if reviewer.actor_type is not ActorType.HUMAN:
            self._deny(run, actor_id, "an agent or system actor cannot review or approve")
        if actor_id not in matter.reviewer_user_ids or not (reviewer.roles & spec.reviewer_roles):
            self._deny(run, actor_id, "not a named reviewer for this matter")
        if ctx.policy.require_reviewer_distinct_from_operator and actor_id == run.initiated_by:
            self._deny(run, actor_id, "policy requires a reviewer other than the person who ran it")
        if approving:
            require_deployment(ctx, matter, actor_id=actor_id, action="report.approve",
                               reviewer_id=actor_id, operator_id=run.initiated_by)  # fmt: skip
        if len(reasons.strip()) < 10:
            raise InvalidInput("record the reasons for the decision")
        report = ctx.store.get(Report, mid, run.report_id or "")

        if not approving:
            if run.status not in (
                RunStatus.AWAITING_HUMAN_REVIEW,
                RunStatus.HELD,
                RunStatus.RETURNED_FOR_CORRECTION,
            ):
                raise InvalidState(f"run is {run.status.value}; it cannot be reviewed now")
            review = HumanReview(
                matter_id=mid,
                run_id=run_id,
                reviewer_user_id=actor_id,
                decision=decision,
                reasons=reasons.strip(),
                report_hash=report.sha256 if report else None,
            )
            run.status = (
                RunStatus.REJECTED
                if decision is ReviewDecision.REJECT
                else RunStatus.RETURNED_FOR_CORRECTION
            )
            return self._record(run, review, actor_id, practice=not matter.real)

        if run.status is not RunStatus.AWAITING_HUMAN_REVIEW:
            raise VerificationGateFailed(
                f"run is {run.status.value}; only a run awaiting review can be approved"
            )
        open_holds = ctx.holds.open_holds(mid, run_id)
        if open_holds:
            raise VerificationGateFailed(
                f"{len(open_holds)} hold(s) are open: "
                + ", ".join(sorted({h.reason_code for h in open_holds}))
            )
        if report is None:
            raise VerificationGateFailed("there is no report to approve")
        if len(report_hash) < 12 or not report.sha256.startswith(report_hash.lower()):
            raise VerificationGateFailed(
                "the report hash given does not match the current report; review the current version"
            )
        draft_path = Path(report.artifact_ref)
        draft = ctx.files.read(mid, draft_path) if draft_path.is_file() else b""
        if hashlib.sha256(draft).hexdigest() != report.sha256:
            raise AuditIntegrityError("the report file on disk no longer matches its recorded hash")
        outstanding = sorted({warning_id(w) for w in report.warnings} - set(acknowledged))
        if outstanding:
            raise VerificationGateFailed(
                "these limits must be acknowledged before approval: " + ", ".join(outstanding)
            )
        ctx.audit.verify_chain()
        completeness = check_run_completeness(
            events=ctx.audit.events(matter_id=mid, run_id=run_id),
            steps=ctx.store.list(RunStep, mid, run_id=run_id),
            holds=ctx.holds.all_holds(mid, run_id),
            reviews=ctx.store.list(HumanReview, mid, run_id=run_id),
            verifications=ctx.store.list(VerificationResult, mid, run_id=run_id),
        )
        if not completeness.ok:
            raise VerificationGateFailed(
                "audit record is incomplete: " + "; ".join(completeness.gaps[:3])
            )

        # The approved copy must be the reviewed draft with only its status banner changed.
        approved_at = utcnow()
        final = build_report(
            ctx,
            matter,
            run,
            audience=report.audience,
            model_notes=[
                w.split(": ", 1)[1] for w in report.warnings if w.startswith("model_note: ")
            ],
            audit_head=report.audit_head,
            built_at=report.created_at,
            approved_by=f"{reviewer.display_name} ({actor_id})",
            approved_at=approved_at,
        )
        if _body(final.markdown) != _body(draft.decode("utf-8")):
            raise VerificationGateFailed(
                "the findings changed after the draft was built; restart the run and review the new draft"
            )
        review = HumanReview(
            matter_id=mid,
            run_id=run_id,
            reviewer_user_id=actor_id,
            decision=decision,
            reasons=reasons.strip(),
            report_hash=report.sha256,
            acknowledged=sorted(set(acknowledged)),
            created_at=approved_at,
        )
        HumanReviewGate().release(run, review)
        approved = write_report(ctx, matter, run, final, version=report.version, final=True)
        approved.audit_head = report.audit_head
        ctx.store.put(approved)
        run.report_id = approved.report_id
        return self._record(
            run, review, actor_id, approved_hash=approved.sha256, practice=not matter.real
        )

    def _deny(self, run: Run, actor_id: str, why: str) -> None:
        self.ctx.log(
            "access_denied",
            actor_id=actor_id,
            matter_id=run.matter_id,
            run_id=run.run_id,
            action="report.approve",
            subject_id=run.run_id,
            outcome="denied",
            object_type="run",
            payload={"reason": why},
        )
        raise PolicyDenied(why)

    def _record(
        self,
        run: Run,
        review: HumanReview,
        actor_id: str,
        approved_hash: str | None = None,
        *,
        practice: bool = False,
    ) -> HumanReview:
        ctx = self.ctx
        run.reviewer_user_id = actor_id
        ctx.store.put(review)
        ctx.store.put(run)
        outcome = {
            # A practice matter is reviewed, never relied on: its step says so, like its report.
            ReviewDecision.APPROVE: (
                StepStatus.OK,
                "practice review complete (not for reliance)"
                if practice
                else "approved for reliance",
            ),
            ReviewDecision.REJECT: (StepStatus.FAILED, "rejected"),
            ReviewDecision.RETURN_FOR_CORRECTION: (StepStatus.HELD, "returned for correction"),
        }[review.decision]
        record_person_step(
            ctx.store,
            ctx.audit,
            matter_id=run.matter_id,
            run_id=run.run_id,
            step_id="human_review",
            status=outcome[0],
            actor_id=actor_id,
            detail=f"{outcome[1]} by {actor_id}",
            outputs={"review_id": review.review_id, "report_hash": review.report_hash},
        )
        ctx.log(
            "review_decision",
            actor_id=actor_id,
            matter_id=run.matter_id,
            run_id=run.run_id,
            action="report.approve"
            if review.decision is ReviewDecision.APPROVE
            else "report.review",
            subject_id=review.review_id,
            outcome=review.decision.value,
            object_type="review",
            reviewer_id=actor_id,
            input_hash=review.report_hash,
            output_hash=approved_hash,
            payload={
                "reasons_hash": content_hash(review.reasons),
                "limits_acknowledged": len(review.acknowledged),
                "run_status": run.status.value,
            },
        )
        return review
