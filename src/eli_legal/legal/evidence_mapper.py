from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from eli_legal.domain.models import Claim, EvidenceLink, Issue
from eli_legal.legal.issue_mapper import stems

_NEGATION = re.compile(
    r"\b(not|no|never|none|neither|nor|without|failed to|refused|denies|denied|did not|"
    r"didn't|wasn't|weren't|isn't|cannot|can't)\b",
    re.I,
)
_MONEY = re.compile(r"[€£$¥]\s?\d[\d,.]*\d|\b\d[\d,.]*\d\s?(?:EUR|GBP|USD|CHF)\b")


@dataclass(slots=True)
class PotentialConflict:
    """Two parties' statements about the same date that appear to disagree. For a human to check."""

    claim_a: str
    claim_b: str
    reason: str


@dataclass(slots=True)
class IssueEvidence:
    issue_id: str
    facts_by_party: dict[str, list[str]] = field(default_factory=dict)
    document_ids: list[str] = field(default_factory=list)
    gap: bool = False  # no evidence located for this issue
    one_sided: bool = False  # evidence from one party only


class EvidenceMapper:
    def link(self, claim: Claim, evidence: EvidenceLink) -> Claim:
        claim.evidence.append(evidence)
        return claim

    def build(self, *, issues: Sequence[Issue], facts: Sequence[Claim]) -> list[IssueEvidence]:
        by_id = {f.claim_id: f for f in facts}
        maps: list[IssueEvidence] = []
        for issue in issues:
            entry = IssueEvidence(issue_id=issue.issue_id)
            for claim_id in issue.claim_ids:
                fact = by_id.get(claim_id)
                if fact is None:
                    continue
                entry.facts_by_party.setdefault(fact.party_id or "unattributed", []).append(
                    claim_id
                )
                for link in fact.evidence:
                    if link.target_type == "document" and link.target_id not in entry.document_ids:
                        entry.document_ids.append(link.target_id)
            entry.gap = not entry.facts_by_party
            attributed = [p for p in entry.facts_by_party if p != "unattributed"]
            entry.one_sided = len(attributed) == 1
            maps.append(entry)
        return maps

    def conflicts(self, facts: Sequence[Claim], *, limit: int = 200) -> list[PotentialConflict]:
        """Pairs of statements by different parties that look inconsistent.

        Two signals only: one party asserts what the other negates about the same date, or the
        two put different sums of money on the same thing. A pointer for a person, not a finding.
        """
        attributed = [f for f in facts if f.party_id]
        found: list[PotentialConflict] = []

        def consider(a: Claim, b: Claim, reason: str) -> bool:
            found.append(PotentialConflict(a.claim_id, b.claim_id, reason))
            return len(found) >= limit

        by_date: dict[object, list[Claim]] = {}
        for fact in attributed:
            if fact.event_date is not None:
                by_date.setdefault(fact.event_date, []).append(fact)
        for same_day in by_date.values():
            for i, a in enumerate(same_day):
                for b in same_day[i + 1 :]:
                    if a.party_id == b.party_id or len(stems(a.text) & stems(b.text)) < 3:
                        continue
                    if bool(_NEGATION.search(a.text)) != bool(_NEGATION.search(b.text)):
                        if consider(a, b, "one party asserts what the other negates"):
                            return found
        priced = [(f, set(_MONEY.findall(f.text))) for f in attributed if _MONEY.search(f.text)]
        for i, (a, sums_a) in enumerate(priced):
            for b, sums_b in priced[i + 1 :]:
                if a.party_id == b.party_id or len(stems(a.text) & stems(b.text)) < 1:
                    continue
                if sums_a != sums_b:
                    if consider(a, b, "the parties state different sums"):
                        return found
        return found
