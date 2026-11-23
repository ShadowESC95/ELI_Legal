"""The system's words for people.

Records keep stable codes (``awaiting_human_review``, ``prompt_injection_detected``,
``matter.manage``) because tests, the audit ledger and other systems depend on them. Nobody should
have to read those codes to use the system. Every screen, report and command that shows a state,
a reason, a check or an action to a person passes it through here, so the same thing is always
called the same thing, in plain words, in every front end.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── states ───────────────────────────────────────────────────────────────────
_STATES: dict[str, str] = {
    # runs
    "created": "Not started",
    "running": "Running",
    "held": "On hold",
    "blocked": "Blocked",
    "stopped": "Stopped",
    "awaiting_human_review": "Waiting for review",
    "approved_for_reliance": "Approved for reliance",
    "rejected": "Rejected",
    "returned_for_correction": "Returned for correction",
    # steps
    "pending": "Not reached yet",
    "ok": "Done",
    "failed": "Failed",
    "skipped": "Skipped",
    # findings
    "draft": "Draft",
    "unverified": "Not yet checked",
    "verified": "Verified",
    "excluded": "Taken out of reliance",
    # checks
    "not_run": "Not checked",
    "inconclusive": "Could not be confirmed",
    "conflict": "Conflicting results",
    # documents
    "registered": "Received, not yet read",
    "processed": "Read",
    "unsupported": "Could not be read",
    "waived": "Not read; gap accepted",
    # matters
    "active": "Active",
    "closed": "Closed",
    # holds, tasks, incidents
    "open": "Open",
    "resolved": "Resolved",
    "done": "Done",
    "cancelled": "Cancelled",
    # reports
    "not_for_reliance": "Draft, not for reliance",
    # authorities
    "in_force": "In force",
    "amended": "Amended",
    "repealed": "Repealed",
    "overruled": "Overruled",
    "reversed": "Reversed",
    "superseded": "Superseded",
    "doubted": "Doubted",
    "not_yet_in_force": "Not yet in force",
    "unknown": "Status unknown",
    # review decisions
    "approve": "Approved",
    "reject": "Rejected",
    "return_for_correction": "Returned for correction",
    # compliance and routine checks
    "met": "Met",
    "software": "Met by the software",
    "waiting": "Waiting for your organisation",
    "to_do": "To do",
    "clear": "Clear",
    "review_due": "Review due",
    "attention": "Needs attention",
    "could_not_run": "Could not run",
    "not_applicable": "Does not apply",
}


def state(value: object) -> str:
    """A state code as a person would say it: ``awaiting_human_review`` → "Waiting for review"."""
    raw = getattr(value, "value", value)
    text = str(raw or "")
    return _STATES.get(text.lower(), text.replace("_", " ").capitalize())


# The tone a state is shown in: good, warn, bad, active or idle. One mapping for every front end.
_TONES: dict[str, set[str]] = {
    "good": {
        "ok", "verified", "approved", "approved_for_reliance", "processed", "valid", "resolved",
        "implemented", "treated", "approve", "done", "staged", "active", "in_force", "signed_in",
        "met", "software", "clear",
    },
    "warn": {
        "held", "inconclusive", "conflict", "open", "awaiting_human_review", "partial", "waived",
        "returned_for_correction", "return_for_correction", "unverified", "registered", "amended",
        "doubted", "not_run", "not_for_reliance", "waiting", "review_due", "attention", "shared",
        "to_do",
    },
    "bad": {
        "failed", "rejected", "blocked", "denied", "invalid", "unsupported", "reject",
        "overruled", "repealed", "reversed", "superseded", "sign_in_refused", "serious", "high",
        "could_not_run", "overdue",
    },
    "active": {"running", "created", "started", "restarted", "recorded"},
    "idle": {
        "pending", "skipped", "stopped", "excluded", "cancelled", "closed", "draft", "unknown",
        "organisational", "organisation", "inactive", "none", "not_applicable",
    },
}  # fmt: skip
TONE = {code: tone for tone, codes in _TONES.items() for code in codes}
_TONE_BY_WORDS = {_STATES[c].lower(): t for c, t in TONE.items() if c in _STATES}


def tone(value: object) -> str:
    """good | warn | bad | active | idle | "" for a state code or its plain words."""
    raw = str(getattr(value, "value", value) or "").lower()
    return TONE.get(raw) or _TONE_BY_WORDS.get(raw, "")


# ── holds ────────────────────────────────────────────────────────────────────
_RESOLUTIONS = {
    "reverified": "Checks now pass",
    "excluded": "Taken out of reliance",
    "waived": "Accepted, with reasons",
    "corrected": "Corrected and run again",
    "lifted": "Lifted, with reasons",
}


def resolution(value: object) -> str:
    """How a hold was closed. Not ``state``: a waived hold is not an unread document."""
    raw = str(getattr(value, "value", value) or "")
    return _RESOLUTIONS.get(raw, raw.replace("_", " ").capitalize())


@dataclass(frozen=True, slots=True)
class Explanation:
    """What happened, why it matters, and what a person can do about it."""

    headline: str
    why: str
    options: tuple[str, ...]


_HOLD_REASONS: dict[str, Explanation] = {
    "prompt_injection_detected": Explanation(
        "Contains text addressed to an AI system",
        "A document holds wording that tries to instruct an AI (for example 'ignore previous "
        "instructions'). It is kept as evidence but nothing in it is given to a model until a "
        "person has looked at it.",
        (
            "Read the passage. If it is ordinary evidence, accept it with reasons.",
            "If it was planted, take the document out of reliance and open an incident.",
        ),
    ),
    "coverage_gap": Explanation(
        "A document was not read",
        "The system could not read this file (for example a scan or photograph without text), "
        "so nothing in it is reflected in the analysis.",
        (
            "Convert it to text (OCR) and add it again, then resume the run.",
            "Or accept the gap with reasons: the report will say the document was not read.",
        ),
    ),
    "pages_not_read": Explanation(
        "Pages of a document were not read",
        "Some pages are only an image (a scan or a photographed exhibit) with no text layer, "
        "and OCR could not read them here, so nothing on them is in the analysis. The rest of "
        "the document was read.",
        (
            "Add a readable copy of those pages (a searchable PDF or the text), then restart.",
            "Or install OCR (Tesseract and Poppler) and restart from the Document reader.",
            "Or, having checked the pages against the original, accept the gap with reasons: "
            "the report will say they were not read.",
        ),
    ),
    "image_text_unread": Explanation(
        "Images beside the text were not read",
        "These pages have text and also images, and OCR is not installed here to read them. "
        "An image may be an exhibit (an invoice or a letter pasted under its caption) whose "
        "words are not in the analysis. On a real matter that is checked, not assumed.",
        (
            "Look at the pages in the original. If the images hold nothing the analysis needs "
            "(a logo, a signature), accept it with reasons.",
            "If one is an exhibit, install OCR and read the document again, or add its text.",
        ),
    ),
    "ocr_low_confidence": Explanation(
        "Pages read by OCR need checking",
        "These pages are images read by OCR, and the OCR was not confident of the words: a "
        "date, a figure or a citation on them may be misread.",
        (
            "Compare the OCR text with the original pages; if it is right, accept it with reasons.",
            "If it is wrong, add a correct text of the pages and restart.",
        ),
    ),
    "verification_failed": Explanation(
        "A check failed",
        "A finding did not pass a check its kind requires, so it cannot be relied on as it stands.",
        (
            "If the check was wrong, verify it by hand with reasons (this is recorded as an "
            "override).",
            "Otherwise take the finding out of reliance; the report lists it with the reason.",
        ),
    ),
    "verification_inconclusive": Explanation(
        "A check could not be completed",
        "The system could not confirm this finding on its own, for example because a "
        "quotation rewords its source or an authority's status was last confirmed too long ago.",
        (
            "Check it against the source and record the result with reasons.",
            "Or take the finding out of reliance.",
        ),
    ),
    "verification_conflict": Explanation(
        "Checks disagree",
        "Different checks or sources gave different answers about this finding.",
        ("Decide which is right and record it with reasons, or take the finding out of reliance.",),
    ),
    "verification_missing": Explanation(
        "A required check was not run",
        "A finding of this kind needs a check that has not been carried out.",
        ("Run the check by hand and record the result, or take the finding out of reliance.",),
    ),
    "dependency_held": Explanation(
        "Relies on a finding that is on hold",
        "This finding rests on another finding that is held, so it is held too.",
        ("Resolve the finding it relies on; this hold then clears on its own.",),
    ),
    "step_failed": Explanation(
        "A step of the work failed",
        "One step of the analysis did not finish cleanly, so nothing after it ran.",
        ("Look at the step in the Workflow page, fix the cause, then resume the run.",),
    ),
    "held_by_person": Explanation(
        "Put on hold by a person",
        "Someone on the matter stopped the work at this point, with reasons: nothing goes "
        "further (no approval, no release, no reliance on an approved report) until a "
        "decision-maker deals with it.",
        (
            "Lift the hold, with reasons, when what prompted it is dealt with: the run returns "
            "to where it was.",
            "Or stop the run; a new run can then be started.",
        ),
    ),
    "missing_reviewer": Explanation(
        "No reviewer is named",
        "Nothing can be relied on until a named person with a reviewing role approves it, so "
        "the work does not start without one.",
        ("On the Case details page, name at least one reviewer, then start the run again.",),
    ),
    "unapproved_source": Explanation(
        "A legal source is not approved",
        "The matter lists a legal source that is no longer approved, and the system reads only "
        "approved sources.",
        (
            "Choose approved sources on the Case details page, or ask for the source to be approved.",
        ),
    ),
    "framework_unusable": Explanation(
        "A law or standards package cannot be used",
        "A package chosen for the matter is withdrawn, changed since it was approved, or not "
        "yet approved.",
        ("Approve the package in Laws and standards, or take it off the case.",),
    ),
    "jurisdiction_pack_unvalidated": Explanation(
        "A legal system's pack is not validated",
        "The policy requires a lawyer qualified in that legal system to have validated its pack.",
        ("Record the lawyer's validation in Settings → Legal systems, or change the policy.",),
    ),
    "authority_changed_after_approval": Explanation(
        "The law changed after approval",
        "An authority relied on in an approved report has since been recorded as overruled, "
        "repealed or otherwise no longer good law.",
        (
            "Tell whoever relied on the report; consider a new run.",
            "Record what was done in the incident.",
        ),
    ),
}


def hold_reason(code: str) -> str:
    known = _HOLD_REASONS.get(code)
    return known.headline if known else code.replace("_", " ").capitalize()


def hold_explanation(code: str) -> Explanation:
    return _HOLD_REASONS.get(
        code,
        Explanation(
            hold_reason(code),
            "The system stopped this item for a person to decide.",
            ("Decide with reasons, or take it out of reliance.",),
        ),
    )


# ── checks on a finding ──────────────────────────────────────────────────────
_CHECKS: dict[str, tuple[str, str]] = {
    "provenance": ("The source exists, unaltered", "The document or authority the finding is "
                   "taken from is held, and its text is unchanged since it was filed or imported."),
    "evidence_support": ("The words appear in the document", "The finding is the quoted words, "
                         "and those words appear in the document they are said to come from."),
    "citation": ("The authority exists", "The case or statute is found in an approved legal "
                 "source."),
    "current_law": ("It is still good law", "The authority had not been overruled, repealed or "
                    "replaced on the date that matters, as the source last confirmed."),
    "proposition": ("The authority says this", "The authority says what it is quoted as saying."),
    "dependency": ("It rests only on verified findings", "Every finding it depends on is "
                   "verified."),
    "outcome_boundary": ("It states no outcome", "It does not say who should win or what the "
                         "result should be."),
}  # fmt: skip


def check_name(vtype: str) -> str:
    return _CHECKS.get(vtype, (vtype.replace("_", " ").capitalize(), ""))[0]


def check_meaning(vtype: str) -> str:
    return _CHECKS.get(vtype, ("", ""))[1]


_STATUS_LINE = re.compile(
    r"^status (?P<when>today|on [\d-]+): (?P<status>[a-z_]+)"
    r"(?: \((?P<treat>[a-z_]+) (?P<date>[\d-]+)(?: by (?P<by>[^)]+))?\))?"
    r"(?:, confirmed (?P<confirmed>[\d-]+|unknown))?(?P<rest>.*)$"
)
_STALE = re.compile(r"^status (?P<last>last confirmed [\d-]+|never confirmed); older than the "
                    r"(?P<days>\d+)-day limit for (?P<code>\S+)$")  # fmt: skip


def check_result(vtype: str, status: object, detail: str) -> str:
    """One check's outcome as a sentence: "Still good law? No: overruled on 2022-03-01 by …"."""
    code = str(getattr(status, "value", status) or "")
    detail = (detail or "").strip()
    if vtype == "current_law":
        stale = _STALE.match(detail)
        if stale:
            return (
                f"Could not confirm it is still good law: its status was "
                f"{stale['last']}, and it must have been confirmed within {stale['days']} days."
            )
        m = _STATUS_LINE.match(detail)
        if m:
            when = "today" if m["when"] == "today" else m["when"]
            said = state(m["status"]).lower()
            how = ""
            if m["treat"]:
                how = f" ({state(m['treat']).lower()} on {m['date']}"
                how += f" by {m['by']})" if m["by"] else ")"
            confirmed = f"; confirmed {m['confirmed']}" if m["confirmed"] else ""
            rest = m["rest"].replace("; needs human assessment", "").strip("; ")
            rest = f"; {rest}" if rest else ""
            verdict = {"verified": "Yes", "failed": "No"}.get(code, "Unclear")
            return f"Still good law {when}? {verdict}: {said}{how}{confirmed}{rest}."
    if code == "not_run" or not detail:
        return f"{check_name(vtype)}: {state(code).lower()}."
    verdict = {
        "verified": "yes",
        "failed": "no",
        "inconclusive": "not confirmed",
        "conflict": "results disagree",
    }.get(code, state(code).lower())
    return f"{check_name(vtype)}: {verdict}. {detail[0].upper()}{detail[1:]}".rstrip(".") + "."


