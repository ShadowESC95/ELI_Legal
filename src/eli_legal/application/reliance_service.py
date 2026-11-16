"""Reliance on an approved report, after its approval.

An approved report rests on authorities checked when the run was made. If one of them is later
found to be no longer good law (overruled, repealed, or no longer confirmed as such), the report
must stop leaving the matter at once: someone may be about to rely on it. That is a
*reliance block* (EL-001).

- ``no_longer_confirmed`` re-checks every authority a run relies on, exactly as a run would
  judge it today. The routine checks use it on every approved report of every open matter, not
  only the latest; resolving a block uses it again, so nothing is lifted on a stale check.
- ``open_or_extend`` records the block and its incident together (one transaction), once per
  report: running the checks again adds to them and never duplicates them.
- ``require_reliance`` is the guard. Preparing a release and sending one both pass through it,
  whichever way they are asked for (desktop, browser, command line, API), and a refusal is
  written to the audit trail.
- ``RelianceService.resolve`` is the only way a block ends. Closing the incident does not end
  it. A named reviewer on the matter, with identity confirmed again and a written basis, either
  lifts it (every authority is confirmed again for this report) or marks it superseded (a later
  run, re-checked and approved after the block opened, replaces the report; this one stays
  barred). The approval and every release already made stay in the record unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from eli_legal.application.container import AppContext
from eli_legal.domain import plain
from eli_legal.domain.enums import (
    ClaimKind,
    ClaimStatus,
    IncidentSeverity,
    ReviewDecision,
    RunStatus,
    VerificationStatus,
)
from eli_legal.domain.errors import (
    InvalidInput,
    InvalidState,
    NotFound,
    PolicyDenied,
    VerificationGateFailed,
)
from eli_legal.domain.models import (
    Authority,
    Claim,
    HumanReview,
    Incident,
    Matter,
    RelianceBlock,
    Report,
    Run,
    VerificationResult,
    utcnow,
)
from eli_legal.domain.profiles import profile_spec
from eli_legal.domain.release import ReleasePackage
from eli_legal.governance.gates import effective_results
from eli_legal.legal.current_law_citator import CurrentLawCitator
from eli_legal.legal.frameworks import combined_rules, tighten_status_age
from eli_legal.security import authn

SYSTEM = "system"
CAUSE = "authority_changed_after_approval"
RELIED = (ClaimKind.PARTY_AUTHORITY, ClaimKind.LEGAL_PROPOSITION)
BARRED = ("active", "superseded")
MIN_BASIS = 40


@dataclass(frozen=True, slots=True)
class Flagged:
    """An authority a run relies on that is no longer confirmed as good law."""

    authority: Authority
    said: str
    claim_ids: tuple[str, ...]


def no_longer_confirmed(
    ctx: AppContext, matter: Matter, run: Run, *, since: datetime | None = None
) -> dict[str, Flagged] | None:
    """Each authority a run relies on that is not confirmed as good law today, by authority id;
    None when the matter has no source to check against (nothing can be said either way).

    A person's own confirmation stands until it is as old as the limit allows, unless the
    source now says something new and negative. With ``since``, only a confirmation made after
    that moment counts: resolving a block needs one made after the block opened."""
    connectors = ctx.connectors_for(matter)
    if not connectors:
        return None
    citator = CurrentLawCitator(connectors)
    packs = [p for i in matter.framework_ids if (p := ctx.frameworks.get(i))]
    rules = combined_rules(packs)
    default_pack = ctx.jurisdictions.for_matter(matter)[0]
    results: dict[str, list[VerificationResult]] = {}
    for r in ctx.store.list(VerificationResult, matter.matter_id, run_id=run.run_id):
        results.setdefault(r.claim_id, []).append(r)
    found: dict[str, tuple[Authority, str, list[str]]] = {}
    for claim in ctx.store.list(Claim, matter.matter_id, run_id=run.run_id):
        if claim.kind not in RELIED or claim.status is not ClaimStatus.VERIFIED:
            continue
        authority = ctx.store.get_authority(claim.authority_id) if claim.authority_id else None
        if authority is None or authority.source_id not in connectors:
            continue
        pack = tighten_status_age(
            ctx.jurisdictions.get(authority.jurisdiction) or default_pack, rules
        )
        result = citator.verify(claim, authority, pack=pack, relevant_date=matter.relevant_date)
        if result.status is VerificationStatus.VERIFIED:
            continue
        human = effective_results(results.get(claim.claim_id, [])).get("current_law")
        if (
            result.status is not VerificationStatus.FAILED
            and human is not None
            and human.by_human
            and human.status is VerificationStatus.VERIFIED
            and (utcnow() - human.created_at).days <= pack.status_max_age_days
            and (since is None or human.created_at > since)
        ):
            continue
        said = plain.check_result("current_law", result.status, result.detail)
        entry = found.setdefault(authority.authority_id, (authority, said, []))
        entry[2].append(claim.claim_id)
    return {k: Flagged(a, s, tuple(c)) for k, (a, s, c) in found.items()}


def barring(ctx: AppContext, matter_id: str, run_id: str) -> list[RelianceBlock]:
    """The blocks that bar this report from leaving the matter."""
    return [
        b for b in ctx.store.list(RelianceBlock, matter_id, run_id=run_id) if b.status in BARRED
    ]


def require_reliance(ctx: AppContext, matter_id: str, run_id: str, *, actor_id: str,
                     action: str) -> None:  # fmt: skip
    """Refuse, and record the refusal, if the report of this run may not be relied on."""
    blocks = barring(ctx, matter_id, run_id)
    if not blocks:
        return
    ctx.log(
        "reliance_denied",
        actor_id=actor_id,
        matter_id=matter_id,
        run_id=run_id,
        action=action,
        subject_id=blocks[0].block_id,
        outcome="denied",
        object_type="reliance_block",
        payload={"blocks": [b.block_id for b in blocks], "statuses": [b.status for b in blocks]},
    )
    first = blocks[0]
    why = (
        "a later run, re-checked and approved, replaces it"
        if first.status == "superseded"
        else "an authority it relies on is no longer confirmed as good law"
    )
    raise VerificationGateFailed(
        f"reliance on this report is suspended ({first.block_id}): {why}. The approval stays "
        "in the record; nothing more may be prepared or sent from it"
    )


def recheck_before_release(ctx: AppContext, matter: Matter, run: Run, *, actor_id: str,
                           action: str) -> None:  # fmt: skip
    """On a real matter, the law a report relies on is checked again at the moment it is to
    leave, not only by the daily checks: an authority no longer confirmed, a source that cannot
    be reached, or a case that needs a person's citator check stops it here, and the report is
    suspended on the record. A practice matter is not relied on and is not re-checked."""
    if not matter.real:
        return
    flagged = no_longer_confirmed(ctx, matter, run)
    if flagged is None:
        reasons = "no approved legal source can be reached to check the law now"
    elif flagged:
        open_or_extend(ctx, matter, run, flagged)
        reasons = "; ".join(f"{f.authority.citation}: {f.said}" for f in flagged.values())
    else:
        return
    ctx.log(
        "release_recheck_failed",
        actor_id=actor_id,
        matter_id=matter.matter_id,
        run_id=run.run_id,
        action=action,
        subject_id=run.run_id,
        outcome="denied",
        object_type="run",
        payload={"authorities": len(flagged or {})},
    )
    raise VerificationGateFailed(
        "the law this report relies on was checked again before release and is not confirmed "
        f"now: {reasons}. Confirm each with a qualified person, or approve a new run"
    )


def open_or_extend(
    ctx: AppContext, matter: Matter, run: Run, flagged: dict[str, Flagged]
) -> tuple[RelianceBlock, bool]:
    """The active block on this report, made with its incident if there is none, or extended
    with any authority not yet in it. Returns the block and whether anything changed."""
    mid = matter.matter_id
    active = [b for b in ctx.store.list(RelianceBlock, mid, run_id=run.run_id)
              if b.status == "active"]  # fmt: skip
    authority_ids = sorted(flagged)
    claim_ids = sorted({c for f in flagged.values() for c in f.claim_ids})
    citations = ", ".join(f.authority.citation for f in flagged.values())
    if active:
        block = active[0]
        new_authorities = [a for a in authority_ids if a not in block.authority_ids]
        new_claims = [c for c in claim_ids if c not in block.claim_ids]
        if not new_authorities and not new_claims:
            return block, False
        block.authority_ids.extend(new_authorities)
        block.claim_ids.extend(new_claims)
        incident = ctx.store.get(Incident, mid, block.incident_id) if block.incident_id else None
        changed: list[object] = [block]
        if incident is not None:
            incident.affected_claim_ids.extend(
                c for c in new_claims if c not in incident.affected_claim_ids
            )
            for a in new_authorities:
                if a not in incident.affected_source_ids:
                    incident.affected_source_ids.append(a)
            changed.append(incident)
        ctx.store.put_many(changed)
        ctx.log(
            "reliance_block_extended",
            actor_id=SYSTEM,
            matter_id=mid,
            run_id=run.run_id,
            action="incident.manage",
            subject_id=block.block_id,
            outcome="active",
            object_type="reliance_block",
            payload={"authorities": len(block.authority_ids), "findings": len(block.claim_ids)},
        )
        return block, True
    report = ctx.store.get(Report, mid, run.report_id or "")
    releases = [
        p
        for p in ctx.store.list(ReleasePackage, mid, run_id=run.run_id)
        if p.status in ("approved_for_delivery", "delivery_attempted")
    ]
    recipients = sorted({r.recipient_id for p in releases for r in p.recipients})
    incident = Incident(
        matter_id=mid,
        run_id=run.run_id,
        category=CAUSE,
        detail=(
            f"Relied on in the approved report and no longer confirmed as good law: {citations}. "
            "Reliance on the report is suspended"
            + (f"; {len(recipients)} recipient(s) already received it" if recipients else "")
        ),
        created_by=SYSTEM,
        severity=IncidentSeverity.HIGH,
        affected_claim_ids=list(claim_ids),
        # The sources, then the authorities: what the incident is about.
        affected_source_ids=sorted({f.authority.source_id for f in flagged.values()})
        + authority_ids,
    )
    block = RelianceBlock(
        matter_id=mid,
        run_id=run.run_id,
        report_id=report.report_id if report else "",
        report_hash=report.sha256 if report else "",
        cause=CAUSE,
        authority_ids=authority_ids,
        claim_ids=claim_ids,
        incident_id=incident.incident_id,
        owner_user_id=matter.owner_user_id,
        release_ids=[p.release_id for p in releases],
        recipient_ids=recipients,
    )
    ctx.store.put_many([incident, block])
    for event, subject, kind in (
        ("incident_opened", incident.incident_id, "incident"),
        ("reliance_block_opened", block.block_id, "reliance_block"),
    ):
        ctx.log(
            event,
            actor_id=SYSTEM,
            matter_id=mid,
            run_id=run.run_id,
            action="incident.manage",
            subject_id=subject,
            outcome="open" if kind == "incident" else "active",
            object_type=kind,
            source_ids=sorted({f.authority.source_id for f in flagged.values()}),
            payload={
                "category": CAUSE,
                "severity": IncidentSeverity.HIGH.value,
                "affected_findings": len(claim_ids),
                "releases_already_made": len(releases),
            },
        )
    return block, True


def standing(ctx: AppContext, matter: Matter, run: Run) -> dict[str, str]:
    """A report's standing now, to show wherever it is read: whether it may be relied on, why
    not, and when the law it rests on was last checked, and from where. A report file keeps the
    status it was approved with; this is what it does not say."""
    from eli_legal.application.checks_service import ChecksService

    blocks = barring(ctx, matter.matter_id, run.run_id)
    if blocks:
        b = blocks[0]
        state = "suspended" if b.status == "active" else "superseded"
        detail = (
            f"reliance suspended since {b.opened_at.date().isoformat()}: an authority it relies "
            "on is no longer confirmed as good law"
            if b.status == "active"
            else f"replaced by a later approved run ({b.superseded_by_run_id})"
        )
    elif not matter.real and run.status is RunStatus.APPROVED_FOR_RELIANCE:
        state, detail = "practice", "a practice matter: reviewed, never for reliance"
    elif run.status is RunStatus.APPROVED_FOR_RELIANCE:
        state, detail = "in_force", "approved for reliance; no status problem detected"
    else:
        state, detail = run.status.value, "not approved for reliance"
    last = ChecksService(ctx).latest()
    law = next((r for r in last.results if r.check_id == "authorities"), None) if last else None
    sources = [ctx.sources.get(i) for i in sorted(matter.approved_source_ids)]
    return {
        "state": state,
        "detail": detail,
        "law_checked_at": last.started_at.isoformat(timespec="minutes") if law and last else "",
        "law_check": law.state if law else "never run",
        "sources": ", ".join(s.name for s in sources if s is not None) or "none approved",
    }


def standing_line(st: dict[str, str]) -> str:
    when = (
        f"law last checked {st['law_checked_at']} UTC by the routine checks ({st['law_check']})"
        if st["law_checked_at"]
        else "the routine checks of the law have not run yet"
    )
    return f"Status now: {st['detail']}; {when}; sources: {st['sources']}."


@dataclass(slots=True)
class RelianceService:
    ctx: AppContext

    def standing(self, matter_id: str, run_id: str, *, actor_id: str) -> dict[str, str]:
        matter = self.ctx.matter_for(matter_id, actor_id, "document.read")
        return standing(self.ctx, matter, self.ctx.store.require(Run, matter.matter_id, run_id))

    def list(self, matter_id: str, *, actor_id: str) -> list[RelianceBlock]:
        matter = self.ctx.matter_for(matter_id, actor_id, "report.review")
        return self.ctx.store.list(RelianceBlock, matter.matter_id)

    def resolve(
        self,
        matter_id: str,
        block_id: str,
        *,
        actor_id: str,
        basis: str,
        superseded_by_run_id: str = "",
    ) -> RelianceBlock:
        """End a block: lift it (every authority confirmed again for this report) or, with
        ``superseded_by_run_id``, mark it superseded by a later run re-checked and approved
        after the block opened. Only a named reviewer who may approve on the matter, with
        identity confirmed again and the basis written down."""
        ctx = self.ctx
        authn.require_step_up(actor_id, "end the suspension of an approved report")
        matter = ctx.matter_for(matter_id, actor_id, "report.approve")
        mid = matter.matter_id
        reviewer = ctx.user(actor_id)
        spec = profile_spec(matter.profile)
        if actor_id not in matter.reviewer_user_ids or not (reviewer.roles & spec.reviewer_roles):
            raise PolicyDenied(
                "only a named reviewer who may approve on this matter can end a suspension"
            )
        block = ctx.store.get(RelianceBlock, mid, block_id)
        if block is None:
            raise NotFound(f"no such suspension on this matter: {block_id}")
        if block.status != "active":
            raise InvalidState(f"this suspension has already ended ({block.status})")
        basis = " ".join(basis.split())
        if len(basis) < MIN_BASIS:
            raise InvalidInput(
                "write down the basis: the legal status found, by whom and from which source, "
                f"and what it means for the report (at least {MIN_BASIS} characters)"
            )
        if superseded_by_run_id:
            approval = self._superseding_approval(matter, block, superseded_by_run_id)
            status, approval_id = "superseded", approval.review_id
        else:
            run = ctx.store.require(Run, mid, block.run_id)
            still = no_longer_confirmed(ctx, matter, run, since=block.opened_at)
            if still is None:
                raise InvalidState("no approved source can be reached to check the law again")
            open_ = [still[a] for a in block.authority_ids if a in still]
            if open_:
                raise InvalidState(
                    "still not confirmed as good law: "
                    + "; ".join(f"{f.authority.citation} ({f.said})" for f in open_)
                    + ". Record a qualified person's confirmation of its current status, "
                    "made after the suspension, on the finding first; or approve a new run "
                    "and mark this report superseded"
                )
            status, approval_id = "lifted", ""

        def end(b: RelianceBlock) -> None:
            if b.status != "active":
                raise InvalidState(f"this suspension has already ended ({b.status})")
            b.status = status
            b.resolved_at = utcnow()
            b.resolved_by = actor_id
            b.resolution_basis = basis
            b.superseded_by_run_id = superseded_by_run_id
            b.approval_id = approval_id

        block = ctx.store.change(RelianceBlock, mid, block_id, end)
        ctx.log(
            "reliance_block_resolved",
            actor_id=actor_id,
            matter_id=mid,
            run_id=block.run_id,
            action="report.approve",
            subject_id=block.block_id,
            outcome=status,
            object_type="reliance_block",
            reviewer_id=actor_id,
            payload={"superseded_by_run": superseded_by_run_id, "approval_id": approval_id},
        )
        return block

    def _superseding_approval(
        self, matter: Matter, block: RelianceBlock, run_id: str
    ) -> HumanReview:
        ctx, mid = self.ctx, matter.matter_id
        run = ctx.store.get(Run, mid, run_id)
        if run is None or run_id == block.run_id:
            raise InvalidInput("name a later run of this matter that replaces the report")
        if run.status is not RunStatus.APPROVED_FOR_RELIANCE:
            raise InvalidState("the later run has not been approved for reliance")
        approvals = [
            r
            for r in ctx.store.list(HumanReview, mid, run_id=run_id)
            if r.decision is ReviewDecision.APPROVE and r.created_at > block.opened_at
        ]
        if not approvals:
            raise InvalidState("the later run was not approved after the suspension opened")
        if barring(ctx, mid, run_id):
            raise InvalidState("the later run is itself suspended from reliance")
        flagged = no_longer_confirmed(ctx, matter, run)
        if flagged:
            raise InvalidState(
                "the later run also relies on law no longer confirmed: "
                + ", ".join(f.authority.citation for f in flagged.values())
            )
        return approvals[-1]
