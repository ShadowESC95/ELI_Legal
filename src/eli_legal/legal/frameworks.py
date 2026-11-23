"""Law and standards packages ("frameworks") that apply to a matter.

A framework pack is one instrument a matter must comply with: an international or EU regulation,
a national statute or court rule, a professional standard, or an organisation's own policy. Each
pack lists its requirements in plain words, with the provision each comes from, and says for each
one how this system meets it:

``enforced``     the system's own controls carry it out (named by id, checked against the
                 control register);
``instruction``  it is given to the model, in every model call on the matter, as a rule;
``attestation``  a named reviewer must confirm it before the report can be approved;
``disclosure``   a statement that must appear in the report;
``note``         an obligation that rests with an organisation rather than with the work on one
                 matter. It is listed in the report so nobody can say they were not told.

A pack can also *tighten* how the system runs: a shorter limit on how old a confirmation of an
authority's status may be, and terms that model-drafted text may never contain. Nothing in a pack
can loosen a control. Packs are data: the ones shipped are summaries prepared for this software,
marked unvalidated until a qualified lawyer signs them off; an organisation's own packs must be
approved, in a named person's name, before any matter can use them.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from eli_legal.domain.enums import Profile
from eli_legal.domain.errors import InvalidInput

SHIPPED_DIR = Path(__file__).resolve().parent.parent / "config" / "frameworks"

EFFECTS = ("enforced", "instruction", "attestation", "disclosure", "note")
SCOPES = ("international", "regional", "national", "sectoral", "professional", "organisational")
PROFILES = tuple(p.value for p in Profile)
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_REQ_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._()/-]{0,63}$")
MAX_REQUIREMENTS = 400
MAX_TEXT = 4000
# The most a pack set may add to a model's instructions. Packs are read by a person in full; the
# model is given each applicable instruction, and a summary line for everything else.
MAX_CONTEXT_CHARS = 9000


@dataclass(frozen=True, slots=True)
class Requirement:
    req_id: str
    reference: str
    title: str
    text: str
    effect: str = "note"
    addressed_to: tuple[str, ...] = ("user",)
    profiles: tuple[str, ...] = ()  # empty: every profile
    controls: tuple[str, ...] = ()
    instruction: str = ""  # what the model is told; the requirement text if empty
    statement: str = ""  # what a reviewer confirms, or what the report discloses

    def applies_to(self, profile: str) -> bool:
        return not self.profiles or profile in self.profiles

    @property
    def model_rule(self) -> str:
        return self.instruction or self.text

    @property
    def confirmation(self) -> str:
        return self.statement or self.text


@dataclass(frozen=True, slots=True)
class Rules:
    """How a pack tightens the system. Tightening only: limits combine to the strictest."""

    status_max_age_days: int | None = None
    forbidden_terms: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FrameworkPack:
    pack_id: str
    title: str
    short_title: str
    scope: str
    jurisdictions: tuple[str, ...]  # pack codes it belongs to; "*" for anywhere
    instrument: str  # the official name and number of what it summarises
    issuer: str
    version: str
    as_at: str  # the date the summary was checked against its source
    description: str
    requirements: tuple[Requirement, ...]
    rules: Rules = field(default_factory=Rules)
    recommend_for: tuple[str, ...] = ()  # profiles for which it is pre-selected
    source_url: str = ""
    licence_note: str = ""
    status_note: str = ""
    origin: str = "shipped"  # shipped | organisation
    example: bool = False  # a worked example, never pre-selected
    validated_by: str = ""  # for a shipped pack, the lawyer who signed it off, if anyone

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical(self).encode("utf-8")).hexdigest()

    @property
    def fingerprint(self) -> str:
        return f"{self.version}@{self.sha256[:12]}"

    def applicable(self, profile: str) -> list[Requirement]:
        return [r for r in self.requirements if r.applies_to(profile)]

    def covers(self, codes: Iterable[str]) -> bool:
        wanted = set(codes)
        return "*" in self.jurisdictions or bool(wanted & set(self.jurisdictions))


# ── reading and writing packs ─────────────────────────────────────────────────
def _text(raw: Mapping[str, Any], key: str, *, required: bool = False, limit: int = 600) -> str:
    value = raw.get(key, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise InvalidInput(f"{key} must be text")
    value = " ".join(value.split()) if limit <= 600 else value.strip()
    if required and not value:
        raise InvalidInput(f"{key} is required")
    if len(value) > limit:
        raise InvalidInput(f"{key} is longer than {limit} characters")
    return value


def _list(raw: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = raw.get(key) or []
    if isinstance(value, str):
        value = [v for v in re.split(r"[;,]", value) if v.strip()]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise InvalidInput(f"{key} must be a list of text")
    return tuple(v.strip() for v in value if v.strip())


def requirement_from(raw: Mapping[str, Any]) -> Requirement:
    if not isinstance(raw, Mapping):
        raise InvalidInput("each requirement must be an object")
    req_id = _text(raw, "id", required=True, limit=64)
    if not _REQ_ID.match(req_id):
        raise InvalidInput(
            f"requirement id {req_id!r} may use letters, digits and . _ - ( ) / only"
        )
    effect = _text(raw, "effect") or "note"
    if effect not in EFFECTS:
        raise InvalidInput(f"requirement {req_id}: effect must be one of {', '.join(EFFECTS)}")
    profiles = _list(raw, "profiles")
    unknown = sorted(set(profiles) - set(PROFILES))
    if unknown:
        raise InvalidInput(f"requirement {req_id}: unknown profile(s) {', '.join(unknown)}")
    # A package written before controls took the RAIMS ids may name one by its former number.
    from eli_legal.governance.registers import current_control_id

    controls = tuple(current_control_id(c) for c in _list(raw, "controls"))
    if effect == "enforced" and not controls:
        raise InvalidInput(f"requirement {req_id}: an enforced requirement must name its controls")
    return Requirement(
        req_id=req_id,
        reference=_text(raw, "reference", limit=200),
        title=_text(raw, "title", required=True, limit=300),
        text=_text(raw, "text", required=True, limit=MAX_TEXT),
        effect=effect,
        addressed_to=_list(raw, "addressed_to") or ("user",),
        profiles=profiles,
        controls=controls,
        instruction=_text(raw, "instruction", limit=MAX_TEXT),
        statement=_text(raw, "statement", limit=MAX_TEXT),
    )


def pack_from(raw: Mapping[str, Any], *, origin: str | None = None) -> FrameworkPack:
    """A pack from its JSON form, checked. Anything malformed is refused with the reason."""
    if not isinstance(raw, Mapping):
        raise InvalidInput("a framework pack must be a JSON object")
    pack_id = _text(raw, "id", required=True, limit=64).lower()
    if not _ID.match(pack_id):
        raise InvalidInput("the pack id may use lower-case letters, digits and . _ - only")
    scope = _text(raw, "scope") or "organisational"
    if scope not in SCOPES:
        raise InvalidInput(f"scope must be one of {', '.join(SCOPES)}")
    items = raw.get("requirements")
    if not isinstance(items, list) or not items:
        raise InvalidInput("a pack needs at least one requirement")
    if len(items) > MAX_REQUIREMENTS:
        raise InvalidInput(f"a pack may hold at most {MAX_REQUIREMENTS} requirements")
    requirements = tuple(requirement_from(r) for r in items)
    seen: set[str] = set()
    for r in requirements:
        if r.req_id in seen:
            raise InvalidInput(f"requirement id {r.req_id} appears twice")
        seen.add(r.req_id)
    rules_raw = raw.get("rules") or {}
    if not isinstance(rules_raw, Mapping):
        raise InvalidInput("rules must be an object")
    age = rules_raw.get("status_max_age_days")
    if age is not None and (not isinstance(age, int) or isinstance(age, bool) or age < 1):
        raise InvalidInput("rules.status_max_age_days must be a whole number of days, 1 or more")
    terms = _list(rules_raw, "forbidden_terms")
    recommend = _list(raw, "recommend_for")
    unknown = sorted(set(recommend) - set(PROFILES))
    if unknown:
        raise InvalidInput(f"recommend_for: unknown profile(s) {', '.join(unknown)}")
    return FrameworkPack(
        pack_id=pack_id,
        title=_text(raw, "title", required=True, limit=300),
        short_title=_text(raw, "short_title", limit=80) or _text(raw, "title", limit=300)[:80],
        scope=scope,
        jurisdictions=tuple(j.upper() if j != "*" else j for j in _list(raw, "jurisdictions"))
        or ("*",),
        instrument=_text(raw, "instrument", limit=400),
        issuer=_text(raw, "issuer", limit=300),
        version=_text(raw, "version", limit=80) or "1",
        as_at=_text(raw, "as_at", limit=40),
        description=_text(raw, "description", limit=MAX_TEXT),
        requirements=requirements,
        rules=Rules(status_max_age_days=age, forbidden_terms=tuple(t.lower() for t in terms)),
        recommend_for=recommend,
        source_url=_text(raw, "source_url", limit=500),
        licence_note=_text(raw, "licence_note", limit=MAX_TEXT),
        status_note=_text(raw, "status_note", limit=MAX_TEXT),
        origin=origin or _text(raw, "origin") or "organisation",
        example=bool(raw.get("example", False)),
        validated_by=_text(raw, "validated_by", limit=200),
    )


def pack_to_dict(pack: FrameworkPack) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": pack.pack_id,
        "title": pack.title,
        "short_title": pack.short_title,
        "scope": pack.scope,
        "jurisdictions": list(pack.jurisdictions),
        "instrument": pack.instrument,
        "issuer": pack.issuer,
        "version": pack.version,
        "as_at": pack.as_at,
        "description": pack.description,
        "source_url": pack.source_url,
        "licence_note": pack.licence_note,
        "status_note": pack.status_note,
        "recommend_for": list(pack.recommend_for),
        "example": pack.example,
        "rules": {
            "status_max_age_days": pack.rules.status_max_age_days,
            "forbidden_terms": list(pack.rules.forbidden_terms),
        },
        "requirements": [
            {
                "id": r.req_id,
                "reference": r.reference,
                "title": r.title,
                "text": r.text,
                "effect": r.effect,
                "addressed_to": list(r.addressed_to),
                "profiles": list(r.profiles),
                "controls": list(r.controls),
                "instruction": r.instruction,
                "statement": r.statement,
            }
            for r in pack.requirements
        ],
    }
    return out


def canonical(pack: FrameworkPack) -> str:
    """The content that is approved and fingerprinted. Who validated a shipped pack is a record
    about the pack, not part of it, so it is left out."""
    return json.dumps(pack_to_dict(pack), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def load_shipped(directory: Path = SHIPPED_DIR) -> dict[str, FrameworkPack]:
    out: dict[str, FrameworkPack] = {}
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        pack = pack_from(json.loads(path.read_text(encoding="utf-8")), origin="shipped")
        if pack.pack_id in out:
            raise InvalidInput(f"two shipped packs use the id {pack.pack_id}")
        out[pack.pack_id] = pack
    return out


# ── importing an organisation's own requirements ──────────────────────────────
_SLUG = re.compile(r"[^a-z0-9]+")


def slug(text: str) -> str:
    return _SLUG.sub("-", text.lower()).strip("-")[:48] or "pack"


def pack_from_csv(
    raw: bytes, *, pack_id: str, title: str, issuer: str = "", version: str = "1"
) -> FrameworkPack:
    """A requirements register kept as a spreadsheet: one row per requirement, with columns
    id, reference, title, text, effect (optional), profiles (optional), instruction, statement."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidInput("the CSV file must be UTF-8") from exc
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise InvalidInput("the CSV file has no rows")
    columns = {c.strip().lower() for c in rows[0].keys() if c}
    if not {"text"} <= columns:
        raise InvalidInput("the CSV file needs at least a 'text' column")
    requirements = []
    for number, row in enumerate(rows, start=1):
        clean = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        if not clean.get("text"):
            continue
        requirements.append(
            {
                "id": clean.get("id") or f"R{number}",
                "reference": clean.get("reference", ""),
                "title": clean.get("title") or clean["text"][:120],
                "text": clean["text"],
                "effect": clean.get("effect") or "instruction",
                "profiles": clean.get("profiles", ""),
                "controls": clean.get("controls", ""),
                "instruction": clean.get("instruction", ""),
                "statement": clean.get("statement", ""),
            }
        )
    return pack_from(
        {
            "id": pack_id,
            "title": title,
            "scope": "organisational",
            "issuer": issuer,
            "version": version,
            "requirements": requirements,
        },
        origin="organisation",
    )