# ── actions and events ───────────────────────────────────────────────────────
_ACTIONS: dict[str, str] = {
    "matter.create": "open a matter",
    "matter.read": "see the matter",
    "matter.manage": "change the matter, its team, sources and laws",
    "matter.close": "close the matter",
    "document.read": "read the documents",
    "document.ingest": "add documents",
    "document.waive": "accept that a document was not read",
    "workflow.run": "start or resume the analysis",
    "workflow.hold": "put work on hold",
    "workflow.stop": "stop the work",
    "workflow.restart": "restart stopped work",
    "facts.extract": "take facts from the documents",
    "issues.map": "map the issues",
    "evidence.map": "map the evidence to the issues",
    "research.run": "research the law",
    "report.draft": "draft the report",
    "citation.verify": "check that an authority exists",
    "authority.status_check": "check that an authority is still good law",
    "proposition.verify": "check that a source says what is claimed",
    "report.review": "review the report",
    "report.approve": "approve the report for reliance",
    "report.export": "export the report",
    "report.prepare_release": "prepare the report's release",
    "report.send": "release the report to the outbox",
    "hold.resolve": "resolve a hold",
    "hold.respond": "answer a hold on their own side's filing",
    "filing.read": "read the papers served on them and their own side's",
    "filing.add": "file papers for the party they act for",
    "verification.override": "overrule an automated check",
    "incident.manage": "open and close incidents",
    "audit.read": "read the audit trail",
    "audit.verify": "verify the audit trail",
    "evidence.export": "export the evidence pack",
    "user.manage": "manage people and their roles",
    "source.manage": "register and approve legal sources",
    "config.manage": "change the system's settings",
    "framework.manage": "manage the law and standards packages",
    "compliance.manage": "record the organisation's compliance work",
    "checks.run": "run the routine checks",
    "server.manage": "start and stop the server for everyone on a case",
    "sign_in": "sign in",
    "user.security": "change sign-in security",
}


