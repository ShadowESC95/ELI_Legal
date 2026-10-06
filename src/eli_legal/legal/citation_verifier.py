from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from eli_legal.domain.enums import VerificationStatus as V
from eli_legal.domain.enums import VerificationType
from eli_legal.domain.models import Authority, Claim, VerificationResult, utcnow
from eli_legal.legal.authority_status import applicable_on
from eli_legal.legal.citations import normalise_citation
from eli_legal.ports.legal_sources import LegalSourcePort

VERIFIER_ID = "deterministic/citation-1"


@dataclass(slots=True)
class CitationVerifier:
    """Does the cited authority exist in a source approved for this matter?

    Existence only. Whether the authority is still good law, and whether it supports what it is
    cited for, are separate checks with separate results.
    """

    connectors: Mapping[str, LegalSourcePort]
    relevant_date: date | None = None

    def resolve(self, citation: str) -> list[Authority]:
        key = normalise_citation(citation)
        found: dict[str, Authority] = {}
        for connector in self.connectors.values():
            for authority in connector.resolve(citation_key=key):
                found[authority.authority_id] = authority
        candidates = list(found.values())
        if len(candidates) > 1:
            # Several versions of one instrument share a citation. The one that counts is the
            # version in force on the matter's relevant date (today, if none is set).
            when = self.relevant_date or utcnow().date()
            in_force = [a for a in candidates if applicable_on(a, when)]
            if len(in_force) == 1:
                return in_force
        return candidates

    def verify(self, claim: Claim) -> tuple[VerificationResult, Authority | None]:
        def result(status: V, detail: str, refs: list[str] | None = None) -> VerificationResult:
            return VerificationResult(
                matter_id=claim.matter_id,
                run_id=claim.run_id,
                claim_id=claim.claim_id,
                verification_type=VerificationType.CITATION.value,
                status=status,
                verifier=VERIFIER_ID,
                detail=detail,
                evidence_refs=refs or [],
            )

        if not claim.citation:
            return result(V.FAILED, "the finding names no authority"), None
        if not self.connectors:
            return (
                result(V.INCONCLUSIVE, "no approved legal source is available for this matter"),
                None,
            )
        found = self.resolve(claim.citation)
        if not found:
            pattern_id = (
                claim.origin.rsplit("/", 1)[-1] if claim.origin.startswith("citation:") else ""
            )
            authoritative = [
                c.source_id
                for c in self.connectors.values()
                if pattern_id and pattern_id in c.describe().authoritative_for
            ]
            if authoritative:
                return (
                    result(
                        V.FAILED,
                        "not found in a source that is complete for this kind of citation "
                        f"({', '.join(authoritative)}): possible mis-citation or non-existent authority",
                    ),
                    None,
                )
            return (
                result(
                    V.INCONCLUSIVE,
                    "not found in the approved sources; its existence could not be confirmed",
                ),
                None,
            )
        if claim.authority_id and all(a.authority_id != claim.authority_id for a in found):
            return (
                result(
                    V.CONFLICT,
                    "the citation resolves to a different authority than the one quoted",
                    [a.source_version_id for a in found],
                ),
                None,
            )
        if len(found) > 1 and not claim.authority_id:
            return (
                result(
                    V.CONFLICT,
                    "the citation matches more than one authority in the approved sources",
                    [a.source_version_id for a in found],
                ),
                None,
            )
        authority = next((a for a in found if a.authority_id == claim.authority_id), found[0])
        return (
            result(V.VERIFIED, f"found in {authority.source_id}", [authority.source_version_id]),
            authority,
        )
