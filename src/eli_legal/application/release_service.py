from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from eli_legal.application.container import AppContext
from eli_legal.application.reliance_service import require_reliance
from eli_legal.domain.enums import Profile, ReviewDecision, RunStatus, StepStatus
from eli_legal.domain.errors import InvalidState, NotFound, VerificationGateFailed
from eli_legal.domain.models import HumanReview, Matter, Report, Run
from eli_legal.domain.release import Recipient, ReleasePackage
from eli_legal.workflows.runner import record_person_step


@dataclass(slots=True)
class ReleaseService:
    """Prepare an immutable, approved report version for human-approved delivery."""

    ctx: AppContext

    def _entitled(self, matter: Matter, report: Report, recipient_id: str) -> bool:
        """Whether a recipient may receive this report at all. Derived, never caller-declared.

        People with access to the matter may. A party may only receive a version built for
        sharing, or — where the matter belongs to a party's own lawyers — if it is their client.
        """
        if recipient_id == matter.owner_user_id or recipient_id in matter.authorised_user_ids:
            return True
        party_ids = {p.party_id for p in matter.parties}
        if recipient_id not in party_ids:
            return False
        if report.audience == "shared":
            return True
        return (
            matter.profile is Profile.PARTY_REPRESENTATIVE
            and recipient_id == matter.represented_party_id
        )

    def prepare(
        self,
        matter_id: str,
        run_id: str,
        *,
        actor_id: str,
        recipients: Sequence[tuple[str, str, str]],
        classification: str = "privileged_confidential",
    ) -> ReleasePackage:
        """``recipients`` are (recipient_id, display_name, address) triples."""
        ctx = self.ctx
        matter = ctx.matter_for(matter_id, actor_id, "report.prepare_release")
        mid = matter.matter_id
        run = ctx.store.get(Run, mid, run_id)
        if run is None:
            raise NotFound(f"run not found in this matter: {run_id}")
        if run.status is not RunStatus.APPROVED_FOR_RELIANCE or run.hard_gate_reasons:
            raise VerificationGateFailed("run is not eligible for release preparation")
        require_reliance(ctx, mid, run_id, actor_id=actor_id, action="report.prepare_release")
        report = ctx.store.get(Report, mid, run.report_id or "")
        if report is None or report.release_status != "APPROVED_FOR_RELIANCE":
            raise VerificationGateFailed("there is no approved report for this run")
        approvals = [
            r
            for r in ctx.store.list(HumanReview, mid, run_id=run_id)
            if r.decision is ReviewDecision.APPROVE
        ]
        if not approvals:
            raise VerificationGateFailed("no approving review is recorded for this run")
        artifact = Path(report.artifact_ref)
        if not artifact.is_file():
            raise FileNotFoundError(artifact)
        report_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if report_hash != report.sha256:
            raise VerificationGateFailed("the approved report file no longer matches its hash")
        if not recipients:
            raise InvalidState("a release needs at least one recipient")
        package = ReleasePackage(
            matter_id=mid,
            run_id=run_id,
            report_id=report.report_id,
            report_version=str(report.version),
            report_hash=report_hash,
            artifact_ref=str(artifact),
            approved_review_id=approvals[-1].review_id,
            prepared_by=actor_id,
            recipients=tuple(
                Recipient(
                    recipient_id=rid,
                    display_name=name,
                    address=address,
                    authorised_for_matter=self._entitled(matter, report, rid),
                )
                for rid, name, address in recipients
            ),
            classification=classification,
        )
        ctx.store.put(package)
        ctx.log(
            "release_prepared",
            actor_id=actor_id,
            matter_id=mid,
            run_id=run_id,
            action="report.prepare_release",
            subject_id=package.release_id,
            outcome="prepared",
            object_type="release_package",
            output_hash=report_hash,
            reviewer_id=approvals[-1].reviewer_user_id,
            payload={
                "report_id": report.report_id,
                "report_version": report.version,
                "recipient_ids": [r.recipient_id for r in package.recipients],
                "not_entitled": [
                    r.recipient_id for r in package.recipients if not r.authorised_for_matter
                ],
                "classification": classification,
            },
        )
        record_person_step(
            ctx.store,
            ctx.audit,
            matter_id=mid,
            run_id=run_id,
            step_id="prepare_release",
            status=StepStatus.OK,
            actor_id=actor_id,
            detail=f"prepared for {len(package.recipients)} recipient(s) by {actor_id}",
            outputs={"release_id": package.release_id, "report_hash": report_hash},
        )
        return package
