from __future__ import annotations

import re
from dataclasses import dataclass

# A detector can only ever raise suspicion. Source text is treated as untrusted data whether or
# not anything here fires; a clean result is never a reason to trust a document.

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|"
            r"all|any|your)\b[^.\n]{0,30}\b(instruction|prompt|rule|direction|guideline)s?\b",
            re.I,
        ),
    ),
    (
        "role_reassignment",
        re.compile(
            r"\b(you are now|from now on you|act as (?:an?|the) |pretend to be|new instructions?:)",
            re.I,
        ),
    ),
    (
        "addressed_to_model",
        re.compile(
            r"\b(system prompt|developer message|as an ai\b|to the (?:ai|llm|assistant|model)\b|"
            r"(?:ai|llm) (?:assistant|system|model) reading this|language model)",
            re.I,
        ),
    ),
    (
        "chat_template_marker",
        re.compile(
            r"(<\|im_start\|>|<\|im_end\|>|\[/?INST\]|<<SYS>>|<\|system\|>|###\s*system\b)", re.I
        ),
    ),
    (
        "boundary_spoofing",
        re.compile(r"\[(BEGIN|END) UNTRUSTED SOURCE MATERIAL", re.I),
    ),
    (
        "concealment_request",
        re.compile(
            r"\b(do not|don't|never)\b[^.\n]{0,30}\b(tell|inform|mention|reveal|disclose)\b"
            r"[^.\n]{0,30}\b(user|reviewer|tribunal|judge|human)\b",
            re.I,
        ),
    ),
    (
        "verification_tampering",
        re.compile(
            r"\b(mark|label|treat|report)\b[^.\n]{0,40}\b(as )?(verified|approved|good law|"
            r"reliable)\b[^.\n]{0,40}\b(without|regardless|even if)\b",
            re.I,
        ),
    ),
    (
        "exfiltration_request",
        re.compile(
            r"\b(send|email|upload|post|forward|exfiltrate)\b[^.\n]{0,50}\b(this|the|all)\b"
            r"[^.\n]{0,30}\b(file|document|data|contents?|conversation)\b[^.\n]{0,30}\bto\b",
            re.I,
        ),
    ),
)

# Characters used to hide text from a human reader while leaving it visible to a model.
_HIDDEN = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿\U000e0000-\U000e007f]")


@dataclass(frozen=True, slots=True)
class InjectionAssessment:
    suspicious: bool
    reasons: tuple[str, ...] = ()


class PromptInjectionDetector:
    """Flags text that looks written for a model rather than for a human reader."""

    def assess(self, text: str) -> InjectionAssessment:
        reasons: list[str] = [name for name, pattern in _PATTERNS if pattern.search(text)]
        hidden = len(_HIDDEN.findall(text))
        # A single byte-order mark or soft joiner is common in exported documents; a cluster
        # of invisible characters is not.
        if hidden >= 5:
            reasons.append("hidden_characters")
        return InjectionAssessment(bool(reasons), tuple(reasons))


def strip_hidden_characters(text: str) -> str:
    return _HIDDEN.sub("", text)