def action(code: str) -> str:
    """``matter.manage`` → "change the matter, its team, sources and laws"."""
    return _ACTIONS.get(code, code.replace(".", " ").replace("_", " "))


_EVENTS: dict[tuple[str, str], str] = {
    ("matter_created", "created"): "Opened the matter",
    ("matter_updated", "access_granted"): "Gave a person access",
    ("matter_updated", "access_revoked"): "Removed a person's access",
    ("matter_updated", "reviewers_set"): "Named the reviewers",
    ("matter_updated", "sources_set"): "Chose the legal sources",
    ("matter_updated", "details_updated"): "Changed the matter's details",
    ("matter_updated", "frameworks_set"): "Chose the law and standards",
    ("matter_updated", "member_role_set"): "Changed a person's role on the matter",
    ("matter_closed", "closed"): "Closed the matter",
    ("matter_closed", "purged"): "Closed the matter and deleted its content",
    ("document_registered", "registered"): "Received a document",
    ("document_processed", "processed"): "Read a document",
    ("sign_in", "signed_in"): "Signed in",
    ("sign_in", "signed_in_two_factor"): "Signed in with a second factor",
    ("sign_in", "signed_out"): "Signed out",
    ("sign_in", "sign_in_refused"): "Sign-in refused",
    ("sign_in", "account_locked"): "Account locked after failed attempts",
    ("access_denied", "denied"): "Refused: not permitted",
    ("cross_matter_access", "denied"): "Refused: a record from another matter",
    ("routine_check", "ok"): "Routine checks: all clear",
    ("routine_check", "attention"): "Routine checks: something needs attention",
}


