from __future__ import annotations

from eli_legal.domain.models import Claim, EvidenceLink


class EvidenceMapper:
    def link(self, claim: Claim, evidence: EvidenceLink) -> Claim:
        claim.evidence.append(evidence)
        return claim
