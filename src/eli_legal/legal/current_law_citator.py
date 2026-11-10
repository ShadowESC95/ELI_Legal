from __future__ import annotations

import re
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

# A provision named in a party's own sentence: "section 25", "s. 25A", "ss 25", "Article 17".
_SECTION = re.compile(r"\b(?:sections?|ss?)\.?\s*(\d+[A-Z]{0,2})\b")
_ARTICLE = re.compile(r"\b(?:articles?|arts?)\.?\s*(\d+[a-z]?)\b", re.I)
_SCHEDULE = re.compile(r"\bschedule\s+(\d+[A-Z]?)\b", re.I)
# How sure the date of a provision's repeal is (``Treatment.note``): exact when blank.
REPEALED_BY_VERSION = "the source says only that it was repealed on or before this date"
REPEALED_IN_PART = "repealed for only part of the legal system"
UNDATED_REPEAL = "the source gives no date for this repeal"


def provision_unit(locator: str) -> str:
    """'s.10(2)' -> 's.10'; 'Art. 17(1)' -> 'Art. 17'; 'Sch. 1 para. 5' unchanged."""
    return re.sub(r"[(].*$", "", locator or "").strip()


def provisions_relied_on(claim: Claim) -> set[str]:
    """The provisions of an Act or regulation a finding rests on: the passage quoted for it, and
    any section, article or schedule a party's own sentence names."""
    out = {
        provision_unit(link.locator)
        for link in claim.evidence
        if link.target_type == "authority" and link.locator
    }
    if claim.kind.value == "party_authority":
        out |= {f"s.{n}" for n in _SECTION.findall(claim.text)}
        out |= {f"Art. {n}" for n in _ARTICLE.findall(claim.text)}
        out |= {f"Sch. {n}" for n in _SCHEDULE.findall(claim.text)}
    return {u for u in out if u}


def _covers(repealed: str, relied: str) -> bool:
    """A repeal of 'Sch. 1' covers 'Sch. 1 para. 5'; one of 's.10' covers 's.10' only."""
    return (
        relied == repealed or relied.startswith(f"{repealed} ") or repealed.startswith(f"{relied} ")
    )


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
        status, detail = self.assess(
            authority, finding, pack=pack, relevant_date=relevant_date, now=now
        )
        if status is not V.FAILED and authority.kind in _VERSIONED:
            status, detail = self.provisions(
                authority, provisions_relied_on(claim), status, detail, relevant_date, now
            )
        return result(status, detail)

    @staticmethod
    def provisions(
        authority: Authority,
        relied: set[str],
        status: V,
        detail: str,
        relevant_date: date | None,
        now: datetime | None = None,
    ) -> tuple[V, str]:
        """An Act in force can hold a provision that is not: the provision relied on is judged
        too. Repealed on or before the date judged: it fails. Repealed since: it stands, with a
        note. Shown repealed with no date: a person must say whether it was in force."""
        judged_on = relevant_date or (now or utcnow()).date()
        when = f"on {judged_on.isoformat()}" if relevant_date else "today"
        notes = []
        for treatment in authority.treatments:
            if not treatment.provision or treatment.treatment.lower() != "repealed":
                continue
            hit = sorted(r for r in relied if _covers(treatment.provision, r))
            if not hit:
                continue
            named = f"{hit[0]} of {authority.citation}"
            repealed_on = treatment.effective_date.isoformat()
            by = f" by {treatment.by_citation}" if treatment.by_citation else ""
            if treatment.note == REPEALED_IN_PART:
                return (
                    V.CONFLICT,
                    f"{named} was repealed for part of the legal system only ({repealed_on}{by}): "
                    f"a person must confirm whether it applied {when}",
                )
            if treatment.note == REPEALED_BY_VERSION:
                if treatment.effective_date <= judged_on:
                    return (
                        V.FAILED,
                        f"{named} was repealed on or before {repealed_on}: not in force {when}",
                    )
                return (
                    V.CONFLICT,
                    f"{named} was repealed on or before {repealed_on}, on a date the source does "
                    f"not give: a person must confirm whether it was in force {when}",
                )
            if treatment.note == UNDATED_REPEAL:
                return (
                    V.CONFLICT,
                    f"{named} is shown as repealed, but the source gives no date for the repeal: "
                    f"a person must confirm whether it was in force {when}",
                )
            if treatment.effective_date <= judged_on:
                return V.FAILED, f"{named} was repealed on {repealed_on}{by}: not in force {when}"
            notes.append(f"{hit[0]} has since been repealed ({repealed_on}{by})")
        return status, detail + "".join(f"; {n}" for n in notes)

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
                if e.treatment.lower() == judged.value and not e.provision
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
