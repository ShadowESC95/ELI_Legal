from __future__ import annotations

from dataclasses import dataclass

from eli_legal.application.container import AppContext
from eli_legal.domain.enums import (
    ActorType,
    ClaimStatus,
    DocumentStatus,
    HoldResolution,
    HoldScope,
    HoldStatus,
    TaskStatus,
    VerificationStatus,
    VerificationType,
)
from eli_legal.domain.errors import InvalidInput, InvalidState, NotFound, PolicyDenied
from eli_legal.domain.models import (
    Claim,
    Document,
    Hold,
    Matter,
    Run,
    VerificationResult,
    VerificationTask,
    utcnow,
)
from eli_legal.governance.completeness import verification_digest
from eli_legal.governance.gates import apply_decision, effective_results, evaluate_claim
from eli_legal.security.redaction import content_hash

# Which permission lets a person decide each kind of check.
_ACTION_FOR_CHECK = {
    VerificationType.CITATION.value: "citation.verify",
    VerificationType.CURRENT_LAW.value: "authority.status_check",
    VerificationType.PROPOSITION.value: "proposition.verify",
    VerificationType.EVIDENCE_SUPPORT.value: "proposition.verify",
    VerificationType.PROVENANCE.value: "proposition.verify",
}
_NEGATIVE = {VerificationStatus.FAILED, VerificationStatus.CONFLICT}


