from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    mode: str
    network_default: str
    version: str


class PartyIn(BaseModel):
    name: str
    role: str


class MatterCreate(BaseModel):
    name: str
    purpose: str
    jurisdiction: str
    profile: str
    governing_law: str | None = None
    forum: str = ""
    procedural_rules: str = ""
    relevant_date: date | None = None
    parties: list[PartyIn] = Field(default_factory=list)
    stated_issues: list[str] = Field(default_factory=list)
    represented_party: str | None = None


class IdList(BaseModel):
    ids: list[str]


class Reasoned(BaseModel):
    reason: str


class ResumeIn(BaseModel):
    reason: str
    from_step: str | None = None


class HoldResolveIn(BaseModel):
    action: str
    reason: str


class VerificationIn(BaseModel):
    check: str
    result: str
    reason: str


class ReviewIn(BaseModel):
    decision: str
    reasons: str
    report_hash: str = ""
    acknowledged: list[str] = Field(default_factory=list)


class RecipientIn(BaseModel):
    recipient_id: str
    display_name: str
    address: str


class ReleaseIn(BaseModel):
    recipients: list[RecipientIn]


class SendIn(BaseModel):
    confirmed_recipient_ids: list[str]
