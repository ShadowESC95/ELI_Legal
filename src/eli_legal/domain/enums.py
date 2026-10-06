from enum import Enum


class MatterStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    HELD = "held"
    CLOSED = "closed"


class VerificationStatus(str, Enum):
    NOT_RUN = "not_run"
    VERIFIED = "verified"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"
    CONFLICT = "conflict"


class ClaimStatus(str, Enum):
    DRAFT = "draft"
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    HELD = "held"
    REJECTED = "rejected"


class RunStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    HELD = "held"
    BLOCKED = "blocked"
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"
    APPROVED_FOR_RELIANCE = "approved_for_reliance"
    REJECTED = "rejected"


class ReviewDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    RETURN_FOR_CORRECTION = "return_for_correction"
