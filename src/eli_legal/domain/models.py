from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

from .enums import (
    AccessScope,
    ActorType,
    AuthorityKind,
    AuthorityStatus,
    ClaimKind,
    ClaimStatus,
    DocumentStatus,
    DocumentType,
    HoldResolution,
    HoldScope,
    HoldStatus,
    IncidentSeverity,
    MatterStatus,
    Profile,
    ReviewDecision,
    RunStatus,
    StepStatus,
    TaskStatus,
    VerificationStatus,
)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class User:
    user_id: str
    display_name: str
    roles: set[str] = field(default_factory=set)
    actor_type: ActorType = ActorType.HUMAN
    active: bool = True
    created_at: datetime = field(default_factory=utcnow)
    passphrase_hash: str = ""  # pbkdf2_sha256$iterations$salt$hash; empty until one is set


@dataclass(slots=True)
class Party:
    name: str
    role: str  # claimant, respondent, applicant, appellant, third party, ...
    party_id: str = field(default_factory=lambda: new_id("pty"))
    represented_by: str | None = None


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
    profile: Profile = Profile.ADJUDICATOR
    governing_law: str | None = None  # jurisdiction code of the substantive law
    forum: str = ""  # e.g. "Arbitration seated in Dublin under the 2010 Act"
    procedural_rules: str = ""
    # The date as at which the substantive law is assessed (usually when the events occurred).
    relevant_date: date | None = None
    reviewer_user_ids: set[str] = field(default_factory=set)
    parties: list[Party] = field(default_factory=list)
    stated_issues: list[str] = field(default_factory=list)
    represented_party_id: str | None = None  # party-representative profile only
    # The law and standards packages that apply, in the order they were chosen.
    framework_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utcnow)
    closed_at: datetime | None = None
    # Each member's role on this matter (eli_legal.security.access.MATTER_ROLES). Someone on the
    # matter with no entry has the narrowest role that keeps what their account allows.
    member_roles: dict[str, str] = field(default_factory=dict)
    # A member who acts for one party never sees what another party gave in confidence.
    member_parties: dict[str, str] = field(default_factory=dict)
    # Material a member may read, where the lead has set it rather than leaving the role's own.
    member_clearance: dict[str, list[str]] = field(default_factory=dict)


@dataclass(slots=True)
class Document:
    matter_id: str
    filename: str
    sha256: str
    size_bytes: int
    media_type: str
    ingested_by: str
    document_id: str = field(default_factory=lambda: new_id("doc"))
    doc_type: DocumentType = DocumentType.OTHER
    status: DocumentStatus = DocumentStatus.REGISTERED
    access_scope: AccessScope = AccessScope.ALL_PARTIES
    party_id: str | None = None  # the party that filed or disclosed it
    custodian: str = ""  # where it came from; chain-of-custody note
    title: str = ""
    document_date: date | None = None
    vault_ref: str = ""
    segment_count: int = 0
    char_count: int = 0
    error: str = ""
    injection_flags: list[str] = field(default_factory=list)
    waived_by: str | None = None
    waiver_reason: str = ""
    ingested_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class Chunk:
    matter_id: str
    document_id: str
    ordinal: int
    locator: str  # human-checkable position, e.g. "p.3 ¶2"
    text: str
    text_hash: str
    chunk_id: str = field(default_factory=lambda: new_id("chk"))


@dataclass(slots=True)
class EvidenceLink:
    """Ties a claim to the exact words that support (or contradict) it."""

    target_type: str  # "document" (matter evidence) or "authority" (legal source)
    target_id: str
    locator: str
    quote: str = ""
    quote_hash: str | None = None
    chunk_id: str | None = None
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
    kind: ClaimKind = ClaimKind.FACT
    issue_ids: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    party_id: str | None = None
    event_date: date | None = None
    authority_id: str | None = None
    citation: str | None = None
    origin: str = ""  # which extractor/model/prompt produced it
    access_scope: AccessScope = AccessScope.ALL_PARTIES
    status_reason: str = ""
    created_at: datetime = field(default_factory=utcnow)
    # For what a party says of an authority: the passage of the authority closest in meaning,
    # chosen during the run so the report is rebuilt the same without the model. A pointer for
    # the reader, never a finding that the authority supports it.
    closest_passage_id: str = ""


@dataclass(slots=True)
class Issue:
    matter_id: str
    run_id: str
    label: str
    issue_id: str = field(default_factory=lambda: new_id("iss"))
    kind: str = "mixed"  # factual | legal | mixed
    description: str = ""
    source: str = "stated"  # stated at intake | extracted from the papers
    claim_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Treatment:
    """A later event affecting an authority (overruled, amended, repealed, ...)."""

    treatment: str
    effective_date: date
    by_citation: str = ""
    note: str = ""


