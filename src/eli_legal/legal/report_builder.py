from __future__ import annotations
from dataclasses import dataclass
from eli_legal.domain.models import Claim


@dataclass(slots=True)
class DraftReport:
    matter_id: str
    run_id: str
    text: str
    claim_ids: list[str]
    release_status: str = "NOT_FOR_RELIANCE"


class LegalReportBuilder:
    def build(self, *, matter_id: str, run_id: str, claims: list[Claim]) -> DraftReport:
        eligible = [c for c in claims if c.status.value == "verified"]
        if len(eligible) != len([c for c in claims if c.material]):
            raise ValueError("cannot draft a reliance-ready report from unverified material claims")
        return DraftReport(matter_id, run_id, "", [c.claim_id for c in eligible])