_CLAUSE = re.compile(r"^\s*((?:\d+[.)]?)+(?:\d+)?|[A-Z][.)]|\([a-z0-9]+\))\s+(.*)$", re.S)


def pack_from_paragraphs(
    paragraphs: Sequence[tuple[str, str]],
    *,
    pack_id: str,
    title: str,
    issuer: str = "",
    version: str = "1",
) -> FrameworkPack:
    """An organisation's standard as a document: each numbered clause, or each paragraph that
    reads as a rule, becomes a requirement the model is told to follow. One further requirement
    asks the reviewer to confirm the work meets the standard as a whole. Export the pack, refine
    which clauses a reviewer must confirm, and import it again for finer control."""
    requirements: list[dict[str, str]] = []
    for locator, raw_text in paragraphs:
        text = " ".join(raw_text.split())
        if len(text) < 25 or (len(text.split()) < 12 and not text.endswith((".", ";", ":", ")"))):
            continue  # headings, page numbers
        match = _CLAUSE.match(text)
        reference = match.group(1).rstrip(".)") if match else locator
        body = match.group(2).strip() if match else text
        requirements.append(
            {
                "id": f"C{len(requirements) + 1}",
                "reference": f"{reference}",
                "title": body[:120],
                "text": body[:MAX_TEXT],
                "effect": "instruction",
            }
        )
        if len(requirements) >= MAX_REQUIREMENTS - 1:
            break
    if not requirements:
        raise InvalidInput("no clause long enough to be a requirement was found in the document")
    requirements.append(
        {
            "id": "WHOLE",
            "reference": "whole document",
            "title": f"The work meets {title}",
            "text": f"The work product meets {title} as a whole, not only the clauses above.",
            "effect": "attestation",
            "statement": f"I have checked this work against {title} and it meets it.",
        }
    )
    return pack_from(
        {
            "id": pack_id,
            "title": title,
            "scope": "organisational",
            "issuer": issuer,
            "version": version,
            "description": f"Imported from a document: {len(requirements) - 1} clauses.",
            "requirements": requirements,
        },
        origin="organisation",
    )


