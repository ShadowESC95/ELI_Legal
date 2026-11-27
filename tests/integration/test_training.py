"""Training the organisation's own model, with each decision taken by the person the law expects:
a matter's lead allows its work to teach, a lawyer approves each example, a technical officer
trains, and the compliance officer, never the one who trained, approves the model. Off until the
compliance officer switches it on with its impact assessment and legal basis. A matter erased or
withdrawn stops the models trained on it being used.

The trainer itself runs here in its dry-run form (the test machine has no PyTorch); the real
training is checked by test_real_training_when_the_environment_is_there, where it can run."""

from __future__ import annotations

import io
import json
import os
import sys
import tarfile
from pathlib import Path

import pytest

from eli_legal.adapters.inference.hardware import Hardware
from eli_legal.demo_run import resolve_demo_holds
from eli_legal.domain.enums import ReviewDecision
from eli_legal.domain.errors import InvalidInput, InvalidState, PolicyDenied
from eli_legal.domain.models import TrainingExample
from eli_legal.training import environment, evaluation, jobs
from eli_legal.training.pseudonymise import Pseudonymiser
from eli_legal.training.records import CallRecorder, calls_path, read_calls
from eli_legal.workflows.case_preparation import warning_id

A, ADMIN, GOV = "arb.keane", "admin", "gov.hale"
SOL, TECH = "sol.ryan", "tech.nolan"
POLICY = dict(
    dpia_reference="DPIA-2026-07",
    legal_basis="Clients' written consent to training "
    "on their approved matters, and practice matters",
    provider_acknowledged=True,
)


@pytest.fixture
def approved(held_run):
    """The synthetic matter's run, approved by its named reviewer, with model calls recorded as
    a model would have made them, and the people who train added."""
    sv, mid, rid = held_run
    resolve_demo_holds(sv, mid, rid)
    sv.runs.resume(mid, rid, actor_id=A, reason="All holds resolved by the tribunal.")
    report = sv.runs.summary(mid, rid, actor_id=A)["report"]
    sv.reviews.decide(
        mid,
        rid,
        actor_id=A,
        decision=ReviewDecision.APPROVE,
        reasons="Read in full against the papers; limits acknowledged.",
        report_hash=report["sha256"],
        acknowledged=[warning_id(w) for w in report["warnings"]],
    )
    matter = sv.ctx.store.get_matter(mid)
    names = [p.name for p in matter.parties]
    record = CallRecorder(sv.ctx, mid, rid, "facts")
    for n in range(40):
        record(
            {
                "task": "fact_select",
                "prompt_version": "fact_select/1",
                "system": "SYSTEM",
                "prompt": f"Item F{n}: {names[0]} delivered late on 3 March 2023 and owes "
                f"€48,250.00; write to {names[0].split()[0]} at claims@port.example or "
                f"+353 1 555 0100 (invoice no. INV-{4400 + n}), witness Mr Declan Furlong.",
                "raw": "{}",
                "parsed": {"selected": [f"F{n}"], "note": f"{names[-1]} disputes it"},
                "model": "test-model",
            }
        )
    record({"task": "chat_answer", "system": "S", "prompt": "p", "raw": "{}", "parsed": {}})
    for user, role in ((SOL, "supervising_solicitor"), (TECH, "system_admin")):
        sv.users.add_user(actor_id=ADMIN, user_id=user, display_name=user, roles=[role])
    return sv, mid, rid, names


def _switch_on(sv, mode="human", **kw):
    return sv.training.set_policy(
        actor_id=GOV,
        enabled=True,
        mode=mode,
        min_examples=1,
        heldout_percent=30,
        **{**POLICY, **kw},
    )


def test_a_runs_model_calls_are_kept_with_it_sealed(approved):
    sv, mid, rid, names = approved
    calls = read_calls(sv.ctx, mid, rid)
    assert len(calls) == 41 and calls[0]["step"] == "facts" and calls[0]["task"] == "fact_select"
    raw = calls_path(sv.ctx, mid, rid).read_bytes()
    assert names[0].encode() not in raw, "sealed with the matter's key, like every case file"


