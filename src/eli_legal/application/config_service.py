from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eli_legal.adapters.inference import fit, gguf, gpu_runtime, hardware
from eli_legal.adapters.inference.gguf import ModelFile, discover, llama_available
from eli_legal.adapters.inference.local import (
    NullInference,
    OpenAICompatInference,
    list_local_models,
)
from eli_legal.application.container import AppContext, gguf_inference
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
            "loaded": self.loaded(),
        }

    def loaded(self) -> dict[str, Any]:
        """How each model is loaded now, by llama.cpp's own account: {} for one that is not
        loaded yet (a model loads at its first use) or is not a GGUF file."""
        out: dict[str, Any] = {}
        for role, model in (("model", self.ctx.model), ("verifier", self.ctx.verifier_model)):
            report = getattr(model.inference, "report", None)
            out[role] = report.as_dict() if report is not None else {}
        return out

    def machine(self) -> dict[str, Any]:
        """What there is to run a model on, and the llama.cpp that will run it. No paths."""
        hw = hardware.detect(force=True)
        runtime = gpu_runtime.current()
        return {
            "summary": hw.describe(),
            "hardware": hw.as_dict(),
            "runtime": runtime.as_dict() | {"summary": runtime.describe()},
            "others_on_the_card": hardware.describe_vram_holders(
                hardware.vram_holders(), total_mb=hw.total_vram_mb
            ),
        }

    def preview(
        self,
        model: str,
        *,
        gguf_context: int | None = None,
        gguf_gpu_layers: int | None = None,
        gguf_threads: int | None = None,
    ) -> dict[str, Any]:
        """How this GGUF file would be placed if it were loaded now, with the reasons. Nothing
        is loaded and nothing is changed."""
        s = self.ctx.settings
        candidate = gguf_inference(
            model,
            n_ctx=s.gguf_context if gguf_context is None else gguf_context,
            n_gpu_layers=s.gguf_gpu_layers if gguf_gpu_layers is None else gguf_gpu_layers,
            n_threads=s.gguf_threads if gguf_threads is None else gguf_threads,
            priority=s.gguf_fit,
        )
        plan = candidate.plan()  # type: ignore[attr-defined]
        return {
            "summary": plan.describe(),
            "context": plan.n_ctx,
            "layers_on_card": plan.n_gpu_layers,
            "layers_total": plan.blocks + 1 if plan.blocks else 0,
            "threads": plan.n_threads,
            "notes": list(plan.notes),
        }

    def preview_by_ref(self, ref: str, **options: Any) -> dict[str, Any]:
        by_ref = {m.ref: m for m in self.gguf_models()}
        if ref not in by_ref:
            raise InvalidInput("that model is not among the GGUF models found on this machine")
        return self.preview(str(by_ref[ref].path), **options)

    def install_gpu_runtime(self, *, actor_id: str, wheel: Path) -> dict[str, Any]:
        """Install a graphics pack from a file on this machine. It replaces the code that runs
        the model, so it needs the same permission as changing the model and is recorded with
        the file's fingerprint. It is used from the next start of the program."""
        authn.require_step_up(actor_id, "install a graphics runtime")
        self.ctx.authorizer().require_global(actor_id, "config.manage")
        pack = gpu_runtime.install(wheel)
        ok, detail = gpu_runtime.verify(pack, again=True)
        manifest = json.loads((pack.path / ".gpu_pack.json").read_text(encoding="utf-8"))
        self.ctx.log(
            "configuration_changed",
            actor_id=actor_id,
            matter_id="-",
            action="config.manage",
            subject_id="inference_runtime",
            outcome="installed" if ok else "installed_not_usable",
            object_type="configuration",
            payload={
                "backend": pack.backend,
                "version": pack.version,
                "file": manifest.get("source", ""),
                "sha256": manifest.get("sha256", ""),
            },
        )
        return {
            "backend": pack.backend,
            "version": pack.version,
            "usable": ok,
            "summary": (
                f"{pack.describe()} installed; it is used from the next start of ELI Legal"
                if ok
                else f"{pack.describe()} installed, but it did not start on this card: {detail}"
            ),
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
            return gguf_inference(
                model,
                n_ctx=n_ctx,
                n_gpu_layers=gpu,
                n_threads=threads,
                priority=self.ctx.settings.gguf_fit,
            )
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
        if n_ctx != 0 and not fit.MIN_CTX <= n_ctx <= 262144:
            raise InvalidInput(
                f"the context length is 0 (sized to the model and this machine) or between "
                f"{fit.MIN_CTX} and 262144 tokens"
            )
        if gpu < -1:
            raise InvalidInput(
                "layers on the graphics card: -1 as many as fit, 0 none, or a number"
            )
        url = url or s.inference_url
        generator = self._build(backend, url, model, n_ctx=n_ctx, gpu=gpu, threads=threads)
        verifier = self._build(backend, url, verifier_model, n_ctx=n_ctx, gpu=gpu, threads=threads)
        before = self.ctx.model.model_id
        self.ctx.model = LegalModel(generator)
        self.ctx.verifier_model = LegalModel(verifier)
        self.ctx.record_loads(self.ctx.model)
        self.ctx.record_loads(self.ctx.verifier_model)
        # A model no longer chosen gives its memory back now: the next one is sized from
        # what is free.
        gguf.release({Path(p) for p in (model, verifier_model) if backend == "gguf" and p})
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
