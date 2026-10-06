from __future__ import annotations

from eli_legal.domain.enums import VerificationStatus
from eli_legal.domain.models import VerificationResult
from eli_legal.ports.legal_sources import LegalSourcePort


class CurrentLawCitator:
    def __init__(self, connector: LegalSourcePort) -> None:
        self.connector = connector

    def verify(
        self, *, matter_id: str, run_id: str, claim_id: str, source_version_id: str
    ) -> VerificationResult:
        result = self.connector.get_current_status(source_version_id=source_version_id)
        ok = bool(result.get("current"))
        return VerificationResult(
            matter_id=matter_id,
            run_id=run_id,
            claim_id=claim_id,
            verification_type="current_law",
            status=VerificationStatus.VERIFIED if ok else VerificationStatus.FAILED,
            verifier=type(self.connector).__name__,
            detail=str(result),
            evidence_refs=[source_version_id],
        )
