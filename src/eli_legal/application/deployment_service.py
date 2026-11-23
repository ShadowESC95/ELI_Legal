"""Deployment authorisation: the approval to use ELI Legal on real matters (EL-005).

A matter is either *practice* (a demonstration, training or testing: no real case material,
never relied on, and every report says so) or *real*. Practice needs no authorisation. On a
real matter, starting work, approving the report and preparing or sending a release each need
a current authorisation that covers it:

- approved: proposed by someone who manages compliance, with the evidence it rests on, then
  signed by a provider lead and by a different deployer lead, each confirming their identity;
- in force: today between its start and its expiry, and not revoked;
- matching: the matter's legal system and kind are among those approved, and the software
  version, the policy and the model are the ones it was approved for. An upgrade, a policy
  change or a different model voids it until it is approved again;
- and, for a real matter, every legal-system pack it uses validated by a lawyer, and for a
  court, tribunal or neutral the reviewer who approves is not the person who ran the work.

A refusal names what is missing and is written to the audit trail. Revoking takes effect at
once. Signing records that people approved; it is not a certificate of conformity.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from eli_legal import __version__
from eli_legal.application.container import AppContext
from eli_legal.domain.enums import Profile
from eli_legal.domain.errors import InvalidInput, InvalidState, NotFound, PolicyDenied
from eli_legal.domain.models import DeploymentAuthorisation, Matter, utcnow
from eli_legal.security import authn

KIND = "deployment_authorisation"
MANAGES = "compliance.manage"
# What an authorisation must rest on, named as the specification and the RAIMS programme name it.
EVIDENCE = {
    "design_review": "the signed design review",
    "legal_validation": "a qualified lawyer's validation of the legal-system packs and date rules",
    "security_assessment": "the security assessment",
    "evaluation": "the accuracy evaluation on representative matters, with thresholds set first",
    "impact_assessment": "the data-protection and fundamental-rights impact assessments",
    "oversight_plan": "the human-oversight and training plan",
}
MAX_DAYS = 400
SEPARATED = (Profile.ADJUDICATOR, Profile.NEUTRAL_FACILITATOR)


class NotAuthorised(PolicyDenied):
    """A real matter's work was asked for without a deployment authorisation that covers it."""


