from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eli_legal.adapters.inference.local import (
    NullInference,
    OpenAICompatInference,
    list_local_models,
)
from eli_legal.application.container import AppContext
from eli_legal.domain.errors import InvalidInput
from eli_legal.legal.llm import LegalModel
from eli_legal.ports.inference import InferencePort
from eli_legal.security import authn


@dataclass(slots=True)
class ConfigService:
    """Runtime configuration that changes how the system behaves. Changing the model changes
    what every later run can produce, so it needs its own permission and is recorded."""

    ctx: AppContext

    def current(self) -> dict[str, Any]:
        s = self.ctx.settings
        return {
            "backend": s.inference,
            "url": s.inference_url,
            "model": s.inference_model,
            "verifier_model": s.verifier_model,
            "active_model_id": self.ctx.model.model_id,
            "active_verifier_id": self.ctx.verifier_model.model_id,
        }

    def available_models(self, base_url: str) -> list[str]:
        return list_local_models(base_url)

    def _build(self, backend: str, url: str, model: str) -> InferencePort:
        if backend == "none" or not model:
            return NullInference()
        if backend != "openai_compat":
            raise InvalidInput(f"unknown inference backend: {backend}")
        return OpenAICompatInference(
            base_url=url,
            model=model,
            api_key=self.ctx.settings.inference_api_key or None,
            timeout=self.ctx.settings.inference_timeout,
            network=self.ctx.guard,
        )

    def set_model(
        self,
        *,
        actor_id: str,
        backend: str,
        url: str,
        model: str,
        verifier_model: str = "",
        persist_to: Path | None = None,
    ) -> dict[str, Any]:
        authn.require_step_up(actor_id, "change the model")
        self.ctx.authorizer().require_global(actor_id, "config.manage")
        if verifier_model and verifier_model == model:
            raise InvalidInput(
                "the verifier must be a different model from the one that drafts; the same "
                "model checking itself is not an independent check"
            )
        generator = self._build(backend, url, model)
        verifier = self._build(backend, url, verifier_model)
        before = self.ctx.model.model_id
        self.ctx.model = LegalModel(generator)
        self.ctx.verifier_model = LegalModel(verifier)
        s = self.ctx.settings
        s.inference, s.inference_url = backend, url
        s.inference_model, s.verifier_model = model, verifier_model
        if persist_to is not None:
            _update_env_file(
                persist_to,
                {
                    "ELI_LEGAL_INFERENCE": backend,
                    "ELI_LEGAL_INFERENCE_URL": url,
                    "ELI_LEGAL_INFERENCE_MODEL": model,
                    "ELI_LEGAL_VERIFIER_MODEL": verifier_model,
                },
            )
        self.ctx.log(
            "configuration_changed",
            actor_id=actor_id,
            matter_id="-",
            action="config.manage",
            subject_id="inference",
            outcome="changed",
            object_type="configuration",
            model_id=self.ctx.model.model_id,
            payload={
                "from": before,
                "to": self.ctx.model.model_id,
                "verifier": self.ctx.verifier_model.model_id,
            },
        )
        return self.current()


def _update_env_file(path: Path, values: dict[str, str]) -> None:
    """Set KEY=value lines in an env file, keeping every other line as it is."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(values)
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    out.extend(f"{key}={value}" for key, value in remaining.items())
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
