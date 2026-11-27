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
    # A real matter (real people's papers, relied on) needs a current deployment authorisation
    # for its work to start, be approved or leave (EL-005). A practice matter (demonstration,
    # training, testing) needs none, holds no real case material, and every report from it says
    # it is not for reliance. Fixed when the matter is opened.
    real: bool = False
    # How long this matter's content is kept once it is closed, in days. None: the organisation's
    # period (Compliance, OA-09). Set when the matter is opened, and changeable by its lead.
    retention_days: int | None = None
    # Each member's role on this matter (eli_legal.security.access.MATTER_ROLES). Someone on the
    # matter with no entry has the narrowest role that keeps what their account allows.
    member_roles: dict[str, str] = field(default_factory=dict)
    # A member who acts for one party never sees what another party gave in confidence.
    member_parties: dict[str, str] = field(default_factory=dict)
    # Material a member may read, where the lead has set it rather than leaving the role's own.
    member_clearance: dict[str, list[str]] = field(default_factory=dict)
    # Who was on the matter when it was closed, so reopening it can give them access again.
    closed_team: ClosedTeam | None = None
    # When its content was sealed into an encrypted archive and taken out of the working
    # database (None: not archived). Reopening the matter restores it.
    archived_at: datetime | None = None
    # Whether this matter's approved work may train the organisation's own model, and on what
    # basis (the clients' consent, a practice matter, the organisation's policy), set by its lead.
    # Off unless chosen; turning it off removes the matter's training examples.
    training_use: bool = False
    training_basis: str = ""
    # A real matter trains only with its client's consent on record (where and when given).
    training_consent: str = ""
    training_set_by: str | None = None
    training_set_at: datetime | None = None


@dataclass(slots=True)
class ClosedTeam:
    """A closed matter's team and state as they were, kept for reopening it."""

    status: MatterStatus
    authorised_user_ids: set[str] = field(default_factory=set)
    reviewer_user_ids: set[str] = field(default_factory=set)
    member_roles: dict[str, str] = field(default_factory=dict)
    member_parties: dict[str, str] = field(default_factory=dict)
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
    # Pages of a PDF, every one accounted for: read by OCR (page → confidence, 0-100), not read
    # (an image that could not be read), blank (no text, no image), or with images beside the
    # text that were not read. A person who checks an unread or a low-confidence page against
    # the original records it, page by page.
    # Which version of the reader read it. A PDF read before every page was accounted for
    # ("" or an older version) is read again from its original before the next run.
    read_with: str = ""
    ocr_pages: dict[str, float] = field(default_factory=dict)
    ocr_engine: str = ""
    unread_pages: list[int] = field(default_factory=list)
    blank_pages: list[int] = field(default_factory=list)
    pictured_pages: list[int] = field(default_factory=list)
    pages_checked: list[int] = field(default_factory=list)
    waived_by: str | None = None
    waiver_reason: str = ""
    ingested_at: datetime = field(default_factory=utcnow)
    # What a person typed from the original where it could not be read (a photograph, a damaged
    # scan): who, and why; the words are passages marked as theirs.
    described_by: str | None = None
    description_reason: str = ""


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
    # The issues a fact was linked to by meaning alone (not its words, not a model), which the
    # report marks for the reviewer to check: meaning finds more links, and some are wrong.
    meaning_issue_ids: list[str] = field(default_factory=list)


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
    # The one provision it affects ("s.25", "Art. 17"), when not the whole authority: a section
    # repealed in an Act otherwise in force.
    provision: str = ""


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
class HoldAnswer:
    """A party's answer to a hold on one of its own filings. It closes nothing: the tribunal
    reads it and then decides the hold."""

    by: str  # the party's representative who answered
    party_id: str
    kind: str  # "refiled" (a readable copy was filed), "withdraw" (asks to withdraw it), "explain"
    reasons: str
    replacement_document_id: str | None = None
    at: datetime = field(default_factory=utcnow)


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
    answers: list[HoldAnswer] = field(default_factory=list)  # from the party that filed it


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
    # EL-006: Art. 73 counts from when the provider (or deployer) became aware, which may be
    # before the incident was entered here. Who became aware, when, and how; who owns the
    # incident and who stands in; when it was escalated to the stand-in.
    occurred_at: datetime | None = None
    aware_at: datetime | None = None
    aware_by: str = ""
    awareness_basis: str = ""
    owner_user_id: str = ""
    backup_user_id: str = ""
    escalated_at: datetime | None = None


