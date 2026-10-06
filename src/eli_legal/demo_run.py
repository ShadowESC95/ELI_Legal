"""Runs the synthetic dispute through the whole lifecycle, narrating each control as it acts.

Used by ``eli-legal demo`` and by the evaluation tests, so what is demonstrated is what is tested.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eli_legal.application.services import Services, build_services
from eli_legal.demo import (
    PARTIES,
    RELEVANT_DATE,
    SOURCE_ID,
    STATED_ISSUES,
    DemoWorkspace,
    build_demo_workspace,
)
from eli_legal.domain.enums import (
    DocumentType,
    HoldScope,
    Profile,
    ReviewDecision,
    VerificationStatus,
)
from eli_legal.domain.errors import EliLegalError
from eli_legal.legal.source_registry import RegisteredSource
from eli_legal.ports.inference import InferencePort
from eli_legal.settings import Settings
from eli_legal.workflows.case_preparation import warning_id

ADMIN, ARBITRATOR, SECRETARY, GOVERNANCE = "admin", "arb.keane", "sec.byrne", "gov.hale"


@dataclass(slots=True)
class DemoResult:
    root: Path
    matter_id: str = ""
    run_id: str = ""
    first_status: str = ""
    final_status: str = ""
    first_holds: list[dict[str, Any]] = field(default_factory=list)
    refusals: dict[str, str] = field(default_factory=dict)
    report_path: str = ""
    evidence_pack: str = ""
    summary: dict[str, Any] = field(default_factory=dict)
    first_summary: dict[str, Any] = field(default_factory=dict)


def demo_settings(root: Path, workspace: DemoWorkspace, **overrides: Any) -> Settings:
    key = root / "secrets" / "audit_hmac.key"
    key.parent.mkdir(parents=True, exist_ok=True)
    if not key.exists():
        fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write(secrets.token_hex(32))
    values: dict[str, Any] = {
        "db_path": root / "data" / "eli_legal.sqlite3",
        "audit_db_path": root / "data" / "audit.sqlite3",
        "audit_key_file": key,
        "data_dir": root / "data" / "matters",
        "artifacts_dir": root / "artifacts",
        "jurisdictions_dir": workspace.jurisdictions,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def setup_demo(services: Services, workspace: DemoWorkspace) -> str:
    """Users, the approved source, the matter and its documents. Returns the matter id."""
    sv = services
    sv.users.bootstrap_admin(ADMIN, "System administrator")
    sv.users.add_user(
        actor_id=ADMIN, user_id=ARBITRATOR, display_name="Aoife Keane", roles=["arbitrator"]
    )
    sv.users.add_user(
        actor_id=ADMIN, user_id=SECRETARY, display_name="Tom Byrne", roles=["tribunal_secretary"]
    )
    sv.users.add_user(
        actor_id=ADMIN, user_id=GOVERNANCE, display_name="Ruth Hale", roles=["governance_officer"]
    )
    sv.sources.register(
        RegisteredSource(
            source_id=SOURCE_ID,
            name="Examplia Law Reports (fictional)",
            jurisdictions=frozenset({"XX"}),
            source_types=("case", "legislation"),
            authority_owner="Examplia Council of Law Reporting (fictional)",
            licence="Synthetic data created for demonstration; no third-party rights",
            terms_reviewed=True,
            freshness="Status is as last confirmed on the date recorded for each authority",
            treatment_semantics="Editorial treatment table: overruled, reversed, amended, repealed",
            authoritative_for=("xx_neutral",),
            inspection="Each record is a file in the demo corpus directory",
        ),
        actor_id=ADMIN,
    )
    sv.sources.approve(SOURCE_ID, actor_id=ADMIN)
    sv.sources.import_corpus(SOURCE_ID, workspace.corpus, actor_id=ADMIN)
    matter = sv.matters.create(
        actor_id=ARBITRATOR,
        name="Harbour Freight Ltd v Northwind Logistics Ltd",
        purpose="Case analysis for the sole arbitrator ahead of the hearing",
        jurisdiction="XX",
        profile=Profile.ADJUDICATOR,
        forum="Arbitration seated at Port Varen, Examplia",
        procedural_rules="Port Varen Arbitration Rules 2020 (fictional)",
        relevant_date=RELEVANT_DATE,
        parties=PARTIES,
        stated_issues=STATED_ISSUES,
    )
    mid = matter.matter_id
    sv.matters.grant(mid, actor_id=ARBITRATOR, user_id=SECRETARY)
    sv.matters.set_reviewers(mid, actor_id=ARBITRATOR, reviewer_ids=[ARBITRATOR])
    sv.matters.set_sources(mid, actor_id=ARBITRATOR, source_ids=[SOURCE_ID])
    matter = sv.matters.get(mid, ARBITRATOR)
    party_by_role = {p.role: p.party_id for p in matter.parties}
    for name, (role, doc_type) in workspace.filing.items():
        sv.ingestion.ingest_path(
            matter=matter,
            actor_id=SECRETARY,
            path=workspace.documents / name,
            party_id=party_by_role.get(role),
            doc_type=DocumentType(doc_type) if doc_type else None,
            custodian="Filed through the tribunal secretary",
        )
    return mid


def run_demo(
    root: str | Path,
    *,
    say: Callable[[str], None] = print,
    inference: InferencePort | None = None,
    verifier: InferencePort | None = None,
    install_network_guard: bool = True,
) -> DemoResult:
    base = Path(root)
    workspace = build_demo_workspace(base / "demo")
    sv = build_services(
        demo_settings(base, workspace),
        inference=inference,
        verifier=verifier,
        install_network_guard=install_network_guard,
    )
    result = DemoResult(root=base)

    def refused(label: str, action: Callable[[], Any]) -> None:
        try:
            action()
        except EliLegalError as exc:
            result.refusals[label] = type(exc).__name__
            say(f"    refused  {label}: {exc}")
        else:
            result.refusals[label] = "ALLOWED"
            say(f"    !! NOT REFUSED: {label}")

    say("1. Set-up: users, one approved legal source, the matter, seven documents")
    mid = result.matter_id = setup_demo(sv, workspace)
    for d in sv.matters.documents(mid, ARBITRATOR):
        flags = f"  flagged: {', '.join(d.injection_flags)}" if d.injection_flags else ""
        say(f"    {d.filename:36s} {d.status.value:11s} {d.doc_type.value}{flags}")

    say("2. First run (started by the tribunal secretary)")
    run = sv.runs.start(mid, actor_id=SECRETARY)
    rid = result.run_id = run.run_id
    first = result.first_summary = sv.runs.summary(mid, rid, actor_id=ARBITRATOR)
    result.first_status = first["status"]
    result.first_holds = first["open_holds"]
    say(f"    run is {first['status'].upper()} with {len(first['open_holds'])} hold(s):")
    for hold in first["open_holds"]:
        say(f"      [{hold['scope']}] {hold['reason']}: {hold['detail']}")

    say("3. What the system refuses while holds are open")
    report = first["report"] or {}
    refused(
        "approve a held run",
        lambda: sv.reviews.decide(
            mid,
            rid,
            actor_id=ARBITRATOR,
            decision=ReviewDecision.APPROVE,
            reasons="Approving without resolving holds",
            report_hash=report.get("sha256", ""),
        ),
    )
    first_hold = sv.holds.list(mid, rid, actor_id=ARBITRATOR)[0]
    refused(
        "secretary resolves a hold",
        lambda: sv.holds.resolve(
            mid,
            first_hold.hold_id,
            actor_id=SECRETARY,
            action="exclude",
            reason="Secretary attempting to clear a hold",
        ),
    )
    refused("administrator opens the matter", lambda: sv.matters.get(mid, ADMIN))

    say("4. The arbitrator deals with each hold, giving reasons")
    claims = {c.claim_id: c for c in sv.verification.claims(mid, rid, actor_id=ARBITRATOR)}
    for hold in sv.holds.list(mid, rid, actor_id=ARBITRATOR):
        still_open = {h.hold_id for h in sv.holds.list(mid, rid, actor_id=ARBITRATOR)}
        if hold.hold_id not in still_open:
            continue  # closed as a consequence of an earlier decision about the same authority
        if hold.scope is HoldScope.DOCUMENT and hold.reason_code == "coverage_gap":
            sv.holds.resolve(
                mid,
                hold.hold_id,
                actor_id=ARBITRATOR,
                action="waive",
                reason="Photograph of the terminal gate; neither party relies on it.",
            )
            say("    waived   the unreadable photograph (gap accepted, recorded)")
        elif hold.scope is HoldScope.DOCUMENT:
            sv.holds.resolve(
                mid,
                hold.hold_id,
                actor_id=ARBITRATOR,
                action="exclude",
                reason="Contains an instruction aimed at an AI system; removed pending enquiry.",
            )
            say("    removed  the file carrying a hidden instruction")
        elif hold.reason_code == "verification_inconclusive":
            claim = claims[hold.subject_id]
            sv.verification.record_human_result(
                mid,
                claim.claim_id,
                actor_id=ARBITRATOR,
                verification_type="current_law",
                status=VerificationStatus.VERIFIED,
                reason="Checked the treatment table today: no negative treatment of this authority.",
            )
            say(f"    verified {claim.citation} by hand (status was stale in the source)")
        elif hold.scope is HoldScope.CLAIM:
            claim = claims[hold.subject_id]
            sv.holds.resolve(
                mid,
                hold.hold_id,
                actor_id=ARBITRATOR,
                action="exclude",
                reason="Authority overruled or not found; not to be relied on.",
            )
            say(f"    excluded {claim.citation} ({hold.reason_code})")

    say("5. Controlled restart by the arbitrator")
    refused(
        "secretary restarts the run",
        lambda: sv.runs.resume(mid, rid, actor_id=SECRETARY, reason="Holds have been dealt with"),
    )
    sv.runs.resume(mid, rid, actor_id=ARBITRATOR, reason="All holds resolved; rebuild the report.")
    summary = sv.runs.summary(mid, rid, actor_id=ARBITRATOR)
    report = summary["report"]
    say(f"    run is {summary['status'].upper()}; report version {report['version']}")

    say("6. Human review")
    refused(
        "approve without acknowledging the stated limits",
        lambda: sv.reviews.decide(
            mid,
            rid,
            actor_id=ARBITRATOR,
            decision=ReviewDecision.APPROVE,
            reasons="Reviewed against the papers.",
            report_hash=report["sha256"],
        ),
    )
    refused(
        "secretary approves",
        lambda: sv.reviews.decide(
            mid,
            rid,
            actor_id=SECRETARY,
            decision=ReviewDecision.APPROVE,
            reasons="Reviewed against the papers.",
            report_hash=report["sha256"],
        ),
    )
    sv.reviews.decide(
        mid,
        rid,
        actor_id=ARBITRATOR,
        decision=ReviewDecision.APPROVE,
        reasons="Checked each finding against its source; the stated limits are accepted.",
        report_hash=report["sha256"],
        acknowledged=[warning_id(w) for w in report["warnings"]],
    )
    say("    approved by the named reviewer, with every limit acknowledged")

    say("7. Release")
    matter = sv.matters.get(mid, ARBITRATOR)
    respondent = next(p for p in matter.parties if p.role == "respondent")
    to_party = sv.releases.prepare(
        mid,
        rid,
        actor_id=ARBITRATOR,
        recipients=[(respondent.party_id, respondent.name, "legal@northwind.example")],
    )
    refused(
        "send the tribunal's memorandum to a party",
        lambda: sv.delivery.distribute(
            mid,
            to_party.release_id,
            actor_id=ARBITRATOR,
            confirmed_recipient_ids=[respondent.party_id],
        ),
    )
    package = sv.releases.prepare(
        mid,
        rid,
        actor_id=ARBITRATOR,
        recipients=[(ARBITRATOR, "Aoife Keane", "a.keane@tribunal.example")],
    )
    receipts = sv.delivery.distribute(
        mid, package.release_id, actor_id=ARBITRATOR, confirmed_recipient_ids=[ARBITRATOR]
    )
    say(f"    staged in the outbox for {receipts[0].recipient_id}; nothing was sent")

    say("8. Evidence pack and audit")
    sv.matters.grant(mid, actor_id=ARBITRATOR, user_id=GOVERNANCE)
    pack = sv.evidence_pack(mid, rid, actor_id=GOVERNANCE)
    chain = sv.ctx.audit.report()
    say(f"    audit chain valid: {chain.ok} ({chain.count} events)")
    say(f"    evidence pack: {pack}")

    final = result.summary = sv.runs.summary(mid, rid, actor_id=ARBITRATOR)
    result.final_status = final["status"]
    result.report_path = final["report"]["path"]
    result.evidence_pack = str(pack)
    say(f"\nRun finished: {final['status']}. Approved report: {result.report_path}")
    return result