# ── combining packs for one matter ───────────────────────────────────────────
def combined_rules(packs: Iterable[FrameworkPack]) -> Rules:
    ages = [p.rules.status_max_age_days for p in packs if p.rules.status_max_age_days]
    terms = sorted({t for p in packs for t in p.rules.forbidden_terms})
    return Rules(status_max_age_days=min(ages) if ages else None, forbidden_terms=tuple(terms))


def tighten_status_age(pack: Any, rules: Rules) -> Any:
    """A jurisdiction pack with its status-age limit shortened by the frameworks, never lengthened."""
    limit = rules.status_max_age_days
    if limit is None or limit >= pack.status_max_age_days:
        return pack
    return replace(pack, status_max_age_days=limit)


def contains_forbidden(text: str, rules: Rules) -> str | None:
    low = text.lower()
    return next((t for t in rules.forbidden_terms if t and t in low), None)


def compile_context(packs: Sequence[FrameworkPack], profile: str) -> str:
    """What the model is told about the law and standards that apply. Rules first, in the
    words the packs give; then one line per pack naming everything else that applies, so the
    model knows the frame it is working in without being asked to decide any of it."""
    if not packs:
        return ""
    head = (
        "LAW AND STANDARDS THAT APPLY TO THIS MATTER. These were chosen and approved by the "
        "people responsible for the matter. They add to the rules above and never relax them. "
        "Where one of them seems to conflict with a rule above, follow the rule above. Do not "
        "state that the work complies with any of them; people decide that."
    )
    lines = [head]
    used = len(head)
    dropped = 0
    for pack in packs:
        rules = [r for r in pack.applicable(profile) if r.effect == "instruction"]
        header = f"[{pack.short_title}] {pack.instrument or pack.title}"
        other = len(pack.applicable(profile)) - len(rules)
        block = [header]
        for r in rules:
            ref = f" ({r.reference})" if r.reference else ""
            block.append(f"- {r.model_rule}{ref}")
        if other:
            block.append(
                f"- {other} further requirement(s) of this instrument are met by the system's "
                "controls or confirmed by a person."
            )
        if pack.rules.forbidden_terms:
            block.append(
                "- Never use these terms in anything you write: "
                + ", ".join(f'"{t}"' for t in pack.rules.forbidden_terms)
            )
        text = "\n".join(block)
        if used + len(text) > MAX_CONTEXT_CHARS:
            dropped += 1
            continue
        lines.append(text)
        used += len(text)
    if dropped:
        lines.append(f"({dropped} further package(s) apply; their rules are enforced elsewhere.)")
    return "\n\n".join(lines)


def search(
    packs: Sequence[FrameworkPack], words: Iterable[str], profile: str, limit: int = 6
) -> list[tuple[FrameworkPack, Requirement, int]]:
    """Requirements whose words overlap the question's, best first."""
    wanted = {w for w in words if len(w) > 2}
    scored: list[tuple[int, FrameworkPack, Requirement]] = []
    for pack in packs:
        for r in pack.applicable(profile):
            hay = f"{pack.short_title} {pack.title} {r.reference} {r.title} {r.text}".lower()
            score = sum(1 for w in wanted if w in hay)
            if score:
                scored.append((score, pack, r))
    scored.sort(key=lambda x: (-x[0], x[1].pack_id, x[2].req_id))
    return [(p, r, s) for s, p, r in scored[:limit]]
