"""The evidence each RAIMS control must leave for one run, taken from the run's own records.

The RAIMS control map names, for each of its five controls, the minimum evidence fields, who
owns them and when they must exist (control_families.csv):

- RM-01: risk limit; exception or hold; action; decision; restart authorisation.
- HO-01: reviewer id; report hash; known limits; approve or reject reason.
- TR-01: claim id; source and locator; status and date; visible limitations.
- MO-01: threshold; alert; affected run; owner; follow-up; re-test.
- DG-01: approved source and version; three checks; hold and dependency trace.

This gathers each field from what the run actually recorded (holds, decisions, reviews, findings,
check results, incidents, audit events) and says, field by field, whether it is there. A field
that is not due yet (no report has been reviewed) is said to be not due, not missing. Nothing
here is asserted: it is read from the records, so "proving the control ran" (RAIMS Week 6) is
a matter of looking at this file in the run's evidence pack.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from eli_legal.application.container import AppContext
from eli_legal.domain.enums import ClaimKind, HoldStatus
from eli_legal.domain.models import (
    Claim,
    Hold,
    HumanReview,
    Incident,
    Matter,
    RelianceBlock,
    Report,
    Run,
    VerificationResult,
)
from eli_legal.governance.registers import load_register

THREE_CHECKS = ("citation", "current_law", "proposition")


def _field(value: Any, *, due: bool = True) -> dict[str, Any]:
    present = bool(value) or value == 0
    return {"value": value, "present": present, "due": due}


def control_evidence(
    ctx: AppContext,
    matter: Matter,
    run: Run,
    *,
    claims: list[Claim],
    verifications: list[VerificationResult],
    holds: list[Hold],
    reviews: list[HumanReview],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    mid, rid = matter.matter_id, run.run_id
    families = {f["family_id"]: f for f in load_register("families")}
    kinds = Counter(e.get("event_type") for e in events)
    reports = ctx.store.list(Report, mid, run_id=rid)
    incidents = ctx.store.list(Incident, mid, run_id=rid)
    blocks = ctx.store.list(RelianceBlock, mid, run_id=rid)
    decided = [h for h in holds if h.status is not HoldStatus.OPEN]
    restarts = [
        {
            "by": e.get("actor_id"),
            "at": e.get("timestamp") or e.get("created_at"),
            "outcome": e.get("outcome"),
        }
        for e in events
        if e.get("event_type") in ("run_restarted", "run_stopped")
    ]
    by_claim: dict[str, dict[str, str]] = {}
    for v in verifications:
        by_claim.setdefault(v.claim_id, {})[v.verification_type] = v.status.value
    material = [c for c in claims if c.material]
    legal = [
        c for c in material if c.kind in (ClaimKind.PARTY_AUTHORITY, ClaimKind.LEGAL_PROPOSITION)
    ]
    sources = [ctx.sources.get(s) for s in matter.approved_source_ids]
    monitoring = dict(ctx.policy.monitoring)

    out: dict[str, Any] = {}

    out["RM-01"] = {
        "risk_limit": _field(
            {
                "policy": ctx.policy.version,
                "matter": "real" if matter.real else "practice",
                "hard_gate": "a failed, conflicting, inconclusive or missing check holds the run",
            }
        ),
        "exception_or_hold": _field(
            [{"hold": h.hold_id, "reason": h.reason_code, "on": h.scope.value} for h in holds]
            or "no hold was raised"
        ),
        "action": _field(
            [
                {"hold": h.hold_id, "action": h.resolution.value if h.resolution else ""}
                for h in decided
            ]
            or ("none needed" if not holds else []),
            due=bool(holds),
        ),
        "decision": _field(
            [
                {"hold": h.hold_id, "by": h.resolved_by, "reason": h.resolution_reason[:200]}
                for h in decided
            ]
            or ("none needed" if not holds else []),
            due=bool(holds),
        ),
        "restart_authorisation": _field(
            restarts or ("no stop or restart" if not kinds.get("run_restarted") else []),
            due=False,
        ),
    }

    report = reports[-1] if reports else None
    review = reviews[-1] if reviews else None
    out["HO-01"] = {
        "reviewer_id": _field(review.reviewer_user_id if review else "", due=review is not None),
        "report_hash": _field(review.report_hash if review else "", due=review is not None),
        "known_limits": _field(
            {
                "stated": len(report.warnings) if report else 0,
                "acknowledged": len(review.acknowledged) if review else 0,
            }
            if review
            else "",
            due=review is not None,
        ),
        "approve_or_reject_reason": _field(
            {"decision": review.decision.value, "reasons": review.reasons[:300]} if review else "",
            due=review is not None,
        ),
    }

    located = [c for c in material if any(e.locator for e in c.evidence)]
    limited = [
        c for c in material if c.status.value != "verified" and (c.status_reason or c.uncertainty)
    ]
    unverified = [c for c in material if c.status.value != "verified"]
    out["TR-01"] = {
        "claim_id": _field(len(material)),
        "source_and_locator": _field(
            {"material_claims": len(material), "with_source_and_locator": len(located)}
        ),
        "status_and_date": _field(
            {"with_a_status": sum(1 for c in material if c.status), "checked": len(by_claim)}
        ),
        "visible_limitations": _field(
            {"not_verified": len(unverified), "with_a_stated_limitation": len(limited)}
            if unverified
            else "every material claim is verified",
        ),
    }

    out["MO-01"] = {
        "threshold": _field(monitoring),
        "alert": _field(
            {
                "holds": len(holds),
                "incidents": len(incidents),
                "reliance_suspensions": len(blocks),
                "people_told": kinds.get("notification_sent", 0),
            }
        ),
        "affected_run": _field(rid),
        "owner": _field(
            sorted({i.owner_user_id or i.created_by for i in incidents})
            or "no incident needed an owner",
            due=False,
        ),
        "follow_up": _field(
            {
                "holds_decided": len(decided),
                "incidents_closed": sum(1 for i in incidents if i.status == "closed"),
                "suspensions_resolved": sum(1 for b in blocks if b.status != "active"),
            }
        ),
        "re_test": _field({"restarts": kinds.get("run_restarted", 0), "routine_checks": "daily"}),
    }

    three = {
        c.claim_id: {
            check: by_claim.get(c.claim_id, {}).get(check, "not run") for check in THREE_CHECKS
        }
        for c in legal
    }
    dependents = [c for c in claims if c.depends_on]
    out["DG-01"] = {
        "approved_source_and_version": _field(
            [
                {
                    "source": s.source_id,
                    "licence": s.licence,
                    "approved_by": s.approved_by,
                    "approved_at": s.approved_at.isoformat() if s.approved_at else None,
                }
                for s in sources
                if s is not None
            ]
        ),
        "three_checks": _field(
            {
                "legal_claims": len(three),
                "with_all_three": sum(
                    1 for checks in three.values() if all(v != "not run" for v in checks.values())
                ),
            }
            if three
            else "no legal claim in this run",
            due=bool(three),
        ),
        "hold_and_dependency_trace": _field(
            {
                "claims_relying_on_others": len(dependents),
                "held_because_what_they_rely_on_is_held": sum(
                    1 for h in holds if h.reason_code == "dependency_held"
                ),
            }
        ),
    }

    for fid, fields in out.items():
        missing = [name for name, f in fields.items() if f["due"] and not f["present"]]
        family = families.get(fid, {})
        out[fid] = {
            "control": family.get("name", fid),
            "minimum_evidence_fields": family.get("minimum_evidence_fields", ""),
            "evidence_owner": family.get("evidence_owner", ""),
            "when": family.get("when", ""),
            "fields": fields,
            "complete": not missing,
            "missing": missing,
        }
    return out
