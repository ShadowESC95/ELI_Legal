from __future__ import annotations

import hashlib
from pathlib import Path

from eli_legal.domain.enums import RunStatus
from eli_legal.domain.errors import VerificationGateFailed
from eli_legal.domain.models import AuditEvent, Matter, Run
from eli_legal.domain.release import Recipient, ReleasePackage
from eli_legal.ports.audit import AuditPort
from eli_legal.security.authorizer import MatterAuthorizer


class ReleaseService:
    """Prepare an immutable report version for later human-approved delivery."""

    def __init__(self, *, authorizer: MatterAuthorizer, audit: AuditPort) -> None:
        self.authorizer = authorizer
        self.audit = audit

    def prepare(
        self,
        *,
        matter: Matter,
        run: Run,
        actor_id: str,
        report_id: str,
        report_version: str,
        report_artifact: str | Path,
        approved_review_id: str,
        recipients: tuple[Recipient, ...],
        classification: str = "privileged_confidential",
    ) -> ReleasePackage:
        self.authorizer.require_matter(matter, actor_id, "report.prepare_release")
        if run.status is not RunStatus.APPROVED_FOR_RELIANCE or run.hard_gate_reasons:
            raise VerificationGateFailed("run is not eligible for release preparation")

        artifact = Path(report_artifact).expanduser().resolve()
        if not artifact.is_file():
            raise FileNotFoundError(artifact)
        report_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()

        package = ReleasePackage(
            matter_id=matter.matter_id,
            run_id=run.run_id,
            report_id=report_id,
            report_version=report_version,
            report_hash=report_hash,
            artifact_ref=str(artifact),
            approved_review_id=approved_review_id,
            prepared_by=actor_id,
            recipients=recipients,
            classification=classification,
        )
        self.audit.append(
            AuditEvent(
                event_type="release_prepared",
                actor_id=actor_id,
                matter_id=matter.matter_id,
                run_id=run.run_id,
                action="report.prepare_release",
                subject_id=package.release_id,
                outcome="prepared",
                object_type="release_package",
                output_hash=report_hash,
                reviewer_id=approved_review_id,
                payload={
                    "report_id": report_id,
                    "report_version": report_version,
                    "recipient_ids": [r.recipient_id for r in recipients],
                    "classification": classification,
                },
            )
        )
        return package