@dataclass(slots=True)
class RelianceBlock:
    """An approved report that may no longer be relied on: an authority it relies on was found,
    after approval, to be no longer good law (or no longer confirmed as such).

    The approval stays in the record as it was; what the block changes is whether the report
    may now be prepared for release or sent. ``active``: nothing may leave. ``superseded``: a
    later run of the matter, re-checked and approved, replaces this report, which stays barred.
    ``lifted``: the authorities were confirmed again for this report by a named reviewer, with
    the basis recorded. Closing the incident never changes a block."""

    matter_id: str
    run_id: str
    report_id: str
    report_hash: str
    cause: str
    block_id: str = field(default_factory=lambda: new_id("blk"))
    severity: IncidentSeverity = IncidentSeverity.HIGH
    authority_ids: list[str] = field(default_factory=list)
    claim_ids: list[str] = field(default_factory=list)
    incident_id: str = ""
    owner_user_id: str = ""
    # Releases of this report already made, and to whom: software cannot recall them, so the
    # people who received it are to be told (an impact and notification task for the owner).
    release_ids: list[str] = field(default_factory=list)
    recipient_ids: list[str] = field(default_factory=list)
    status: str = "active"
    opened_at: datetime = field(default_factory=utcnow)
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_basis: str = ""
    superseded_by_run_id: str = ""
    approval_id: str = ""


@dataclass(slots=True)
class Notification:
    """Work waiting for a named person: holds to clear, a report to review, an approved report
    suspended. Shown inside ELI Legal to each person who can act on it, wherever they are signed
    in; it is never sent outside the system. ``open``: not seen yet; ``read``: seen; ``done``: the
    work has moved on (cleared, decided, or no longer theirs). Holds ids and counts, never content.
    """

    matter_id: str
    user_id: str
    # holds_open | restart_needed | review_required | reviewer_needed | returned |
    # reliance_suspended
    kind: str
    subject_id: str
    title: str
    detail: str = ""
    page: str = "review"  # the page the person acts on
    actions: list[str] = field(default_factory=list)
    run_id: str | None = None
    notification_id: str = field(default_factory=lambda: new_id("ntf"))
    status: str = "open"
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    read_at: datetime | None = None
    done_at: datetime | None = None


@dataclass(slots=True)
class PreservationHold:
    """A legal hold on a matter's content: nothing it covers is deleted, at closure or when the
    retention period ends, until it is released (EL-004). Not a workflow hold: it does not stop
    the work, it stops disposal. ``document_ids`` empty: the whole matter; otherwise only those
    documents (their originals, records and text) are kept and the rest may go."""

    matter_id: str
    legal_basis: str
    authority: str
    opened_by: str
    hold_id: str = field(default_factory=lambda: new_id("pres"))
    scope: str = "matter"
    document_ids: list[str] = field(default_factory=list)
    status: str = "active"
    opened_at: datetime = field(default_factory=utcnow)
    review_by: date | None = None
    released_by: str | None = None
    released_at: datetime | None = None
    release_reason: str = ""
    run_id: str | None = None


@dataclass(slots=True)
class DeploymentAuthorisation:
    """The deploying organisation's and the provider's approval to use ELI Legal on real matters
    (EL-005): for what, where, on which kinds of matter, on what evidence, until when, and for
    exactly which version of the software, policy and model. Approved once a provider lead and
    a different deployer lead have both signed; void when it expires, is revoked, or what it
    was approved for changes."""

    intended_use: str
    provider: str
    deployer: str
    jurisdictions: list[str]
    profiles: list[str]
    effective_from: date
    expires_on: date
    proposed_by: str
    authorisation_id: str = field(default_factory=lambda: new_id("dep"))
    environment: str = "production"
    data_classes: list[str] = field(default_factory=list)
    # References to the documents relied on: the design review, the lawyer's validation of the
    # legal-system packs, the security assessment, the accuracy evaluation, the data-protection
    # and fundamental-rights impact assessments.
    evidence: dict[str, str] = field(default_factory=dict)
    # What it was approved for: software version, policy, model.
    pinned: dict[str, str] = field(default_factory=dict)
    provider_signed_by: str = ""
    provider_signed_at: datetime | None = None
    deployer_signed_by: str = ""
    deployer_signed_at: datetime | None = None
    status: str = "proposed"  # proposed | approved | revoked
    proposed_at: datetime = field(default_factory=utcnow)
    revoked_by: str = ""
    revoked_at: datetime | None = None
    revoke_reason: str = ""