def test_training_is_off_until_the_compliance_officer_switches_it_on_with_its_basis(approved):
    sv, mid, *_ = approved
    with pytest.raises(PolicyDenied, match="switched off"):
        sv.training.allow_matter(mid, actor_id=A, allow=True, basis="Clients consented in writing.")
    with pytest.raises(InvalidInput, match="impact assessment"):
        sv.training.set_policy(actor_id=GOV, enabled=True, **{**POLICY, "dpia_reference": ""})
    with pytest.raises(InvalidInput, match="provider"):
        sv.training.set_policy(
            actor_id=GOV, enabled=True, **{**POLICY, "provider_acknowledged": False}
        )
    with pytest.raises(PolicyDenied):
        sv.training.set_policy(actor_id=SOL, enabled=True, **POLICY)
    policy = _switch_on(sv)
    assert policy.enabled and policy.updated_by == GOV
    events = [e for e in sv.ctx.audit.events() if e["event_type"] == "training_policy_set"]
    assert events and events[-1]["payload"]["dpia"] == "DPIA-2026-07"


def test_only_the_lead_allows_a_matter_and_examples_come_with_names_replaced(approved):
    sv, mid, rid, names = approved
    _switch_on(sv)
    with pytest.raises(PolicyDenied, match="lead"):
        sv.training.allow_matter(
            mid, actor_id=SOL, allow=True, basis="The clients consented in writing."
        )
    with pytest.raises(InvalidInput, match="basis"):
        sv.training.allow_matter(mid, actor_id=A, allow=True, basis="ok")
    sv.training.allow_matter(
        mid, actor_id=A, allow=True, basis="A practice matter: invented papers."
    )
    built = sv.training.build(actor_id=SOL)
    assert built.added == 40 and built.runs == 1, "the chat is not trained on"
    examples = sv.training.examples(actor_id=SOL)
    text = " ".join(e.prompt + e.answer for e in examples)
    assert names[0] not in text and "[PARTY 1]" in text
    assert "claims@port.example" not in text and "[EMAIL]" in text and "[PHONE]" in text
    assert "Furlong" not in text and "[PERSON]" in text, "a witness named with a title"
    assert "48,250" not in text and "[AMOUNT]" in text and "[DATE]" in text and "[REF]" in text
    assert examples[0].omitted["name"] >= 2 and examples[0].omitted["amount"] == 1
    # the reviewer took findings out of reliance in this run: a person checks each example
    assert {e.source for e in examples} == {"reviewer_corrected"}
    assert {e.status for e in examples} == {"candidate"}
    assert {"train", "heldout"} == {e.split for e in examples}
    assert sv.training.build(actor_id=SOL).added == 0, "a call is taken once"
    with pytest.raises(PolicyDenied):
        sv.training.examples(actor_id=TECH)  # the technical officer never sees case content


def test_a_lawyer_approves_corrects_or_rejects_each_example(approved):
    sv, mid, *_ = approved
    _switch_on(sv)
    sv.training.allow_matter(
        mid, actor_id=A, allow=True, basis="A practice matter: invented papers."
    )
    sv.training.build(actor_id=SOL)
    first, second, third, *_ = sv.training.examples(actor_id=SOL)
    assert (
        sv.training.decide(first.example_id, actor_id=SOL, decision="approve").status == "approved"
    )
    with pytest.raises(InvalidInput, match="JSON"):
        sv.training.decide(
            second.example_id,
            actor_id=SOL,
            decision="correct",
            reason="wrong item",
            answer="F2 only",
        )
    fixed = sv.training.decide(
        second.example_id,
        actor_id=SOL,
        decision="correct",
        reason="the item named was wrong",
        answer='{"selected": ["F2"]}',
    )
    assert fixed.answer == '{"selected": ["F2"]}' and fixed.source == "edited"
    with pytest.raises(InvalidInput, match="say why"):
        sv.training.decide(third.example_id, actor_id=SOL, decision="reject")
    assert (
        sv.training.decide(
            third.example_id, actor_id=SOL, decision="reject", reason="names a witness"
        ).status
        == "rejected"
    )
    with pytest.raises(PolicyDenied):
        sv.training.decide(third.example_id, actor_id=GOV, decision="approve")


