from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_MONTHS: dict[str, int] = {}
for _number, _names in enumerate(
    (
        ("january", "jan", "janvier", "januar"),
        ("february", "feb", "février", "fevrier", "februar"),
        ("march", "mar", "mars", "märz", "maerz"),
        ("april", "apr", "avril"),
        ("may", "mai"),
        ("june", "jun", "juin", "juni"),
        ("july", "jul", "juillet", "juli"),
        ("august", "aug", "août", "aout"),
        ("september", "sep", "sept", "septembre"),
        ("october", "oct", "octobre", "oktober", "okt"),
        ("november", "nov", "novembre"),
        ("december", "dec", "décembre", "decembre", "dezember", "dez"),
    ),
    start=1,
):
    for _name in _names:
        _MONTHS[_name] = _number

_MONTH_ALT = "|".join(sorted((re.escape(m) for m in _MONTHS), key=len, reverse=True))
_DAY_MONTH_YEAR = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th|er|\.)?\s+(?:of\s+)?({_MONTH_ALT})\.?,?\s+((?:1[6-9]|20)\d{{2}})\b",
    re.I,
)
_MONTH_DAY_YEAR = re.compile(
    rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+((?:1[6-9]|20)\d{{2}})\b", re.I
)
_ISO = re.compile(r"\b((?:1[6-9]|20)\d{2})-(\d{2})-(\d{2})\b")
_NUMERIC = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-]((?:1[6-9]|20)\d{2})\b")


@dataclass(frozen=True, slots=True)
class DateMention:
    value: date
    text: str
    start: int
    ambiguous: bool = False


def _safe(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def find_dates(text: str, *, date_order: str = "dmy") -> list[DateMention]:
    """Dates written in the text, in order of appearance.

    A numeric date such as 03/04/2021 is read using the jurisdiction's convention and flagged
    ambiguous when both readings are valid calendar dates.
    """
    found: list[DateMention] = []
    for m in _DAY_MONTH_YEAR.finditer(text):
        d = _safe(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
        if d:
            found.append(DateMention(d, m.group(0), m.start()))
    for m in _MONTH_DAY_YEAR.finditer(text):
        d = _safe(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
        if d:
            found.append(DateMention(d, m.group(0), m.start()))
    for m in _ISO.finditer(text):
        d = _safe(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            found.append(DateMention(d, m.group(0), m.start()))
    for m in _NUMERIC.finditer(text):
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        day, month = (b, a) if date_order == "mdy" else (a, b)
        d = _safe(year, month, day)
        if d:
            other = _safe(year, day, month)
            found.append(DateMention(d, m.group(0), m.start(), other is not None and other != d))
    found.sort(key=lambda x: x.start)
    kept: list[DateMention] = []
    for item in found:
        if kept and item.start < kept[-1].start + len(kept[-1].text):
            continue
        kept.append(item)
    return kept


_ABBREVIATIONS = (
    "Mr", "Mrs", "Ms", "Dr", "Prof", "No", "Nos", "Ltd", "Inc", "Co", "Corp", "plc", "v", "vs",
    "e.g", "i.e", "cf", "para", "paras", "p", "pp", "s", "ss", "art", "arts", "cl", "ch", "vol",
    "ed", "eds", "St", "Jr", "Sr", "J", "JJ", "LJ", "CJ", "P", "S.I", "U.S", "U.S.C", "C.F.R",
    "F", "Supp", "Ct", "Civ", "Cass", "al", "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug",
    "Sep", "Sept", "Oct", "Nov", "Dec", "Abs", "Nr", "Art",
)  # fmt: skip
_ABBREV_RE = re.compile(r"(?:\b(?:" + "|".join(re.escape(a) for a in _ABBREVIATIONS) + r"))\.$")
_BOUNDARY = re.compile(r"(?<=[.!?])[\"'”’)\]]*\s+(?=[\"'“‘(\[]?[A-Z0-9])")


def split_sentences(text: str) -> list[str]:
    """Sentence splitter that does not break on legal abbreviations and citations."""
    pieces = _BOUNDARY.split(text)
    out: list[str] = []
    buffer = ""
    for piece in pieces:
        candidate = f"{buffer} {piece}".strip() if buffer else piece.strip()
        if _ABBREV_RE.search(candidate) or re.search(r"\b[A-Z]\.$", candidate):
            buffer = candidate
            continue
        out.append(candidate)
        buffer = ""
    if buffer:
        out.append(buffer)
    return [s for s in out if s]
