"""What the server accepts. Unknown fields are refused and every string has a limit."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Short = Annotated[str, StringConstraints(max_length=200)]
Long = Annotated[str, StringConstraints(max_length=20_000)]
Secret = Annotated[str, StringConstraints(min_length=1, max_length=1024)]
Ident = Annotated[
    str, StringConstraints(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.@:-]+$")
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(Strict):
    status: str
    version: str


class LoginIn(Strict):
    user_id: Ident
    passphrase: Secret
    code: Annotated[str, StringConstraints(max_length=12)] | None = None


class PassphraseChange(Strict):
    current: Secret
    new: Secret


class NewPassphrase(Strict):
    new: Secret


class CodeIn(Strict):
    code: Annotated[str, StringConstraints(min_length=6, max_length=12)]


class LabelIn(Strict):
    label: Short = ""


class UserCreate(Strict):
    user_id: Ident
    display_name: Name
    roles: list[Ident] = Field(default_factory=list, max_length=20)
    passphrase: Secret | None = None


class PartyIn(Strict):
    name: Name
    role: Name


class TeamMemberIn(Strict):
    user_id: Ident
    matter_role: Annotated[str, StringConstraints(max_length=40)] = ""
    party: Short | None = None


class MatterCreate(Strict):
    name: Name
    purpose: Long
    jurisdiction: Ident
    profile: Ident
    governing_law: Short | None = None
    forum: Short = ""
    procedural_rules: Short = ""
    relevant_date: date | None = None
    parties: list[PartyIn] = Field(default_factory=list, max_length=100)
    stated_issues: list[Long] = Field(default_factory=list, max_length=100)
    represented_party: Short | None = None
    # Packages to apply. With recommended_frameworks, they are added to the recommended set.
    frameworks: list[Ident] = Field(default_factory=list, max_length=100)
    recommended_frameworks: bool = True
    # The rest of the set-up, in the same step: who works on it, who reviews, which sources.
    team: list[TeamMemberIn] = Field(default_factory=list, max_length=100)
    reviewers: list[Ident] = Field(default_factory=list, max_length=50)
    sources: list[Ident] = Field(default_factory=list, max_length=50)
    # A real matter (real case papers, to be relied on) needs a deployment authorisation.
    real: bool = False


class MatterUpdate(Strict):
    relevant_date: date | None = None
    stated_issues: list[Long] | None = Field(default=None, max_length=100)
    forum: Short | None = None
    procedural_rules: Short | None = None
    add_parties: list[PartyIn] = Field(default_factory=list, max_length=100)


class IdList(Strict):
    ids: list[Ident] = Field(max_length=200)


class Reasoned(Strict):
    reason: Long


class CloseIn(Strict):
    purge_content: bool = False
    reason: Long


class ResumeIn(Strict):
    reason: Long
    from_step: Ident | None = None


class HoldResolveIn(Strict):
    action: Ident
    reason: Long


class VerificationIn(Strict):
    check: Ident
    result: Ident
    reason: Long


class ReviewIn(Strict):
    decision: Ident
    reasons: Long
    report_hash: Short = ""
    acknowledged: list[Short] = Field(default_factory=list, max_length=200)


class RecipientIn(Strict):
    recipient_id: Ident
    display_name: Name
    address: Short


class ReleaseIn(Strict):
    recipients: list[RecipientIn] = Field(min_length=1, max_length=100)


class SendIn(Strict):
    confirmed_recipient_ids: list[Ident] = Field(max_length=100)


class ChatIn(Strict):
    question: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    run_id: Ident | None = None
    use_model: bool = False


class IncidentIn(Strict):
    category: Name
    detail: Long
    severity: Ident = "medium"
    run_id: Ident | None = None


class IncidentClose(Strict):
    containment: Long
    reason: Long


class SourceIn(Strict):
    source_id: Ident
    name: Name
    jurisdictions: list[Ident] = Field(min_length=1, max_length=50)
    source_types: list[Short] = Field(default_factory=list, max_length=20)
    authority_owner: Short = ""
    licence: Long = ""
    terms_reviewed: bool = False
    freshness: Short = ""
    treatment_semantics: Long = ""
    authoritative_for: list[Short] = Field(default_factory=list, max_length=20)
    inspection: Long = ""


class ImportIn(Strict):
    directory: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class ModelIn(Strict):
    backend: Ident
    url: Short = ""
    # For a model server: model names. For GGUF: the references the model list gives, never paths.
    model: Short = ""
    verifier_model: Short = ""
    # 0: sized to the model and this machine. Otherwise the service checks the range.
    gguf_context: int | None = Field(default=None, ge=0, le=262144)
    gguf_gpu_layers: int | None = Field(default=None, ge=-1, le=999)
    gguf_threads: int | None = Field(default=None, ge=0, le=256)


class ValidationIn(Strict):
    lawyer: Annotated[str, StringConstraints(min_length=3, max_length=200)]


class MemberIn(Strict):
    """A person's place on a matter: their role on it, whom they act for, what they read."""

    matter_role: Ident | None = None
    party: Short | None = None
    clear_party: bool = False
    reads: list[Ident] | None = Field(default=None, max_length=8)


class ComplianceIn(Strict):
    answers: dict[Ident, Long] = Field(default_factory=dict, max_length=60)
    confirmed: bool = False
    notes: Long = ""
    reference: Short = ""
    not_applicable: bool = False


class RetentionIn(Strict):
    audit_days: int = Field(ge=0, le=36_500)
    closed_matter_days: int = Field(ge=0, le=36_500)
    notes: Long = ""


class TrainingIn(Strict):
    user_id: Ident
    course: Name
    completed_on: date
    expires_on: date | None = None


class EvaluationIn(Strict):
    thresholds: dict[Ident, float] = Field(default_factory=dict, max_length=10)


class SignOffIn(Strict):
    sha256: Annotated[str, StringConstraints(min_length=64, max_length=64)]
    notes: Long = ""


class LawCurrentIn(Strict):
    checked_on: date
    note: Long


class AwarenessIn(Strict):
    aware_at: datetime
    basis: Long
    aware_by: Ident | None = None
    occurred_at: datetime | None = None


class AssignIn(Strict):
    owner: Ident
    backup: Ident


class PreservationIn(Strict):
    legal_basis: Long
    authority: Short
    document_ids: list[Ident] = []
    review_by: date | None = None


class PreservationRelease(Strict):
    reason: Long


class EvidenceFile(Strict):
    filename: Name
    content_base64: Annotated[str, StringConstraints(max_length=40_000_000)]


class DeploymentProposeIn(Strict):
    intended_use: Long
    provider: Short
    deployer: Short
    jurisdictions: list[Ident] = Field(min_length=1, max_length=50)
    profiles: list[Ident] = Field(min_length=1, max_length=3)
    effective_from: date
    expires_on: date
    evidence: dict[Ident, EvidenceFile]
    data_classes: list[Ident] = Field(default_factory=list, max_length=20)


class DeploymentSignIn(Strict):
    as_lead: Ident


class DeploymentRevokeIn(Strict):
    reason: Long


class RelianceResolveIn(Strict):
    basis: Long
    superseded_by_run_id: Ident = ""


class ReportingIn(Strict):
    reportable: bool
    reason: Long
    serious_kind: Ident = "general"
    reported_on: date | None = None
    reference: Short = ""


class OnOff(Strict):
    on: bool