def event(event_type: str, outcome: str) -> str:
    """An audit event as a sentence a person can scan."""
    known = _EVENTS.get((event_type, outcome))
    if known:
        return known
    what = event_type.replace("_", " ").capitalize()
    how = outcome.replace("_", " ")
    return what if not how or how in what.lower() else f"{what}: {how}"


_METHODS = {
    "gui-passphrase": "desktop sign-in with passphrase",
    "web-session": "browser sign-in with passphrase",
    "cli-session": "command-line sign-in",
    "api-token": "API token issued to the person",
    "eli-host": "signed in through ELI v3",
    "system": "the system itself",
}


def identity(method: str) -> str:
    """How someone proved who they were: ``gui-passphrase+step-up`` → "desktop sign-in with
    passphrase, passphrase confirmed again"."""
    if not method:
        return "not recorded"
    base, _, extra = method.partition("+")
    words = _METHODS.get(base, base.replace("-", " "))
    if "harness" in base:
        words = f"test or demonstration harness ({base}), not a real sign-in"
    if extra:
        words += ", passphrase confirmed again"
    return words


# ── roles ────────────────────────────────────────────────────────────────────
_ROLES: dict[str, tuple[str, str]] = {
    "judge": ("Judge", "Decides the case. Runs, reviews, approves and releases the analysis."),
    "tribunal_member": ("Tribunal member", "Decides the case as part of a tribunal."),
    "arbitrator": ("Arbitrator", "Decides the dispute. Runs, reviews, approves and releases."),
    "tribunal_secretary": ("Tribunal secretary or registrar", "Files documents and runs the "
                           "analysis for the tribunal; decides nothing."),
    "mediator": ("Mediator", "Facilitates a settlement. Prepares and approves the brief."),
    "conciliator": ("Conciliator", "Facilitates a settlement. Prepares and approves the brief."),
    "supervising_solicitor": ("Supervising solicitor", "Leads the legal team; approves and "
                              "releases its work."),
    "solicitor": ("Solicitor", "Prepares the case and checks findings; cannot approve."),
    "barrister": ("Barrister", "Researches, drafts and checks; cannot run the system or approve."),
    "in_house_counsel": ("In-house counsel", "Leads the client's own legal work; approves it."),
    "paralegal": ("Paralegal", "Adds documents and runs the analysis; records no checks."),
    "reviewer": ("Reviewer", "Checks findings and reads reports on the matters they are given. To approve a report the account also needs a role that decides that kind of matter, such as judge, arbitrator, mediator or solicitor."),
    "legal_admin": ("Legal administrator", "Manages people, sources, laws and matters; can "
                    "also act on matters they are on."),
    "governance_officer": ("Governance officer", "Oversees compliance: sources, laws, holds, "
                           "incidents and the audit trail; prepares no case."),
    "auditor": ("Auditor", "Reads and verifies the audit trail and evidence packs; sees no "
                "case content."),
    "system_admin": ("Technical administrator", "Manages accounts and settings; has no access "
                     "to any matter."),
    "read_only": ("Read only", "Reads the matters they are given; changes nothing."),
    "prosecutor": ("Prosecutor", "Prosecutes for the state. On the court's matter acts for "
                   "the prosecution: files its papers and answers for them."),
    "self_represented": ("Party acting for themselves", "A party with no lawyer. On the "
                         "court's matter files their own papers and answers for them."),
}  # fmt: skip