def test_autonomous_mode_takes_only_what_a_reviewer_accepted_unchanged(approved):
    from eli_legal.domain.enums import ClaimStatus
    from eli_legal.domain.models import Claim

    sv, mid, rid, _ = approved
    for claim in sv.ctx.store.list(Claim, mid, run_id=rid):  # as if nothing was taken out
        if claim.status is ClaimStatus.EXCLUDED:
            claim.status = ClaimStatus.VERIFIED
            sv.ctx.store.put(claim)
    _switch_on(sv, mode="autonomous")
    sv.training.allow_matter(
        mid, actor_id=A, allow=True, basis="A practice matter: invented papers."
    )
    built = sv.training.build(actor_id=SOL)
    assert built.approved_by_review == 40
    ex = sv.training.examples(actor_id=SOL)[0]
    assert ex.status == "approved" and ex.reviewed_by == A and "review of run" in ex.review_note


def _base(sv):
    base = Path(sv.ctx.settings.artifacts_dir).parent / "base-model"
    if not base.exists():
        base.mkdir()
        (base / "config.json").write_text('{"model_type": "llama"}')
        (base / "model.safetensors").write_bytes(b"weights")
    return base


def _trained(sv, mid, trainer=TECH, policy=None, consent=""):
    _switch_on(sv, **(policy or {}))
    sv.training.allow_matter(
        mid, actor_id=A, allow=True, basis="A practice matter: invented papers.", consent=consent
    )
    sv.training.build(actor_id=SOL)
    for ex in sv.training.examples(actor_id=SOL):
        sv.training.decide(ex.example_id, actor_id=SOL, decision="approve")
    model = sv.training.start(
        actor_id=trainer,
        name="Firm model 1",
        base=str(_base(sv)),
        recipe={"max_steps": 3},
        dry_run=True,
        python=sys.executable,
    )
    jobs.wait(model.model_id, timeout=60)
    return sv.training.refresh(model.model_id)


def test_a_model_is_trained_evaluated_and_approved_only_by_someone_else(approved):
    sv, mid, *_ = approved
    with pytest.raises(PolicyDenied):
        _switch_on(sv) and sv.training.start(actor_id=SOL, name="x", base="/nowhere")
    model = _trained(sv, mid)
    assert model.status == "trained" and model.gguf_sha256 and len(model.example_ids) > 0
    assert set(model.matter_ids) == {mid} and model.heldout_ids
    assert not (Path(model.folder) / "train.jsonl").exists(), "the examples do not outlive the run"
    with pytest.raises(InvalidState, match="evaluated"):
        sv.training.approve(
            model.model_id, actor_id=GOV, reasons="Looks fine to me after reading it."
        )

    held = {e.example_id: e for e in sv.training.examples(actor_id=SOL)}
    by_prompt = {held[i].prompt: held[i].answer for i in model.heldout_ids}
    bad = sv.training.evaluate(
        model.model_id,
        actor_id=TECH,
        generate=lambda s, p: "The claimant should succeed.",
        current=None,
    )
    assert not bad.evaluation["supports_approval"]
    with pytest.raises(InvalidState, match="does not support approval"):
        sv.training.approve(
            model.model_id, actor_id=GOV, reasons="Approved after reading the figures."
        )

    good = sv.training.evaluate(
        model.model_id, actor_id=TECH, generate=lambda s, p: by_prompt[p], current=None
    )
    assert good.evaluation["trained"]["agreement"] == 1.0 and good.evaluation["supports_approval"]
    with pytest.raises(PolicyDenied):  # the technical officer approves nothing
        sv.training.approve(model.model_id, actor_id=TECH, reasons="I trained it and I approve it.")
    done = sv.training.approve(
        model.model_id,
        actor_id=GOV,
        reasons="Agreement 100% on kept-back examples; no outcome language.",
    )
    assert done.status == "approved" and done.approved_by == GOV
    assert sv.training.is_approved_file(done.gguf_path)


def test_an_unapproved_trained_model_cannot_be_chosen_in_the_settings(approved):
    sv, mid, *_ = approved
    model = _trained(sv, mid)
    with pytest.raises(InvalidInput, match="not been approved"):
        sv.config.set_model(actor_id=ADMIN, backend="gguf", model=model.gguf_path)


