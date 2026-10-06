from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from eli_legal.application.container import AppContext
from eli_legal.domain.enums import ReviewDecision, RunStatus, VerificationStatus
from eli_legal.domain.models import (
    Document,
    Hold,
    HumanReview,
    Incident,
    Run,
    RunStep,
    VerificationResult,
)


@dataclass(frozen=True, slots=True)
class MonitoringSample:
    failed_source_checks: int = 0
    unsupported_claims: int = 0
    missing_documents: int = 0
    reviewer_corrections: int = 0
    overrides: int = 0


@dataclass(slots=True)
class MonitoringSnapshot:
    matters: int = 0
    runs_by_status: dict[str, int] = field(default_factory=dict)
    holds_by_reason: dict[str, int] = field(default_factory=dict)
    checks: dict[str, int] = field(default_factory=dict)
    human_results: int = 0
    overrides: int = 0
    reviews: dict[str, int] = field(default_factory=dict)
    documents_not_read: int = 0
    model_items_rejected: int = 0
    open_incidents: int = 0
    version_changes: list[str] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__slots__}


@dataclass(slots=True)
class MonitoringService:
    """Post-deployment monitoring from control evidence, not from how good the reports look."""

    ctx: AppContext | None = None

    def requires_review(self, sample: MonitoringSample, *, failed_check_threshold: int = 1) -> bool:
        return sample.failed_source_checks >= failed_check_threshold

    def snapshot(self, *, actor_id: str) -> MonitoringSnapshot:
        if self.ctx is None:
            raise RuntimeError("monitoring needs an application context")
        ctx = self.ctx
        ctx.authorizer().require_global(actor_id, "audit.read")
        snap = MonitoringSnapshot()
        store = ctx.store
        for matter in store.list_matters():
            snap.matters += 1
            mid = matter.matter_id
            runs = store.list(Run, mid)
            for run in runs:
                snap.runs_by_status[run.status.value] = (
                    snap.runs_by_status.get(run.status.value, 0) + 1
                )
            for hold in store.list(Hold, mid):
                snap.holds_by_reason[hold.reason_code] = (
                    snap.holds_by_reason.get(hold.reason_code, 0) + 1
                )
            for result in store.list(VerificationResult, mid):
                key = f"{result.verification_type}:{result.status.value}"
                snap.checks[key] = snap.checks.get(key, 0) + 1
                snap.human_results += int(result.by_human)
                snap.overrides += int(result.override)
            for review in store.list(HumanReview, mid):
                snap.reviews[review.decision.value] = snap.reviews.get(review.decision.value, 0) + 1
            snap.documents_not_read += sum(
                1 for d in store.list(Document, mid) if d.status.value != "processed"
            )
            for step in store.list(RunStep, mid):
                snap.model_items_rejected += int(step.outputs.get("model_items_rejected", 0) or 0)
            snap.open_incidents += sum(1 for i in store.list(Incident, mid) if i.status == "open")
            # A change of model, prompt, tool or policy between runs is a change to reassess.
            finished = [r for r in runs if r.status is not RunStatus.RUNNING]
            for earlier, later in zip(finished, finished[1:], strict=False):
                for label, a, b in (
                    ("model", earlier.model_versions, later.model_versions),
                    ("tool", earlier.tool_versions, later.tool_versions),
                    ("prompt", earlier.prompt_versions, later.prompt_versions),
                    ("policy", {"v": earlier.policy_version}, {"v": later.policy_version}),
                    ("workflow", {"v": earlier.workflow_version}, {"v": later.workflow_version}),
                ):
                    if a != b:
                        snap.version_changes.append(
                            f"{mid}: {label} changed between {earlier.run_id} and {later.run_id}"
                        )

        limits = ctx.policy.monitoring
        negative = sum(
            n
            for key, n in snap.checks.items()
            if key.split(":")[1]
            in (VerificationStatus.FAILED.value, VerificationStatus.CONFLICT.value)
        )
        if negative >= int(limits.get("hard_gate_breach_alert", 1)):
            snap.alerts.append(
                f"{negative} check(s) failed or conflicted: confirm each was held and resolved by a named person"
            )
        if snap.human_results and snap.overrides / snap.human_results > float(
            limits.get("override_rate_alert", 0.10)
        ):
            snap.alerts.append(
                f"{snap.overrides} of {snap.human_results} human results overrode the system: "
                "either a source is wrong or the checks are being bypassed"
            )
        approvals = snap.reviews.get(ReviewDecision.APPROVE.value, 0)
        challenged = sum(n for k, n in snap.reviews.items() if k != ReviewDecision.APPROVE.value)
        if approvals >= int(limits.get("approval_without_challenge_runs", 20)) and challenged == 0:
            snap.alerts.append(
                f"{approvals} approvals and no rejection or return: near-zero challenge suggests "
                "reviewers may be relying on the output rather than reviewing it"
            )
        if snap.open_incidents:
            snap.alerts.append(f"{snap.open_incidents} incident(s) are open")
        if snap.version_changes:
            snap.alerts.append(
                f"{len(snap.version_changes)} change(s) of model, prompt, tool, policy or workflow "
                "between runs: complete a change assessment and revalidate"
            )
        return snap