@dataclass(slots=True)
class Authority:
    """One version of a legal source held in an approved corpus or fetched from a connector."""

    source_id: str
    citation: str
    title: str
    jurisdiction: str
    kind: AuthorityKind = AuthorityKind.CASE
    authority_id: str = field(default_factory=lambda: new_id("aut"))
    source_version_id: str = field(default_factory=lambda: new_id("srv"))
    uri: str = ""
    content_hash: str = ""
    retrieved_at: datetime = field(default_factory=utcnow)
    court: str = ""
    decision_date: date | None = None  # judgment date or enactment date
    effective_from: date | None = None
    effective_to: date | None = None
    status: AuthorityStatus = AuthorityStatus.UNKNOWN
    status_checked_at: datetime | None = None  # when the status was last confirmed at source
    status_basis: str = ""  # who/what says so
    treatments: list[Treatment] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)  # parallel citations


@dataclass(slots=True)
class AuthorityPassage:
    authority_id: str
    ordinal: int
    locator: str
    text: str
    text_hash: str
    passage_id: str = field(default_factory=lambda: new_id("psg"))
    # The heading the source prints above it ("Right to erasure", "Stipulations about time."):
    # searched with the text, never quoted as if it were the text.
    heading: str = ""


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
    by_human: bool = False
    override: bool = False  # a human result that contradicts an automated one
    reason: str = ""


@dataclass(slots=True)
class Run:
    matter_id: str
    initiated_by: str
    run_id: str = field(default_factory=lambda: new_id("run"))
    status: RunStatus = RunStatus.CREATED
    hard_gate_reasons: list[str] = field(default_factory=list)
    model_versions: dict[str, str] = field(default_factory=dict)
    tool_versions: dict[str, str] = field(default_factory=dict)
    prompt_versions: dict[str, str] = field(default_factory=dict)
    # Each law and standards package the run was prepared under: id -> version@fingerprint.
    framework_versions: dict[str, str] = field(default_factory=dict)
    workflow_id: str = ""
    workflow_version: str = ""
    policy_version: str = ""
    reviewer_user_id: str | None = None
    report_id: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None


@dataclass(slots=True)
class RunStep:
    matter_id: str
    run_id: str
    step_id: str
    status: StepStatus = StepStatus.PENDING
    attempt: int = 0
    detail: str = ""
    outputs: dict[str, Any] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def record_id(self) -> str:
        return f"{self.run_id}:{self.step_id}"


@dataclass(slots=True)
class Hold:
    matter_id: str
    run_id: str
    scope: HoldScope
    subject_id: str
    reason_code: str
    detail: str = ""
    hold_id: str = field(default_factory=lambda: new_id("hld"))
    status: HoldStatus = HoldStatus.OPEN
    created_at: datetime = field(default_factory=utcnow)
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution: HoldResolution | None = None
    resolution_reason: str = ""


@dataclass(slots=True)
class VerificationTask:
    """A check the system could not complete on its own and has routed to a named human."""

    matter_id: str
    run_id: str
    claim_id: str
    verification_type: str
    question: str
    task_id: str = field(default_factory=lambda: new_id("tsk"))
    status: TaskStatus = TaskStatus.OPEN
    created_at: datetime = field(default_factory=utcnow)
    completed_by: str | None = None
    completed_at: datetime | None = None
    result_verification_id: str | None = None


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
    report_hash: str | None = None  # the exact report version the reviewer saw
    acknowledged: list[str] = field(default_factory=list)  # warning ids the reviewer accepted


@dataclass(slots=True)
class Report:
    matter_id: str
    run_id: str
    template: str
    audience: str
    sha256: str
    artifact_ref: str
    report_id: str = field(default_factory=lambda: new_id("rpt"))
    version: int = 1
    release_status: str = "NOT_FOR_RELIANCE"
    claim_ids: list[str] = field(default_factory=list)
    excluded_claim_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data_ref: str = ""
    audit_head: str = ""  # ledger head when the draft was built; binds the report to its record
    created_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class Incident:
    matter_id: str
    run_id: str | None
    category: str
    detail: str
    created_by: str
    incident_id: str = field(default_factory=lambda: new_id("inc"))
    severity: IncidentSeverity = IncidentSeverity.MEDIUM
    affected_claim_ids: list[str] = field(default_factory=list)
    affected_source_ids: list[str] = field(default_factory=list)
    status: str = "open"
    containment: str = ""
    created_at: datetime = field(default_factory=utcnow)
    closed_by: str | None = None
    closed_at: datetime | None = None
    closure_reason: str = ""
    # EU AI Act Art. 73, for a serious incident: which deadline applies ("general" 15 days,
    # "death" 10 days, "widespread" 2 days), whether a person decided it is reportable, and
    # when and under what reference it was reported to the market surveillance authority.
    serious_kind: str = ""
    reportable: bool | None = None
    report_decided_by: str | None = None
    report_reason: str = ""
    reported_at: datetime | None = None
    report_reference: str = ""


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


# Kept for callers that used the earlier name for a retrieved source version.
SourceVersion = Authority
