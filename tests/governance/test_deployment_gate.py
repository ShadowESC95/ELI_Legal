"""EL-005: a real matter's work starts, is approved and leaves only under a current deployment
authorisation that covers it, signed by a provider lead and a different deployer lead; a
practice matter needs none and every report from it says it is not for reliance."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from eli_legal.application import deployment_service
from eli_legal.application.deployment_service import NotAuthorised
from eli_legal.domain.enums import Profile
from eli_legal.domain.errors import InvalidInput, PolicyDenied
from eli_legal.domain.models import utcnow
from tests.conftest import case_text

A, G, ADMIN = "arb.keane", "gov.hale", "admin"


def _evidence(sv):
    """The evidence documents themselves, as an organisation would have them on file."""
    folder = Path(sv.ctx.settings.artifacts_dir).parent / "evidence_on_file"
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    for key in deployment_service.EVIDENCE:
        path = folder / f"{key}.pdf"
        path.write_bytes(f"%PDF-1.4 {key} signed 2026-11-01".encode())
        out[key] = str(path)
    return out


def _real(sv):
    return sv.matters.create(
        actor_id=A, name="Real v Matter", purpose="Bench memorandum for the tribunal",
        jurisdiction="XX", profile=Profile.ADJUDICATOR, real=True,
    )  # fmt: skip


PROPOSER = "gov.lead"


def _proposer(sv):
    """Whoever proposes an authorisation does not sign it: a third person proposes."""
    if sv.ctx.store.get_user(PROPOSER) is None:
        sv.users.add_user(
            actor_id=ADMIN, user_id=PROPOSER, display_name="Compliance lead",
            roles=["governance_officer"],
        )  # fmt: skip
    return PROPOSER


def _authorise(sv, **changes):
    today = utcnow().date()
    proposal = dict(
        actor_id=_proposer(sv), intended_use="Case preparation for the arbitral tribunal of the deployer",
        provider="ELI Legal provider", deployer="Port Varen Arbitration Centre",
        jurisdictions=["XX"], profiles=["adjudicator"], effective_from=today,
        expires_on=today + timedelta(days=365), evidence=_evidence(sv),
    ) | changes  # fmt: skip
    a = sv.deployment.propose(**proposal)
    sv.deployment.sign(a.authorisation_id, actor_id=G, as_lead="provider")
    return sv.deployment.sign(a.authorisation_id, actor_id=ADMIN, as_lead="deployer")


def _validated(monkeypatch):
    from eli_legal.legal.jurisdictions import JurisdictionPack

    monkeypatch.setattr(JurisdictionPack, "validated", property(lambda self: True))


def test_a_practice_matter_needs_no_authorisation_and_says_it_is_not_for_reliance(demo):
    sv, mid = demo
    assert not sv.matters.get(mid, A).real
    run = sv.runs.start(mid, actor_id=A)
    report = sv.runs.summary(mid, run.run_id, actor_id=A)["report"]

    text = case_text(sv, report["path"])
    assert "PRACTICE MATTER — DRAFT, NOT FOR RELIANCE" in text and "APPROVED FOR" not in text


def test_a_real_matter_is_refused_until_an_authorisation_covers_it(demo, monkeypatch):
    sv, _ = demo
    matter = _real(sv)
    with pytest.raises(NotAuthorised, match="no deployment authorisation"):
        sv.runs.create(matter.matter_id, actor_id=A)
    denied = [e for e in sv.ctx.audit.events(matter_id=matter.matter_id)
              if e["event_type"] == "deployment_denied"]  # fmt: skip
    assert denied and denied[0]["action"] == "workflow.run"
    approved = _authorise(sv)
    assert approved.status == "approved" and approved.pinned["version"]
    with pytest.raises(NotAuthorised, match="not validated by a lawyer"):
        sv.runs.create(matter.matter_id, actor_id=A)
    _validated(monkeypatch)
    assert sv.runs.create(matter.matter_id, actor_id=A).run_id
    monkeypatch.setattr(deployment_service, "__version__", "9.9.9")
    with pytest.raises(NotAuthorised, match="different version"):
        sv.runs.create(matter.matter_id, actor_id=A)
    monkeypatch.undo()
    _validated(monkeypatch)
    sv.deployment.revoke(approved.authorisation_id, actor_id=G, reason="Security finding open.")
    with pytest.raises(NotAuthorised, match="no deployment authorisation"):
        sv.runs.create(matter.matter_id, actor_id=A)


def test_an_authorisation_rests_on_evidence_and_two_different_signers(demo):
    sv, _ = demo
    today = utcnow().date()
    with pytest.raises(InvalidInput, match="still to provide"):
        _authorise(sv, evidence={"design_review": "DR-1"})
    with pytest.raises(InvalidInput, match="expire"):
        _authorise(sv, expires_on=today + timedelta(days=900))
    a = sv.deployment.propose(
        actor_id=_proposer(sv), intended_use="Case preparation for the arbitral tribunal of the deployer",
        provider="P", deployer="D", jurisdictions=["XX"], profiles=["adjudicator"],
        effective_from=today, expires_on=today + timedelta(days=30), evidence=_evidence(sv),
    )  # fmt: skip
    with pytest.raises(InvalidInput, match="the document itself"):
        _authorise(sv, evidence={k: "DOC-1, signed" for k in deployment_service.EVIDENCE})
    assert all(" sha256:" in v for v in a.evidence.values()), "bound to the files"
    sv.deployment.sign(a.authorisation_id, actor_id=G, as_lead="provider")
    with pytest.raises(PolicyDenied, match="different people"):
        sv.deployment.sign(a.authorisation_id, actor_id=G, as_lead="deployer")
    with pytest.raises(PolicyDenied, match="proposed an authorisation cannot also sign"):
        sv.deployment.sign(a.authorisation_id, actor_id=PROPOSER, as_lead="deployer")
    with pytest.raises(PolicyDenied):
        sv.deployment.sign(a.authorisation_id, actor_id=A, as_lead="deployer")
    refused = [e for e in sv.ctx.audit.events() if e["event_type"] == "access_denied"
               and e["actor_id"] == PROPOSER]  # fmt: skip
    assert refused, "the refusal is recorded"


def test_evidence_changed_after_the_proposal_stops_the_signature(demo):
    sv, _ = demo
    today = utcnow().date()
    a = sv.deployment.propose(
        actor_id=G, intended_use="Case preparation for the arbitral tribunal of the deployer",
        provider="P", deployer="D", jurisdictions=["XX"], profiles=["adjudicator"],
        effective_from=today, expires_on=today + timedelta(days=30), evidence=_evidence(sv),
    )  # fmt: skip
    name = a.evidence["security_assessment"].split(" sha256:")[0]
    kept = Path(sv.ctx.settings.artifacts_dir) / "deployment" / a.authorisation_id / name
    kept.write_bytes(b"%PDF-1.4 a different assessment")
    from eli_legal.domain.errors import InvalidState

    with pytest.raises(InvalidState, match="security assessment changed"):
        sv.deployment.sign(a.authorisation_id, actor_id=G, as_lead="provider")