@dataclass(slots=True)
class VerificationService:
    """The human half of verification: people decide what the system could not."""

    ctx: AppContext

    def apply(self, run: Run, claim: Claim, results: list[VerificationResult]) -> None:
        from eli_legal.governance.gates import apply_verification_gate

        apply_verification_gate(run, claim, results)

    def tasks(self, matter_id: str, run_id: str, *, actor_id: str) -> list[VerificationTask]:
        matter = self.ctx.matter_for(matter_id, actor_id, "matter.read")
        return self.ctx.store.list(
            VerificationTask, matter.matter_id, run_id=run_id, status=TaskStatus.OPEN.value
        )

    def claims(self, matter_id: str, run_id: str, *, actor_id: str) -> list[Claim]:
        matter = self.ctx.matter_for(matter_id, actor_id, "document.read")
        return self.ctx.store.list(Claim, matter.matter_id, run_id=run_id)

    def results_for(
        self, matter_id: str, claim_id: str, *, actor_id: str
    ) -> list[VerificationResult]:
        matter = self.ctx.matter_for(matter_id, actor_id, "document.read")
        claim = self.ctx.store.require(Claim, matter.matter_id, claim_id)
        results = self.ctx.store.list(VerificationResult, matter.matter_id, run_id=claim.run_id)
        return [r for r in results if r.claim_id == claim_id]

    def record_human_result(
        self,
        matter_id: str,
        claim_id: str,
        *,
        actor_id: str,
        verification_type: str,
        status: VerificationStatus,
        reason: str,
    ) -> VerificationResult:
        """A named person records the outcome of a check, with reasons.

        If the person's result is favourable where the system's was a failure or conflict, that
        is an override: it needs the separate override permission and is shown in the report.
        """
        ctx = self.ctx
        action = _ACTION_FOR_CHECK.get(verification_type)
        if action is None:
            raise InvalidState(f"{verification_type!r} is not a check a person can decide")
        matter = ctx.matter_for(matter_id, actor_id, action)
        if ctx.user(actor_id).actor_type is not ActorType.HUMAN:
            raise PolicyDenied("only a human user may record a verification result")
        if status not in (VerificationStatus.VERIFIED, VerificationStatus.FAILED):
            raise InvalidState("a person records a check as verified or failed")
        if len(reason.strip()) < 10:
            raise InvalidInput("give the reason for this result (what was checked, and where)")
        claim = ctx.store.require(Claim, matter.matter_id, claim_id)
        mid, rid = matter.matter_id, claim.run_id
        prior = [
            r
            for r in ctx.store.list(VerificationResult, mid, run_id=rid)
            if r.claim_id == claim_id and r.verification_type == verification_type
        ]
        automated = [r for r in prior if not r.by_human]
        system_view = effective_results(automated).get(verification_type)
        override = bool(
            status is VerificationStatus.VERIFIED
            and system_view is not None
            and system_view.status in _NEGATIVE
        )
        if override:
            ctx.authorizer().require_matter(matter, actor_id, "verification.override")
        result = VerificationResult(
            matter_id=mid,
            run_id=rid,
            claim_id=claim_id,
            verification_type=verification_type,
            status=status,
            verifier=f"human:{actor_id}",
            detail="decided by a named person"
            + (" (overrides the system result)" if override else ""),
            by_human=True,
            override=override,
            reason=reason.strip(),
        )
        ctx.store.put(result)
        # Existence and status belong to the authority, not to one mention of it. The decision
        # therefore covers every finding in the run that rests on the same authority.
        siblings: list[Claim] = []
        if claim.authority_id and verification_type in (
            VerificationType.CITATION.value,
            VerificationType.CURRENT_LAW.value,
        ):
            siblings = [
                other
                for other in ctx.store.list(Claim, mid, run_id=rid)
                if other.authority_id == claim.authority_id and other.claim_id != claim_id
            ]
            ctx.store.put_many(
                VerificationResult(
                    matter_id=mid,
                    run_id=rid,
                    claim_id=other.claim_id,
                    verification_type=verification_type,
                    status=status,
                    verifier=result.verifier,
                    detail=f"decided by a named person for the same authority ({result.verification_id})",
                    by_human=True,
                    override=override,
                    reason=reason.strip(),
                )
                for other in siblings
            )
        ctx.log(
            "human_verification",
            actor_id=actor_id,
            matter_id=mid,
            run_id=rid,
            action=action,
            subject_id=result.verification_id,
            outcome=status.value,
            object_type="verification",
            verification_status=status.value,
            reviewer_id=actor_id,
            input_hash=content_hash(reason),
            payload={"claim_id": claim_id, "check": verification_type, "override": override},
        )
        covered = {claim_id, *(other.claim_id for other in siblings)}
        for task in ctx.store.list(VerificationTask, mid, run_id=rid, status=TaskStatus.OPEN.value):
            if task.claim_id in covered and task.verification_type == verification_type:
                task.status = TaskStatus.DONE
                task.completed_by, task.completed_at = actor_id, utcnow()
                task.result_verification_id = result.verification_id
                ctx.store.put(task)
        self._log_digest(matter, rid, actor_id)
        for affected in (claim, *siblings):
            self.reevaluate(matter, affected, actor_id=actor_id)
        return result

    def _log_digest(self, matter: Matter, run_id: str, actor_id: str) -> None:
        results = self.ctx.store.list(VerificationResult, matter.matter_id, run_id=run_id)
        self.ctx.log(
            "verification_batch",
            actor_id=actor_id,
            matter_id=matter.matter_id,
            run_id=run_id,
            action="verification.record",
            subject_id=run_id,
            outcome="recorded",
            object_type="verification_set",
            output_hash=verification_digest(results),
            payload={"results": len(results)},
        )

    def reevaluate(self, matter: Matter, claim: Claim, *, actor_id: str) -> Claim:
        """Re-apply the gate to one finding and close its holds if it now passes."""
        ctx = self.ctx
        if claim.status in (ClaimStatus.EXCLUDED, ClaimStatus.REJECTED):
            return claim
        results = [
            r
            for r in ctx.store.list(VerificationResult, matter.matter_id, run_id=claim.run_id)
            if r.claim_id == claim.claim_id
        ]
        apply_decision(claim, evaluate_claim(claim, results))
        ctx.store.put(claim)
        if claim.status is ClaimStatus.VERIFIED:
            for hold in ctx.holds.open_holds(matter.matter_id, claim.run_id):
                if hold.scope is HoldScope.CLAIM and hold.subject_id == claim.claim_id:
                    ctx.holds.resolve(
                        hold,
                        resolved_by=actor_id,
                        resolution=HoldResolution.REVERIFIED,
                        reason="every required check now passes",
                    )
        return claim


