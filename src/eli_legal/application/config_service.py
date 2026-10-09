from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eli_legal.adapters.inference.gguf import (
    GgufInference,
    ModelFile,
    discover,
    llama_available,
)
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
            "gguf_context": s.gguf_context,
            "gguf_gpu_layers": s.gguf_gpu_layers,
            "gguf_threads": s.gguf_threads,
            "active_model_id": self.ctx.model.model_id,
            "active_verifier_id": self.ctx.verifier_model.model_id,
            "gguf_supported": llama_available(),
            "hosted_by_eli_v3": s.mode == "eli_v3",
        }

    def available_models(self, base_url: str) -> list[str]:
        """Models a model server on this machine offers."""
        return list_local_models(base_url)

    def gguf_models(self) -> list[ModelFile]:
        """GGUF models found in ELI's folders, ELI Legal's own, and any the administrator added."""
        from eli_legal.settings import HOME

        return discover(self.ctx.settings.models_dirs, HOME)

    def _build(
        self, backend: str, url: str, model: str, *, n_ctx: int, gpu: int, threads: int
    ) -> InferencePort:
        if backend == "eli_v3":
            if self.ctx.settings.mode != "eli_v3":
                raise InvalidInput(
                    "ELI v3's model is available only when ELI Legal is launched from ELI v3"
                )
            from eli_legal.adapters.eli_v3.inference import EliV3Inference

            return EliV3Inference() if model else NullInference()
        if backend == "none" or not model:
            return NullInference()
        if backend == "gguf":
            return GgufInference(model, n_ctx=n_ctx, n_gpu_layers=gpu, n_threads=threads)
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
        url: str = "",
        model: str = "",
        verifier_model: str = "",
        persist_to: Path | None = None,
        gguf_context: int | None = None,
        gguf_gpu_layers: int | None = None,
        gguf_threads: int | None = None,
    ) -> dict[str, Any]:
        """Change the model. For ``gguf`` the model and verifier are paths to GGUF files; for
        ``openai_compat`` they are names a server on this machine knows; ``eli_v3`` uses ELI v3's
        loaded model. A decision: it needs the passphrase again, and it is recorded."""
        authn.require_step_up(actor_id, "change the model")
        self.ctx.authorizer().require_global(actor_id, "config.manage")
        s = self.ctx.settings
        if backend == "eli_v3" and not model:
            model = "eli_v3"
        if verifier_model and verifier_model == model:
            raise InvalidInput(
                "the verifier must be a different model from the one that drafts; the same "
                "model checking itself is not an independent check"
            )
        n_ctx = gguf_context if gguf_context is not None else s.gguf_context
        gpu = gguf_gpu_layers if gguf_gpu_layers is not None else s.gguf_gpu_layers
        threads = gguf_threads if gguf_threads is not None else s.gguf_threads
        if not 2048 <= n_ctx <= 262144:
            raise InvalidInput("the context length must be between 2048 and 262144 tokens")
        url = url or s.inference_url
        generator = self._build(backend, url, model, n_ctx=n_ctx, gpu=gpu, threads=threads)
        verifier = self._build(backend, url, verifier_model, n_ctx=n_ctx, gpu=gpu, threads=threads)
        before = self.ctx.model.model_id
        self.ctx.model = LegalModel(generator)
        self.ctx.verifier_model = LegalModel(verifier)
        s.inference, s.inference_url = backend, url
        s.inference_model, s.verifier_model = model, verifier_model
        s.gguf_context, s.gguf_gpu_layers, s.gguf_threads = n_ctx, gpu, threads
        if persist_to is not None:
            _update_env_file(
                persist_to,
                {
                    "ELI_LEGAL_INFERENCE": backend,
                    "ELI_LEGAL_INFERENCE_URL": url,
                    "ELI_LEGAL_INFERENCE_MODEL": model,
                    "ELI_LEGAL_VERIFIER_MODEL": verifier_model,
                    "ELI_LEGAL_GGUF_CONTEXT": str(n_ctx),
                    "ELI_LEGAL_GGUF_GPU_LAYERS": str(gpu),
                    "ELI_LEGAL_GGUF_THREADS": str(threads),
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
                "backend": backend,
            },
        )
        return self.current()

    def set_model_by_ref(
        self, *, actor_id: str, ref: str, verifier_ref: str = "", **options: Any
    ) -> dict[str, Any]:
        """Choose a GGUF model by the reference the model list gives, so a screen on another
        machine never needs to know or send a path on this one."""
        by_ref = {m.ref: m for m in self.gguf_models()}
        if ref not in by_ref or (verifier_ref and verifier_ref not in by_ref):
            raise InvalidInput("that model is not among the GGUF models found on this machine")
        verifier = str(by_ref[verifier_ref].path) if verifier_ref else ""
        return self.set_model(
            actor_id=actor_id,
            backend="gguf",
            model=str(by_ref[ref].path),
            verifier_model=verifier,
            **options,
        )


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
