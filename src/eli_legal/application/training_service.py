"""Training the organisation's own model, under the people the law expects to decide.

Who does what (security/rbac.py):

- the **compliance officer** (training.approve) switches training on for the organisation, with
  the data protection impact assessment (GDPR Art. 35), the legal basis for training on case
  material, and the acknowledgement that training may make the organisation the provider of the
  system it changes (EU AI Act Art. 25(1)(b)); sets whether training is human or autonomous;
  approves or retires each trained model, never one they trained themselves;
- a **matter's lead** allows its approved work to train, with the basis (the clients' consent,
  a practice matter), and can withdraw it, which deletes its examples;
- a **lawyer** (training.data) approves, corrects or rejects each training example;
- a **technical officer** (training.run) sets up the environment and runs training and its
  evaluation, without seeing case content;
- the person who manages the configuration (config.manage) puts an approved model into use.

Every decision needs the person's passphrase again where it changes what the system will do, and
every one is recorded in the audit ledger.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from eli_legal.application.container import AppContext
from eli_legal.domain.errors import InvalidInput, InvalidState, NotFound, PolicyDenied
from eli_legal.domain.models import Matter, TrainedModel, TrainingExample, TrainingPolicy, utcnow
from eli_legal.security import authn
from eli_legal.security.rbac import TRAINING_APPROVE, TRAINING_DATA, TRAINING_RUN
from eli_legal.training import dataset, environment, evaluation, jobs
from eli_legal.training.pseudonymise import OPTIONAL, Pseudonymiser, never_kept

POLICY = ("training", "policy")
MODELS = "trained_model"
MIN_TEXT = 20
RECIPES: dict[str, dict[str, Any]] = {
    "light": {
        "epochs": 1,
        "seq_len": 1024,
        "batch_size": 1,
        "grad_accum": 8,
        "learning_rate": 2e-4,
        "rank": 8,
        "alpha": 16,
    },
    "standard": {
        "epochs": 2,
        "seq_len": 2048,
        "batch_size": 1,
        "grad_accum": 8,
        "learning_rate": 1e-4,
        "rank": 16,
        "alpha": 32,
    },
    "thorough": {
        "epochs": 3,
        "seq_len": 3072,
        "batch_size": 1,
        "grad_accum": 16,
        "learning_rate": 5e-5,
        "rank": 32,
        "alpha": 64,
    },
}


def weights_digest(folder: Path) -> str:
    """SHA-256 over a base model's configuration and weight files, in name order."""
    h = hashlib.sha256()
    names = sorted(
        p
        for p in folder.iterdir()
        if p.suffix in (".safetensors", ".bin", ".json", ".model") and p.is_file()
    )
    if not any(p.suffix in (".safetensors", ".bin") for p in names):
        raise InvalidInput(f"{folder} holds no model weights (.safetensors or .bin)")
    for p in names:
        h.update(p.name.encode())
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _by_review(e: TrainingExample) -> bool:
    """Approved by its run's review in autonomous mode, not by a person looking at it."""
    return e.status == "approved" and e.review_note.startswith("approved by the review of run")


