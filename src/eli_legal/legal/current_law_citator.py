from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime

from eli_legal.domain.enums import AuthorityKind, AuthorityStatus, VerificationType
from eli_legal.domain.enums import VerificationStatus as V
from eli_legal.domain.models import Authority, Claim, VerificationResult, utcnow
from eli_legal.legal.jurisdictions import JurisdictionPack
from eli_legal.ports.legal_sources import LegalSourcePort, StatusFinding

VERIFIER_ID = "deterministic/current-law-1"

# Enacted or agreed text exists in dated versions; what matters is the version on the relevant
# date. Case law is judged as it stands today, because a later decision changes what the earlier
# one is worth whenever the events happened.
_VERSIONED = {AuthorityKind.LEGISLATION, AuthorityKind.RULE, AuthorityKind.TREATY}


@dataclass(slots=True)
class CurrentLawCitator:
    """Is the authority still good law, independently of whoever cited it?"""

    connectors: Mapping[str, LegalSourcePort]

    def verify(
        self,
        claim: Claim,
        authority: Authority | None,
        *,
        pack: JurisdictionPack,
        relevant_date: date | None,
        now: datetime | None = None,
    ) -> VerificationResult:
        def result(status: V, detail: str) -> VerificationResult:
            return VerificationResult(
                matter_id=claim.matter_id,
                run_id=claim.run_id,
                claim_id=claim.claim_id,
                verification_type=VerificationType.CURRENT_LAW.value,
                status=status,
                verifier=VERIFIER_ID,
                detail=detail,
                evidence_refs=[authority.source_version_id] if authority else [],
            )

        if authority is None:
            return result(
                V.NOT_RUN, "the authority was not identified, so its status was not checked"
            )
        connector = self.connectors.get(authority.source_id)
        if connector is None:
            return result(V.INCONCLUSIVE, "the authority's source is not available to this matter")
        finding = connector.status(authority=authority, as_of=relevant_date)
        return result(
            *self.assess(authority, finding, pack=pack, relevant_date=relevant_date, now=now)
        )

    @staticmethod
    def assess(
        authority: Authority,
        finding: StatusFinding,
        *,
        pack: JurisdictionPack,
        relevant_date: date | None,
        now: datetime | None = None,
    ) -> tuple[V, str]:
        policy = pack.policy_for(authority.kind)
        fail = set(policy.get("fail", []))
        conflict = set(policy.get("conflict", []))
        versioned = authority.kind in _VERSIONED
        use_relevant = versioned and relevant_date is not None
        judged = (
            finding.status_at_relevant_date
            if use_relevant and finding.status_at_relevant_date is not None
            else finding.status_now
        )
        when = f"on {relevant_date.isoformat()}" if use_relevant and relevant_date else "today"
        event = next(
            (
                e
                for e in sorted(finding.events, key=lambda e: e.effective_date, reverse=True)
                if e.treatment.lower() == judged.value
            ),
            None,
        )
        how = (
            f" ({event.treatment} {event.effective_date.isoformat()}"
            + (f" by {event.by_citation}" if event.by_citation else "")
            + ")"
            if event
            else ""
        )
        if judged.value in fail:
            return V.FAILED, f"status {when}: {judged.value}{how}"
        if versioned and judged is AuthorityStatus.AMENDED:
            if use_relevant:
                return (
                    V.FAILED,
                    f"amended before the relevant date{how}; the version held is not the one in "
                    "force on that date",
                )
            return (
                V.CONFLICT,
                f"amended{how} and the matter has no relevant date; a person must confirm which "
                "version applies",
            )
        if judged.value in conflict:
            return V.CONFLICT, f"status {when}: {judged.value}{how}; needs human assessment"
        if judged is AuthorityStatus.UNKNOWN:
            return V.INCONCLUSIVE, "the source holds no status information for this authority"
        checked = finding.checked_at
        age_days = ((now or utcnow()) - checked).days if checked else None
        if age_days is None or age_days > pack.status_max_age_days:
            last = f"last confirmed {checked.date().isoformat()}" if checked else "never confirmed"
            return (
                V.INCONCLUSIVE,
                f"status {last}; older than the {pack.status_max_age_days}-day limit for "
                f"{pack.code}",
            )
        note = ""
        if judged is not finding.status_now:
            note = f"; has since changed (now {finding.status_now.value})"
        basis = f"; basis: {finding.basis}" if finding.basis else ""
        confirmed = checked.date().isoformat() if checked else "unknown"
        return V.VERIFIED, f"status {when}: {judged.value}, confirmed {confirmed}{note}{basis}"
