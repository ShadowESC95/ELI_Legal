from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eli_legal.adapters.local.outbox import OutboxDeliveryAdapter
from eli_legal.application import archive_service
from eli_legal.application.chat_service import ChatService
from eli_legal.application.checks_service import ChecksService
from eli_legal.application.collection_service import CollectionService
from eli_legal.application.compliance_service import ComplianceService
from eli_legal.application.config_service import ConfigService, NetworkControl
from eli_legal.application.container import AppContext, build_context
from eli_legal.application.delivery_service import DeliveryService
from eli_legal.application.deployment_service import DeploymentService
from eli_legal.application.framework_service import FrameworkService
from eli_legal.application.guidance_service import GuidanceService
from eli_legal.application.incident_service import IncidentService
from eli_legal.application.ingestion_service import IngestionService
from eli_legal.application.matter_service import MatterService, UserService
from eli_legal.application.monitoring_service import MonitoringService
from eli_legal.application.notification_service import NotificationService
from eli_legal.application.party_service import PartyService
from eli_legal.application.preservation_service import PreservationService
from eli_legal.application.release_service import ReleaseService
from eli_legal.application.reliance_service import RelianceService
from eli_legal.application.review_service import ReviewService
from eli_legal.application.run_service import RunService
from eli_legal.application.source_service import SourceService
from eli_legal.application.verification_service import HoldService, VerificationService
from eli_legal.domain.models import HumanReview, RunStep, VerificationResult
from eli_legal.governance.completeness import CompletenessReport, check_run_completeness
from eli_legal.governance.evidence_pack import export_evidence_pack
from eli_legal.governance.release_gate import ReleaseGate
from eli_legal.ports.document_parser import DocumentParserPort
from eli_legal.ports.inference import InferencePort
from eli_legal.settings import Settings


@dataclass(slots=True)
class Services:
    """Everything a front end (CLI, API, or an ELI host) calls. No front end touches the store."""

    ctx: AppContext
    users: UserService
    matters: MatterService
    sources: SourceService
    ingestion: IngestionService
    runs: RunService
    verification: VerificationService
    holds: HoldService
    reviews: ReviewService
    releases: ReleaseService
    delivery: DeliveryService
    incidents: IncidentService
    reliance: RelianceService
    preservation: PreservationService
    deployment: DeploymentService
    monitoring: MonitoringService
    chat: ChatService
    frameworks: FrameworkService
    config: ConfigService
    compliance: ComplianceService
    checks: ChecksService
    guidance: GuidanceService
    network: NetworkControl
    notifications: NotificationService
    parties: PartyService
    released: CollectionService

    def audit_trail(self, *, actor_id: str, matter_id: str | None = None) -> list[dict[str, Any]]:
        """Audit events for a matter, or (with the global right) those that belong to no matter:
        sign-ins, users, sources, configuration."""
        if matter_id:
            matter = self.ctx.matter_for(matter_id, actor_id, "audit.read")
            return list(self.ctx.audit.events(matter_id=matter.matter_id))
        self.ctx.authorizer().require_global(actor_id, "audit.read")
        return list(self.ctx.audit.events(matter_id="-"))

    def run_record(self, matter_id: str, run_id: str, *, actor_id: str) -> CompletenessReport:
        """Reconcile what the store says happened in a run with what the ledger holds."""
        matter = self.ctx.matter_for(matter_id, actor_id, "audit.read")
        mid = matter.matter_id
        return check_run_completeness(
            events=self.ctx.audit.events(matter_id=mid, run_id=run_id),
            steps=self.ctx.store.list(RunStep, mid, run_id=run_id),
            holds=self.ctx.holds.all_holds(mid, run_id),
            reviews=self.ctx.store.list(HumanReview, mid, run_id=run_id),
            verifications=self.ctx.store.list(VerificationResult, mid, run_id=run_id),
        )

    def evidence_pack(
        self, matter_id: str, run_id: str, *, actor_id: str, out_dir: str | Path | None = None
    ) -> Path:
        target = out_dir or Path(self.ctx.settings.artifacts_dir) / "evidence"
        return export_evidence_pack(self.ctx, matter_id, run_id, actor_id=actor_id, out_dir=target)


def build_services(
    settings: Settings | None = None,
    *,
    inference: InferencePort | None = None,
    verifier: InferencePort | None = None,
    parser: DocumentParserPort | None = None,
    install_network_guard: bool = True,
    ctx: AppContext | None = None,
) -> Services:
    ctx = ctx or build_context(
        settings,
        inference=inference,
        verifier=verifier,
        parser=parser,
        install_network_guard=install_network_guard,
    )
    notifications = NotificationService(ctx)
    ingestion = IngestionService(ctx)
    # Each event signed into the ledger may change who must act; the ledger tells the service.
    listen = getattr(ctx.audit, "subscribe", None)
    if callable(listen):
        listen(notifications.on_event)
    # What an earlier version stored, brought up to this one's protection (sealed on disk,
    # archives by kind). A failure is logged and tried again at the next start.
    try:
        archive_service.upgrade(ctx)
    except Exception:  # noqa: BLE001 - the application still opens; the files stay readable
        logging.getLogger(__name__).warning("storage upgrade not completed", exc_info=True)
    return Services(
        ctx=ctx,
        users=UserService(ctx),
        matters=MatterService(ctx),
        sources=SourceService(ctx),
        ingestion=ingestion,
        runs=RunService(ctx),
        verification=VerificationService(ctx),
        holds=HoldService(ctx),
        reviews=ReviewService(ctx),
        releases=ReleaseService(ctx),
        delivery=DeliveryService(
            ctx=ctx,
            delivery=OutboxDeliveryAdapter(
                Path(ctx.settings.artifacts_dir) / "outbox", files=ctx.files
            ),
            release_gate=ReleaseGate(),
        ),
        incidents=IncidentService(ctx),
        reliance=RelianceService(ctx),
        preservation=PreservationService(ctx),
        deployment=DeploymentService(ctx),
        monitoring=MonitoringService(ctx),
        chat=ChatService(ctx),
        frameworks=FrameworkService(ctx),
        config=ConfigService(ctx),
        compliance=ComplianceService(ctx),
        checks=ChecksService(ctx),
        guidance=GuidanceService(ctx),
        network=NetworkControl(ctx),
        notifications=notifications,
        parties=PartyService(ctx, ingestion),
        released=CollectionService(ctx),
    )