def _digest(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def pinned_now(ctx: AppContext) -> dict[str, str]:
    """Everything an authorisation is approved for, as it is in use now: the software version,
    the policy, the model and the embedding model, the workflow, the legal-system packs (with
    who validated them) and the approved legal sources (with their licence and terms review).
    A change to any of them voids the authorisation until it is approved again."""
    policy = asdict(ctx.policy)
    policy = {k: sorted(v) if isinstance(v, (set, frozenset)) else v for k, v in policy.items()}
    packs = {
        code: _digest(asdict(p)) for code in ctx.jurisdictions.codes()
        if (p := ctx.jurisdictions.get(code)) is not None
    }  # fmt: skip
    sources = {
        s.source_id: [s.name, getattr(s, "licence", ""), bool(s.terms_reviewed)]
        for s in ctx.sources.list()
        if s.approved
    }
    workflow = [(s.id, sorted(s.depends_on)) for s in ctx.workflow.steps]
    return {
        "version": __version__,
        "policy": _digest(policy),
        "model": ctx.model.model_id,
        "embedding_model": ctx.embedder.model_id,
        "workflow": _digest(workflow),
        "jurisdiction_packs": _digest(packs),
        "sources": _digest(sources),
    }


def _in_force(a: DeploymentAuthorisation, today: date) -> bool:
    return a.status == "approved" and a.effective_from <= today <= a.expires_on


def why_not(ctx: AppContext, matter: Matter, *, reviewer_id: str = "",
            operator_id: str = "") -> list[str]:  # fmt: skip
    """What stops work on this real matter now, in words; empty when it may go ahead."""
    if not matter.real:
        return []
    today = utcnow().date()
    approved = [
        a for a in ctx.store.list_registry(KIND, DeploymentAuthorisation) if _in_force(a, today)
    ]
    if not approved:
        return ["no deployment authorisation is approved and in force"]
    now = pinned_now(ctx)
    reasons: list[str] = []
    for a in approved:
        missing = []
        if matter.jurisdiction not in a.jurisdictions:
            missing.append(f"the legal system {matter.jurisdiction} is not among those approved")
        if matter.profile.value not in a.profiles:
            missing.append(f"matters for {matter.profile.value} are not among those approved")
        changed = [k for k in now if a.pinned.get(k) != now[k]]
        if changed:
            missing.append(
                "approved for a different " + " and ".join(changed) + f" (approved {a.pinned}, "
                f"now {now}); approve it again"
            )
        if not missing:
            reasons = []
            break
        reasons = missing
    if reasons:
        return reasons
    unvalidated = [p.code for p in ctx.jurisdictions.for_matter(matter) if not p.validated]
    if unvalidated:
        reasons.append(
            "the legal-system pack(s) " + ", ".join(unvalidated) + " are not validated by a lawyer"
        )
    if reviewer_id and operator_id and reviewer_id == operator_id and matter.profile in SEPARATED:
        reasons.append("the reviewer who approves must not be the person who ran the work")
    return reasons


def require_deployment(
    ctx: AppContext,
    matter: Matter,
    *,
    actor_id: str,
    action: str,
    reviewer_id: str = "",
    operator_id: str = "",
) -> None:
    """Refuse, and record the refusal, unless this real matter's work may go ahead."""
    reasons = why_not(ctx, matter, reviewer_id=reviewer_id, operator_id=operator_id)
    if not reasons:
        return
    ctx.log(
        "deployment_denied",
        actor_id=actor_id,
        matter_id=matter.matter_id,
        action=action,
        subject_id=matter.matter_id,
        outcome="denied",
        object_type="matter",
        payload={"reasons": [r[:120] for r in reasons][:4]},
    )
    raise NotAuthorised("this is a real matter and its work cannot go ahead: " + "; ".join(reasons))


@dataclass(slots=True)
class DeploymentService:
    ctx: AppContext

    def list(self, *, actor_id: str) -> list[DeploymentAuthorisation]:
        self.ctx.authorizer().require_global(actor_id, "audit.read")
        return self.ctx.store.list_registry(KIND, DeploymentAuthorisation)

    def _get(self, authorisation_id: str) -> DeploymentAuthorisation:
        found = self.ctx.store.get_registry(KIND, authorisation_id, DeploymentAuthorisation)
        if found is None:
            raise NotFound(f"no such deployment authorisation: {authorisation_id}")
        return found

    def _put(self, a: DeploymentAuthorisation, actor_id: str, event: str, outcome: str) -> None:
        self.ctx.store.put_registry(KIND, a.authorisation_id, a)
        self.ctx.log(
            event,
            actor_id=actor_id,
            matter_id="-",
            action=MANAGES,
            subject_id=a.authorisation_id,
            outcome=outcome,
            object_type="deployment_authorisation",
            payload={
                "jurisdictions": a.jurisdictions,
                "profiles": a.profiles,
                "expires_on": a.expires_on.isoformat(),
                "pinned": a.pinned,
            },  # fmt: skip
        )

    def propose(
        self,
        *,
        actor_id: str,
        intended_use: str,
        provider: str,
        deployer: str,
        jurisdictions: Sequence[str],
        profiles: Sequence[str],
        effective_from: date,
        expires_on: date,
        evidence: dict[str, str],
        data_classes: Sequence[str] = (),
    ) -> DeploymentAuthorisation:
        """Set out what is to be approved. Nothing is authorised until both leads sign."""
        authn.require_step_up(actor_id, "propose a deployment authorisation")
        self.ctx.authorizer().require_global(actor_id, MANAGES)
        if len(" ".join(intended_use.split())) < 30 or not provider.strip() or not deployer.strip():
            raise InvalidInput(
                "say what it is to be used for, by which deployer, from which provider"
            )
        known = set(self.ctx.jurisdictions.codes())
        unknown = [j for j in jurisdictions if j not in known]
        if not jurisdictions or unknown:
            raise InvalidInput(f"name the legal systems it is for (unknown: {unknown})")
        kinds = {p.value for p in Profile}
        if not profiles or any(p not in kinds for p in profiles):
            raise InvalidInput(f"name the kinds of matter it is for: {sorted(kinds)}")
        missing = [k for k in EVIDENCE if not evidence.get(k, "").strip()]
        if missing:
            raise InvalidInput(
                "an authorisation rests on evidence; still to provide: "
                + "; ".join(EVIDENCE[k] for k in missing)
            )
        files = {k: Path(evidence[k]).expanduser() for k in EVIDENCE}
        absent = [EVIDENCE[k] for k, f in files.items() if not f.is_file()]
        if absent:
            raise InvalidInput(
                "each piece of evidence is the document itself, not a name for it; not found: "
                + "; ".join(absent)
            )
        if not effective_from < expires_on or (expires_on - effective_from).days > MAX_DAYS:
            raise InvalidInput(f"it must expire after it starts, and within {MAX_DAYS} days")
        a = DeploymentAuthorisation(
            intended_use=" ".join(intended_use.split()),
            provider=provider.strip(),
            deployer=deployer.strip(),
            jurisdictions=sorted(set(jurisdictions)),
            profiles=sorted(set(profiles)),
            effective_from=effective_from,
            expires_on=expires_on,
            proposed_by=actor_id,
            data_classes=sorted(set(data_classes)),
            pinned=pinned_now(self.ctx),
        )
        # The approval binds to the evidence as it is now: each document is copied into the
        # application's keeping and recorded by its SHA-256, and signing checks it unchanged.
        kept = Path(self.ctx.settings.artifacts_dir) / "deployment" / a.authorisation_id
        kept.mkdir(parents=True, exist_ok=True)
        for k, f in files.items():
            body = f.read_bytes()
            copy = kept / f"{k}{f.suffix}"
            copy.write_bytes(body)
            a.evidence[k] = f"{copy.name} sha256:{hashlib.sha256(body).hexdigest()}"
        self._put(a, actor_id, "deployment_proposed", "proposed")
        return a

    def sign(
        self, authorisation_id: str, *, actor_id: str, as_lead: str
    ) -> DeploymentAuthorisation:
        """A provider lead or a deployer lead approves. Two different people; it is approved
        when both have signed, for the version, policy and model in use when it was proposed."""
        authn.require_step_up(actor_id, f"sign a deployment authorisation as the {as_lead} lead")
        self.ctx.authorizer().require_global(actor_id, MANAGES)
        if as_lead not in ("provider", "deployer"):
            raise InvalidInput("sign as the provider lead or the deployer lead")
        a = self._get(authorisation_id)
        if a.status != "proposed":
            raise InvalidState(f"this authorisation is {a.status}")
        if a.pinned != pinned_now(self.ctx):
            raise InvalidState(
                "what it was proposed for (software, policy, models, workflow, legal-system packs "
                "or sources) changed since; propose it again"
            )
        kept = Path(self.ctx.settings.artifacts_dir) / "deployment" / a.authorisation_id
        for k, recorded in a.evidence.items():
            name, _, digest = recorded.partition(" sha256:")
            copy = kept / name
            if not copy.is_file() or hashlib.sha256(copy.read_bytes()).hexdigest() != digest:
                raise InvalidState(f"the evidence for {EVIDENCE.get(k, k)} changed or is missing")
        if actor_id == a.proposed_by:
            raise PolicyDenied(
                "the person who proposed an authorisation cannot also sign it; two other people "
                "sign, as the provider lead and the deployer lead"
            )
        other = a.deployer_signed_by if as_lead == "provider" else a.provider_signed_by
        if other == actor_id:
            raise PolicyDenied("the provider lead and the deployer lead must be different people")
        if as_lead == "provider":
            a.provider_signed_by, a.provider_signed_at = actor_id, utcnow()
        else:
            a.deployer_signed_by, a.deployer_signed_at = actor_id, utcnow()
        if a.provider_signed_by and a.deployer_signed_by:
            a.status = "approved"
        self._put(a, actor_id, "deployment_signed", f"{as_lead}:{a.status}")
        return a

    def revoke(
        self, authorisation_id: str, *, actor_id: str, reason: str
    ) -> DeploymentAuthorisation:
        """Withdraw it at once: real matters' work stops until another is approved."""
        authn.require_step_up(actor_id, "revoke a deployment authorisation")
        self.ctx.authorizer().require_global(actor_id, MANAGES)
        if len(" ".join(reason.split())) < 10:
            raise InvalidInput("say why it is revoked")
        a = self._get(authorisation_id)
        if a.status == "revoked":
            raise InvalidState("already revoked")
        a.status, a.revoked_by, a.revoked_at = "revoked", actor_id, utcnow()
        a.revoke_reason = " ".join(reason.split())
        self._put(a, actor_id, "deployment_revoked", "revoked")
        return a
