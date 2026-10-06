from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from eli_legal.domain.models import new_id, utcnow


@dataclass(slots=True, frozen=True)
class Recipient:
    recipient_id: str
    display_name: str
    address: str
    channel: str = "secure_email"
    authorised_for_matter: bool = False


@dataclass(slots=True)
class ReleasePackage:
    matter_id: str
    run_id: str
    report_id: str
    report_version: str
    report_hash: str
    artifact_ref: str
    approved_review_id: str
    prepared_by: str
    recipients: tuple[Recipient, ...]
    classification: str = "privileged_confidential"
    release_id: str = field(default_factory=lambda: new_id("rel"))
    status: str = "prepared"
    approved_by: str | None = None
    approved_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True, frozen=True)
class ReleaseApproval:
    release_id: str
    approver_user_id: str
    approved_review_id: str
    report_hash: str
    recipient_ids: tuple[str, ...]
    actor_type: str = "human"
    created_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True, frozen=True)
class DeliveryReceipt:
    release_id: str
    recipient_id: str
    channel: str
    status: str
    detail: str = ""
    delivery_id: str = field(default_factory=lambda: new_id("del"))
    created_at: datetime = field(default_factory=utcnow)
