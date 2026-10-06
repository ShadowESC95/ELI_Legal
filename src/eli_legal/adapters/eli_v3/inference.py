from __future__ import annotations

from pathlib import Path

from eli_legal.adapters.eli_v3.compat import EliV3Unavailable, import_attr
from eli_legal.domain.errors import InferenceUnavailable


class EliV3Inference:
    """The host's local model through its raw generate() call.

    The raw call is used deliberately. It runs the model and returns text; it does not pass
    through the host's conversation pipeline, so matter content is never written to the
    assistant's chat history or personal memory.
    """

    available = True

    def __init__(self) -> None:
        try:
            get_model_path = import_attr("eli.cognition.gguf_inference", "get_model_path")
            path = get_model_path()
            self.model_id = f"eli:{Path(str(path)).name}" if path else "eli:unloaded"
        except Exception:  # model identity is best-effort; the call below is what matters
            self.model_id = "eli:unknown"

    def generate(
        self, *, system: str, prompt: str, max_tokens: int = 2048, json_mode: bool = False
    ) -> str:
        try:
            generate = import_attr("eli.cognition.gguf_inference", "generate")
            result = generate(system=system, prompt=prompt, max_tokens=max_tokens, temperature=0.0)
        except EliV3Unavailable as exc:
            raise InferenceUnavailable(str(exc)) from exc
        except Exception as exc:
            raise InferenceUnavailable(f"host inference failed: {type(exc).__name__}") from exc
        if isinstance(result, dict):
            for key in ("text", "content", "response"):
                if key in result:
                    return str(result[key])
        return str(result)
