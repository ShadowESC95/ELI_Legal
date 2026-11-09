"""Where each legal requirement stands, from the software's controls and the organisation's own
recorded work.

The requirements register says, for every requirement of the instruments that apply, what the
software does about it: all of it (``implemented``), part of it (``partial``), or nothing because
it is a duty of an organisation (``organisational``). That alone reads as "half done", which is
true of the software and says nothing about whether the requirement is met.

A requirement is *met* when the software's part is in place and the organisation has done and
recorded its part. Each organisation duty is an **action** (``organisation_actions.csv``): what
to do, the evidence it leaves (a form, a statement, training records, retention settings, an
evaluation, a registration number, a generated document), and how often it must be looked at
again. Recording one is a decision in a named person's name. This module turns the registers and
those records into one status per requirement, in plain words.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from eli_legal.domain.models import new_id, utcnow
from eli_legal.governance.registers import REGISTER_DIR, load_register

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
EVIDENCE_KINDS = (
    "form",
    "attestation",
    "training",
    "retention",
    "evaluation",
    "registration",
    "document",
)
DOCUMENT_KINDS = ("annex_iv", "declaration")
# The audit trail must be kept at least six months (EU AI Act Art. 19(1) and 26(6)).
MIN_AUDIT_RETENTION_DAYS = 183


@dataclass(frozen=True, slots=True)
class FormField:
    key: str
    label: str


@dataclass(frozen=True, slots=True)
class OrganisationAction:
    action_id: str
    title: str
    what_to_do: str
    requirement_ids: tuple[str, ...]
    owner: str
    evidence: str
    template: str
    statement: str
    review_days: int
    before_real_use: bool

    @property
    def form(self) -> tuple[FormField, ...]:
        return template_fields(self.template) if self.evidence == "form" else ()


@dataclass(slots=True)
class ComplianceRecord:
    """One piece of an organisation's compliance work, recorded in a named person's name."""

    action_id: str
    recorded_by: str
    summary: str  # one line a person reads in a list
    answers: dict[str, str] = field(default_factory=dict)  # form answers, or record fields
    notes: str = ""
    reference: str = ""  # where the full document is kept, a registration number, a file hash
    not_applicable: bool = False
    record_id: str = field(default_factory=lambda: new_id("cmp"))
    recorded_at: datetime = field(default_factory=utcnow)
    review_by: date | None = None


@dataclass(slots=True)
class TrainingRecord:
    user_id: str
    course: str
    completed_on: date
    recorded_by: str
    expires_on: date | None = None
    record_id: str = field(default_factory=lambda: new_id("trn"))
    recorded_at: datetime = field(default_factory=utcnow)

    def current(self, today: date) -> bool:
        return self.completed_on <= today and (self.expires_on is None or self.expires_on >= today)


@dataclass(frozen=True, slots=True)
class ActionStatus:
    action: OrganisationAction
    state: str  # done | waiting | review_due | not_applicable
    detail: str  # in plain words
    record: ComplianceRecord | None = None


@dataclass(frozen=True, slots=True)
class RequirementStatus:
    requirement_id: str
    instrument: str
    reference: str
    requirement: str
    addressed_to: str
    controls: tuple[str, ...]
    software_part: str  # implemented | partial | organisational
    how_met: str
    state: str  # software | met | waiting | review_due
    who: str  # "The software", "The software and your organisation", "Your organisation"
    actions: tuple[ActionStatus, ...]

    @property
    def outstanding(self) -> tuple[ActionStatus, ...]:
        return tuple(a for a in self.actions if a.state in ("waiting", "review_due"))


# ── the registers ────────────────────────────────────────────────────────────
def _ids(cell: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in cell.split(";") if part.strip())


def load_actions(directory: Path = REGISTER_DIR) -> list[OrganisationAction]:
    import csv

    with (directory / "organisation_actions.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [
        OrganisationAction(
            action_id=r["action_id"],
            title=r["title"],
            what_to_do=r["what_to_do"],
            requirement_ids=_ids(r["requirement_ids"]),
            owner=r["owner"],
            evidence=r["evidence"],
            template=r["template"],
            statement=r["statement"],
            review_days=int(r["review_days"] or 0),
            before_real_use=r["before_real_use"].strip().lower() == "yes",
        )
        for r in rows
    ]


_BULLET = re.compile(r"^- (.+)$")
_SIGNED = re.compile(r"^(approved|assessed) by\b", re.I)


def template_fields(name: str) -> tuple[FormField, ...]:
    """The questions of a governance template, read from the template itself so the form in
    the application and the document on paper can never differ. Each top-level bullet is a
    question; who signed it and when is recorded by the system, not typed."""
    path = TEMPLATE_DIR / f"{name}.md"
    if not name or not path.is_file():
        return ()
    questions: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        bullet = _BULLET.match(line)
        if bullet:
            questions.append(bullet.group(1).strip())
        elif questions and line.startswith("  ") and line.strip():
            questions[-1] += " " + line.strip()
    out = []
    for text in questions:
        label = text.rstrip(":").strip()
        if _SIGNED.match(label):
            continue
        key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:48]
        out.append(FormField(key=key, label=label))
    return tuple(out)


def template_title(name: str) -> str:
    path = TEMPLATE_DIR / f"{name}.md"
    if not path.is_file():
        return name.replace("_", " ")
    first = path.read_text(encoding="utf-8").splitlines()[0]
    return first.lstrip("# ").strip()


# ── statuses ─────────────────────────────────────────────────────────────────
_WHO = {
    "implemented": "The software",
    "partial": "The software and your organisation",
    "organisational": "Your organisation",
}


def action_status(
    action: OrganisationAction,
    records: Sequence[ComplianceRecord],
    *,
    today: date,
    people_untrained: Sequence[str] = (),
) -> ActionStatus:
    """Where one organisation action stands. ``records`` are that action's records, any order;
    the latest one counts."""
    latest = max(records, key=lambda r: r.recorded_at) if records else None
    if action.evidence == "training":
        if people_untrained:
            names = ", ".join(people_untrained[:4]) + ("…" if len(people_untrained) > 4 else "")
            return ActionStatus(
                action,
                "waiting",
                f"{len(people_untrained)} person(s) who work on matters have no current "
                f"training record: {names}.",
                latest,
            )
        return ActionStatus(
            action, "done", "Everyone who works on matters has a current record.", latest
        )
    if latest is None:
        return ActionStatus(action, "waiting", "Not recorded yet.")
    who = f"{latest.recorded_by} on {latest.recorded_at.date().isoformat()}"
    if latest.review_by is not None and latest.review_by < today:
        return ActionStatus(
            action,
            "review_due",
            f"Recorded by {who}; due for review since {latest.review_by.isoformat()}.",
            latest,
        )
    if latest.not_applicable:
        return ActionStatus(
            action, "not_applicable", f"Does not apply ({who}): {latest.notes}", latest
        )
    if latest.answers.get("passed") == "no":
        return ActionStatus(
            action, "waiting", f"Last run by {who} fell short. {latest.summary}", latest
        )
    return ActionStatus(action, "done", f"Recorded by {who}. {latest.summary}".strip(), latest)


def requirement_statuses(
    actions: Iterable[OrganisationAction],
    records: Iterable[ComplianceRecord],
    *,
    today: date | None = None,
    people_untrained: Sequence[str] = (),
    register: Sequence[Mapping[str, str]] | None = None,
) -> list[RequirementStatus]:
    today = today or utcnow().date()
    by_action: dict[str, list[ComplianceRecord]] = {}
    for record in records:
        by_action.setdefault(record.action_id, []).append(record)
    action_list = list(actions)
    states = {
        a.action_id: action_status(
            a, by_action.get(a.action_id, []), today=today, people_untrained=people_untrained
        )
        for a in action_list
    }
    out = []
    for row in register if register is not None else load_register("requirements"):
        rid = row["requirement_id"]
        linked = tuple(states[a.action_id] for a in action_list if rid in a.requirement_ids)
        software = row["status"]
        if software == "implemented" and not linked:
            state = "software"
        elif any(a.state == "waiting" for a in linked) or not linked:
            state = "waiting"
        elif any(a.state == "review_due" for a in linked):
            state = "review_due"
        else:
            state = "met"
        out.append(
            RequirementStatus(
                requirement_id=rid,
                instrument=row["instrument"].split(" (")[0],
                reference=row["reference"],
                requirement=row["requirement_in_plain_words"],
                addressed_to=row["addressed_to"],
                controls=_ids(row["control_ids"]),
                software_part=software,
                how_met=row["how_met_and_what_remains"],
                state=state,
                who=_WHO.get(software, software),
                actions=linked,
            )
        )
    return out


def review_date(action: OrganisationAction, recorded: date) -> date | None:
    return recorded + timedelta(days=action.review_days) if action.review_days else None


def check_actions(
    actions: Sequence[OrganisationAction], register: Sequence[Mapping[str, str]]
) -> list[str]:
    """Problems with the actions register, as sentences. Empty means it is consistent."""
    problems = []
    known = {r["requirement_id"] for r in register}
    ids = [a.action_id for a in actions]
    for duplicate in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"duplicate organisation action {duplicate}")
    for a in actions:
        problems += [
            f"{a.action_id} refers to unknown requirement {r}"
            for r in a.requirement_ids
            if r not in known
        ]
        if a.evidence not in EVIDENCE_KINDS:
            problems.append(f"{a.action_id} has unknown evidence kind {a.evidence!r}")
        if a.evidence == "form" and not template_fields(a.template):
            problems.append(f"{a.action_id} names template {a.template!r}, which has no questions")
        if a.evidence == "document" and a.template not in DOCUMENT_KINDS:
            problems.append(f"{a.action_id} names unknown document {a.template!r}")
        if a.evidence in ("attestation", "document") and not a.statement:
            problems.append(f"{a.action_id} needs the statement a person confirms")
    linked = {r for a in actions for r in a.requirement_ids}
    for row in register:
        if row["status"] != "implemented" and row["requirement_id"] not in linked:
            problems.append(
                f"{row['requirement_id']} is {row['status']} but no organisation action covers "
                "what remains"
            )
    return problems
