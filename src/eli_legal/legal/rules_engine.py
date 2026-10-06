from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuleResult:
    rule_id: str
    applies: bool
    source_ref: str
    rationale: str


class CourtAdrRulesEngine:
    """Deterministic rules belong here; legal sources must be versioned and jurisdiction-scoped."""
    def evaluate(self, *, rule_id: str, facts: dict) -> RuleResult:
        return RuleResult(rule_id, False, "NOT_CONFIGURED", "rules pack not configured")
