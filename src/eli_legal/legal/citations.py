from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from eli_legal.domain.enums import AuthorityKind
from eli_legal.legal.jurisdictions import JurisdictionPack

_DASHES = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-"})
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
# Words that begin a sentence or phrase but are not part of a statute's title.
_LEADING_NOISE = {
    "the", "under", "in", "by", "see", "per", "and", "of", "to", "for", "section", "sections",
    "pursuant", "that", "this", "said", "a", "an", "as", "with", "from", "s", "ss", "article",
    "part", "schedule", "both", "also", "where", "when", "whereas", "since", "on",
}  # fmt: skip


def normalise_citation(text: str) -> str:
    """Canonical lookup key: case, spacing, dash style and reporter full stops are ignored."""
    s = text.translate(_DASHES).translate(_QUOTES).lower()
    s = re.sub(r"(?<=[a-z])\.(?=\s|[a-z]|$)", "", s)  # I.R. -> ir, U.S. -> us
    s = re.sub(r"\bno\s+(?=\d)", "", s)  # "(EC) No 44/2001" == "(EC) 44/2001"
    s = re.sub(r"[,;]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    s = re.sub(r"^(?:joined cases?|case)\s+", "", s)
    return s


def _clean_act_title(raw: str) -> str:
    words = raw.split()
    while len(words) > 2 and words[0].lower().strip(".,") in _LEADING_NOISE:
        words.pop(0)
    return " ".join(words)


@dataclass(frozen=True, slots=True)
class CitationMatch:
    raw: str
    key: str
    kind: AuthorityKind
    pattern_id: str
    jurisdiction: str
    start: int
    end: int


class CitationExtractor:
    """Finds citations using the grammars of the packs that apply to a matter."""

    def __init__(self, packs: Iterable[JurisdictionPack]) -> None:
        self.packs = list(packs)

    def extract(self, text: str) -> list[CitationMatch]:
        found: list[CitationMatch] = []
        for pack in self.packs:
            for pattern in pack.citation_patterns:
                for m in pattern.regex.finditer(text):
                    raw = m.group(0)
                    start = m.start()
                    if pattern.pattern_id == "act_title_year":
                        cleaned = _clean_act_title(raw)
                        start += len(raw) - len(cleaned)
                        raw = cleaned
                        words = raw.replace(",", " ").split()
                        # Needs a real title ending in a capitalised word: "Sale Act 1980",
                        # not "the Act 2010".
                        if len(words) < 3 or not words[-3][:1].isupper():
                            continue
                        if words[-3].lower() in _LEADING_NOISE:
                            continue
                    found.append(
                        CitationMatch(
                            raw=raw.strip(),
                            key=normalise_citation(raw),
                            kind=pattern.kind,
                            pattern_id=pattern.pattern_id,
                            jurisdiction=pack.code,
                            start=start,
                            end=m.end(),
                        )
                    )
        # Keep the longest match where matches overlap; drop exact duplicates across packs.
        found.sort(key=lambda c: (c.start, -(c.end - c.start)))
        kept: list[CitationMatch] = []
        for c in found:
            if kept and c.start < kept[-1].end:
                continue
            kept.append(c)
        return kept

    def keys(self, text: str) -> list[str]:
        out: list[str] = []
        for c in self.extract(text):
            if c.key not in out:
                out.append(c.key)
        return out