class TrainingService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    # ── who may ─────────────────────────────────────────────────────────────
    def _require(self, actor_id: str, action: str) -> None:
        self.ctx.authorizer().require_global(actor_id, action)

    def _log(
        self,
        event: str,
        actor_id: str,
        subject: str,
        outcome: str,
        *,
        matter_id: str = "-",
        action: str = TRAINING_RUN,
        **payload: Any,
    ) -> None:
        self.ctx.log(
            event,
            actor_id=actor_id,
            matter_id=matter_id,
            action=action,
            subject_id=subject,
            outcome=outcome,
            object_type="training",
            payload=payload,
        )

    @property
    def data_dir(self) -> Path:
        # The data folder (beside artifacts/): training/env, training/models, training/work.
        return Path(self.ctx.settings.artifacts_dir).parent

    # ── the organisation's policy ───────────────────────────────────────────
    def policy(self) -> TrainingPolicy:
        return self.ctx.store.get_registry(*POLICY, TrainingPolicy) or TrainingPolicy()

    def set_policy(
        self,
        *,
        actor_id: str,
        enabled: bool,
        mode: str = "human",
        dpia_reference: str = "",
        legal_basis: str = "",
        provider_acknowledged: bool = False,
        min_examples: int | None = None,
        heldout_percent: int | None = None,
        scope: str = "practice",
        cross_matter_acknowledged: bool = False,
        omit: list[str] | tuple[str, ...] = OPTIONAL,
        keep_reason: str = "",
        max_matter_share: int | None = None,
    ) -> TrainingPolicy:
        authn.require_step_up(actor_id, "change how the organisation trains its model")
        self._require(actor_id, TRAINING_APPROVE)
        if mode not in ("human", "autonomous"):
            raise InvalidInput("training is human (a person approves each example) or autonomous")
        if scope not in ("practice", "consented"):
            raise InvalidInput("train on practice matters only, or on consented real matters too")
        if scope == "consented" and not cross_matter_acknowledged:
            raise InvalidInput(
                "one model learns from every matter it trains on and can repeat one client's "
                "material in another client's work: acknowledge that before allowing real "
                "matters (each model is tested for it before it may be approved)"
            )
        unknown = set(omit) - set(OPTIONAL)
        if unknown:
            raise InvalidInput(f"what may be taken out: {', '.join(OPTIONAL)}")
        kept = [k for k in OPTIONAL if k not in omit]
        if kept and len(keep_reason.strip()) < MIN_TEXT:
            raise InvalidInput(
                f"keeping {', '.join(kept)} in the examples needs a reason on record: the task "
                "must need them (GDPR Art. 5(1)(c), data minimisation)"
            )
        if enabled:
            if len(dpia_reference.strip()) < 3:
                raise InvalidInput(
                    "name the data protection impact assessment that covers "
                    "training on case material (GDPR Art. 35)"
                )
            if len(legal_basis.strip()) < MIN_TEXT:
                raise InvalidInput("state the legal basis for using case material to train")
            if not provider_acknowledged:
                raise InvalidInput(
                    "training changes the AI system: acknowledge that the "
                    "organisation may become its provider (EU AI Act Art. 25)"
                )
        current = self.policy()
        policy = replace(
            current,
            enabled=enabled,
            mode=mode,
            dpia_reference=dpia_reference.strip(),
            legal_basis=legal_basis.strip(),
            provider_acknowledged=provider_acknowledged,
            scope=scope,
            cross_matter_acknowledged=bool(cross_matter_acknowledged) and scope == "consented",
            omit=[k for k in OPTIONAL if k in omit],
            keep_reason=keep_reason.strip() if kept else "",
            max_matter_share=max(
                5,
                min(
                    100,
                    int(
                        max_matter_share
                        if max_matter_share is not None
                        else current.max_matter_share
                    ),
                ),
            ),
            min_examples=max(
                1, int(min_examples if min_examples is not None else current.min_examples)
            ),
            heldout_percent=max(
                5,
                min(
                    30,
                    int(
                        heldout_percent if heldout_percent is not None else current.heldout_percent
                    ),
                ),
            ),
            updated_by=actor_id,
            updated_at=utcnow(),
        )
        self.ctx.store.put_registry(*POLICY, policy)
        self._log(
            "training_policy_set",
            actor_id,
            "policy",
            "enabled" if enabled else "disabled",
            action=TRAINING_APPROVE,
            mode=mode,
            dpia=policy.dpia_reference,
            scope=policy.scope,
            omit=policy.omit,
            kept=kept,
            max_matter_share=policy.max_matter_share,
            min_examples=policy.min_examples,
            heldout_percent=policy.heldout_percent,
        )
        return policy

    def _enabled(self) -> TrainingPolicy:
        policy = self.policy()
        if not policy.enabled:
            raise PolicyDenied(
                "training is switched off for this organisation: the compliance "
                "officer switches it on, with its impact assessment and legal basis"
            )
        return policy

    # ── which matters may teach ─────────────────────────────────────────────
    def allow_matter(
        self, matter_id: str, *, actor_id: str, allow: bool, basis: str = "", consent: str = ""
    ) -> Matter:
        """A matter's lead (or the compliance officer) lets its approved work train, or stops it.
        A real matter needs the organisation's consented scope and its client's consent on
        record. Stopping deletes the examples already taken from it."""
        authn.require_step_up(actor_id, "change whether a matter may train the model")
        matter = self.ctx.store.get_matter(matter_id)
        if matter is None:
            raise NotFound(f"no such matter: {matter_id}")
        authz = self.ctx.authorizer()
        if actor_id != matter.owner_user_id and not authz.bindings.can(
            actor_id, "compliance.manage"
        ):
            raise PolicyDenied(
                "only the matter's lead or the compliance officer decides whether "
                "its work may train the model"
            )
        if allow:
            policy = self._enabled()
            if len(basis.strip()) < MIN_TEXT:
                raise InvalidInput(
                    "state the basis for training on this matter's material (the "
                    "clients' consent, a practice matter, the organisation's policy)"
                )
            if matter.real and policy.scope != "consented":
                raise PolicyDenied(
                    "the organisation trains on practice matters only: the compliance officer "
                    "decides whether real matters may teach"
                )
            if matter.real and len(consent.strip()) < MIN_TEXT:
                raise InvalidInput(
                    "a real matter teaches only with its client's consent: record where and "
                    "when the client gave it (the engagement letter, a signed form)"
                )
        matter.training_use = allow
        matter.training_basis = basis.strip() if allow else ""
        matter.training_consent = consent.strip() if allow and matter.real else ""
        matter.training_set_by = actor_id
        matter.training_set_at = utcnow()
        self.ctx.store.put_matter(matter)
        removed = 0 if allow else self.ctx.store.delete_records(TrainingExample, matter_id)
        if not allow:  # its consent or basis is gone: models trained on it may not be used
            self.matter_erased(matter_id, actor_id=actor_id)
        self._log(
            "training_matter_" + ("allowed" if allow else "withdrawn"),
            actor_id,
            matter_id,
            "allowed" if allow else "withdrawn",
            matter_id=matter_id,
            action="training.matter",
            examples_deleted=removed,
            real=matter.real,
            consent_recorded=bool(matter.training_consent),
        )
        return matter

    # ── examples ────────────────────────────────────────────────────────────
    def build(self, *, actor_id: str) -> dataset.Built:
        self._require(actor_id, TRAINING_DATA)
        policy = self._enabled()
        built = dataset.build(
            self.ctx,
            heldout_percent=policy.heldout_percent,
            autonomous=policy.mode == "autonomous",
            scope=policy.scope,
            omit=policy.omit,
        )
        self._log(
            "training_examples_built",
            actor_id,
            "examples",
            "built",
            action=TRAINING_DATA,
            matters=built.matters,
            runs=built.runs,
            added=built.added,
            approved_by_review=built.approved_by_review,
            not_kept=built.skipped,
        )
        return built

    def examples(
        self,
        *,
        actor_id: str,
        status: str | None = None,
        task: str | None = None,
        matter_id: str | None = None,
    ) -> list[TrainingExample]:
        self._require(actor_id, TRAINING_DATA)
        out = []
        for matter in self.ctx.store.list_matters():
            if matter_id and matter.matter_id != matter_id:
                continue
            for ex in self.ctx.store.list(TrainingExample, matter.matter_id):
                if (status is None or ex.status == status) and (task is None or ex.task == task):
                    out.append(ex)
        return sorted(out, key=lambda e: e.created_at)

    def counts(self) -> dict[str, int]:
        found: dict[str, int] = {}
        for matter in self.ctx.store.list_matters():
            for ex in self.ctx.store.list(TrainingExample, matter.matter_id):
                key = f"{ex.status}:{ex.split}"
                found[key] = found.get(key, 0) + 1
        return found

    def _example(self, example_id: str) -> TrainingExample:
        matter_id = self.ctx.store.owner_matter(TrainingExample, example_id)
        found = self.ctx.store.get(TrainingExample, matter_id, example_id) if matter_id else None
        if found is None:
            raise NotFound(f"no such training example: {example_id}")
        return found

    def decide(
        self,
        example_id: str,
        *,
        actor_id: str,
        decision: str,
        reason: str = "",
        answer: str | None = None,
    ) -> TrainingExample:
        """A lawyer approves an example, approves it with a corrected answer, or rejects it."""
        self._require(actor_id, TRAINING_DATA)
        policy = self._enabled()
        ex = self._example(example_id)
        if decision not in ("approve", "correct", "reject"):
            raise InvalidInput("approve, correct or reject")
        if decision in ("correct", "reject") and len(reason.strip()) < 4:
            raise InvalidInput("say why")
        if decision == "correct":
            if answer is None:
                raise InvalidInput("give the corrected answer")
            try:
                parsed = json.loads(answer)
            except ValueError:
                raise InvalidInput(
                    "the corrected answer must be a JSON object, as the step expects"
                ) from None
            if not isinstance(parsed, dict):
                raise InvalidInput("the corrected answer must be a JSON object")
            text = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
            kind = never_kept(text)
            if kind is not None:
                raise InvalidInput(f"an example may not concern {kind}: reject it instead")
            matter = self.ctx.store.get_matter(ex.matter_id)
            hide = Pseudonymiser(dataset.names_of(matter) if matter else [], policy.omit)
            ex.answer = hide(text)  # what a person types is taken out the same way
            for k, n in hide.counts.items():
                ex.omitted[k] = ex.omitted.get(k, 0) + n
            ex.source = "edited"
        if decision == "reject":  # its content has no further use: only the decision stays
            ex.system = ex.prompt = ex.answer = ex.model_answer = ""
        ex.status = "rejected" if decision == "reject" else "approved"
        ex.reviewed_by = actor_id
        ex.reviewed_at = utcnow()
        ex.review_note = reason.strip()
        self.ctx.store.put(ex)
        self._log(
            {"approve": "training_example_approved", "correct": "training_example_corrected"}.get(
                decision, "training_example_rejected"
            ),
            actor_id,
            ex.example_id,
            ex.status,
            matter_id=ex.matter_id,
            action=TRAINING_DATA,
            task=ex.task,
        )
        return ex

    # ── the environment ─────────────────────────────────────────────────────
    def environment_status(self, *, actor_id: str) -> dict[str, Any]:
        self._require(actor_id, TRAINING_RUN)
        return environment.probe(environment.folder(self.data_dir))

    def setup_plan(self, *, actor_id: str, hw: Any) -> environment.Plan:
        self._require(actor_id, TRAINING_RUN)
        return environment.plan(self.data_dir, hw)

    def set_up(
        self,
        *,
        actor_id: str,
        hw: Any,
        on_line: Callable[[str], None],
        cancelled: Callable[[], bool] = lambda: False,
    ) -> dict[str, Any]:
        self._require(actor_id, TRAINING_RUN)
        self._log("training_environment_setup", actor_id, "environment", "started")
        found = environment.set_up(self.data_dir, hw, on_line, cancelled=cancelled)
        self._log(
            "training_environment_setup",
            actor_id,
            "environment",
            "ready" if found.get("ready") else "failed",
            why=found.get("why", ""),
            packages=found.get("packages", {}),
        )
        return found

    # ── training ────────────────────────────────────────────────────────────
    def models(self) -> list[TrainedModel]:
        return sorted(
            self.ctx.store.list_registry(MODELS, TrainedModel),
            key=lambda m: m.started_at,
            reverse=True,
        )

    def model(self, model_id: str) -> TrainedModel:
        found = self.ctx.store.get_registry(MODELS, model_id, TrainedModel)
        if found is None:
            raise NotFound(f"no such trained model: {model_id}")
        return found

    def _put(self, m: TrainedModel) -> None:
        self.ctx.store.put_registry(MODELS, m.model_id, m)

    def start(
        self,
        *,
        actor_id: str,
        name: str,
        base: str,
        recipe: str | dict[str, Any] = "standard",
        four_bit: bool = False,
        quantize: str = "q4_k_m",
        dry_run: bool = False,
        python: str | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> TrainedModel:
        """Train on every approved example not kept back. Needs the policy's minimum."""
        authn.require_step_up(actor_id, "train the organisation's model")
        self._require(actor_id, TRAINING_RUN)
        return self._start(
            trained_by=actor_id,
            name=name,
            base=base,
            recipe=recipe,
            four_bit=four_bit,
            quantize=quantize,
            dry_run=dry_run,
            python=python,
            on_event=on_event,
        )

    def _start(
        self,
        *,
        trained_by: str,
        name: str,
        base: str,
        recipe: str | dict[str, Any],
        four_bit: bool,
        quantize: str,
        dry_run: bool,
        python: str | None,
        on_event: Callable[[dict[str, Any]], None] | None,
        autonomous: bool = False,
    ) -> TrainedModel:
        policy = self._enabled()
        if len(name.strip()) < 3:
            raise InvalidInput("give the model a name")
        folder = Path(base).expanduser()
        if not (folder / "config.json").is_file():
            raise InvalidInput(
                "the base model is a folder in Hugging Face form (config.json, the "
                "weights, the tokenizer); a GGUF file cannot be trained"
            )
        if isinstance(recipe, str) and recipe not in RECIPES:
            raise InvalidInput(f"the recipe is one of {', '.join(RECIPES)}")
        if quantize not in ("", "f16", "q8_0", "q4_k_m", "q5_k_m"):
            raise InvalidInput("the GGUF is written as f16, q8_0, q5_k_m or q4_k_m")
        approved = [e for e in self._all_examples() if e.status == "approved"]
        train, capped = self._capped(
            [e for e in approved if e.split == "train"], policy.max_matter_share
        )
        heldout = [e for e in approved if e.split == "heldout"]
        if len(train) < policy.min_examples:
            raise InvalidState(
                f"{len(train)} approved examples to train on; the organisation's "
                f"policy needs at least {policy.min_examples}"
            )
        if not dry_run:
            ready = environment.probe(environment.folder(self.data_dir), python=python)
            if not ready.get("ready"):
                raise InvalidState(
                    f"the training environment is not ready (step 2): {ready.get('why', '')}"
                )
        digest = weights_digest(folder)
        chosen = dict(RECIPES[recipe]) if isinstance(recipe, str) else dict(recipe)
        chosen["four_bit"] = bool(four_bit)
        # q8_0 and f16 the converter writes itself; the smaller forms are made from f16 after.
        chosen["quantize"] = quantize if quantize in ("q4_k_m", "q5_k_m") else ""
        gguf_type = "f16" if chosen["quantize"] else (quantize or "q8_0")
        dataset_digest = hashlib.sha256(
            "".join(sorted(e.content_hash for e in train)).encode()
        ).hexdigest()
        model = TrainedModel(
            name=name.strip(),
            base_model=str(folder),
            base_digest=digest,
            trained_by=trained_by,
            recipe=chosen,
            example_ids=[e.example_id for e in train],
            heldout_ids=[e.example_id for e in heldout],
            matter_ids=sorted({e.matter_id for e in train} | {e.matter_id for e in heldout}),
            dataset_digest=dataset_digest,
            datasheet=self._datasheet(policy, train, heldout, capped),
            autonomous=autonomous,
        )
        model.folder = str(jobs.job_dir(self.data_dir, model.model_id))
        self._put(model)
        jobs.start(
            self.data_dir,
            model.model_id,
            base=str(folder),
            train_rows=[dataset.chat_rows(e) for e in train],
            recipe=chosen,
            gguf_type=gguf_type,
            dry_run=dry_run,
            python=python,
            on_event=on_event,
        )
        self._log(
            "training_started",
            "autonomous" if autonomous else trained_by,
            model.model_id,
            "started",
            name=model.name,
            base=folder.name,
            base_digest=digest,
            examples=len(train),
            heldout=len(heldout),
            matters=len(model.matter_ids),
            dataset_digest=dataset_digest,
            recipe=chosen,
            capped=capped,
            dry_run=dry_run,
            instructed_by=trained_by if autonomous else None,
        )
        return model

    @staticmethod
    def _capped(
        train: list[TrainingExample], share: int
    ) -> tuple[list[TrainingExample], dict[str, int]]:
        """No one matter gives more than ``share`` per cent of what is trained on: it would be
        learnt by heart, and the model would learn one case's ways. The examples kept from a
        matter over its share are chosen by their content, so the choice never changes."""
        if share >= 100 or not train:
            return train, {}
        limit = max(1, int(len(train) * share / 100))
        by_matter: dict[str, list[TrainingExample]] = {}
        for e in train:
            by_matter.setdefault(e.matter_id, []).append(e)
        if len(by_matter) == 1:  # one matter: nothing to balance against (the datasheet says so)
            return train, {}
        kept: list[TrainingExample] = []
        capped: dict[str, int] = {}
        for mid, found in by_matter.items():
            found.sort(key=lambda e: e.content_hash)
            kept += found[:limit]
            if len(found) > limit:
                capped[mid] = len(found) - limit
        return sorted(kept, key=lambda e: e.created_at), capped

    def _datasheet(
        self,
        policy: TrainingPolicy,
        train: list[TrainingExample],
        heldout: list[TrainingExample],
        capped: dict[str, int],
    ) -> dict[str, Any]:
        """What the model is trained on, for its technical documentation: where each example
        came from and on what basis, who approved it, what was taken out, and the gaps."""
        every = train + heldout
        matters = {mid: self.ctx.store.get_matter(mid) for mid in {e.matter_id for e in every}}

        def count(values: Any) -> dict[str, int]:
            out: dict[str, int] = {}
            for v in values:
                out[str(v)] = out.get(str(v), 0) + 1
            return dict(sorted(out.items()))

        omitted: dict[str, int] = {}
        for e in every:
            for k, n in e.omitted.items():
                omitted[k] = omitted.get(k, 0) + n
        by_task = count(e.task for e in train)
        share = max(count(e.matter_id for e in train).values(), default=0) / max(1, len(train))
        gaps = [f"no examples of the step {t}" for t in dataset.TASKS if t not in by_task]
        gaps += [f"fewer than 10 examples of {t}" for t, n in by_task.items() if n < 10]
        if len(matters) == 1:
            gaps.append("one matter only: the model learns that case's ways, not the practice's")
        jurisdictions = count(m.jurisdiction for m in matters.values() if m)
        if len(jurisdictions) == 1:
            gaps.append(f"one jurisdiction only ({next(iter(jurisdictions))})")
        not_kept: dict[str, int] = {}
        for event in self.ctx.audit.events(matter_id="-"):
            if event["event_type"] == "training_examples_built":
                not_kept = event["payload"].get("not_kept") or {}
        return {
            "purpose": (
                "to draft ELI Legal's analysis steps (choosing facts, proposing issues, linking "
                "them, setting out arguments, checking support) the way this organisation's "
                "approved work does; never to decide or recommend an outcome"
            ),
            "policy": {
                "scope": policy.scope,
                "mode": policy.mode,
                "taken_out_always": ["names", "contact details", "identifying numbers"],
                "taken_out": policy.omit,
                "kept": [k for k in OPTIONAL if k not in policy.omit],
                "keep_reason": policy.keep_reason,
                "never_kept": "special categories (GDPR Art. 9), criminal offences (Art. 10), "
                "children",
                "dpia": policy.dpia_reference,
                "legal_basis": policy.legal_basis,
                "max_matter_share": policy.max_matter_share,
            },
            "provenance": [
                {
                    "matter_id": mid,
                    "real": bool(m.real) if m else None,
                    "profile": m.profile.value if m else None,
                    "jurisdiction": m.jurisdiction if m else None,
                    "basis": m.training_basis if m else "",
                    "consent": m.training_consent if m else "",
                    "allowed_by": m.training_set_by if m else None,
                    "allowed_at": m.training_set_at.isoformat()
                    if m and m.training_set_at
                    else None,
                    "train": sum(1 for e in train if e.matter_id == mid),
                    "heldout": sum(1 for e in heldout if e.matter_id == mid),
                }
                for mid, m in sorted(matters.items())
            ],
            "examples": {
                "train": len(train),
                "heldout": len(heldout),
                "by_task": by_task,
                "by_source": count(e.source for e in train),
                "approved_by": {
                    "a person": sum(1 for e in train if not _by_review(e)),
                    "the run's review (autonomous)": sum(1 for e in train if _by_review(e)),
                },
            },
            "left_out": {
                "taken_out_by_kind": dict(sorted(omitted.items())),
                "over_a_matters_share": capped,
                "never_kept_at_last_build": not_kept,
            },
            "examination": {
                "jurisdictions": jurisdictions,
                "profiles": count(m.profile.value for m in matters.values() if m),
                "largest_matter_share": round(share, 3),
            },
            "gaps": gaps,
        }

    def _all_examples(self) -> list[TrainingExample]:
        """The examples of every matter that may teach under the organisation's scope now."""
        scope = self.policy().scope
        out = []
        for matter in self.ctx.store.list_matters():
            if dataset.may_teach(matter, scope) is None:
                out += self.ctx.store.list(TrainingExample, matter.matter_id)
        return out

    def _sources_allowed(self, m: TrainedModel) -> None:
        """A model is approved or used only while every matter it learnt from may still teach."""
        scope = self.policy().scope
        for mid in m.matter_ids:
            matter = self.ctx.store.get_matter(mid)
            why = "it no longer exists" if matter is None else dataset.may_teach(matter, scope)
            if why is not None:
                raise InvalidState(
                    f"it was trained on matter {mid}, which may no longer teach ({why}): "
                    "train a new model without it"
                )

    def refresh(self, model_id: str) -> TrainedModel:
        """Bring a model's record up to its job's state (a run ends while no window watches)."""
        m = self.model(model_id)
        if m.status != "training":
            return m
        st = jobs.state(Path(m.folder))
        if st.get("status") == "done" and st.get("result"):
            result = st["result"]
            m.gguf_path = str(result.get("gguf", ""))
            m.gguf_sha256 = str(result.get("gguf_sha256", ""))
            quant = str(m.recipe.get("quantize") or "")
            if quant and not result.get("dry_run"):
                try:  # the converter wrote 16 bits; make the smaller file and keep only it
                    from eli_legal.training.quantize import quantize

                    source = Path(m.gguf_path)
                    target = source.with_name(f"model-{quant}.gguf")
                    quantize(source, target, quant)
                    source.unlink()
                    m.gguf_path = str(target)
                    m.gguf_sha256 = _sha256(target)
                except Exception as exc:
                    m.status = "failed"
                    m.failure = f"quantising to {quant} failed: {exc}"
                    m.finished_at = utcnow()
                    self._put(m)
                    self._log(
                        "training_finished", m.trained_by, m.model_id, "failed", why=m.failure
                    )
                    return m
            m.status = "trained"
            m.finished_at = utcnow()
            m.recipe = {
                **m.recipe,
                "result": {
                    k: result.get(k)
                    for k in (
                        "steps",
                        "examples",
                        "first_loss",
                        "final_loss",
                        "device",
                        "four_bit",
                        "seconds",
                        "versions",
                        "dry_run",
                    )
                },
            }
            self._put(m)
            self._log(
                "training_finished",
                m.trained_by,
                m.model_id,
                "trained",
                gguf_sha256=m.gguf_sha256,
                final_loss=result.get("final_loss"),
            )
        elif st.get("status") in ("failed", "cancelled"):
            m.status = "failed"
            m.failure = str(st.get("message") or st["status"])
            m.finished_at = utcnow()
            self._put(m)
            self._log("training_finished", m.trained_by, m.model_id, st["status"], why=m.failure)
        return m

    def cancel(self, model_id: str, *, actor_id: str) -> bool:
        self._require(actor_id, TRAINING_RUN)
        done = jobs.cancel(self.data_dir, model_id)
        self._log("training_cancel_asked", actor_id, model_id, "asked")
        return done

    # ── evaluation and approval ─────────────────────────────────────────────
    def evaluate(
        self,
        model_id: str,
        *,
        actor_id: str,
        generate: Callable[[str, str], str] | None = None,
        current: Callable[[str, str], str] | None = None,
    ) -> TrainedModel:
        """Score the trained model (and the model in use) on the examples kept back, and test it
        for repeating what it was trained on."""
        self._require(actor_id, TRAINING_RUN)
        return self._evaluate(model_id, actor_id, generate, current)

    def _evaluate(
        self,
        model_id: str,
        actor_id: str,
        generate: Callable[[str, str], str] | None,
        current: Callable[[str, str], str] | None,
    ) -> TrainedModel:
        m = self.refresh(model_id)
        if m.status not in ("trained", "candidate"):
            raise InvalidState(f"the model is {m.status}; only a trained model is evaluated")
        if generate is None:
            generate = self._gguf_generate(m.gguf_path)
        if current is None:
            current = self._current_generate()
        everything = {e.example_id: e for e in self._all_examples()}
        held = [everything[i] for i in m.heldout_ids if i in everything]
        learnt = [everything[i] for i in m.example_ids if i in everything] + held
        names = {}
        for mid in m.matter_ids:
            matter = self.ctx.store.get_matter(mid)
            if matter is not None:
                names[mid] = dataset.names_of(matter)
        recall = evaluation.Recall(learnt, names)
        trained = evaluation.run(generate, held, recall).as_dict()
        in_use = evaluation.run(current, held).as_dict() if current is not None and held else None
        ok, reasons = evaluation.verdict(trained, in_use)
        m.evaluation = {
            "trained": trained,
            "in_use": in_use,
            "supports_approval": ok,
            "reasons": reasons,
            "heldout": len(held),
        }
        m.evaluated_at = utcnow()
        m.status = "candidate"
        self._put(m)
        self._log(
            "training_evaluated",
            actor_id,
            m.model_id,
            "supports approval" if ok else "does not",
            readable=trained.get("readable"),
            agreement=trained.get("agreement"),
            outcome_language=trained.get("outcome_language"),
            leaks=trained.get("leaks"),
            names=trained.get("names"),
            recalled=trained.get("recalled"),
            reasons=reasons,
        )
        return m

    def _gguf_generate(self, path: str) -> Callable[[str, str], str]:
        from eli_legal.application.container import gguf_inference

        s = self.ctx.settings
        if not path or not Path(path).is_file():
            raise InvalidState("the trained model's GGUF file is missing")
        model = gguf_inference(
            path,
            n_ctx=s.gguf_context,
            n_gpu_layers=s.gguf_gpu_layers,
            n_threads=s.gguf_threads,
            priority=s.gguf_fit,
        )
        return lambda system, prompt: model.generate(
            system=system, prompt=prompt, max_tokens=1500, json_mode=True
        )

    def _current_generate(self) -> Callable[[str, str], str] | None:
        inference = getattr(self.ctx.model, "inference", None)
        if inference is None or not getattr(inference, "available", False):
            return None
        return lambda system, prompt: inference.generate(
            system=system, prompt=prompt, max_tokens=1500, json_mode=True
        )

    def approve(self, model_id: str, *, actor_id: str, reasons: str) -> TrainedModel:
        """The compliance officer approves a trained model for use. Never their own."""
        authn.require_step_up(actor_id, "approve a trained model")
        self._require(actor_id, TRAINING_APPROVE)
        m = self.model(model_id)
        if actor_id == m.trained_by:
            raise PolicyDenied("the person who trained a model does not approve it")
        if m.erased_sources:
            raise InvalidState(
                "it was trained on matters whose content has since been erased; "
                "train a new model without them"
            )
        self._sources_allowed(m)
        if m.status != "candidate" or not m.evaluation:
            raise InvalidState("only a trained model that has been evaluated is approved")
        if not m.evaluation.get("supports_approval"):
            raise InvalidState(
                "its evaluation does not support approval: "
                + "; ".join(m.evaluation.get("reasons") or [])
            )
        if len(reasons.strip()) < MIN_TEXT:
            raise InvalidInput("record the reasons for approving it")
        self._check_file(m)
        m.status = "approved"
        m.approved_by = actor_id
        m.approved_at = utcnow()
        m.approval_reasons = reasons.strip()
        self._put(m)
        self._log(
            "training_model_approved",
            actor_id,
            m.model_id,
            "approved",
            action=TRAINING_APPROVE,
            gguf_sha256=m.gguf_sha256,
            trained_by=m.trained_by,
        )
        return m

    def _check_file(self, m: TrainedModel) -> None:
        path = Path(m.gguf_path)
        if not path.is_file():
            raise InvalidState("the trained model's GGUF file is missing")
        if _sha256(path) != m.gguf_sha256:
            raise InvalidState("the trained model's GGUF file has changed since it was trained")

    def activate(
        self, model_id: str, *, actor_id: str, persist_to: Path | None = None
    ) -> dict[str, Any]:
        """Put an approved model into use as the drafting model. Real matters then need a
        deployment authorisation that covers it: the one in force was pinned to the old model."""
        m = self.model(model_id)
        if m.status != "approved":
            raise InvalidState("only an approved model is put into use")
        if m.erased_sources:
            raise InvalidState("it was trained on matters whose content has since been erased")
        self._sources_allowed(m)
        self._check_file(m)
        from eli_legal.application.config_service import ConfigService

        verifier = self.ctx.settings.verifier_model
        result = ConfigService(self.ctx).set_model(
            actor_id=actor_id,
            backend="gguf",
            model=m.gguf_path,
            verifier_model=verifier if verifier and verifier != m.gguf_path else "",
            persist_to=persist_to,
        )
        self._log(
            "training_model_activated",
            actor_id,
            m.model_id,
            "in use",
            action="config.manage",
            gguf_sha256=m.gguf_sha256,
        )
        return result

    def retire(self, model_id: str, *, actor_id: str, reason: str) -> TrainedModel:
        authn.require_step_up(actor_id, "retire a trained model")
        self._require(actor_id, TRAINING_APPROVE)
        m = self.model(model_id)
        if len(reason.strip()) < 4:
            raise InvalidInput("say why")
        m.status = "retired"
        m.retired_by = actor_id
        m.retired_at = utcnow()
        m.retire_reason = reason.strip()
        self._put(m)
        self._log(
            "training_model_retired",
            actor_id,
            m.model_id,
            "retired",
            action=TRAINING_APPROVE,
            why=m.retire_reason,
        )
        return m

    def is_approved_file(self, path: str) -> bool:
        """Whether a GGUF under the training folder is an approved model's, unchanged."""
        target = Path(path).resolve()
        for m in self.models():
            if m.gguf_path and Path(m.gguf_path).resolve() == target:
                if m.status != "approved" or m.erased_sources:
                    return False
                try:
                    self._sources_allowed(m)
                    self._check_file(m)
                except InvalidState:
                    return False
                return True
        return False

    # ── autonomous mode ─────────────────────────────────────────────────────
    def set_standing_instruction(
        self, *, actor_id: str, base: str, recipe: str = "standard", quantize: str = "q4_k_m"
    ) -> TrainingPolicy:
        """The technical officer says what autonomous training uses. Its runs are theirs."""
        authn.require_step_up(actor_id, "set what autonomous training uses")
        self._require(actor_id, TRAINING_RUN)
        policy = self._enabled()
        folder = Path(base).expanduser()
        if not (folder / "config.json").is_file():
            raise InvalidInput("the base model is a folder in Hugging Face form (config.json)")
        if recipe not in RECIPES:
            raise InvalidInput(f"the recipe is one of {', '.join(RECIPES)}")
        if quantize not in ("f16", "q8_0", "q4_k_m", "q5_k_m"):
            raise InvalidInput("the GGUF is written as f16, q8_0, q5_k_m or q4_k_m")
        policy = replace(
            policy,
            auto_base=str(folder),
            auto_recipe=recipe,
            auto_quantize=quantize,
            auto_set_by=actor_id,
            auto_set_at=utcnow(),
        )
        self.ctx.store.put_registry(*POLICY, policy)
        self._log(
            "training_standing_instruction",
            actor_id,
            "policy",
            "set",
            base=folder.name,
            base_digest=weights_digest(folder),
            recipe=recipe,
            quantize=quantize,
        )
        return policy

    def autonomous_step(
        self, *, python: str | None = None, dry_run: bool = False
    ) -> dict[str, Any]:
        """What autonomous mode does when it is its turn (the window's timer, or
        ``eli-legal training auto`` on a schedule): evaluate a model that has finished, take the
        examples new approved runs give, and train when there are enough new ones. It never
        approves a model or puts one into use: a named person does both."""
        policy = self.policy()
        if not (policy.enabled and policy.mode == "autonomous"):
            return {"did": [], "why": "autonomous training is not switched on"}
        did: list[str] = []
        for m in self.models():
            if m.autonomous and m.status == "training":
                m = self.refresh(m.model_id)
            if m.autonomous and m.status == "trained":
                try:
                    self._evaluate(m.model_id, "autonomous", None, None)
                    did.append(f"evaluated {m.model_id}")
                except Exception as exc:  # a model that cannot be loaded waits for a person
                    did.append(f"could not evaluate {m.model_id}: {exc}")
                    self._log(
                        "training_evaluated", "autonomous", m.model_id, "could not", why=str(exc)
                    )
        built = dataset.build(
            self.ctx,
            heldout_percent=policy.heldout_percent,
            autonomous=True,
            scope=policy.scope,
            omit=policy.omit,
        )
        if built.added:
            self._log(
                "training_examples_built",
                "autonomous",
                "examples",
                "built",
                action=TRAINING_DATA,
                matters=built.matters,
                runs=built.runs,
                added=built.added,
                approved_by_review=built.approved_by_review,
                not_kept=built.skipped,
                enabled_by=policy.updated_by,
            )
            did.append(
                f"took {built.added} examples ({built.approved_by_review} approved by review)"
            )
        if not policy.auto_set_by or not policy.auto_base:
            return {"did": did, "why": "no standing instruction: the technical officer sets one"}
        if jobs.running():
            return {"did": did, "why": "a training run is going"}
        used = {i for m in self.models() if m.status != "failed" for i in m.example_ids}
        fresh = [
            e
            for e in self._all_examples()
            if e.status == "approved" and e.split == "train" and e.example_id not in used
        ]
        if len(fresh) < policy.min_examples:
            return {
                "did": did,
                "why": f"{len(fresh)} new approved examples; training starts at {policy.min_examples}",
            }
        model = self._start(
            trained_by=policy.auto_set_by,
            name=f"Autonomous {utcnow():%Y-%m-%d %H:%M}",
            base=policy.auto_base,
            recipe=policy.auto_recipe,
            four_bit=False,
            quantize=policy.auto_quantize,
            dry_run=dry_run,
            python=python,
            on_event=None,
            autonomous=True,
        )
        did.append(f"started {model.model_id}")
        return {"did": did, "why": "", "model_id": model.model_id}

    # ── erasure ─────────────────────────────────────────────────────────────
    def matter_erased(self, matter_id: str, *, actor_id: str) -> list[str]:
        """A matter's content is gone: every model trained on it says so, and cannot be approved
        or put into use again. Returns the models flagged."""
        flagged = []
        for m in self.models():
            if matter_id in m.matter_ids and matter_id not in m.erased_sources:
                m.erased_sources.append(matter_id)
                self._put(m)
                flagged.append(m.model_id)
                self._log(
                    "training_model_source_erased",
                    actor_id,
                    m.model_id,
                    "flagged",
                    matter_id=matter_id,
                    action="training.matter",
                )
        return flagged
