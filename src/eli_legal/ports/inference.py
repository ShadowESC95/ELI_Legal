from __future__ import annotations

from typing import Protocol


class InferencePort(Protocol):
    def generate(self, *, system: str, prompt: str, max_tokens: int = 2048) -> str: ...
