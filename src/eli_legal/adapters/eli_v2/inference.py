from __future__ import annotations

from eli_legal.adapters.eli_v2.compat import import_attr


class EliV2InferenceAdapter:
    """Wrap ELI v2's model-agnostic GGUF generate() behind ELI Legal's InferencePort."""

    def generate(self, *, system: str, prompt: str, max_tokens: int = 2048) -> str:
        generate = import_attr("eli.cognition.gguf_inference", "generate")
        result = generate(system=system, prompt=prompt, max_tokens=max_tokens)
        if isinstance(result, dict):
            for key in ("text", "content", "response"):
                if key in result:
                    return str(result[key])
        return str(result)
