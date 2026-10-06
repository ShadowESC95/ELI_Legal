from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InjectionAssessment:
    suspicious: bool
    reasons: tuple[str, ...] = ()


class PromptInjectionDetector:
    """Starter interface only; source text remains untrusted regardless of detector outcome."""

    def assess(self, text: str) -> InjectionAssessment:
        markers = ("ignore previous instructions", "system prompt", "developer message")
        hits = tuple(m for m in markers if m in text.lower())
        return InjectionAssessment(bool(hits), hits)
