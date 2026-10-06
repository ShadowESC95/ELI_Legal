from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .enums import ClaimStatus, MatterStatus, ReviewDecision, RunStatus, VerificationStatus


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class Matter:
    name: str
    purpose: str
    jurisdiction: str
    owner_user_id: str
    matter_id: str = field(default_factory=lambda: new_id("mat"))
    status: MatterStatus = MatterStatus.DRAFT
    approved_source_ids: set[str] = field(default_factory=set)
    approved_tool_ids: set[str] = field(default_factory=set)
    authorised_user_ids: set[str] = field(default_factory=set)


@dataclass(slots=True, frozen=True)
class SourceVersion:
    source_id: str
    source_version_id: str
    uri: str
    content_hash: str
    retrieved_at: datetime
    effective_at: datetime | None = None
    jurisdiction: str | None = None
    legal_status: str | None = None
    approved: bool = False


@dataclass(slots=True)
class EvidenceLink:
    source_version_id: str
    locator: str
    quote_hash: str | None = None
    relationship: str = "supports"


@dataclass(slots=True)
class Claim:
    matter_id: str
    run_id: str
    text: str
    material: bool = True
    claim_id: str = field(default_factory=lambda: new_id("clm"))
    status: ClaimStatus = ClaimStatus.UNVERIFIED
    evidence: list[EvidenceLink] = field(default_factory=list)
    uncertainty: str | None = None


@dataclass(slots=True)
class VerificationResult:
    matter_id: str
    run_id: str
    claim_id: str
    verification_type: str
    status: VerificationStatus
    verifier: str
    detail: str
    evidence_refs: list[str] = field(default_factory=list)
    verification_id: str = field(default_factory=lambda: new_id("ver"))
    created_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class Run:
    matter_id: str
    initiated_by: str
    run_id: str = field(default_factory=lambda: new_id("run"))
    status: RunStatus = RunStatus.CREATED
    hard_gate_reasons: list[str] = field(default_factory=list)
    model_versions: dict[str, str] = field(default_factory=dict)
    tool_versions: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class HumanReview:
    matter_id: str
    run_id: str
    reviewer_user_id: str
    decision: ReviewDecision
    reasons: str
    reviewer_actor_type: str = "human"
    review_id: str = field(default_factory=lambda: new_id("rev"))
    created_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class AuditEvent:
    event_type: str
    actor_id: str
    matter_id: str
    run_id: str | None
    action: str
    subject_id: str
    outcome: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)
    event_id: str = field(default_factory=lambda: new_id("evt"))
    object_type: str | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    tool_id: str | None = None
    source_ids: list[str] = field(default_factory=list)
    input_hash: str | None = None
    output_hash: str | None = None
    verification_status: str | None = None
    reviewer_id: str | None = None
