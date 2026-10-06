from __future__ import annotations

from typing import Protocol


class InferencePort(Protocol):
    model_id: str
    available: bool

    def generate(
        self, *, system: str, prompt: str, max_tokens: int = 2048, json_mode: bool = False
    ) -> str: ...
