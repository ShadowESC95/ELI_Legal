from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from eli_legal.application.container import AppContext
from eli_legal.domain.enums import ActorType, StepStatus
from eli_legal.domain.errors import NotFound
from eli_legal.domain.models import Run
from eli_legal.domain.release import DeliveryReceipt, ReleaseApproval, ReleasePackage
from eli_legal.governance.release_gate import ReleaseGate
from eli_legal.ports.delivery import DeliveryPort
from eli_legal.security import authn
from eli_legal.workflows.runner import record_person_step


@dataclass(slots=True)
class DeliveryService:
    ctx: AppContext
    delivery: DeliveryPort
    release_gate: ReleaseGate

    def distribute(
        self,
        matter_id: str,
        release_id: str,
        *,
        actor_id: str,
        confirmed_recipient_ids: Sequence[str],
    ) -> list[DeliveryReceipt]:
        """A named person confirms the exact recipient list; only then is anything staged."""
        ctx = self.ctx
        authn.require_step_up(actor_id, "release a report")
        matter = ctx.matter_for(matter_id, actor_id, "report.send")
        mid = matter.matter_id
        package = ctx.store.get(ReleasePackage, mid, release_id)
        if package is None:
            raise NotFound(f"release not found in this matter: {release_id}")
        run = ctx.store.require(Run, mid, package.run_id)
        approver = ctx.user(actor_id)
        approval = ReleaseApproval(
            release_id=package.release_id,
            approver_user_id=actor_id,
            approved_review_id=package.approved_review_id,
            report_hash=package.report_hash,
            recipient_ids=tuple(confirmed_recipient_ids),
            # Taken from the user record; a caller cannot declare itself human.
            actor_type="human"
            if approver.actor_type is ActorType.HUMAN
            else approver.actor_type.value,
        )
        self.release_gate.require_distribution(
            run=run, package=package, approval=approval, audit=ctx.audit
        )
        # Do not put addresses or report content into the audit payload.
        ctx.log(
            "release_approval",
            actor_id=actor_id,
            matter_id=mid,
            run_id=run.run_id,
            action="report.send",
            subject_id=package.release_id,
            outcome="approved",
            object_type="release_package",
            output_hash=package.report_hash,
            reviewer_id=actor_id,
            payload={
                "report_id": package.report_id,
                "report_version": package.report_version,
                "recipient_ids": [r.recipient_id for r in package.recipients],
                "classification": package.classification,
            },
        )
        self._step(run, "recipient_approval", StepStatus.OK, actor_id,
                   f"{len(confirmed_recipient_ids)} recipient(s) confirmed by {actor_id}",
                   {"release_id": package.release_id})  # fmt: skip
        try:
            receipts = self.delivery.send(package)
        except Exception as exc:
            package.status = "delivery_failed"
            ctx.store.put(package)
            self._step(run, "controlled_delivery", StepStatus.FAILED, actor_id,
                       f"staging failed: {type(exc).__name__}", {"release_id": package.release_id})  # fmt: skip
            ctx.log(
                "delivery_failure",
                actor_id=actor_id,
                matter_id=mid,
                run_id=run.run_id,
                action="report.delivery",
                subject_id=package.release_id,
                outcome="failed",
                object_type="release_package",
                payload={"error_type": type(exc).__name__},
            )
            raise
        package.status = "delivery_attempted"
        ctx.store.put(package)
        for receipt in receipts:
            ctx.log(
                "delivery_receipt",
                actor_id=actor_id,
                matter_id=mid,
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
        self._step(run, "controlled_delivery", StepStatus.OK, actor_id,
                   "staged in the outbox; nothing was sent", {"release_id": package.release_id})  # fmt: skip
        return receipts

    def _step(
        self, run: Run, step_id: str, status: StepStatus, actor_id: str, detail: str,
        outputs: dict[str, str],
    ) -> None:  # fmt: skip
        record_person_step(
            self.ctx.store, self.ctx.audit, matter_id=run.matter_id, run_id=run.run_id,
            step_id=step_id, status=status, actor_id=actor_id, detail=detail, outputs=outputs,
        )  # fmt: skip
