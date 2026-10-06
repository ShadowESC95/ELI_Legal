"""Verification gates.

A finding is verified only when every check its kind requires has been run and has passed. One
passing check is never enough: that an authority exists says nothing about whether it is still
good law. A failed, conflicting, inconclusive or missing check holds the finding, and a held
finding holds everything that relies on it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from eli_legal.domain.enums import (
    ClaimKind,
    ClaimStatus,
    HoldScope,
    RunStatus,
    VerificationStatus,
    VerificationType,
)
from eli_legal.domain.models import Claim, Hold, Run, VerificationResult

_T = VerificationType

REQUIRED_CHECKS: dict[ClaimKind, frozenset[str]] = {
    ClaimKind.FACT: frozenset({_T.PROVENANCE.value, _T.EVIDENCE_SUPPORT.value}),
    ClaimKind.PROCEDURAL: frozenset({_T.PROVENANCE.value, _T.EVIDENCE_SUPPORT.value}),
    ClaimKind.PARTY_AUTHORITY: frozenset(
        {_T.PROVENANCE.value, _T.EVIDENCE_SUPPORT.value, _T.CITATION.value, _T.CURRENT_LAW.value}
    ),
    ClaimKind.LEGAL_PROPOSITION: frozenset(
        {_T.PROVENANCE.value, _T.CITATION.value, _T.CURRENT_LAW.value, _T.PROPOSITION.value}
    ),
    ClaimKind.APPLICATION: frozenset({_T.DEPENDENCY.value, _T.OUTCOME_BOUNDARY.value}),
}

HARD_VERIFICATION_TYPES = frozenset(t.value for t in VerificationType)

# Worst first. When several automated results exist for one check, the worst one counts.
_SEVERITY = {
    VerificationStatus.FAILED: 0,
    VerificationStatus.CONFLICT: 1,
    VerificationStatus.INCONCLUSIVE: 2,
    VerificationStatus.NOT_RUN: 3,
    VerificationStatus.VERIFIED: 4,
}

# Finding-level reason codes, most serious first.
_REASON_BY_STATUS = {
    VerificationStatus.FAILED: "verification_failed",
    VerificationStatus.CONFLICT: "verification_conflict",
    VerificationStatus.INCONCLUSIVE: "verification_inconclusive",
    VerificationStatus.NOT_RUN: "verification_missing",
}


@dataclass(frozen=True, slots=True)
class GateDecision:
    status: ClaimStatus
    reason_code: str = ""
    detail: str = ""
    failed: tuple[str, ...] = ()
    conflicting: tuple[str, ...] = ()
    inconclusive: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    overridden: tuple[str, ...] = ()  # checks where a human result replaced an automated one

    @property
    def needs_human(self) -> tuple[str, ...]:
        return self.conflicting + self.inconclusive + self.missing


def effective_results(results: Iterable[VerificationResult]) -> dict[str, VerificationResult]:
    """One result per check type: the latest human result if there is one, else the worst."""
    by_type: dict[str, list[VerificationResult]] = {}
    for r in results:
        by_type.setdefault(r.verification_type, []).append(r)
    out: dict[str, VerificationResult] = {}
    for vtype, items in by_type.items():
        human = sorted((r for r in items if r.by_human), key=lambda r: r.created_at)
        if human:
            out[vtype] = human[-1]
        else:
            out[vtype] = min(items, key=lambda r: (_SEVERITY[r.status], r.created_at))
    return out


def evaluate_claim(claim: Claim, results: Sequence[VerificationResult]) -> GateDecision:
    relevant = [r for r in results if r.claim_id == claim.claim_id]
    effective = effective_results(relevant)
    required = REQUIRED_CHECKS.get(claim.kind, REQUIRED_CHECKS[ClaimKind.FACT])

    def of(status: VerificationStatus) -> tuple[str, ...]:
        return tuple(sorted(t for t, r in effective.items() if r.status is status))

    failed, conflicting = of(VerificationStatus.FAILED), of(VerificationStatus.CONFLICT)
    inconclusive = of(VerificationStatus.INCONCLUSIVE)
    missing = tuple(
        sorted(
            t
            for t in required
            if t not in effective or effective[t].status is VerificationStatus.NOT_RUN
        )
    )
    overridden = tuple(sorted(t for t, r in effective.items() if r.override))
    for status, group in (
        (VerificationStatus.FAILED, failed),
        (VerificationStatus.CONFLICT, conflicting),
        (VerificationStatus.INCONCLUSIVE, inconclusive),
        (VerificationStatus.NOT_RUN, missing),
    ):
        if group:
            first = effective.get(group[0])
            return GateDecision(
                status=ClaimStatus.HELD,
                reason_code=_REASON_BY_STATUS[status],
                detail=f"{group[0]}: {first.detail}" if first else f"{group[0]}: check not run",
                failed=failed,
                conflicting=conflicting,
                inconclusive=inconclusive,
                missing=missing,
                overridden=overridden,
            )
    return GateDecision(status=ClaimStatus.VERIFIED, overridden=overridden)


def apply_decision(claim: Claim, decision: GateDecision) -> None:
    if claim.status in (ClaimStatus.EXCLUDED, ClaimStatus.REJECTED):
        return  # a human removed it; verification results do not bring it back
    if decision.status is ClaimStatus.VERIFIED:
        claim.status = ClaimStatus.VERIFIED
        claim.status_reason = ""
    elif claim.material:
        claim.status = ClaimStatus.HELD
        claim.status_reason = f"{decision.reason_code} — {decision.detail}"
    else:
        # Not material, so it blocks nothing, but it is never shown as verified.
        claim.status = (
            ClaimStatus.HELD if decision.failed or decision.conflicting else ClaimStatus.UNVERIFIED
        )
        claim.status_reason = f"{decision.reason_code} — {decision.detail}"


def propagate_dependencies(claims: Sequence[Claim]) -> list[Claim]:
    """Hold every finding that relies, directly or indirectly, on one that is not verified."""
    by_id = {c.claim_id: c for c in claims}
    changed: list[Claim] = []
    progressed = True
    while progressed:
        progressed = False
        for claim in claims:
            if claim.status is not ClaimStatus.VERIFIED or not claim.depends_on:
                continue
            bad = [
                d
                for d in claim.depends_on
                if d not in by_id or by_id[d].status is not ClaimStatus.VERIFIED
            ]
            if bad:
                claim.status = ClaimStatus.HELD
                claim.status_reason = (
                    f"dependency_held — relies on {len(bad)} unverified finding(s)"
                )
                changed.append(claim)
                progressed = True
    return changed


def hold_for(claim: Claim, decision: GateDecision) -> Hold:
    return Hold(
        matter_id=claim.matter_id,
        run_id=claim.run_id,
        scope=HoldScope.CLAIM,
        subject_id=claim.claim_id,
        reason_code=decision.reason_code or "dependency_held",
        detail=(decision.detail or claim.status_reason)[:280],
    )


def apply_verification_gate(run: Run, claim: Claim, results: list[VerificationResult]) -> None:
    """Gate one finding and reflect a material hold on the run."""
    decision = evaluate_claim(claim, results)
    apply_decision(claim, decision)
    if claim.material and claim.status is ClaimStatus.HELD:
        run.status = RunStatus.HELD
        reason = (
            "material_verification_missing"
            if decision.reason_code == "verification_missing"
            else "material_verification_failed_or_inconclusive"
        )
        if reason not in run.hard_gate_reasons:
            run.hard_gate_reasons.append(reason)


@dataclass(slots=True)
class GateSummary:
    verified: int = 0
    held: int = 0
    unverified: int = 0
    excluded: int = 0
    holds: list[Hold] = field(default_factory=list)
