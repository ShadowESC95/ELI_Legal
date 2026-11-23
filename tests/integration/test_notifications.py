"""When a run stops for a person, every person on the matter who can act on it is told, wherever
they are signed in; nobody is told to do what they may not do; and the notification goes once the
work is done. Each one is in the audit trail. Nothing is sent outside ELI Legal."""

from __future__ import annotations

from fastapi.testclient import TestClient

from eli_legal.api.app import create_app
from eli_legal.application.matter_service import hash_passphrase
from eli_legal.demo_run import resolve_demo_holds
from eli_legal.domain.enums import ReviewDecision
from eli_legal.domain.errors import NotFound
from eli_legal.workflows.case_preparation import warning_id

A, S, G = "arb.keane", "sec.byrne", "gov.hale"


def _kinds(sv, user):
    return {n["kind"]: n for n in sv.notifications.inbox(user)}


def test_a_held_run_tells_those_who_can_clear_its_holds_and_no_one_else(held_run):
    sv, mid, rid = held_run
    mine = _kinds(sv, A)
    assert set(mine) == {"holds_open"}
    note = mine["holds_open"]
    assert note["status"] == "open" and note["page"] == "review" and note["run_id"] == rid
    assert "6 holds to clear" in note["title"] and "A check failed" in note["detail"]
    assert _kinds(sv, S) == {}, "the secretary cannot resolve holds, so is not asked to"
    assert _kinds(sv, G) == {} and _kinds(sv, "admin") == {}, "not on the matter"
    told = [e for e in sv.ctx.audit.events(matter_id=mid) if e["event_type"] == "notification_sent"]
    assert [(e["payload"]["recipient"], e["payload"]["kind"]) for e in told] == [(A, "holds_open")]
    assert sv.ctx.audit.report().ok
    assert sv.run_record(mid, rid, actor_id=A).ok, "the run's own record is still complete"


def test_notifications_follow_the_work_to_review_and_go_when_it_is_decided(held_run):
    sv, mid, rid = held_run
    resolve_demo_holds(sv, mid, rid)
    assert set(_kinds(sv, A)) == {"restart_needed"}, "every hold cleared: restart is next"
    sv.runs.resume(mid, rid, actor_id=A, reason="All holds resolved; rebuild the report.")
    mine = _kinds(sv, A)
    assert set(mine) == {"review_required"}, "the earlier ones are done"
    assert {"approve", "reject", "return for correction"} <= set(mine["review_required"]["actions"])
    report = sv.runs.summary(mid, rid, actor_id=A)["report"]
    sv.reviews.decide(
        mid,
        rid,
        actor_id=A,
        decision=ReviewDecision.APPROVE,
        reasons="Checked each finding against its source; the stated limits are accepted.",
        report_hash=report["sha256"],
        acknowledged=[warning_id(w) for w in report["warnings"]],
    )
    assert _kinds(sv, A) == {}, "decided: nothing left waiting"


def test_seen_is_not_done_and_no_one_can_mark_another_persons(held_run):
    sv, mid, _rid = held_run
    note = sv.notifications.inbox(A)[0]
    try:
        sv.notifications.mark_read(mid, note["notification_id"], actor_id=S)
        raise AssertionError("another person's notification was marked")
    except NotFound:
        pass
    sv.notifications.mark_read(mid, note["notification_id"], actor_id=A)
    again = sv.notifications.inbox(A)
    assert again[0]["status"] == "read", "seen, but kept until the holds are cleared"
    assert sv.notifications.unread(A) == 0


def test_two_people_signed_in_to_the_server_are_each_told_what_is_theirs(held_run):
    sv, mid, rid = held_run
    admin = sv.ctx.user("admin")
    admin.passphrase_hash = hash_passphrase("administrator phrase")
    sv.ctx.store.put_user(admin)
    tokens = {u: sv.users.issue_token(actor_id="admin", user_id=u) for u in (A, S)}
    client = TestClient(create_app(sv), base_url="http://localhost")
    auth = {u: {"Authorization": f"Bearer {t}"} for u, t in tokens.items()}
    arbitrator = client.get("/v1/notifications", headers=auth[A]).json()
    secretary = client.get("/v1/notifications", headers=auth[S]).json()
    assert arbitrator["unread"] == 1 and arbitrator["items"][0]["kind"] == "holds_open"
    assert secretary == {"unread": 0, "items": []}
    nid = arbitrator["items"][0]["notification_id"]
    path = f"/v1/matters/{mid}/notifications/{nid}/read"
    assert client.post(path, headers=auth[S]).status_code == 404, "not theirs to mark"
    assert client.post(path, headers=auth[A]).json()["status"] == "read"
    assert client.get("/v1/notifications", headers=auth[A]).json()["unread"] == 0
    assert client.get("/v1/notifications").status_code == 401


def test_a_closed_matter_asks_nothing_of_anyone(held_run):
    sv, mid, _rid = held_run
    sv.matters.close(mid, actor_id=A, purge_content=False, reason="Settled between the parties.")
    assert _kinds(sv, A) == {}
