"""Composition root.

Everything the application needs is built here from settings, and nowhere else. Standalone and
ELI-hosted deployments differ only in which adapters are passed in; the services, gates and
workflow are identical.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eli_legal.adapters.inference.embedding_null import NullEmbedder
from eli_legal.adapters.inference.local import (
    NullInference,
    OpenAICompatInference,
    UnavailableInference,
)
from eli_legal.adapters.local.hmac_audit import HmacAuditLedger
from eli_legal.adapters.local.network import NetworkGuard
from eli_legal.adapters.local.parsers import LocalDocumentParser
from eli_legal.adapters.local.vault import EvidenceVault
from eli_legal.adapters.sources import live
from eli_legal.adapters.sources.local_corpus import LocalCorpusConnector
from eli_legal.domain.errors import InvalidInput, NotFound, PolicyDenied
from eli_legal.domain.models import AuditEvent, Matter, User
from eli_legal.domain.policy import RuntimePolicy
from eli_legal.governance.holds import HoldBook
from eli_legal.legal.framework_library import FrameworkLibrary
from eli_legal.legal.jurisdictions import JurisdictionRegistry
from eli_legal.legal.llm import LegalModel
from eli_legal.legal.semantic import SemanticIndex
from eli_legal.legal.source_registry import SourceRegistry
from eli_legal.persistence.sqlite import Store
from eli_legal.ports.document_parser import DocumentParserPort
from eli_legal.ports.embedding import EmbeddingPort
from eli_legal.ports.inference import InferencePort
from eli_legal.ports.legal_sources import LegalSourcePort
from eli_legal.security.authorizer import MatterAuthorizer
from eli_legal.security.prompt_injection import PromptInjectionDetector
from eli_legal.security.rbac import RoleBindings
from eli_legal.settings import Settings
from eli_legal.workflows.runner import WorkflowDef, load_workflow


@dataclass(slots=True)
class AppContext:
    settings: Settings
    policy: RuntimePolicy
    store: Store
    audit: HmacAuditLedger
    vault: EvidenceVault
    guard: NetworkGuard
    jurisdictions: JurisdictionRegistry
    sources: SourceRegistry
    workflow: WorkflowDef
    parser: DocumentParserPort
    detector: PromptInjectionDetector
    model: LegalModel
    verifier_model: LegalModel
    holds: HoldBook
    frameworks: FrameworkLibrary
    embedder: EmbeddingPort = field(default_factory=NullEmbedder)
    extra_connectors: dict[str, LegalSourcePort] = field(default_factory=dict)
    _semantic: SemanticIndex | None = field(default=None, repr=False)

    @property
    def semantic(self) -> SemanticIndex | None:
        """Searching by meaning, when an embedding model is set up."""
        if not self.embedder.available:
            return None
        if self._semantic is None or self._semantic.embedder is not self.embedder:
            self._semantic = SemanticIndex(self.store, self.embedder)
        return self._semantic

    # ── identity and authorisation ───────────────────────────────────────────
    def authorizer(self) -> MatterAuthorizer:
        bindings = RoleBindings.from_users(self.store.list_users())
        return MatterAuthorizer(bindings=bindings, audit=self.audit, policy=self.policy)

    def user(self, user_id: str) -> User:
        user = self.store.get_user(user_id)
        if user is None or not user.active:
            raise PolicyDenied(f"unknown or inactive user: {user_id!r}")
        return user

    def matter_for(self, matter_id: str, actor_id: str, action: str) -> Matter:
        """Load a matter and authorise the action on it. The only way services get a matter."""
        matter = self.store.get_matter(matter_id)
        if matter is None:
            raise NotFound(f"matter not found: {matter_id}")
        self.authorizer().require_matter(matter, actor_id, action)
        return matter

    # ── helpers ──────────────────────────────────────────────────────────────
    def log(
        self,
        event_type: str,
        *,
        actor_id: str,
        matter_id: str,
        action: str,
        subject_id: str,
        outcome: str,
        run_id: str | None = None,
        **fields: Any,
    ) -> int:
        return self.audit.append(
            AuditEvent(
                event_type=event_type,
                actor_id=actor_id,
                matter_id=matter_id,
                run_id=run_id,
                action=action,
                subject_id=subject_id,
                outcome=outcome,
                **fields,
            )
        )

    def connectors_for(self, matter: Matter) -> dict[str, LegalSourcePort]:
        """Connectors for the sources that are approved, cover the law in play, and are listed
        on the matter. A source missing any of the three is simply not reachable."""
        codes = self.jurisdictions.jurisdiction_codes(matter)
        usable = self.sources.usable_for(matter.approved_source_ids, codes)
        out: dict[str, LegalSourcePort] = {}
        for source_id in usable:
            source = self.sources.require_approved(source_id)
            if source_id in self.extra_connectors:
                out[source_id] = self.extra_connectors[source_id]
            elif source.connector == "local_corpus":
                out[source_id] = LocalCorpusConnector(self.store, source)
            elif source.connector in live.CONNECTORS:
                out[source_id] = live.connector_for(
                    self.store, source, self.guard, matter.relevant_date
                )
        return out

    def record_loads(self, model: LegalModel) -> None:
        """Have each load of this model written to the audit trail as llama.cpp reported it:
        the context it holds, the layers on the graphics card, the llama.cpp that ran it.
        What was asked for is a setting; what loaded is a fact about the runs that follow."""
        inference = model.inference
        if not hasattr(inference, "on_load"):
            return
        model_id = model.model_id
        also = getattr(inference, "on_load", None)  # whoever built the model hears of it too

        def record(report: Any) -> None:
            if also is not None:
                also(report)
            facts = report.as_dict()
            facts["notes"] = [str(n)[:280] for n in facts.get("notes", ())]
            self.log(
                "model_loaded",
                actor_id="system",
                matter_id="-",
                action="config.manage",
                subject_id="inference",
                outcome="loaded",
                object_type="configuration",
                model_id=model_id,
                payload=facts,
            )

        inference.on_load = record  # type: ignore[union-attr]

    def run_dir(self, matter_id: str, run_id: str) -> Path:
        path = Path(self.settings.artifacts_dir) / "runs" / matter_id / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path


def gguf_inference(
    model: str, *, n_ctx: int, n_gpu_layers: int, n_threads: int, priority: str
) -> InferencePort:
    """A GGUF model sized, when it loads, to this machine and to what the steps need."""
    from eli_legal.adapters.inference.gguf import GgufInference
    from eli_legal.legal.llm import working_context_tokens

    return GgufInference(
        model,
        n_ctx=n_ctx,
        n_gpu_layers=n_gpu_layers,
        n_threads=n_threads,
        working_ctx=working_context_tokens(),
        priority=priority,
    )


def _inference_from_settings(settings: Settings, guard: NetworkGuard, model: str) -> InferencePort:
    if settings.inference == "eli_v3":
        from eli_legal.adapters.eli_v3.inference import EliV3Inference

        return EliV3Inference() if model else NullInference()
    if settings.inference == "none" or not model:
        return NullInference()
    if settings.inference == "gguf":
        from eli_legal.adapters.inference.gguf import llama_available

        if not llama_available():
            return UnavailableInference(
                "the configured GGUF model cannot run: llama.cpp for Python is not installed here"
            )
        try:
            return gguf_inference(
                model,
                n_ctx=settings.gguf_context,
                n_gpu_layers=settings.gguf_gpu_layers,
                n_threads=settings.gguf_threads,
                priority=settings.gguf_fit,
            )
        except (InvalidInput, OSError) as exc:  # the file was moved or deleted
            return UnavailableInference(f"the configured GGUF model cannot be used: {exc}")
    if settings.inference == "openai_compat":
        return OpenAICompatInference(
            base_url=settings.inference_url,
            model=model,
            api_key=settings.inference_api_key or None,
            timeout=settings.inference_timeout,
            network=guard,
        )
    raise InvalidInput(
        f"inference backend {settings.inference!r} must be supplied by the host "
        "(pass inference= to build_context)"
    )


def _embedder_from_settings(settings: Settings) -> EmbeddingPort:
    from eli_legal.adapters.inference.embedding import from_settings
    from eli_legal.settings import HOME

    embedder: EmbeddingPort = from_settings(
        settings.embedding_model, extra_dirs=settings.models_dirs, home=HOME
    )
    return embedder


def build_context(
    settings: Settings | None = None,
    *,
    inference: InferencePort | None = None,
    verifier: InferencePort | None = None,
    parser: DocumentParserPort | None = None,
    install_network_guard: bool = True,
    embedder: EmbeddingPort | None = None,
) -> AppContext:
    if settings is None:
        settings = Settings()
    policy = RuntimePolicy.from_file(settings.policy_file)
    if settings.network_default.lower() != "deny":
        raise PolicyDenied("ELI Legal only runs with the network denied by default")
    # Fail closed: no protected key, no ledger, no governed runtime.
    audit = HmacAuditLedger(settings.audit_db_path, settings.audit_key_file)
    store = Store(settings.db_path)
    sources = SourceRegistry(store=store)
    guard = NetworkGuard(
        host for s in sources.list() if s.approved and s.network_required for host in s.hosts
    )
    if install_network_guard:
        guard.install()
    model = LegalModel(
        inference or _inference_from_settings(settings, guard, settings.inference_model)
    )
    verifier_model = LegalModel(
        verifier or _inference_from_settings(settings, guard, settings.verifier_model)
    )
    ctx = AppContext(
        settings=settings,
        policy=policy,
        store=store,
        audit=audit,
        vault=EvidenceVault(settings.data_dir),
        guard=guard,
        jurisdictions=JurisdictionRegistry.from_dir(settings.jurisdictions_dir),
        sources=sources,
        workflow=load_workflow(settings.workflow_file),
        parser=parser or LocalDocumentParser(),
        detector=PromptInjectionDetector(),
        model=model,
        verifier_model=verifier_model,
        holds=HoldBook(store=store, audit=audit),
        frameworks=FrameworkLibrary(store),
        embedder=embedder if embedder is not None else _embedder_from_settings(settings),
    )
    ctx.record_loads(ctx.model)
    ctx.record_loads(ctx.verifier_model)
    return ctx