@dataclass(slots=True)
class TrainingExample:
    """One supervised example for the organisation's own model: a model call made during a run a
    named reviewer approved, with the parties' names and contact details replaced, and the answer
    a person approved. Kept with its matter, so it is erased with the matter's content."""

    matter_id: str
    run_id: str
    task: str
    prompt_version: str
    system: str
    prompt: str
    answer: str  # the answer to train on: JSON text
    model_answer: str  # what the model answered at the time
    example_id: str = field(default_factory=lambda: new_id("tex"))
    # candidate (waiting for a person) | approved | rejected
    status: str = "candidate"
    # Where its answer comes from: "reviewer_unchanged" (the run's reviewer approved what was
    # built from it, nothing taken out), "reviewer_corrected" (a reviewer took findings out: a
    # person must check the answer), "edited" (a person rewrote it).
    source: str = ""
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_note: str = ""
    # train | heldout: examples kept back to evaluate a trained model, never trained on.
    split: str = "train"
    content_hash: str = ""
    # What was taken out of it before it was kept, by kind: {"name": 3, "amount": 1, ...}.
    omitted: dict[str, int] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class TrainingPolicy:
    """How this organisation trains its own model."""

    # human: a person approves each example. autonomous: examples a reviewer accepted unchanged
    # are approved by that review, and training and evaluation start by themselves; switching a
    # trained model on always needs a second person.
    mode: str = "human"
    min_examples: int = 40
    heldout_percent: int = 10
    # Training is off until the compliance officer switches it on, recording the data protection
    # impact assessment (GDPR Art. 35), the legal basis for using case material to train, and
    # that the organisation has been told training may make it the provider of the system it
    # changes (EU AI Act Art. 25(1)(b)).
    enabled: bool = False
    dpia_reference: str = ""
    legal_basis: str = ""
    provider_acknowledged: bool = False
    # Which matters may teach: "practice" (practice matters only, the default) or "consented"
    # (real matters too, each with its client's consent on record). One model learns from every
    # matter it is trained on and can repeat what it learnt in another client's work: consented
    # scope needs the compliance officer to acknowledge that, and every model is tested for it.
    scope: str = "practice"
    cross_matter_acknowledged: bool = False
    # What is taken out of every example besides names, contact details and identifying numbers
    # (always): amounts, dates, references, addresses. Keeping any needs a reason on record.
    omit: list[str] = field(default_factory=lambda: ["amounts", "dates", "references", "addresses"])
    keep_reason: str = ""
    # No real matter gives more than this share of what a model trains on.
    max_matter_share: int = 25
    updated_by: str = ""
    updated_at: datetime | None = None
    # Autonomous mode's standing instruction, set by the technical officer: the base model, the
    # recipe and the GGUF form an automatic run uses. Its runs are trained in their name.
    auto_base: str = ""
    auto_recipe: str = "standard"
    auto_quantize: str = "q4_k_m"
    auto_set_by: str = ""
    auto_set_at: datetime | None = None


@dataclass(slots=True)
class TrainedModel:
    """A model the organisation trained, with what went into it and who decided what."""

    name: str
    base_model: str  # the folder of the base model trained from
    base_digest: str  # SHA-256 over the base model's weight files
    trained_by: str
    model_id: str = field(default_factory=lambda: new_id("tmd"))
    # training | failed | candidate (trained, evaluated, waiting) | approved | retired
    status: str = "training"
    recipe: dict[str, Any] = field(default_factory=dict)
    example_ids: list[str] = field(default_factory=list)
    heldout_ids: list[str] = field(default_factory=list)
    matter_ids: list[str] = field(default_factory=list)
    dataset_digest: str = ""
    folder: str = ""  # where its adapter, merged weights, GGUF and log are kept
    gguf_path: str = ""
    gguf_sha256: str = ""
    started_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None
    failure: str = ""
    evaluation: dict[str, Any] = field(default_factory=dict)
    evaluated_at: datetime | None = None
    approved_by: str = ""
    approved_at: datetime | None = None
    approval_reasons: str = ""
    retired_by: str = ""
    retired_at: datetime | None = None
    retire_reason: str = ""
    # Matters whose examples trained it and whose content has since been erased: its weights may
    # still carry what it learnt from them.
    erased_sources: list[str] = field(default_factory=list)
    # What it was trained on, described for the technical documentation (EU AI Act Art. 10(2),
    # Annex IV 2(d); ISO/IEC 42001 A.7): provenance, what was left out, the gaps.
    datasheet: dict[str, Any] = field(default_factory=dict)
    autonomous: bool = False  # started by autonomous mode's standing instruction


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
