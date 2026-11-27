"""Deciding what a training example may keep, and what it never may.

A model learns its task from the examples, not the people and facts in them, and what it learns
cannot be taken back out of its weights (EDPB Opinion 28/2024: a model trained on personal data
is not anonymous while that data can be drawn out of it). So an example keeps only what the task
needs (GDPR Art. 5(1)(c), Art. 25):

- **always taken out**, whatever the organisation sets: the parties' names and their
  representatives' (each in full and each word of it that is a name, the same party the same
  ``[PARTY n]`` throughout), other people's names the text gives with a title or as a signatory
  or witness (``[PERSON]``), contact details and identifying numbers (``[EMAIL]``, ``[PHONE]``,
  ``[IBAN]``, ``[PPSN]``, ``[EIRCODE]``, ``[CARD]``);
- **taken out unless the compliance officer keeps them, with a reason**: amounts
  (``[AMOUNT]``), dates (``[DATE]``), case, invoice and other references (``[REF]``), street
  addresses (``[ADDRESS]``);
- **never taken at all**: an example that concerns health, racial or ethnic origin, political
  opinions, religious or philosophical beliefs, trade union membership, genetic or biometric
  data, sex life or sexual orientation (GDPR Art. 9), criminal convictions and offences
  (GDPR Art. 10), or a child. ELI Legal does not keep it: training on such data is not
  necessary for the task, and the AI Act allows special categories in a training set only to
  find and correct bias (Art. 10(5)), which this is not.

This removes what can be recognised. It cannot know every name in every document: a person
reviews each example before it trains, unless autonomous mode accepts the run's review for it,
and every trained model is tested for repeating what it learnt before anyone may approve it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

OPTIONAL = ("amounts", "dates", "references", "addresses")

_ALWAYS: list[tuple[str, re.Pattern[str], str]] = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[EMAIL]"),
    (
        "iban",
        re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,4})?\b"),
        "[IBAN]",
    ),
    ("card", re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"), "[CARD]"),
    ("ppsn", re.compile(r"\b\d{7}[A-W][A-IW]?\b"), "[PPSN]"),
    ("eircode", re.compile(r"\b[AC-FHKNPRTV-Y]\d{2}\s?[AC-FHKNPRTV-Y0-9]{4}\b"), "[EIRCODE]"),
    ("phone", re.compile(r"(?<![\w/])\+?\d[\d ()-]{7,}\d\b"), "[PHONE]"),
]
_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December|"
    "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)
_OPTIONAL: dict[str, list[tuple[str, re.Pattern[str], str]]] = {
    "amounts": [
        (
            "amount",
            re.compile(
                r"(?:[€$£¥]|\b(?:EUR|USD|GBP|CHF|JPY)\s?)\s?\d[\d,. ]*\d(?:\s?(?:m|bn|k|million|billion))?\b"
                r"|\b\d[\d,.]*\d\s?(?:euro|euros|EUR|USD|GBP|dollars|pounds)\b",
                re.IGNORECASE,
            ),
            "[AMOUNT]",
        )
    ],
    "dates": [
        (
            "date",
            re.compile(
                rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{_MONTHS})\.?,?\s+\d{{4}}\b"
                rf"|\b(?:{_MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b"
                r"|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b"
            ),
            "[DATE]",
        )
    ],
    "references": [
        (
            "reference",
            re.compile(
                r"\b(?:(?:case|claim|file|invoice|order|policy|account|contract|ref(?:erence)?|"
                r"record)\s*(?:no\.?|number|#|ref\.?)?\s*[:#]?\s*)[A-Z0-9][A-Z0-9/._-]{2,}\b"
                r"|\b\d{4}\s?/\s?\d{1,6}\s?[A-Z]{1,4}\b|\b[A-Z]{2,5}[/-]\d{2,}(?:[/-]\d+)*\b",
                re.IGNORECASE,
            ),
            "[REF]",
        )
    ],
    "addresses": [
        (
            "address",
            re.compile(
                r"\b\d{1,4}[A-Za-z]?,?\s+(?:[A-Z][a-z']+\s+){1,3}(?:Street|St|Road|Rd|Avenue|Ave|"
                r"Lane|Ln|Drive|Dr|Square|Sq|Place|Pl|Terrace|Quay|Park|Court|Crescent|Close|Way|"
                r"Row|Hill|Grove|Gardens|Green|Walk|Parade)\b\.?"
            ),
            "[ADDRESS]",
        )
    ],
}
# A title or a role names a person: "Mr John Smith", "witness Anne Walsh", "signed by P. Doyle".
_PERSON = re.compile(
    r"\b(?:(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof|Professor|Judge|Justice|Sir|Dame|Lord|Lady|Fr|Sr|Rev)"
    r"\.?\s+|(?:witness|signed by|per|attention of|attn:?|deponent|sworn by|employee|"
    r"director|manager|nurse|doctor|surgeon|officer|guard|garda|inspector|sergeant)\s+)"
    r"((?:[A-Z]\.\s?)*[A-Z][a-z'’-]+(?:\s+(?:[A-Z]\.\s?)*[A-Z][a-z'’-]+){0,3})"
)
# Words in a party's name that are not names: they stay, so "Port Varen Shipping Ltd" does
# not turn every "Shipping" in a contract into a placeholder.
_COMMON = frozenset(
    """
    the of and for ltd limited plc llc llp inc co company dac clg uc teo group holdings holding
    trust bank state minister director republic council county city court tribunal mr mrs ms dr
    port shipping logistics freight marine maritime transport haulage airlines aviation motors
    construction building builders contractors engineering services solutions systems supplies
    supply trading traders imports exports manufacturing industries industrial enterprises
    ventures international global national european irish properties property estates homes
    housing developments development foods food dairy farm farms energy power partners
    consulting consultants management insurance assurance finance financial capital investments
    investment technologies technology tech software digital data media communications retail
    stores hotel hotels health healthcare care medical hospital pharma pharmaceuticals school
    university college association society union federation agency authority department office
    board commission north south east west new first general united royal central
    """.split()
)

# What an example must never be kept for (GDPR Arts. 9 and 10; a child). Matched as words.
NEVER: dict[str, tuple[str, ...]] = {
    "health": (
        "diagnosis", "diagnosed", "medical record", "medical history", "illness", "disease",
        "disability", "disabled", "pregnant", "pregnancy", "mental health", "psychiatric",
        "depression", "cancer", "hiv", "medication", "prescription", "therapy", "injury to",
        "hospitalised", "hospitalized", "sick leave", "medical certificate", "symptoms",
    ),
    "racial or ethnic origin": (
        "racial", "ethnic origin", "ethnicity", "race of", "traveller community", "nationality of",
    ),
    "political opinions": ("political opinion", "political party", "voted for", "party member"),
    "religious or philosophical beliefs": (
        "religion", "religious", "catholic", "protestant", "muslim", "jewish", "hindu",
        "sikh", "buddhist", "atheist", "church member",
    ),
    "trade union membership": ("trade union", "union member", "union membership", "shop steward"),
    "genetic or biometric data": ("genetic", "dna", "biometric", "fingerprint", "facial image"),
    "sex life or sexual orientation": (
        "sexual orientation", "sex life", "gay", "lesbian", "bisexual", "transgender",
        "gender identity",
    ),
    "criminal convictions and offences": (
        "convicted", "conviction", "criminal record", "offence", "offense", "prosecuted",
        "arrested", "charged with", "sentenced", "imprisonment", "garda vetting", "criminal",
    ),
    "a child": (
        "minor", "child", "children", "infant", "juvenile", "under 18", "aged under",
        "guardian ad litem", "custody of",
    ),
}  # fmt: skip
_NEVER = {
    kind: re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b", re.IGNORECASE)
    for kind, words in NEVER.items()
}


def never_kept(text: str) -> str | None:
    """The kind of data that keeps ``text`` out of training altogether, if any."""
    for kind, pattern in _NEVER.items():
        if pattern.search(text):
            return kind
    return None


class Pseudonymiser:
    """Takes out what an example may not keep. ``omit`` names the optional kinds taken out too
    (all of them unless the organisation keeps some); ``counts`` totals what it took, by kind."""

    def __init__(self, names: Iterable[str], omit: Iterable[str] = OPTIONAL) -> None:
        self.placeholders: dict[str, str] = {}
        for n, name in enumerate(dict.fromkeys(x.strip() for x in names if x and x.strip()), 1):
            self.placeholders[name] = f"[PARTY {n}]"
        # The full names first, longest first; then each distinctive word of them.
        parts: dict[str, str] = {}
        for name, mark in self.placeholders.items():
            for word in re.findall(r"[^\W\d_][\w'’-]{2,}", name):
                if word.lower() not in _COMMON:
                    parts.setdefault(word, mark)
        self._full = sorted(self.placeholders, key=len, reverse=True)
        self._parts = sorted(parts.items(), key=lambda kv: len(kv[0]), reverse=True)
        chosen = set(omit)
        self._patterns = list(_ALWAYS) + [p for k in OPTIONAL if k in chosen for p in _OPTIONAL[k]]
        self.counts: dict[str, int] = {}

    def _count(self, kind: str, n: int) -> None:
        if n:
            self.counts[kind] = self.counts.get(kind, 0) + n

    def __call__(self, text: str) -> str:
        out = text
        for name in self._full:
            out, n = re.subn(re.escape(name), self.placeholders[name], out, flags=re.IGNORECASE)
            self._count("name", n)
        for word, mark in self._parts:
            out, n = re.subn(rf"\b{re.escape(word)}\b", mark, out)
            self._count("name", n)
        out, n = _PERSON.subn(lambda m: m.group(0)[: m.start(1) - m.start(0)] + "[PERSON]", out)
        self._count("person", n)
        for kind, pattern, mark in self._patterns:
            out, n = pattern.subn(mark, out)
            self._count(kind, n)
        return out
