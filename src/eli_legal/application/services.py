from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eli_legal.adapters.local.outbox import OutboxDeliveryAdapter
from eli_legal.application.container import AppContext, build_context
from eli_legal.application.delivery_service import DeliveryService
from eli_legal.application.incident_service import IncidentService
from eli_legal.application.ingestion_service import IngestionService
from eli_legal.application.matter_service import MatterService, UserService
from eli_legal.application.monitoring_service import MonitoringService
from eli_legal.application.release_service import ReleaseService
from eli_legal.application.review_service import ReviewService
from eli_legal.application.run_service import RunService
from eli_legal.application.source_service import SourceService
from eli_legal.application.verification_service import HoldService, VerificationService
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
    monitoring: MonitoringService

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
    return Services(
        ctx=ctx,
        users=UserService(ctx),
        matters=MatterService(ctx),
        sources=SourceService(ctx),
        ingestion=IngestionService(ctx),
        runs=RunService(ctx),
        verification=VerificationService(ctx),
        holds=HoldService(ctx),
        reviews=ReviewService(ctx),
        releases=ReleaseService(ctx),
        delivery=DeliveryService(
            ctx=ctx,
            delivery=OutboxDeliveryAdapter(Path(ctx.settings.artifacts_dir) / "outbox"),
            release_gate=ReleaseGate(),
        ),
        incidents=IncidentService(ctx),
        monitoring=MonitoringService(ctx),
    )
