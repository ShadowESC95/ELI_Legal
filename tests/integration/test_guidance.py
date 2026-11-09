"""What to do next, for each person, at every stage of a matter."""

from eli_legal.application.matter_service import TeamMember
from eli_legal.demo_run import resolve_demo_holds
from eli_legal.domain.enums import Profile, ReviewDecision
from eli_legal.workflows.case_preparation import warning_id

A, S = "arb.keane", "sec.byrne"


def _guide(sv, mid, who=A):
    return sv.guidance.for_matter(mid, actor_id=who)


def _current(guide):
    return [s.key for s in guide.stages if s.state == "current"]


def test_a_new_matter_says_what_it_needs_before_anything_can_run(services):
    sv = services
    sv.users.bootstrap_admin("admin")
    sv.users.add_user(actor_id="admin", user_id="judge.a", display_name="J", roles=["judge"])
    matter = sv.matters.create(
        actor_id="judge.a",
        name="A v B",
        purpose="p",
        jurisdiction="XX",
        profile=Profile.ADJUDICATOR,
        team=[],
    )
    guide = _guide(sv, matter.matter_id, "judge.a")
    assert _current(guide) == ["set_up"] and "named reviewer" in guide.headline
    titles = [s.title for s in guide.steps]
    assert titles[:3] == [
        "Name at least one reviewer",
        "Choose the legal sources",
        "State the issues",
    ]
    assert "Add the documents" in titles and "Run the analysis" not in titles
    assert all(s.can_do for s in guide.steps)
    assert guide.role == "Lead" and guide.reads == "You read all of this matter's material."


def test_each_stage_of_the_lifecycle_points_to_the_next_thing_to_do(demo):
    sv, mid = demo
    assert _guide(sv, mid).steps[0].title == "Run the analysis"
    run = sv.runs.start(mid, actor_id=S)
    held = _guide(sv, mid)
    assert _current(held) == ["holds"]
    assert held.steps[0].title.startswith("Resolve ") and held.steps[0].page == "review"
    secretary = _guide(sv, mid, S)
    assert secretary.role == "Case worker" and not secretary.steps[0].can_do
    assert "Aoife Keane" in secretary.steps[0].who
    assert {(w.text, w.page) for w in sv.guidance.my_work(actor_id=A)} >= {
        (s.title, s.page) for s in held.steps
    }
    assert not sv.guidance.my_work(actor_id=S), "nothing waits for someone who cannot do it"
    # Resolve everything as the demonstration does, then the guide moves on.
    resolve_demo_holds(sv, mid, run.run_id)
    assert _guide(sv, mid).steps[0].title == "Resume the run"
    sv.runs.resume(mid, run.run_id, actor_id=A, reason="All holds resolved by the tribunal.")
    review = _guide(sv, mid)
    assert (
        _current(review) == ["review"] and review.steps[0].title == "Review and approve the report"
    )
    report = sv.runs.summary(mid, run.run_id, actor_id=A)["report"]
    sv.reviews.decide(
        mid,
        run.run_id,
        actor_id=A,
        decision=ReviewDecision.APPROVE,
        reasons="Read in full; limits acknowledged.",
        report_hash=report["sha256"],
        acknowledged=[warning_id(w) for w in report["warnings"]],
    )
    assert _guide(sv, mid).steps[0].title == "Release the approved report"


def test_a_member_is_told_what_they_read_and_what_is_withheld(demo):
    sv, mid = demo
    sv.users.add_user(actor_id="admin", user_id="obs.x", display_name="O", roles=["read_only"])
    sv.matters.grant(mid, actor_id=A, user_id="obs.x")
    guide = _guide(sv, mid, "obs.x")
    assert guide.role == "Observer"
    assert "before all parties" in guide.reads and "withheld" in guide.reads
    assert "masked" in guide.reads
    claimant = next(p for p in sv.matters.get(mid, A).parties if p.role == "claimant")
    sv.matters.set_member(
        mid, actor_id=A, user_id=S, matter_role="case_worker", party=claimant.name
    )
    assert f"You act for {claimant.name}" in _guide(sv, mid, S).reads
    assert TeamMember  # imported for the reader: a team is set up the same way at creation