def role(code: str) -> str:
    return _ROLES.get(code, (code.replace("_", " ").capitalize(), ""))[0]


def role_summary(code: str) -> str:
    return _ROLES.get(code, ("", ""))[1]


def either(names: list[str]) -> str:
    """ "Judge, Tribunal member or Arbitrator" for any number of names."""
    if not names:
        return "nobody"
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


def approvers(codes: object) -> str:
    """The account roles that may approve, in words: "Arbitrator, Judge or Tribunal member"."""
    return either(sorted(role(c) for c in codes))  # type: ignore[attr-defined]


def roles(codes: object) -> str:
    return ", ".join(sorted(role(c) for c in codes)) if codes else "no role"  # type: ignore[attr-defined]


_SCOPES = {
    "all_parties": ("Before all parties", "Filed in the proceedings; everyone on the matter may "
                    "see it."),
    "neutral_only": ("For the neutral only", "The tribunal's or mediator's own material; only "
                     "the decision-makers on the matter see it."),
    "party_confidential": ("In confidence from one party", "Given to the neutral by one party "
                           "in confidence; never in a shared output, and withheld from people "
                           "aligned with another party."),
    "privileged": ("Privileged", "Legal advice or work product; withheld from observers and "
                   "auditors."),
}  # fmt: skip


