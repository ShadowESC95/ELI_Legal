"""Jurisdiction packs.

A pack describes how a legal system is organised and how it cites authority. It holds no rules of
law: the law itself always comes from an approved source through a connector. Packs are data
(``config/jurisdictions/*.json``), so a new legal system is added without changing code.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eli_legal.domain.enums import AuthorityKind
from eli_legal.domain.models import Matter

# Statute titles of the form "Arbitration Act 2010" are shared by the common-law packs. The
# title is a run of capitalised words (with small connecting words) ending in "Act(s)" + year.
_CAP = r"[A-Z][A-Za-z'’&()-]*"
_JOIN = r"(?:of|and|the|for|in|to|on)"
ACT_TITLE_REGEX = rf"\b{_CAP}(?:\s+(?:{_CAP}|{_JOIN})){{0,12}}?\s+Acts?,?\s+(?:1[6-9]|20)\d{{2}}\b"

FALLBACK_CODE = "GENERIC"


@dataclass(frozen=True, slots=True)
class CitationPattern:
    pattern_id: str
    kind: AuthorityKind
    regex: re.Pattern[str]
    example: str = ""


@dataclass(frozen=True, slots=True)
class JurisdictionPack:
    code: str
    name: str
    legal_family: str
    date_order: str = "dmy"
    languages: tuple[str, ...] = ()
    applies_also: tuple[str, ...] = ()
    court_hierarchy: tuple[dict[str, Any], ...] = ()
    citation_patterns: tuple[CitationPattern, ...] = ()
    status_policy: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    status_max_age_days: int = 30
    official_sources: tuple[dict[str, str], ...] = ()
    pack_status: str = "structural"
    validated_by: str | None = None
    notes: str = ""

    @property
    def validated(self) -> bool:
        return bool(self.validated_by)

    def policy_for(self, kind: AuthorityKind) -> dict[str, list[str]]:
        return self.status_policy.get(kind.value, {})


def load_pack(path: Path) -> JurisdictionPack:
    raw = json.loads(path.read_text(encoding="utf-8"))
    patterns = []
    for item in raw.get("citation_patterns", []):
        regex = ACT_TITLE_REGEX if item["regex"] == "@ACT" else item["regex"]
        patterns.append(
            CitationPattern(
                pattern_id=item["id"],
                kind=AuthorityKind(item.get("kind", "case")),
                regex=re.compile(regex),
                example=item.get("example", ""),
            )
        )
    return JurisdictionPack(
        code=raw["code"],
        name=raw["name"],
        legal_family=raw.get("legal_family", "unspecified"),
        date_order=raw.get("date_order", "dmy"),
        languages=tuple(raw.get("languages", [])),
        applies_also=tuple(raw.get("applies_also", [])),
        court_hierarchy=tuple(raw.get("court_hierarchy", [])),
        citation_patterns=tuple(patterns),
        status_policy=raw.get("status_policy", {}),
        status_max_age_days=int(raw.get("status_max_age_days", 30)),
        official_sources=tuple(raw.get("official_sources", [])),
        pack_status=raw.get("pack_status", "structural"),
        validated_by=raw.get("validated_by"),
        notes=raw.get("notes", ""),
    )


class JurisdictionRegistry:
    def __init__(self, packs: list[JurisdictionPack]) -> None:
        self._packs = {p.code: p for p in packs}

    @classmethod
    def from_dir(cls, directory: str | Path) -> JurisdictionRegistry:
        packs = [load_pack(p) for p in sorted(Path(directory).glob("*.json"))]
        return cls(packs)

    def codes(self) -> list[str]:
        return sorted(self._packs)

    def has(self, code: str) -> bool:
        return code in self._packs

    def get(self, code: str) -> JurisdictionPack:
        """The pack for a code, or the generic fallback when none has been authored."""
        pack = self._packs.get(code) or self._packs.get(FALLBACK_CODE)
        if pack is None:
            raise KeyError(f"no jurisdiction pack for {code!r} and no fallback pack installed")
        return pack

    def for_matter(self, matter: Matter) -> list[JurisdictionPack]:
        """Every legal system that can supply law for the matter, most specific first."""
        ordered: list[str] = []
        for code in (matter.governing_law or matter.jurisdiction, matter.jurisdiction):
            if code and code not in ordered:
                ordered.append(code)
        for code in list(ordered):
            for extra in self.get(code).applies_also:
                if extra not in ordered:
                    ordered.append(extra)
        seen: set[str] = set()
        packs: list[JurisdictionPack] = []
        for code in ordered:
            pack = self.get(code)
            if pack.code not in seen:
                seen.add(pack.code)
                packs.append(pack)
        return packs

    def jurisdiction_codes(self, matter: Matter) -> list[str]:
        """Codes used to filter approved sources (the real codes, not the fallback's)."""
        codes: list[str] = []
        for code in (matter.governing_law or matter.jurisdiction, matter.jurisdiction):
            if code and code not in codes:
                codes.append(code)
        for code in list(codes):
            if self.has(code):
                for extra in self._packs[code].applies_also:
                    if extra not in codes:
                        codes.append(extra)
        return codes
