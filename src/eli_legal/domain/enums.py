from enum import Enum


class MatterStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    HELD = "held"
    CLOSED = "closed"


class Profile(str, Enum):
    """Who is using the system. The profile fixes roles, outputs and regulatory posture."""

    ADJUDICATOR = "adjudicator"  # judge, tribunal member, arbitrator
    NEUTRAL_FACILITATOR = "neutral_facilitator"  # mediator, conciliator
    PARTY_REPRESENTATIVE = "party_representative"  # solicitor, barrister, in-house counsel


class DocumentType(str, Enum):
    PLEADING = "pleading"
    SUBMISSION = "submission"
    WITNESS_STATEMENT = "witness_statement"
    EXPERT_REPORT = "expert_report"
    CONTRACT = "contract"
    CORRESPONDENCE = "correspondence"
    EXHIBIT = "exhibit"
    ORDER = "order"
    TRANSCRIPT = "transcript"
    AUTHORITY = "authority"
    OTHER = "other"


class DocumentStatus(str, Enum):
    REGISTERED = "registered"
    PROCESSED = "processed"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    WAIVED = "waived"


class AccessScope(str, Enum):
    """Who may see content derived from a document."""

    ALL_PARTIES = "all_parties"
    NEUTRAL_ONLY = "neutral_only"  # e.g. a mediator's private caucus notes
    PARTY_CONFIDENTIAL = "party_confidential"  # disclosed to the neutral by one party only
    PRIVILEGED = "privileged"


class AuthorityKind(str, Enum):
    CASE = "case"
    LEGISLATION = "legislation"
    RULE = "rule"
    TREATY = "treaty"
    SECONDARY = "secondary"


class AuthorityStatus(str, Enum):
    IN_FORCE = "in_force"  # legislation/rules currently applicable; case not negatively treated
    AMENDED = "amended"
    REPEALED = "repealed"
    OVERRULED = "overruled"
    REVERSED = "reversed"
    SUPERSEDED = "superseded"
    DOUBTED = "doubted"
    NOT_YET_IN_FORCE = "not_yet_in_force"
    UNKNOWN = "unknown"


class ClaimKind(str, Enum):
    FACT = "fact"  # asserted from the matter evidence
    # A party relies on an authority. The system reports that reliance and checks the authority
    # exists and is still good law; it does not itself assert what the authority decides.
    PARTY_AUTHORITY = "party_authority"
    LEGAL_PROPOSITION = "legal_proposition"  # what an authority establishes
    APPLICATION = "application"  # law applied to facts; analysis for the reviewer
    PROCEDURAL = "procedural"


class ClaimStatus(str, Enum):
    DRAFT = "draft"
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    HELD = "held"
    REJECTED = "rejected"
    EXCLUDED = "excluded"  # removed from reliance by a named human decision


class VerificationType(str, Enum):
    PROVENANCE = "provenance"
    EVIDENCE_SUPPORT = "evidence_support"
    CITATION = "citation"
    CURRENT_LAW = "current_law"
    PROPOSITION = "proposition"
    DEPENDENCY = "dependency"
    OUTCOME_BOUNDARY = "outcome_boundary"


class VerificationStatus(str, Enum):
    NOT_RUN = "not_run"
    VERIFIED = "verified"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"
    CONFLICT = "conflict"


class RunStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    HELD = "held"
    BLOCKED = "blocked"
    STOPPED = "stopped"
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"
    APPROVED_FOR_RELIANCE = "approved_for_reliance"
    REJECTED = "rejected"
    RETURNED_FOR_CORRECTION = "returned_for_correction"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    HELD = "held"
    FAILED = "failed"
    SKIPPED = "skipped"


class HoldScope(str, Enum):
    CLAIM = "claim"
    DOCUMENT = "document"
    STEP = "step"
    RUN = "run"


class HoldStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"


class HoldResolution(str, Enum):
    REVERIFIED = "reverified"  # the check now passes
    EXCLUDED = "excluded"  # the finding was removed from reliance
    WAIVED = "waived"  # an authorised human accepted the gap, with reasons
    CORRECTED = "corrected"  # the underlying defect was fixed and the step re-run
    LIFTED = "lifted"  # a person's own hold on the run, lifted by a person with reasons


class ReviewDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    RETURN_FOR_CORRECTION = "return_for_correction"


class TaskStatus(str, Enum):
    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"


class IncidentSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    SERIOUS = "serious"  # candidate for AI Act Art. 73 assessment; a human decides


class ActorType(str, Enum):
    HUMAN = "human"
    SYSTEM = "system"
    AGENT = "agent"
