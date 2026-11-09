"""The audit trail, the governance registers, the approved sources and the configuration."""

# No "from __future__ import annotations": see routes_auth.
import json
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException

from eli_legal.application.services import Services
from eli_legal.domain import plain
from eli_legal.domain.errors import EliLegalError, InvalidInput
from eli_legal.governance.registers import REGISTER_FILES, load_register
from eli_legal.legal.source_registry import RegisteredSource
from eli_legal.persistence import codec

from . import schemas
from .auth import Access
from .config import ServerConfig, is_loopback


def register(app: FastAPI, sv: Services, cfg: ServerConfig, access: Access) -> None:
    Actor = Annotated[str, Depends(access.user)]
    js = codec.to_jsonable

    # ── audit ────────────────────────────────────────────────────────────────
    @app.get("/v1/audit/events")
    def audit_events(actor: Actor, matter_id: str | None = None, limit: int = 2000) -> Any:
        """The ledger for a matter, or (with the right) the events that belong to none: sign-ins,
        users, sources, configuration. Identifiers and hashes only; never document text."""
        events = sv.audit_trail(actor_id=actor, matter_id=matter_id)
        shown = events[-max(1, min(limit, 20_000)) :]
        # Each event also in words, as every screen shows it; the record itself is unchanged.
        return js(
            [
                e
                | {
                    "said": plain.event(e["event_type"], e["outcome"]),
                    "proof": plain.identity((e.get("payload") or {}).get("auth", "")),
                }
                for e in shown
            ]
        )

    @app.get("/v1/audit/verify")
    def audit_verify(actor: Actor) -> Any:
        """Verify every signature and link of the audit chain."""
        sv.ctx.authorizer().require_global(actor, "audit.verify")
        chain = sv.ctx.audit.report()
        return {"ok": chain.ok, "events": chain.count, "error": chain.error}

    @app.post("/v1/audit/checkpoint")
    def audit_checkpoint(actor: Actor) -> Any:
        """A signed statement of where the chain stands now, to keep somewhere else."""
        sv.ctx.authorizer().require_global(actor, "audit.verify")
        return json.loads(sv.ctx.audit.checkpoint().to_json())

    # ── governance ───────────────────────────────────────────────────────────
    @app.get("/v1/governance/registers")
    def registers(actor: Actor) -> list[str]:
        """The names of the governance registers."""
        return sorted(REGISTER_FILES)

    @app.get("/v1/governance/registers/{name}")
    def register_rows(name: str, actor: Actor) -> Any:
        """One register as rows: requirements, controls, risks or responsibilities."""
        if name not in REGISTER_FILES:
            raise HTTPException(404, "no such register")
        return load_register(name)

    @app.get("/v1/monitoring")
    def monitoring(actor: Actor) -> Any:
        """Monitoring figures computed from control evidence, with any alerts."""
        return sv.monitoring.snapshot(actor_id=actor).to_dict()

    # ── approved legal sources ───────────────────────────────────────────────
    @app.get("/v1/sources")
    def sources(actor: Actor) -> Any:
        """The approved-source register."""
        return js(sv.sources.list())

    @app.post("/v1/sources", status_code=201)
    def add_source(body: schemas.SourceIn, actor: Actor) -> Any:
        """Register a legal source. It cannot be used until approved."""
        sv.sources.register(
            RegisteredSource(
                source_id=body.source_id,
                name=body.name,
                jurisdictions=frozenset(body.jurisdictions),
                source_types=tuple(body.source_types),
                authority_owner=body.authority_owner,
                licence=body.licence,
                terms_reviewed=body.terms_reviewed,
                freshness=body.freshness,
                treatment_semantics=body.treatment_semantics,
                authoritative_for=tuple(body.authoritative_for),
                inspection=body.inspection,
            ),
            actor_id=actor,
        )
        return {"source_id": body.source_id, "approved": False}

    @app.post("/v1/sources/{source_id}/approve", status_code=204)
    def approve_source(source_id: str, actor: Actor) -> None:
        """Approve a source for use. Refused unless its owner, licence and status semantics are recorded. A decision."""
        sv.sources.approve(source_id, actor_id=actor)

    @app.post("/v1/sources/{source_id}/revoke", status_code=204)
    def revoke_source(source_id: str, actor: Actor) -> None:
        """Withdraw a source's approval."""
        sv.sources.revoke(source_id, actor_id=actor)

    @app.post("/v1/sources/{source_id}/import")
    def import_corpus(source_id: str, body: schemas.ImportIn, actor: Actor) -> Any:
        """Load a corpus from a folder on the server. Only folders inside the import area can be
        named, so this cannot be used to read anything else on the machine."""
        sv.ctx.authorizer().require_global(actor, "source.manage")
        root = Path(sv.ctx.settings.import_root).resolve()
        target = (root / body.directory).resolve()
        if root not in (target, *target.parents) or not target.is_dir():
            raise InvalidInput(f"no such folder inside the import area: {body.directory}")
        imported = sv.sources.import_corpus(source_id, target, actor_id=actor)
        return {"imported": len(imported)}

    @app.get("/v1/sources/{source_id}/authorities")
    def authorities(source_id: str, actor: Actor) -> Any:
        """What a source holds: each authority with its citation and current status."""
        return js(sv.sources.authorities(source_id, actor_id=actor))

    @app.get("/v1/authorities/{authority_id}")
    def authority(authority_id: str, actor: Actor) -> Any:
        """The text of one authority as located passages."""
        return [
            {"ordinal": p.ordinal, "locator": p.locator, "text": p.text}
            for p in sv.sources.authority_text(authority_id, actor_id=actor)
        ]

    # ── configuration ────────────────────────────────────────────────────────
    @app.get("/v1/config")
    def config(actor: Actor) -> Any:
        """The model in use, the runtime policy and the server's settings."""
        return {
            "model": _public(sv.config.current()),
            "policy": js(sv.ctx.policy),
            "server": {
                "second_factor_required": cfg.require_second_factor,
                "idle_minutes": cfg.idle_minutes,
                "session_hours": cfg.session_hours,
                "max_upload_bytes": cfg.max_upload_bytes,
                "tls": cfg.secure,
            },
        }

    @app.get("/v1/config/models")
    def models(actor: Actor, url: str = "") -> Any:
        """The models that can be chosen: GGUF files found on this machine (by reference, never
        by path), and those a model server on this machine offers. Only an address on this
        machine can be asked, so the server cannot be made to call anywhere else."""
        sv.ctx.authorizer().require_global(actor, "config.manage")
        target = url or sv.ctx.settings.inference_url
        if not is_loopback(urlsplit(target).hostname or ""):
            raise InvalidInput("only an inference server on this machine can be queried")
        try:
            served = sv.config.available_models(target)
        except EliLegalError:
            served = []
        return {
            "url": target,
            "models": served,
            "gguf": [m.as_dict(with_path=False) for m in sv.config.gguf_models()],
            "gguf_supported": sv.config.current()["gguf_supported"],
            "machine": sv.config.machine(),
        }

    @app.get("/v1/config/models/{ref}/placement")
    def placement(
        ref: str,
        actor: Actor,
        gguf_context: int | None = None,
        gguf_gpu_layers: int | None = None,
        gguf_threads: int | None = None,
    ) -> Any:
        """How that GGUF model would be placed on this machine if it were loaded now: context,
        layers on the graphics card, and the reasons. Nothing is loaded or changed."""
        sv.ctx.authorizer().require_global(actor, "config.manage")
        return sv.config.preview_by_ref(
            ref,
            gguf_context=gguf_context,
            gguf_gpu_layers=gguf_gpu_layers,
            gguf_threads=gguf_threads,
        )

    @app.post("/v1/config/model")
    def set_model(body: schemas.ModelIn, actor: Actor) -> Any:
        """Change the model. A decision, recorded. For GGUF, give the references from the list."""
        from eli_legal.settings import ENV_FILE

        options = {
            k: v
            for k, v in (
                ("gguf_context", body.gguf_context),
                ("gguf_gpu_layers", body.gguf_gpu_layers),
                ("gguf_threads", body.gguf_threads),
            )
            if v is not None
        }
        if body.backend == "gguf":
            sv.config.set_model_by_ref(
                actor_id=actor, ref=body.model, verifier_ref=body.verifier_model,
                persist_to=ENV_FILE, **options,
            )  # fmt: skip
        else:
            sv.config.set_model(
                actor_id=actor,
                backend=body.backend,
                url=body.url or sv.ctx.settings.inference_url,
                model=body.model,
                verifier_model=body.verifier_model,
                persist_to=ENV_FILE,
                **options,
            )
        return _public(sv.config.current())


def _public(current: dict[str, Any]) -> dict[str, Any]:
    """The model configuration without the GGUF file paths, which are this machine's business."""
    out = dict(current)
    if out.get("backend") == "gguf":
        from pathlib import Path

        out["model"] = Path(out["model"]).name if out.get("model") else ""
        out["verifier_model"] = (
            Path(out["verifier_model"]).name if out.get("verifier_model") else ""
        )
    return out
