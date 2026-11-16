import pytest

from eli_legal.domain.enums import ActorType, Profile, ReviewDecision
from eli_legal.domain.errors import MatterAccessDenied, NotFound, PolicyDenied
from eli_legal.domain.models import Claim, Matter
from eli_legal.security.authorizer import MatterAuthorizer
from eli_legal.security.rbac import DEFAULT_ROLE_ACTIONS, RoleBindings

A, S = "arb.keane", "sec.byrne"


def _denials(sv, mid):
    return [
        e
        for e in sv.ctx.audit.events(matter_id=mid)
        if e["event_type"] in ("access_denied", "cross_matter_access")
    ]


def test_role_and_matter_membership_are_both_required():
    bindings = RoleBindings()
    bindings.bind("judge.a", "judge")
    bindings.bind("judge.b", "judge")
    matter = Matter("M", "p", "IE", "judge.a", authorised_user_ids={"judge.a"})
    authz = MatterAuthorizer(bindings)
    authz.require_matter(matter, "judge.a", "report.approve")
    with pytest.raises(MatterAccessDenied):
        authz.require_matter(matter, "judge.b", "matter.read")  # right role, not on the matter
    bindings.bind("reader", "read_only")
    matter.authorised_user_ids.add("reader")
    with pytest.raises(PolicyDenied):
        authz.require_matter(matter, "reader", "report.approve")  # on the matter, wrong role


def test_a_partys_lawyer_cannot_enter_the_tribunals_matter_even_if_added(demo):
    sv, mid = demo
    sv.users.add_user(
        actor_id="admin", user_id="sol.reid", display_name="P Reid", roles=["solicitor"]
    )
    with pytest.raises(PolicyDenied, match="valid on a adjudicator matter"):
        sv.matters.grant(mid, actor_id=A, user_id="sol.reid")
    matter = sv.matters.get(mid, A)
    matter.authorised_user_ids.add("sol.reid")  # even if membership were forced in
    sv.ctx.store.put_matter(matter)
    with pytest.raises(PolicyDenied):
        sv.matters.get(mid, "sol.reid")
    assert _denials(sv, mid)[-1]["payload"]["reason"] == "role_not_valid_for_profile"


def test_unauthorised_matter_access_is_denied_and_recorded(demo):
    sv, mid = demo
    before = len(_denials(sv, mid))
    with pytest.raises(MatterAccessDenied):
        sv.matters.get(mid, "admin")  # technical administrator, not a member
    with pytest.raises(PolicyDenied):
        sv.runs.resume(mid, "run_x", actor_id=S, reason="trying to restart")
    recorded = _denials(sv, mid)[before:]
    assert [(e["actor_id"], e["payload"]["reason"]) for e in recorded] == [
        ("admin", "not_a_member"),
        (S, "role_lacks_permission"),
    ]
    assert all(e["outcome"] == "denied" for e in recorded)


def test_technical_administration_gives_no_access_to_legal_matters():
    assert not {
        a
        for a in DEFAULT_ROLE_ACTIONS["system_admin"]
        if a.startswith(("matter.", "document.", "report."))
    }


def test_cross_matter_access_denied_and_recorded(held_run):
    sv, mid, rid = held_run
    other = sv.matters.create(
        actor_id=A, name="Other", purpose="p", jurisdiction="XX", profile=Profile.ADJUDICATOR
    )
    with pytest.raises(NotFound):
        sv.runs.get(
            other.matter_id, rid, actor_id=A
        )  # a real run id, presented under another matter
    event = _denials(sv, other.matter_id)[-1]
    assert event["event_type"] == "cross_matter_access" and event["subject_id"] == rid
    assert sv.ctx.store.search_chunks(other.matter_id, "containers delivered Port Varen") == []
    assert sv.ctx.store.list(Claim, other.matter_id) == []
    stolen = sv.verification.claims(mid, rid, actor_id=A)[0]
    stolen.matter_id = other.matter_id
    with pytest.raises(MatterAccessDenied):
        sv.ctx.store.put(stolen)  # a record cannot be rewritten into another matter


def test_only_a_human_can_hold_a_role_review_or_resolve(held_run):
    sv, mid, rid = held_run
    with pytest.raises(PolicyDenied, match="only a human"):
        sv.users.add_user(
            actor_id="admin",
            user_id="agent.one",
            display_name="Agent",
            roles=["arbitrator"],
            actor_type=ActorType.AGENT,
        )
    agent = sv.ctx.user(A)
    agent.actor_type = ActorType.AGENT  # even if a record were altered to carry the role
    sv.ctx.store.put_user(agent)
    report = sv.runs.summary(mid, rid, actor_id=A)["report"]
    with pytest.raises(PolicyDenied, match="agent or system actor"):
        sv.reviews.decide(
            mid,
            rid,
            actor_id=A,
            decision=ReviewDecision.REJECT,
            reasons="rejecting as an agent",
            report_hash=report["sha256"],
        )
    hold = sv.holds.list(mid, rid, actor_id=A)[0]
    with pytest.raises(PolicyDenied, match="only a human"):
        sv.holds.resolve(
            mid, hold.hold_id, actor_id=A, action="exclude", reason="agent trying to clear a hold"
        )


def test_a_run_cannot_start_without_a_named_human_reviewer(demo):
    sv, mid = demo
    sv.matters.set_reviewers(mid, actor_id=A, reviewer_ids=[])
    run = sv.runs.start(mid, actor_id=S)
    summary = sv.runs.summary(mid, run.run_id, actor_id=A)
    assert summary["status"] == "held"
    assert [h["reason"] for h in summary["open_holds"]] == ["missing_reviewer"]
    assert {s["step"]: s["status"] for s in summary["steps"]}["facts"] == "skipped"


def test_an_unapproved_source_cannot_be_used(demo):
    sv, mid = demo
    with pytest.raises(PolicyDenied):
        sv.matters.set_sources(mid, actor_id=A, source_ids=["some-website"])
    sv.sources.revoke("examplia-law-reports", actor_id="admin")
    run = sv.runs.start(mid, actor_id=S)
    assert (
        sv.runs.summary(mid, run.run_id, actor_id=A)["open_holds"][0]["reason"]
        == "unapproved_source"
    )


def test_closing_a_matter_ends_access_and_deletes_content_but_keeps_the_account(tmp_path):
    from eli_legal.application.services import build_services
    from eli_legal.demo import build_demo_workspace
    from eli_legal.demo_run import demo_settings, run_demo

    # Its own lifecycle: closing and deleting must not take away what other tests read from
    # the shared one (deletion now takes the reports and evidence packs too).
    lifecycle = run_demo(tmp_path / "own", say=lambda _line: None, install_network_guard=False)
    sv = build_services(
        demo_settings(lifecycle.root, build_demo_workspace(lifecycle.root / "demo")),
        install_network_guard=False,
    )
    mid, rid = lifecycle.matter_id, lifecycle.run_id
    counts = sv.matters.close(
        mid,
        actor_id=A,
        purge_content=True,
        reason="Award issued; retention period for working papers ended.",
    )
    assert counts["documents"] == 7 and counts["claims"] > 0 and counts["vault_files"] == 7
    assert sv.ctx.store.search_chunks(mid, "containers") == []
    with pytest.raises(PolicyDenied, match="closed"):
        sv.runs.start(mid, actor_id=A)
    with pytest.raises(MatterAccessDenied):
        sv.matters.get(mid, S)  # everyone but the owner lost access
    assert sv.runs.get(mid, rid, actor_id=A).status.value == "approved_for_reliance"
    assert sv.ctx.audit.report().ok
