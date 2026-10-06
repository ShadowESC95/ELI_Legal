from __future__ import annotations

from eli_legal.domain.models import AuditEvent, Matter, Run
from eli_legal.domain.release import DeliveryReceipt, ReleaseApproval, ReleasePackage
from eli_legal.governance.release_gate import ReleaseGate
from eli_legal.ports.audit import AuditPort
from eli_legal.ports.delivery import DeliveryPort
from eli_legal.security.authorizer import MatterAuthorizer


class DeliveryService:
    def __init__(
        self,
        *,
        authorizer: MatterAuthorizer,
        audit: AuditPort,
        delivery: DeliveryPort,
        release_gate: ReleaseGate | None = None,
    ) -> None:
        self.authorizer = authorizer
        self.audit = audit
        self.delivery = delivery
        self.release_gate = release_gate or ReleaseGate()

    def distribute(
        self,
        *,
        matter: Matter,
        run: Run,
        package: ReleasePackage,
        approval: ReleaseApproval,
        actor_id: str,
    ) -> list[DeliveryReceipt]:
        self.authorizer.require_matter(matter, actor_id, "report.send")
        self.release_gate.require_distribution(
            run=run,
            package=package,
            approval=approval,
            audit=self.audit,
        )

        # Do not put email addresses or report content into the audit payload.
        self.audit.append(
            AuditEvent(
                event_type="release_approval",
                actor_id=actor_id,
                matter_id=matter.matter_id,
                run_id=run.run_id,
                action="report.send",
                subject_id=package.release_id,
                outcome="approved",
                object_type="release_package",
                output_hash=package.report_hash,
                reviewer_id=approval.approver_user_id,
                payload={
                    "report_id": package.report_id,
                    "report_version": package.report_version,
                    "recipient_ids": [r.recipient_id for r in package.recipients],
                    "classification": package.classification,
                },
            )
        )

        try:
            receipts = self.delivery.send(package)
        except Exception as exc:
            package.status = "delivery_failed"
            self.audit.append(
                AuditEvent(
                    event_type="delivery_failure",
                    actor_id=actor_id,
                    matter_id=matter.matter_id,
                    run_id=run.run_id,
                    action="report.delivery",
                    subject_id=package.release_id,
                    outcome="failed",
                    object_type="release_package",
                    payload={"error_type": type(exc).__name__},
                )
            )
            raise

        package.status = "delivery_attempted"
        for receipt in receipts:
            self.audit.append(
                AuditEvent(
                    event_type="delivery_receipt",
                    actor_id=actor_id,
                    matter_id=matter.matter_id,
                    run_id=run.run_id,
                    action="report.delivery",
                    subject_id=receipt.delivery_id,
                    outcome=receipt.status,
                    object_type="delivery_receipt",
                    payload={
                        "release_id": package.release_id,
                        "recipient_id": receipt.recipient_id,
                        "channel": receipt.channel,
                    },
                )
            )
        return receipts