def test_erasing_or_withdrawing_a_matter_stops_its_models_being_used(approved):
    from eli_legal.application.preservation_service import dispose

    sv, mid, *_ = approved
    model = _trained(sv, mid)
    sv.training.allow_matter(mid, actor_id=A, allow=False)
    assert sv.ctx.store.list(TrainingExample, mid) == [], "withdrawing deletes its examples"
    flagged = sv.training.model(model.model_id)
    assert flagged.erased_sources == [mid]
    with pytest.raises(InvalidState, match="erased"):
        sv.training.approve(
            model.model_id, actor_id=GOV, reasons="Approved after reading the figures."
        )
    assert not sv.training.is_approved_file(flagged.gguf_path)
    matter = sv.ctx.store.get_matter(mid)
    receipt = dispose(sv.ctx, matter, actor_id=A, why="Retention period ended for the analysis.")
    assert receipt is not None


def test_names_and_contact_details_are_replaced():
    hide = Pseudonymiser(["Port Varen Shipping Ltd", "Mary O'Neill"])
    out = hide(
        "Port Varen Shipping Ltd v Mary O'Neill: O'Neill wrote from mary@oneill.ie, "
        "PPSN 1234567TA, Eircode D02 X285, IBAN IE29 AIBK 9311 5212 3456 78. Shipping law."
    )
    assert "Varen" not in out and "O'Neill" not in out and "[PARTY 1]" in out and "[PARTY 2]" in out
    assert "[EMAIL]" in out and "[PPSN]" in out and "[EIRCODE]" in out and "[IBAN]" in out
    assert "Shipping law" in out, "common words of a name stay"


def test_scoring_names_agreement_readability_and_outcome_language():
    s = evaluation.score(
        [
            ("fact_select", '{"selected": ["F1", "F2"]}', '{"selected": ["F1", "F2"]}'),
            ("fact_select", '{"selected": ["F1", "F2"]}', '{"selected": ["F1", "F3"]}'),
            ("issue_propose", '{"issues": []}', "not json"),
            ("arguments", '{"text": "x"}', '{"text": "The respondent is liable and should lose."}'),
        ]
    ).as_dict()
    assert s["readable"] == 0.75 and s["exact"] == 0.25 and s["outcome_language"] >= 1
    ok, reasons = evaluation.verdict(s, None)
    assert not ok and any("outcome" in r for r in reasons)


def _hw(vendor, name="card", integrated=False):
    return Hardware(
        has_gpu=bool(vendor), gpu_vendor=vendor, gpu_name=name, gpu_integrated=integrated
    )


def test_the_environment_suits_the_accelerator(monkeypatch, tmp_path):
    monkeypatch.setattr(environment, "_cuda_version", lambda: (13, 0))
    cuda = environment.accelerator(_hw("nvidia", "RTX 2060 SUPER"))
    assert cuda.kind == "cuda" and cuda.index_url.endswith("cu130")
    monkeypatch.setattr(environment, "_cuda_version", lambda: (12, 4))
    assert environment.accelerator(_hw("nvidia")).index_url.endswith("cu118")
    assert environment.accelerator(_hw("")).kind == "cpu"
    if sys.platform.startswith("linux"):
        assert environment.accelerator(_hw("amd", "RX 7900")).kind == "rocm"
    plan = environment.plan(tmp_path, _hw("nvidia"))
    labels = [s.label for s in plan.steps]
    assert any("PyTorch" in label for label in labels) and any(
        "converter" in label for label in labels
    )
    assert any("training libraries" in label for label in labels)


def test_an_intel_mac_is_told_it_cannot_train(monkeypatch, tmp_path):
    monkeypatch.setattr(environment.sys, "platform", "darwin")
    monkeypatch.setattr(environment.platform, "machine", lambda: "x86_64")
    plan = environment.plan(tmp_path, _hw("intel", "Iris"))
    assert plan.steps == [] and "Intel Macs" in plan.problems[0]