@dataclass(slots=True)
class HoldService:
    ctx: AppContext

    def list(
        self, matter_id: str, run_id: str, *, actor_id: str, open_only: bool = True
    ) -> list[Hold]:
        matter = self.ctx.matter_for(matter_id, actor_id, "matter.read")
        holds = self.ctx.holds.all_holds(matter.matter_id, run_id)
        return [h for h in holds if not open_only or h.status is HoldStatus.OPEN]

    def resolve(
        self, matter_id: str, hold_id: str, *, actor_id: str, action: str, reason: str
    ) -> Hold:
        """Close a hold by a named decision: ``exclude`` or ``waive``.

        A hold on a finding closes by itself once its checks pass; a person closes it only by
        taking the finding out of reliance. A hold on a document closes by accepting the gap or
        by removing the document from the analysis.
        """
        ctx = self.ctx
        matter = ctx.matter_for(matter_id, actor_id, "hold.resolve")
        if ctx.user(actor_id).actor_type is not ActorType.HUMAN:
            raise PolicyDenied("only a human user may resolve a hold")
        hold = ctx.store.get(Hold, matter.matter_id, hold_id)
        if hold is None:
            raise NotFound(f"hold not found in this matter: {hold_id}")
        if hold.status is not HoldStatus.OPEN:
            raise InvalidState("hold is already resolved")
        if len(reason.strip()) < 10:
            raise InvalidInput("give the reason for this decision")
        mid = matter.matter_id

        if hold.scope is HoldScope.CLAIM:
            if action != "exclude":
                raise InvalidState(
                    "a held finding is released by passing its checks (record a verification "
                    "result) or removed with action 'exclude'"
                )
            claim = ctx.store.require(Claim, mid, hold.subject_id)
            claim.status = ClaimStatus.EXCLUDED
            claim.status_reason = f"excluded by {actor_id}: {reason.strip()[:200]}"
            ctx.store.put(claim)
            for task in ctx.store.list(VerificationTask, mid, run_id=hold.run_id, status="open"):
                if task.claim_id == claim.claim_id:
                    task.status = TaskStatus.CANCELLED
                    ctx.store.put(task)
            return ctx.holds.resolve(
                hold, resolved_by=actor_id, resolution=HoldResolution.EXCLUDED, reason=reason
            )

        if hold.scope is HoldScope.DOCUMENT:
            ctx.authorizer().require_matter(matter, actor_id, "document.waive")
            document = ctx.store.require(Document, mid, hold.subject_id)
            if hold.reason_code == "coverage_gap" and action == "waive":
                document.status = DocumentStatus.WAIVED
                document.waived_by, document.waiver_reason = actor_id, reason.strip()[:200]
                ctx.store.put(document)
                return ctx.holds.resolve(
                    hold, resolved_by=actor_id, resolution=HoldResolution.WAIVED, reason=reason
                )
            if hold.reason_code == "prompt_injection_detected" and action == "waive":
                # The person has read the flagged text and accepts it as ordinary evidence.
                return ctx.holds.resolve(
                    hold, resolved_by=actor_id, resolution=HoldResolution.WAIVED, reason=reason
                )
            if action == "exclude":
                ctx.store.replace_chunks(mid, document.document_id, [])
                document.status = DocumentStatus.WAIVED
                document.waived_by = actor_id
                document.waiver_reason = f"removed from analysis: {reason.strip()[:160]}"
                ctx.store.put(document)
                return ctx.holds.resolve(
                    hold, resolved_by=actor_id, resolution=HoldResolution.EXCLUDED, reason=reason
                )
            raise InvalidState("a document hold is closed with action 'waive' or 'exclude'")

        raise InvalidState(
            "a hold on a step clears when the cause is corrected and the run is restarted "
            "by an authorised person"
        )
