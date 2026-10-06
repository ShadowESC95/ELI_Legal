"""Audit completeness for a run.

A hash chain proves that recorded events were not altered. It cannot prove that an event which
should have been recorded was. This check closes that gap for a run by comparing what the store
says happened with what the ledger holds: every finished step, every hold and its resolution,
every review, and the full set of verification results (by digest) must have a matching event.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from eli_legal.domain.enums import HoldStatus, StepStatus
from eli_legal.domain.models import Hold, HumanReview, RunStep, VerificationResult
from eli_legal.workflows.runner import outputs_hash


def verification_digest(results: Iterable[VerificationResult]) -> str:
    """Order-independent digest of a set of verification results (id, claim, type, status)."""
    lines = sorted(
        f"{r.verification_id}|{r.claim_id}|{r.verification_type}|{r.status.value}|{int(r.by_human)}"
        for r in results
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


@dataclass(slots=True)
class CompletenessReport:
    ok: bool
    gaps: list[str] = field(default_factory=list)
    events_checked: int = 0


def check_run_completeness(
    *,
    events: Iterable[Mapping[str, Any]],
    steps: Iterable[RunStep],
    holds: Iterable[Hold],
    reviews: Iterable[HumanReview] = (),
    verifications: Iterable[VerificationResult] | None = None,
) -> CompletenessReport:
    by_type: dict[str, list[Mapping[str, Any]]] = {}
    count = 0
    for event in events:
        by_type.setdefault(str(event.get("event_type")), []).append(event)
        count += 1
    gaps: list[str] = []

    if not by_type.get("run_started"):
        gaps.append("no run_started event")

    step_events: dict[str, Mapping[str, Any]] = {}
    for event in by_type.get("step_completed", []):
        step_events[str(event.get("subject_id"))] = event  # the latest event per step wins
    for step in steps:
        if step.status in (StepStatus.PENDING, StepStatus.RUNNING):
            continue
        logged = step_events.get(step.record_id)
        if logged is None:
            gaps.append(f"step {step.step_id}: no step_completed event")
        elif logged.get("outcome") != step.status.value:
            gaps.append(f"step {step.step_id}: recorded outcome differs from the ledger")
        elif logged.get("output_hash") != outputs_hash(step.outputs):
            gaps.append(f"step {step.step_id}: stored outputs differ from those logged")

    raised = {str(e.get("subject_id")) for e in by_type.get("hold_raised", [])}
    resolved = {str(e.get("subject_id")) for e in by_type.get("hold_resolved", [])}
    for hold in holds:
        if hold.hold_id not in raised:
            gaps.append(f"hold {hold.hold_id}: no hold_raised event")
        if hold.status is HoldStatus.RESOLVED and hold.hold_id not in resolved:
            gaps.append(f"hold {hold.hold_id}: resolved without a hold_resolved event")

    decided = {str(e.get("subject_id")) for e in by_type.get("review_decision", [])}
    for review in reviews:
        if review.review_id not in decided:
            gaps.append(f"review {review.review_id}: no review_decision event")

    if verifications is not None:
        batches = by_type.get("verification_batch", [])
        if not batches:
            gaps.append("no verification_batch event")
        elif batches[-1].get("output_hash") != verification_digest(verifications):
            gaps.append("verification results in the store differ from the last logged digest")

    return CompletenessReport(ok=not gaps, gaps=gaps, events_checked=count)
