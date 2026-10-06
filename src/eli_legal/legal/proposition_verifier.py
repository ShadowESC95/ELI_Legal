from __future__ import annotations

from dataclasses import dataclass

from eli_legal.domain.enums import VerificationStatus


@dataclass(frozen=True, slots=True)
class PropositionCheck:
    status: VerificationStatus
    rationale: str
    evidence_refs: tuple[str, ...] = ()


class PropositionVerifier:
    """Interface-level placeholder: use independent evidence/tooling, not the drafting agent agreeing with itself."""

    def verify(self, claim_text: str, source_text: str) -> PropositionCheck:
        if not claim_text.strip() or not source_text.strip():
            return PropositionCheck(VerificationStatus.INCONCLUSIVE, "missing claim/source text")
        return PropositionCheck(
            VerificationStatus.INCONCLUSIVE, "specialised proposition verification not configured"
        )