def test_the_converter_is_unpacked_and_nothing_outside_its_folder(tmp_path):
    env = tmp_path / "env"
    (env / "downloads").mkdir(parents=True)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in (
            ("p/vendor/llama.cpp/convert_hf_to_gguf.py", b"print(1)"),
            ("p/vendor/llama.cpp/conversion/__init__.py", b""),
            ("p/vendor/llama.cpp/gguf-py/gguf/__init__.py", b""),
            ("p/vendor/llama.cpp/conversion/../../../evil.py", b"x"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    (env / "downloads" / "llama_cpp_python-0.3.36.tar.gz").write_bytes(buf.getvalue())
    out = environment.unpack_converter(env, on_line=lambda _l: None)
    assert (out / "convert_hf_to_gguf.py").is_file() and (out / "gguf-py" / "gguf").is_dir()
    assert not (tmp_path / "evil.py").exists() and not any(out.rglob("evil.py"))


# Read when the tests are collected: each test's sandbox clears ELI_LEGAL_* settings.
REAL = {
    k: os.environ.get(f"ELI_LEGAL_TRAINING_{k}", "")
    for k in ("PYTHON", "BASE", "CONVERTER", "STEPS", "QUANT")
}


@pytest.mark.skipif(
    not REAL["PYTHON"],
    reason="set ELI_LEGAL_TRAINING_PYTHON (a Python with PyTorch, transformers and peft), "
    "ELI_LEGAL_TRAINING_BASE (a small model folder) and ELI_LEGAL_TRAINING_CONVERTER (llama.cpp's "
    "folder, with convert_hf_to_gguf.py and gguf-py) to train for real",
)
def test_real_training_when_the_environment_is_there(approved):
    """The whole of it for real: a lawyer approves the examples, the technical officer trains on
    the machine's own accelerator, the GGUF is written and made smaller with ELI Legal's own
    llama.cpp, loaded by ELI Legal, scored and tested for repeating what it learnt."""
    sv, mid, *_ = approved
    env = sv.training.data_dir / "training" / "env"
    env.mkdir(parents=True)
    (env / "llama.cpp").symlink_to(REAL["CONVERTER"])
    _switch_on(sv)
    sv.training.allow_matter(
        mid, actor_id=A, allow=True, basis="A practice matter: invented papers."
    )
    sv.training.build(actor_id=SOL)
    for ex in sv.training.examples(actor_id=SOL):
        sv.training.decide(ex.example_id, actor_id=SOL, decision="approve")
    steps = int(REAL["STEPS"] or 40)
    model = sv.training.start(
        actor_id=TECH,
        name="Real run",
        base=REAL["BASE"],
        recipe={
            "max_steps": steps,
            "seq_len": 512,
            "grad_accum": 1,
            "batch_size": 4,
            "learning_rate": 1e-3,
            "rank": 16,
            "alpha": 32,
        },
        quantize=REAL["QUANT"] or "q8_0",
        python=REAL["PYTHON"],
    )
    jobs.wait(model.model_id, timeout=3600)
    done = sv.training.refresh(model.model_id)
    log = (Path(done.folder) / "trainer.log").read_text()
    print(log[-4000:])
    assert done.status == "trained", done.failure + "\n" + log[-3000:]
    result = done.recipe["result"]
    assert result["steps"] == steps and result["final_loss"] < result["first_loss"], result
    assert Path(done.gguf_path).is_file() and done.gguf_sha256
    assert not (Path(done.folder) / "merged").exists()
    assert not (Path(done.folder) / "train.jsonl").exists()
    scored = sv.training.evaluate(model.model_id, actor_id=TECH, current=None)
    figures = {k: v for k, v in scored.evaluation["trained"].items() if k != "failures"}
    print(json.dumps(figures, indent=1), scored.evaluation["reasons"])
    assert scored.evaluation["trained"]["examples"] == len(done.heldout_ids)
    assert scored.evaluation["trained"]["probes"] == 3


def test_nobody_approves_a_model_they_trained_even_holding_both_roles(approved):
    sv, mid, *_ = approved
    both = "it.compliance"
    sv.users.add_user(
        actor_id=ADMIN,
        user_id=both,
        display_name="Both roles",
        roles=["system_admin", "governance_officer"],
    )
    model = _trained(sv, mid, trainer=both)
    held = {e.example_id: e for e in sv.training.examples(actor_id=SOL)}
    answers = {held[i].prompt: held[i].answer for i in model.heldout_ids}
    sv.training.evaluate(
        model.model_id, actor_id=both, generate=lambda s, p: answers[p], current=None
    )
    with pytest.raises(PolicyDenied, match="trained a model"):
        sv.training.approve(
            model.model_id, actor_id=both, reasons="I trained it and I approve it too."
        )
    assert (
        sv.training.approve(
            model.model_id, actor_id=GOV, reasons="Checked the figures on the kept-back examples."
        ).status
        == "approved"
    )


def _make_real(sv, mid):
    matter = sv.ctx.store.get_matter(mid)
    matter.real = True
    sv.ctx.store.put_matter(matter)


CONSENT = "Client consent to training, engagement letter clause 14, signed 2026-10-03."


def test_a_real_matter_teaches_only_in_consented_scope_with_its_clients_consent(approved):
    sv, mid, *_ = approved
    _make_real(sv, mid)
    _switch_on(sv)  # practice matters only
    with pytest.raises(PolicyDenied, match="practice matters only"):
        sv.training.allow_matter(
            mid, actor_id=A, allow=True, basis="The client agreed in writing.", consent=CONSENT
        )
    with pytest.raises(InvalidInput, match="another client's work"):
        _switch_on(sv, scope="consented")
    _switch_on(sv, scope="consented", cross_matter_acknowledged=True)
    with pytest.raises(InvalidInput, match="consent"):
        sv.training.allow_matter(mid, actor_id=A, allow=True, basis="The client agreed in writing.")
    matter = sv.training.allow_matter(
        mid, actor_id=A, allow=True, basis="The client agreed in writing.", consent=CONSENT
    )
    assert matter.training_consent == CONSENT
    assert sv.training.build(actor_id=SOL).added == 40


def test_a_model_from_a_matter_no_longer_in_scope_is_not_approved(approved):
    sv, mid, *_ = approved
    _make_real(sv, mid)
    _switch_on(sv, scope="consented", cross_matter_acknowledged=True)
    sv.training.allow_matter(
        mid, actor_id=A, allow=True, basis="The client agreed in writing.", consent=CONSENT
    )
    model = _trained(
        sv, mid, policy=dict(scope="consented", cross_matter_acknowledged=True), consent=CONSENT
    )
    held = {e.example_id: e for e in sv.training.examples(actor_id=SOL)}
    answers = {held[i].prompt: held[i].answer for i in model.heldout_ids}
    sv.training.evaluate(
        model.model_id, actor_id=TECH, generate=lambda s, p: answers[p], current=None
    )
    _switch_on(sv)  # the compliance officer goes back to practice matters only
    with pytest.raises(InvalidState, match="may no longer teach"):
        sv.training.approve(
            model.model_id, actor_id=GOV, reasons="Checked the figures on the kept-back examples."
        )


def test_what_concerns_health_crime_or_a_child_is_never_kept(approved):
    sv, mid, rid, _ = approved
    record = CallRecorder(sv.ctx, mid, rid, "facts")
    for words in (
        "She was diagnosed with depression in May.",
        "He was convicted of assault.",
        "The child lived with the claimant.",
    ):
        record(
            {
                "task": "fact_select",
                "system": "SYSTEM",
                "prompt": f"Item F1: {words}",
                "raw": "{}",
                "parsed": {"selected": ["F1"]},
            }
        )
    _switch_on(sv)
    sv.training.allow_matter(
        mid, actor_id=A, allow=True, basis="A practice matter: invented papers."
    )
    built = sv.training.build(actor_id=SOL)
    assert built.added == 40
    assert built.skipped["never kept: health"] == 1
    assert built.skipped["never kept: criminal convictions and offences"] == 1
    assert built.skipped["never kept: a child"] == 1
    kept = " ".join(e.prompt for e in sv.training.examples(actor_id=SOL))
    assert "diagnosed" not in kept and "convicted" not in kept


def test_keeping_amounts_or_dates_needs_a_reason(approved):
    sv, mid, *_ = approved
    with pytest.raises(InvalidInput, match="minimisation"):
        _switch_on(sv, omit=["references", "addresses"])
    _switch_on(
        sv,
        omit=["references", "addresses"],
        keep_reason="Limitation and quantum steps need the real dates and amounts.",
    )
    sv.training.allow_matter(
        mid, actor_id=A, allow=True, basis="A practice matter: invented papers."
    )
    sv.training.build(actor_id=SOL)
    text = " ".join(e.prompt for e in sv.training.examples(actor_id=SOL))
    assert "48,250" in text and "3 March 2023" in text and "[REF]" in text


def test_a_rejected_example_keeps_only_the_decision_and_a_correction_is_cleaned(approved):
    sv, mid, _, names = approved
    _switch_on(sv)
    sv.training.allow_matter(
        mid, actor_id=A, allow=True, basis="A practice matter: invented papers."
    )
    sv.training.build(actor_id=SOL)
    first, second, *_ = sv.training.examples(actor_id=SOL)
    gone = sv.training.decide(
        first.example_id, actor_id=SOL, decision="reject", reason="not useful"
    )
    assert gone.prompt == gone.answer == gone.system == "" and gone.content_hash
    assert sv.training.build(actor_id=SOL).added == 0, "a rejected call is not taken again"
    fixed = sv.training.decide(
        second.example_id,
        actor_id=SOL,
        decision="correct",
        reason="names",
        answer=json.dumps({"selected": ["F2"], "note": f"{names[0]} paid"}),
    )
    assert names[0] not in fixed.answer and "[PARTY 1]" in fixed.answer
    with pytest.raises(InvalidInput, match="health"):
        sv.training.decide(
            second.example_id,
            actor_id=SOL,
            decision="correct",
            reason="facts",
            answer='{"note": "the witness was diagnosed with cancer"}',
        )


def test_a_model_that_repeats_another_matters_material_or_a_name_fails(approved):
    sv, mid, _, names = approved
    model = _trained(sv, mid)
    held = {e.example_id: e for e in sv.training.examples(actor_id=SOL)}
    answers = {held[i].prompt: held[i].answer for i in model.heldout_ids}
    named = sv.training.evaluate(
        model.model_id,
        actor_id=TECH,
        current=None,
        generate=lambda s, p: answers.get(p, "{}")[:-1] + f', "x": "{names[0]}"}}',
    )
    assert named.evaluation["trained"]["names"] >= 1 and not named.evaluation["supports_approval"]
    assert any("real name" in r for r in named.evaluation["reasons"])

    class Ex:
        def __init__(self, matter_id, prompt, answer="{}", system="SYSTEM", task="arguments"):
            self.matter_id, self.prompt, self.answer, self.system, self.task = (
                matter_id,
                prompt,
                answer,
                system,
                task,
            )

    other = "the vessel left the quay at dawn with the cargo of frozen salmon still unloaded"
    recall = evaluation.Recall(
        [Ex("mat_a", "Item F1: the contract was signed late."), Ex("mat_b", f"Item F1: {other}.")],
        {"mat_b": ["Saoirse Kavanagh"]},
    )
    assert recall.leaked(f'{{"text": "{other}"}}', own="mat_a", given="Item F1: x") == {"mat_b"}
    assert recall.leaked(f'{{"text": "{other}"}}', own="mat_b", given="Item F1: x") == set()
    score = evaluation.run(
        lambda s, p: f'{{"text": "{other}"}}', [Ex("mat_a", "Item F1: x", '{"text": "y"}')], recall
    ).as_dict()
    assert score["leaks"] == 1 and score["recalled"] >= 1 and score["probes"] == 3
    assert not evaluation.verdict(score, None)[0]


def test_no_matter_gives_more_than_its_share():
    from eli_legal.application.training_service import TrainingService

    def ex(mid, n):
        return TrainingExample(
            matter_id=mid,
            run_id="r",
            task="fact_select",
            prompt_version="1",
            system="",
            prompt=str(n),
            answer="{}",
            model_answer="{}",
            content_hash=f"{n:064x}",
        )

    train = [ex("big", n) for n in range(80)] + [ex("small", 100 + n) for n in range(20)]
    kept, capped = TrainingService._capped(train, 25)
    assert sum(1 for e in kept if e.matter_id == "big") == 25 and capped == {"big": 55}
    assert sum(1 for e in kept if e.matter_id == "small") == 20
    assert TrainingService._capped(train[:80], 25) == (train[:80], {}), (
        "one matter: nothing to balance"
    )


def test_each_model_carries_a_datasheet(approved):
    sv, mid, *_ = approved
    model = _trained(sv, mid)
    sheet = model.datasheet
    assert sheet["provenance"][0]["matter_id"] == mid and sheet["provenance"][0]["real"] is False
    assert sheet["examples"]["by_task"] == {"fact_select": sheet["examples"]["train"]}
    assert sheet["left_out"]["taken_out_by_kind"]["name"] > 0
    assert any("one matter only" in g for g in sheet["gaps"])
    assert any("no examples of the step issue_propose" in g for g in sheet["gaps"])


def test_autonomous_mode_trains_by_itself_and_never_approves(approved, monkeypatch):
    from eli_legal.domain.enums import ClaimStatus
    from eli_legal.domain.models import Claim

    sv, mid, rid, _ = approved
    for claim in sv.ctx.store.list(Claim, mid, run_id=rid):
        if claim.status is ClaimStatus.EXCLUDED:
            claim.status = ClaimStatus.VERIFIED
            sv.ctx.store.put(claim)
    _switch_on(sv, mode="autonomous")
    sv.training.allow_matter(
        mid, actor_id=A, allow=True, basis="A practice matter: invented papers."
    )
    assert (
        "standing instruction"
        in sv.training.autonomous_step(dry_run=True, python=sys.executable)["why"]
    )
    base = _base(sv)
    with pytest.raises(PolicyDenied):
        sv.training.set_standing_instruction(actor_id=SOL, base=str(base))
    sv.training.set_standing_instruction(actor_id=TECH, base=str(base), recipe="light")
    step = sv.training.autonomous_step(dry_run=True, python=sys.executable)
    assert step["model_id"], step
    jobs.wait(step["model_id"], timeout=60)
    held = {e.example_id: e for e in sv.training.examples(actor_id=SOL)}
    answers = {e.prompt: e.answer for e in held.values()}
    monkeypatch.setattr(sv.training, "_gguf_generate", lambda path: lambda s, p: answers[p])
    monkeypatch.setattr(sv.training, "_current_generate", lambda: None)
    after = sv.training.autonomous_step(dry_run=True, python=sys.executable)
    assert f"evaluated {step['model_id']}" in after["did"]
    model = sv.training.model(step["model_id"])
    assert model.autonomous and model.trained_by == TECH and model.status == "candidate"
    assert "new approved examples" in after["why"], "nothing new to train on"
    assert model.approved_by == "" and not sv.training.is_approved_file(model.gguf_path)
    approvals = [e for e in sv.ctx.audit.events() if e["event_type"] == "training_model_approved"]
    assert approvals == [], "autonomous mode approves nothing: a named person does"


def test_the_daily_checks_name_models_that_may_no_longer_be_used(approved):
    sv, mid, *_ = approved
    model = _trained(sv, mid)
    held = {e.example_id: e for e in sv.training.examples(actor_id=SOL)}
    answers = {held[i].prompt: held[i].answer for i in model.heldout_ids}
    sv.training.evaluate(
        model.model_id, actor_id=TECH, generate=lambda s, p: answers[p], current=None
    )
    found = {r.check_id: r for r in sv.checks.run().results}["training"]
    assert (
        found.state == "attention" and "waiting for the compliance officer" in found.items[0].text
    )
    sv.training.allow_matter(mid, actor_id=A, allow=False)
    found = {r.check_id: r for r in sv.checks.run().results}["training"]
    assert "may no longer be used" in found.items[0].text


def test_a_trainer_that_dies_leaves_no_examples_behind_and_says_how_it_ended(tmp_path):
    from eli_legal.training import worker

    out = tmp_path / "job"
    out.mkdir()
    train = out / "train.jsonl"
    train.write_text('{"messages": []}\n')
    job = {"out": str(out), "train": str(train), "base": "/nowhere", "recipe": {}, "dry_run": False}
    (out / "job.json").write_text(json.dumps(job))
    assert worker.main(["worker.py", str(out / "job.json")]) == 1  # no PyTorch here, or no base
    outcome = json.loads((out / "outcome.json").read_text())
    assert outcome["status"] == "failed" and outcome["message"]
    assert not train.exists(), "case material does not outlive the run"
    assert jobs.state(out)["status"] == "failed"
