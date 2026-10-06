from __future__ import annotations

from eli_legal.domain.enums import RunStatus
from eli_legal.domain.errors import VerificationGateFailed
from eli_legal.domain.models import Run
from eli_legal.domain.release import ReleaseApproval, ReleasePackage
from eli_legal.ports.audit import AuditPort


class ReleaseGate:
    """Final fail-closed gate before a report can leave the matter workspace."""

    def require_distribution(
        self,
        *,
        run: Run,
        package: ReleasePackage,
        approval: ReleaseApproval,
        audit: AuditPort,
    ) -> None:
        if run.matter_id != package.matter_id or run.run_id != package.run_id:
            raise VerificationGateFailed("release package does not belong to this run")
        if run.status is not RunStatus.APPROVED_FOR_RELIANCE:
            raise VerificationGateFailed("run has not been approved for reliance")
        if run.hard_gate_reasons:
            raise VerificationGateFailed("run contains unresolved hard-gate reasons")
        if approval.actor_type.lower() != "human":
            raise VerificationGateFailed("release recipients must be approved by a human")
        if approval.release_id != package.release_id:
            raise VerificationGateFailed("release approval does not match package")
        if approval.approved_review_id != package.approved_review_id:
            raise VerificationGateFailed(
                "release approval does not match the approved legal review"
            )
        if approval.report_hash != package.report_hash:
            raise VerificationGateFailed("approved report hash does not match release package")

        package_recipient_ids = tuple(r.recipient_id for r in package.recipients)
        if approval.recipient_ids != package_recipient_ids:
            raise VerificationGateFailed("approved recipient list does not match package")
        if not package.recipients:
            raise VerificationGateFailed("release has no recipients")
        if any(not recipient.authorised_for_matter for recipient in package.recipients):
            raise VerificationGateFailed("one or more recipients are not authorised for the matter")

        if not audit.verify_chain():
            raise VerificationGateFailed("audit chain verification failed")

        package.status = "approved_for_delivery"
        package.approved_by = approval.approver_user_id
        package.approved_at = approval.created_at