def scope(code: object) -> str:
    raw = str(getattr(code, "value", code) or "")
    return _SCOPES.get(raw, (raw.replace("_", " "), ""))[0]


def scope_meaning(code: object) -> str:
    raw = str(getattr(code, "value", code) or "")
    return _SCOPES.get(raw, ("", ""))[1]


_EFFECTS = {
    "enforced": "enforced by the system",
    "instruction": "given to the model",
    "attestation": "reviewer confirms",
    "disclosure": "disclosed in the report",
    "note": "for the organisation",
}


def effect(code: str) -> str:
    """How a law or standards requirement is met: ``attestation`` → "reviewer confirms"."""
    return _EFFECTS.get(code, code.replace("_", " "))


def kind(code: object) -> str:
    """A finding's or document's kind: ``party_authority`` → "Authority a party relies on"."""
    raw = str(getattr(code, "value", code) or "")
    return {
        "fact": "Fact",
        "party_authority": "Authority a party relies on",
        "legal_proposition": "Passage of an authority",
        "application": "Argument (model-drafted)",
        "procedural": "Procedural fact",
        "witness_statement": "Witness statement",
        "expert_report": "Expert report",
    }.get(raw, raw.replace("_", " ").capitalize())


def count(n: int, singular: str, plural: str | None = None) -> str:
    """``count(1, "hold")`` → "1 hold"; ``count(3, "hold")`` → "3 holds"."""
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def check_state(code: str) -> str:
    """A routine check's outcome: ``ok`` is "Clear", not "Done"."""
    return state("clear" if code == "ok" else code)


def lower_first(text: str) -> str:
    """ "A check failed" → "a check failed", leaving "AI" and names as they are."""
    first = text.split(" ", 1)[0]
    return text if len(first) > 1 and first.isupper() else text[:1].lower() + text[1:]


def short_id(record_id: str) -> str:
    """The part of a record id a person can read out: ``hld_3f1a…c9`` → ``…c9d2e1``."""
    return "…" + record_id[-6:] if len(record_id) > 8 else record_id


def vocabulary() -> dict[str, object]:
    """Everything here, for a front end that is not written in Python (the browser
    application), so it says things exactly as the others do."""
    return {
        "states": dict(_STATES),
        "tones": dict(TONE),
        "resolutions": dict(_RESOLUTIONS),
        "checks": {k: {"name": n, "meaning": m} for k, (n, m) in _CHECKS.items()},
        "holds": {
            k: {"headline": e.headline, "why": e.why, "options": list(e.options)}
            for k, e in _HOLD_REASONS.items()
        },
        "roles": {k: {"label": n, "summary": d} for k, (n, d) in _ROLES.items()},
        "scopes": {k: {"label": n, "meaning": d} for k, (n, d) in _SCOPES.items()},
        "effects": dict(_EFFECTS),
        "actions": dict(_ACTIONS),
    }
