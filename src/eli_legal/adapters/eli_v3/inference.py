from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eli_legal.adapters.eli_v3.compat import EliV3Unavailable, import_attr
from eli_legal.domain.errors import InferenceUnavailable

_HOST = "eli.cognition.gguf_inference"


class EliV3Inference:
    """The host's local model through its raw calls.

    The raw calls are used deliberately. They run the model and return text; they do not pass
    through the host's conversation pipeline, so matter content is never written to the
    assistant's chat history or personal memory, and the system message is ELI Legal's own,
    not the assistant's persona. How the model is placed on the machine (context, layers on
    the graphics card) is the host's: ELI v3 sized it when it loaded it.

    A JSON answer is asked for through the host's JSON call, which holds the model to JSON.
    The host shortens a prompt that does not fit its context without saying so; here that
    prompt is refused instead, since material silently left out is not acceptable in this
    work. An older host without these calls is used through its plain one.
    """

    available = True

    def __init__(self) -> None:
        try:
            get_model_path = import_attr(_HOST, "get_model_path")
            path = get_model_path()
            self.model_id = f"eli:{Path(str(path)).name}" if path else "eli:unloaded"
        except Exception:  # model identity is best-effort; the call below is what matters
            self.model_id = "eli:unknown"

    def context_tokens(self) -> int:
        """The context the host's model is loaded with."""
        try:
            window = int(import_attr(_HOST, "context_window")())
        except (EliV3Unavailable, TypeError, ValueError) as exc:
            raise InferenceUnavailable(f"the host does not say its context: {exc}") from exc
        if window <= 0:
            raise InferenceUnavailable("the host has no model loaded")
        return window

    def count_tokens(self, text: str) -> int:
        """The length of this text as the host's model counts it, with what the host adds."""
        try:
            left = int(import_attr(_HOST, "available_generation_tokens")(text))
        except (EliV3Unavailable, TypeError, ValueError) as exc:
            raise InferenceUnavailable(f"the host does not count tokens: {exc}") from exc
        if left < 0:
            raise InferenceUnavailable("the host has no model loaded")
        return max(0, self.context_tokens() - left)

    def _fits(self, system: str, prompt: str) -> bool:
        try:
            return self.context_tokens() > self.count_tokens(system + prompt)
        except InferenceUnavailable:
            return True  # an older host cannot say; its own handling applies

    def generate(
        self, *, system: str, prompt: str, max_tokens: int = 2048, json_mode: bool = False
    ) -> str:
        if not self._fits(system, prompt):
            raise InferenceUnavailable(
                "this step's material does not fit the context ELI v3's model is loaded with"
            )
        options: dict[str, Any] = {"max_tokens": max_tokens, "temperature": 0.0}
        try:
            if json_mode:
                try:
                    generate_json = import_attr(_HOST, "generate_json")
                except EliV3Unavailable:
                    generate_json = None
                if generate_json is not None:
                    return json.dumps(generate_json(system=system, prompt=prompt, **options))
            result = import_attr(_HOST, "generate")(system=system, prompt=prompt, **options)
        except EliV3Unavailable as exc:
            raise InferenceUnavailable(str(exc)) from exc
        except Exception as exc:
            raise InferenceUnavailable(
                f"host inference failed: {type(exc).__name__}: {str(exc)[:200]}"
            ) from exc
        if isinstance(result, dict):
            for key in ("text", "content", "response"):
                if key in result:
                    return str(result[key])
        return str(result)
