from __future__ import annotations
from eli_legal.domain.enums import VerificationStatus
from eli_legal.domain.models import VerificationResult
from eli_legal.ports.legal_sources import LegalSourcePort


class CitationVerifier:
    def __init__(self, connector: LegalSourcePort) -> None:
        self.connector = connector

    def verify(self, *, matter_id: str, run_id: str, claim_id: str, citation: str) -> VerificationResult:
        result = self.connector.verify_citation(citation=citation)
        ok = bool(result.get("exists")) and result.get("pinpoint_valid", True) is not False
        return VerificationResult(
            matter_id=matter_id, run_id=run_id, claim_id=claim_id,
            verification_type="citation", status=VerificationStatus.VERIFIED if ok else VerificationStatus.FAILED,
            verifier=type(self.connector).__name__, detail=str(result)
        )
