from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from eli_legal.application.container import AppContext
from eli_legal.domain.enums import ActorType, ReviewDecision, RunStatus
from eli_legal.domain.errors import (
    AuditIntegrityError,
    InvalidInput,
    InvalidState,
    NotFound,
    PolicyDenied,
    VerificationGateFailed,
)
from eli_legal.domain.models import HumanReview, Report, Run, RunStep, VerificationResult, utcnow
from eli_legal.domain.profiles import profile_spec
from eli_legal.governance.completeness import check_run_completeness
from eli_legal.legal.human_review_gate import HumanReviewGate
from eli_legal.security import authn
from eli_legal.security.redaction import content_hash
from eli_legal.workflows.case_preparation import build_report, warning_id, write_report

_BODY_MARK = "## 1. Matter"


def _body(markdown: str) -> str:
    """The report without its status banner; identical before and after approval."""
    return markdown.split(_BODY_MARK, 1)[-1]


@dataclass(slots=True)
class ReviewService:
    """The human review gate. Nothing is released for reliance except through here."""

    ctx: AppContext

    def release_for_reliance(self, run: Run, review: HumanReview | None) -> Run:
        return HumanReviewGate().release(run, review)

    def pending_warnings(self, matter_id: str, run_id: str, *, actor_id: str) -> list[str]:
        matter = self.ctx.matter_for(matter_id, actor_id, "report.review")
        run = self.ctx.store.require(Run, matter.matter_id, run_id)
        report = self.ctx.store.get(Report, matter.matter_id, run.report_id or "")
        return list(report.warnings) if report else []

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
            return self._record(run, review, actor_id)

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
        draft = draft_path.read_bytes() if draft_path.is_file() else b""
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
        return self._record(run, review, actor_id, approved_hash=approved.sha256)

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
        self, run: Run, review: HumanReview, actor_id: str, approved_hash: str | None = None
    ) -> HumanReview:
        ctx = self.ctx
        run.reviewer_user_id = actor_id
        ctx.store.put(review)
        ctx.store.put(run)
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
