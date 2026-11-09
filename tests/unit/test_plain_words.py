"""Every code a person might be shown has words, and the same thing is called the same thing."""

from eli_legal.domain import plain
from eli_legal.domain.enums import (
    ClaimStatus,
    DocumentStatus,
    HoldResolution,
    RunStatus,
    StepStatus,
    VerificationStatus,
    VerificationType,
)
from eli_legal.governance.gates import _REASON_BY_STATUS
from eli_legal.security.rbac import ALL_ACTIONS, DEFAULT_ROLE_ACTIONS


def test_every_state_a_person_is_shown_has_plain_words_and_a_tone():
    for enum in (RunStatus, StepStatus, ClaimStatus, VerificationStatus, DocumentStatus):
        for member in enum:
            words = plain.state(member)
            assert "_" not in words and words[0].isupper(), member
            assert plain.tone(member.value), member
            assert plain.tone(words) == plain.tone(member.value), (member, words)
    assert plain.state("awaiting_human_review") == "Waiting for review"
    assert plain.resolution(HoldResolution.WAIVED) == "Accepted, with reasons"
    assert plain.state(DocumentStatus.WAIVED) == "Not read; gap accepted"
    assert all(plain.resolution(r) != r.value for r in HoldResolution)


def test_every_hold_reason_the_gates_raise_is_explained_with_what_to_do():
    for code in [*_REASON_BY_STATUS.values(), "prompt_injection_detected", "coverage_gap",
                 "dependency_held", "step_failed", "missing_reviewer", "unapproved_source",
                 "framework_unusable"]:  # fmt: skip
        explained = plain.hold_explanation(code)
        assert explained.headline != code.replace("_", " ").capitalize(), code
        assert explained.why and explained.options, code


def test_checks_actions_and_roles_read_as_words():
    for vtype in VerificationType:
        assert plain.check_name(vtype.value) != vtype.value
    for action in ALL_ACTIONS:
        assert "." not in plain.action(action), action
    for role in DEFAULT_ROLE_ACTIONS:
        assert plain.role(role) and plain.role_summary(role), role


def test_a_check_result_reads_as_a_sentence():
    said = plain.check_result(
        "current_law", "failed", "status today: overruled (overruled 2022-06-10 by [2022] XXSC 7)"
    )
    assert said == "Still good law today? No: overruled (overruled on 2022-06-10 by [2022] XXSC 7)."
    stale = plain.check_result(
        "current_law",
        "inconclusive",
        "status last confirmed 2024-01-02; older than the 365-day limit for XX",
    )
    assert "must have been confirmed within 365 days" in stale
    assert plain.check_result("citation", "verified", "found in examplia") == (
        "The authority exists: yes. Found in examplia."
    )


def test_identity_and_events_are_said_plainly():
    assert plain.identity("gui-passphrase+step-up") == (
        "desktop sign-in with passphrase, passphrase confirmed again"
    )
    assert "not a real sign-in" in plain.identity("test-harness")
    assert plain.event("matter_updated", "access_granted") == "Gave a person access"
    assert plain.event("something_new", "done") == "Something new: done"
    assert plain.lower_first("AI literacy") == "AI literacy"
    assert plain.lower_first("A check failed") == "a check failed"
