"""Training the organisation's own model, step by step, each step done by the person it belongs to.

1. Before you start: the law, who decides what, and the organisation's training policy.
2. This machine: what it can train on, the components training needs, and setting them up.
3. The base model: which model to start from, how much memory it needs, how to train it.
4. Which cases teach: the open case allowed (or not) to teach, on what basis.
5. Training examples: what each case gave, a lawyer's approval of each one.
6. Train: the run itself, its progress, autonomous mode's standing instruction.
7. Check, approve and use: the figures, the recall test, approval by someone else, use.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from eli_legal.gui.tabs.base import Tab
from eli_legal.gui.widgets import ReasonDialog, button, card, fill, label, row, selected_id, table
from eli_legal.security.rbac import TRAINING_APPROVE, TRAINING_DATA, TRAINING_RUN
from eli_legal.training import environment, jobs
from eli_legal.training.pseudonymise import OPTIONAL

LAW = (
    "<b>Training changes the AI system, so the law asks more of the organisation.</b><ul>"
    "<li><b>EU AI Act.</b> Case preparation for a court or tribunal is high-risk (Annex III "
    "point 8(a)). Training ELI Legal's model is a substantial modification: the organisation "
    "may become the provider of the system it changes (Art. 25(1)(b)), with the provider's "
    "duties. These include data governance (Art. 10), technical documentation (Art. 11, "
    "Annex IV), records (Art. 12), human oversight (Art. 14), accuracy (Art. 15), a quality "
    "system (Art. 17) and a new conformity assessment (Art. 43(4)).</li>"
    "<li><b>GDPR.</b> Case papers hold personal data, and training is a new purpose for it. The "
    "organisation needs a legal basis (Art. 6, with Art. 6(4)) and an impact assessment "
    "(Art. 35). It must take out what the task does not need (Art. 5(1)(c), Art. 25). It must "
    "also honour erasure and objection (Arts. 17, 21). A model is not anonymous while what it "
    "learnt can be drawn back out of it (EDPB Opinion 28/2024).</li>"
    "<li><b>Professional confidentiality.</b> One model learns from every case it trains on. "
    "It could repeat one client's material in another client's work. Real cases teach only "
    "when the compliance officer allows it and the client has consented. Every model is "
    "tested for repeating what it learnt.</li>"
    "<li><b>ISO/IEC 42001.</b> The training policy, the roles, the datasheet and the "
    "evaluation are the records clauses A.2–A.7 of an AI management system expect.</li></ul>"
    "<b>Who decides what</b><ul>"
    "<li>The <b>compliance officer</b> switches training on, chooses what may be learnt and "
    "approves or retires each model. They never approve a model they trained.</li>"
    "<li>A <b>case's lead</b> decides whether that case may teach, and on what basis.</li>"
    "<li>A <b>lawyer</b> (supervising solicitor or legal administrator) approves, corrects or "
    "rejects each example.</li>"
    "<li>The <b>technical officer</b> (system or legal administrator) sets up the machine and "
    "runs training. They never see case content.</li>"
    "<li>The person who <b>manages the configuration</b> puts an approved model into use. Real "
    "cases then need a new deployment authorisation.</li></ul>"
    "<b>Human or autonomous.</b> In human mode a lawyer approves every example. In autonomous "
    "mode, the examples from a run its reviewer approved unchanged count as approved. Training "
    "and its checks then start by themselves. A person still approves every model and puts it "
    "into use: autonomous mode never does either."
)
NEVER = (
    "Always taken out of every example: names (parties, representatives, people named with "
    "a title or as a witness), contact details and identifying numbers. Never kept at all: "
    "anything about health, racial or ethnic origin, political opinions, religious or "
    "philosophical beliefs, trade union membership, genetic or biometric data, sex life or "
    "sexual orientation (GDPR Art. 9), criminal offences (Art. 10), or a child."
)


def _scroll(*widgets: QWidget) -> QScrollArea:
    holder = QWidget()
    layout = QVBoxLayout(holder)
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch(1)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(holder)
    return area


class PolicyDialog(QDialog):
    """The compliance officer's training policy."""

    def __init__(self, parent: QWidget, policy: Any) -> None:
        super().__init__(parent)
        self.setWindowTitle("The organisation's training policy")
        self.setMinimumWidth(640)
        form = QFormLayout()
        self.enabled = QCheckBox("Training is switched on for this organisation")
        self.enabled.setChecked(policy.enabled)
        self.mode = QComboBox()
        self.mode.addItem("Human: a lawyer approves every example", "human")
        self.mode.addItem("Autonomous: an approved run's examples count as approved", "autonomous")
        self.mode.setCurrentIndex(1 if policy.mode == "autonomous" else 0)
        self.scope = QComboBox()
        self.scope.addItem("Practice cases only", "practice")
        self.scope.addItem("Real cases too, each with its client's consent", "consented")
        self.scope.setCurrentIndex(1 if policy.scope == "consented" else 0)
        self.cross = QCheckBox(
            "I understand one model learns from every case it trains on and could repeat one "
            "client's material in another client's work"
        )
        self.cross.setChecked(policy.cross_matter_acknowledged)
        self.dpia = QLineEdit(policy.dpia_reference)
        self.dpia.setPlaceholderText("e.g. DPIA-2026-07, approved by the DPO on 2 Nov 2026")
        self.basis = QPlainTextEdit(policy.legal_basis)
        self.basis.setPlaceholderText(
            "The legal basis for using case material to train (GDPR Art. 6, and why the new "
            "purpose is compatible or consented to)"
        )
        self.basis.setMaximumHeight(80)
        self.provider = QCheckBox(
            "I understand training may make the organisation the provider of the changed "
            "system (EU AI Act Art. 25), with a new conformity assessment"
        )
        self.provider.setChecked(policy.provider_acknowledged)
        self.omit = {}
        for kind in OPTIONAL:
            box = QCheckBox(f"Take out {kind}")
            box.setChecked(kind in policy.omit)
            self.omit[kind] = box
        self.keep_reason = QLineEdit(policy.keep_reason)
        self.keep_reason.setPlaceholderText("Why the task needs what you keep (data minimisation)")
        self.share = QSpinBox()
        self.share.setRange(5, 100)
        self.share.setSuffix(" %")
        self.share.setValue(policy.max_matter_share)
        self.minimum = QSpinBox()
        self.minimum.setRange(1, 100000)
        self.minimum.setValue(policy.min_examples)
        self.heldout = QSpinBox()
        self.heldout.setRange(5, 30)
        self.heldout.setSuffix(" %")
        self.heldout.setValue(policy.heldout_percent)
        form.addRow(self.enabled)
        form.addRow("How examples are approved", self.mode)
        form.addRow("Which cases may teach", self.scope)
        form.addRow(self.cross)
        form.addRow("Impact assessment (GDPR Art. 35)", self.dpia)
        form.addRow("Legal basis", self.basis)
        form.addRow(self.provider)
        for box in self.omit.values():
            form.addRow(box)
        form.addRow("Reason for keeping any", self.keep_reason)
        form.addRow("Most one real case may give", self.share)
        form.addRow("Examples needed to train", self.minimum)
        form.addRow("Kept back to test each model", self.heldout)
        layout = QVBoxLayout(self)
        layout.addWidget(label(NEVER, "muted", wrap=True))
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled.isChecked(),
            "mode": self.mode.currentData(),
            "scope": self.scope.currentData(),
            "cross_matter_acknowledged": self.cross.isChecked(),
            "dpia_reference": self.dpia.text(),
            "legal_basis": self.basis.toPlainText(),
            "provider_acknowledged": self.provider.isChecked(),
            "omit": [k for k, box in self.omit.items() if box.isChecked()],
            "keep_reason": self.keep_reason.text(),
            "max_matter_share": self.share.value(),
            "min_examples": self.minimum.value(),
            "heldout_percent": self.heldout.value(),
        }


class TrainingTab(Tab):
    title = "🧠 Training"

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.training = self.sv.training
        self.headline = label("", wrap=True)
        self.root.addWidget(self.headline)
        self.steps = QTabWidget()
        self.root.addWidget(self.steps, 1)
        self._hw: Any = None
        self._base = ""

        # 1 · before you start
        self.policy_text = label("", wrap=True, selectable=True)
        self.policy_button = button("Set the training policy…", self._set_policy, kind="primary")
        self.steps.addTab(
            _scroll(label(LAW, wrap=True), card("This organisation's policy", self.policy_text,
                                                row(self.policy_button))),
            "1 · Before you start",
        )  # fmt: skip

        # 2 · this machine
        self.machine = label("", wrap=True, selectable=True)
        self.plan_text = QPlainTextEdit()
        self.plan_text.setReadOnly(True)
        self.plan_text.setMinimumHeight(140)
        self.install_log = QPlainTextEdit()
        self.install_log.setReadOnly(True)
        self.install_log.setMinimumHeight(160)
        self.setup_button = button("Set up the training components", self._set_up, kind="primary")
        self.check_button = button("Check them", self._check_environment)
        self.remove_button = button("Remove them", self._remove_environment)
        self.steps.addTab(
            _scroll(
                label(
                    "Training runs in its own folder of components, apart from ELI Legal, "
                    "which is never changed by it. The list below is chosen for this machine's "
                    "graphics card (NVIDIA through CUDA, AMD through ROCm on Linux, Apple "
                    "through Metal, Intel through XPU, or the processor). Setting up downloads "
                    "about 3 to 6 GB once, from the Python Package Index, PyTorch and "
                    "llama-cpp-python; nothing else is sent.",
                    wrap=True,
                ),
                card("This machine", self.machine),
                card("What will be installed, and how", self.plan_text),
                card("Setting up", self.install_log,
                     row(self.setup_button, self.check_button, self.remove_button)),
            ),
            "2 · This machine",
        )  # fmt: skip

        # 3 · the base model
        self.base_label = label("No base model chosen.", wrap=True, selectable=True)
        self.recipe = QComboBox()
        for key, text in (
            ("light", "Light: one pass, quick"),
            ("standard", "Standard: two passes"),
            ("thorough", "Thorough: three passes, longer texts"),
        ):
            self.recipe.addItem(text, key)
        self.recipe.setCurrentIndex(1)
        self.four_bit = QCheckBox("4-bit training (NVIDIA cards only: half the memory or less)")
        self.quant = QComboBox()
        for key, text in (
            ("q4_k_m", "Q4_K_M: smallest, suits an 8 GB card"),
            ("q5_k_m", "Q5_K_M: a little larger and closer"),
            ("q8_0", "Q8_0: near the original"),
            ("f16", "F16: the original size"),
        ):
            self.quant.addItem(text, key)
        self.recipe.currentIndexChanged.connect(lambda _i: self._show_fit())
        self.four_bit.toggled.connect(lambda _c: self._show_fit())
        how = QWidget()
        how_form = QFormLayout(how)
        how_form.addRow("Recipe", self.recipe)
        how_form.addRow(self.four_bit)
        how_form.addRow("The model file it makes", self.quant)
        self.steps.addTab(
            _scroll(
                label(
                    "Training starts from a model in Hugging Face form: a folder with "
                    "config.json, the weights (.safetensors) and the tokenizer. A GGUF file "
                    "cannot be trained. Choose an instruct model whose licence allows "
                    "fine-tuning and use in your work. Smaller models train faster and fit "
                    "smaller cards: 1–4 billion weights suits an 8 GB card, with 4-bit for the "
                    "larger ones.",
                    wrap=True,
                ),
                card("Base model", self.base_label, row(button("Choose its folder…", self._choose_base))),
                card("How to train it", how),
            ),
            "3 · The base model",
        )  # fmt: skip

        # 4 · which cases teach
        self.case_text = label("", wrap=True, selectable=True)
        self.allow_button = button(
            "Allow this case to teach…", lambda: self._allow(True), kind="primary"
        )
        self.stop_button = button("Stop this case teaching…", lambda: self._allow(False))
        self.steps.addTab(
            _scroll(
                label(
                    "Only the approved runs of cases their lead has allowed give examples. A "
                    "practice case may teach once training is on. A real case teaches only "
                    "where the policy allows real cases, and only with its client's consent "
                    "on record. Stopping a case deletes its examples. A model already trained "
                    "on it may then not be approved or used.",
                    wrap=True,
                ),
                card("The open case", self.case_text, row(self.allow_button, self.stop_button)),
            ),
            "4 · Which cases teach",
        )  # fmt: skip

        # 5 · training examples
        self.example_counts = label("", wrap=True)
        self.examples = table(["Example", "Case", "Step", "Where its answer comes from", "Status",
                               "Kept back to test", "Taken out"], stretch=3)  # fmt: skip
        self.examples.itemSelectionChanged.connect(self._example_chosen)
        self.example_view = QPlainTextEdit()
        self.example_view.setReadOnly(True)
        self.example_view.setMinimumHeight(160)
        self.build_button = button("Take examples from approved runs", self._build, kind="primary")
        self.approve_example = button("Approve", lambda: self._decide("approve"))
        self.correct_example = button("Correct the answer…", lambda: self._decide("correct"))
        self.reject_example = button("Reject…", lambda: self._decide("reject"))
        self.steps.addTab(
            _scroll(
                label(NEVER, "muted", wrap=True),
                self.example_counts,
                row(self.build_button),
                self.examples,
                self.example_view,
                row(self.approve_example, self.correct_example, self.reject_example),
            ),
            "5 · Training examples",
        )

        # 6 · train
        self.model_name = QLineEdit()
        self.model_name.setPlaceholderText("A name for the model, e.g. Firm model, November 2026")
        self.train_button = button("Start training", self._start, kind="primary")
        self.cancel_button = button("Cancel the run", self._cancel)
        self.progress = QProgressBar()
        self.progress_text = label("", wrap=True)
        self.train_log = QPlainTextEdit()
        self.train_log.setReadOnly(True)
        self.train_log.setMinimumHeight(180)
        self.auto_text = label("", wrap=True)
        self.instruct_button = button("Use step 3's choices for autonomous runs", self._instruct)
        self.auto_button = button("Do autonomous mode's step now", self._auto_step)
        self.steps.addTab(
            _scroll(
                card("Train", row(self.model_name, stretch_last=True),
                     row(self.train_button, self.cancel_button), self.progress,
                     self.progress_text, self.train_log),
                card("Autonomous mode", self.auto_text, row(self.instruct_button, self.auto_button)),
            ),
            "6 · Train",
        )  # fmt: skip

        # 7 · check, approve and use
        self.models = table(["Model", "Status", "Trained by", "Examples", "Usable answers",
                             "Agreement", "Repeated what it learnt", "Approved by", "Flags"],
                            stretch=0)  # fmt: skip
        self.models.itemSelectionChanged.connect(self._model_chosen)
        self.model_view = QPlainTextEdit()
        self.model_view.setReadOnly(True)
        self.model_view.setMinimumHeight(220)
        self.evaluate_button = button("Check it", self._evaluate, kind="primary")
        self.approve_button = button("Approve it…", self._approve)
        self.use_button = button("Put it into use…", self._activate)
        self.retire_button = button("Retire it…", self._retire)
        self.steps.addTab(
            _scroll(
                label(
                    "A model is checked on the examples kept back from it. It must give usable "
                    "answers (95% at least) and never say who should win. It must agree with "
                    "the approved answers at least as well as the model in use. It must not "
                    "repeat another case's wording or anyone's real name, even when asked for "
                    "them with no case material. Then the compliance officer, not the person "
                    "who trained it, may approve it. Putting it into use needs your passphrase. "
                    "Real cases then need a new deployment authorisation.",
                    wrap=True,
                ),
                self.models,
                row(self.evaluate_button, self.approve_button, self.use_button, self.retire_button),
                self.model_view,
            ),
            "7 · Check, approve and use",
        )  # fmt: skip

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._poll)
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(10 * 60 * 1000)
        self._auto_timer.timeout.connect(self._auto_tick)
        self._auto_timer.start()

    # ── reading ──────────────────────────────────────────────────────────────
    def refresh(self) -> None:
        policy = self.training.policy()
        kept = [k for k in OPTIONAL if k not in policy.omit]
        if policy.enabled:
            self.headline.setText(
                f"<b>Training is on</b> ({policy.mode}). "
                + (
                    "Practice cases only."
                    if policy.scope == "practice"
                    else "Real cases too, with their clients' consent."
                )  # fmt: skip
            )
        else:
            self.headline.setText(
                "<b>Training is off.</b> The compliance officer switches it on in step 1."
            )
        self.policy_text.setText(
            f"Switched {'on' if policy.enabled else 'off'}"
            + (f" by {policy.updated_by} on {policy.updated_at:%d %b %Y}" if policy.updated_at else "")
            + f"<br>Examples approved by: {'a lawyer, each one' if policy.mode == 'human' else 'the approved run’s review, where nothing was taken out'}"
            + f"<br>Cases that may teach: {'practice cases only' if policy.scope == 'practice' else 'real cases too, each with its client’s consent'}"
            + f"<br>Impact assessment: {policy.dpia_reference or '—'}"
            + f"<br>Legal basis: {policy.legal_basis or '—'}"
            + f"<br>Taken out besides names and contact details: {', '.join(policy.omit) or 'nothing more'}"
            + (f"<br>Kept: {', '.join(kept)} ({policy.keep_reason})" if kept else "")
            + f"<br>Most one real case may give: {policy.max_matter_share}% · examples to train: "
            f"{policy.min_examples} · kept back to test: {policy.heldout_percent}%"
        )  # fmt: skip
        self.policy_button.setEnabled(self.session.may(TRAINING_APPROVE))
        run = self.session.may(TRAINING_RUN)
        for widget in (
            self.setup_button,
            self.check_button,
            self.remove_button,
            self.train_button,
            self.cancel_button,
            self.evaluate_button,
            self.instruct_button,
            self.auto_button,
        ):
            widget.setEnabled(run and policy.enabled)  # fmt: skip
        self.setup_button.setEnabled(run)
        self.check_button.setEnabled(run)
        self.remove_button.setEnabled(run)
        data = self.session.may(TRAINING_DATA)
        for widget in (
            self.build_button,
            self.approve_example,
            self.correct_example,
            self.reject_example,
        ):
            widget.setEnabled(data and policy.enabled)  # fmt: skip
        self.approve_button.setEnabled(self.session.may(TRAINING_APPROVE))
        self.retire_button.setEnabled(self.session.may(TRAINING_APPROVE))
        self.use_button.setEnabled(self.session.may("config.manage"))
        self._show_machine()
        self._show_case()
        self._show_examples(data)
        self._show_models()
        self._show_auto(policy)
        self._poll()

    def _show_machine(self) -> None:
        if self._hw is None:
            from eli_legal.adapters.inference.hardware import detect

            self._hw = detect()
        hw = self._hw
        acc = environment.accelerator(hw)
        self.machine.setText(f"{hw.describe()}<br>Training would use: <b>{acc.label}</b>")
        plan = environment.plan(self.training.data_dir, hw, four_bit=self.four_bit.isChecked())
        self.plan_text.setPlainText(
            "\n".join(
                f"{n}. {s.label}: {s.why}\n   {' '.join(s.argv)}"
                for n, s in enumerate(plan.steps, 1)
            )
            + f"\n{len(plan.steps) + 1}. llama.cpp's converter, from llama-cpp-python's source "
            f"({environment.runtime_release() or 'the release ELI Legal runs'}), to write the GGUF"
            + ("\n\nProblems:\n" + "\n".join(plan.problems) if plan.problems else "")
        )
        self.four_bit.setEnabled(acc.four_bit)
        if not acc.four_bit:
            self.four_bit.setChecked(False)

    def _show_case(self) -> None:
        matter = self.session.matter
        if matter is None:
            self.case_text.setText("Open a case to decide whether it may teach.")
            self.allow_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            return
        lead = self.actor == matter.owner_user_id or self.session.may("compliance.manage")
        kind = "a real case" if matter.real else "a practice case"
        if matter.training_use:
            when = f" on {matter.training_set_at:%d %b %Y}" if matter.training_set_at else ""
            text = (f"<b>{matter.name}</b> ({kind}) may teach: allowed by {matter.training_set_by}"
                    f"{when}.<br>Basis: {matter.training_basis}")  # fmt: skip
            if matter.training_consent:
                text += f"<br>Client's consent: {matter.training_consent}"
        else:
            text = f"<b>{matter.name}</b> ({kind}) does not teach."
        if not lead:
            text += "<br><i>Only its lead or the compliance officer decides this.</i>"
        self.case_text.setText(text)
        self.allow_button.setEnabled(lead and not matter.training_use)
        self.stop_button.setEnabled(lead and matter.training_use)

    def _show_examples(self, may_read: bool) -> None:
        counts = self.training.counts()
        waiting = sum(v for k, v in counts.items() if k.startswith("candidate"))
        approved = sum(v for k, v in counts.items() if k == "approved:train")
        held = sum(v for k, v in counts.items() if k == "approved:heldout")
        self.example_counts.setText(
            f"{waiting} waiting for a lawyer · {approved} approved to train on · {held} approved "
            "and kept back to test"
        )
        if not may_read:
            fill(self.examples, [])
            self.example_view.setPlainText(
                "Only a lawyer (supervising solicitor or legal administrator) reads the examples."
            )
            return
        found = self.training.examples(actor_id=self.actor)
        fill(
            self.examples,
            [[e.example_id, e.matter_id, e.task, e.source.replace("_", " "), e.status,
              "yes" if e.split == "heldout" else "",
              ", ".join(f"{n} {k}" for k, n in sorted(e.omitted.items()))] for e in found],
            ids=[e.example_id for e in found],
            state_columns=[4],
        )  # fmt: skip

    def _example_chosen(self) -> None:
        chosen = selected_id(self.examples)
        if not chosen:
            return
        ex = next(
            (e for e in self.training.examples(actor_id=self.actor) if e.example_id == chosen), None
        )
        if ex is None:
            return
        self.example_view.setPlainText(
            f"Step: {ex.task}\nFrom run {ex.run_id} of case {ex.matter_id}\n"
            f"Status: {ex.status}{' by ' + ex.reviewed_by if ex.reviewed_by else ''}"
            f"{' (' + ex.review_note + ')' if ex.review_note else ''}\n\n"
            f"WHAT THE MODEL WAS ASKED\n{ex.prompt}\n\nTHE ANSWER TO LEARN\n{ex.answer}"
        )

    def _show_models(self) -> None:
        found = self.training.models()
        rows = []
        for m in found:
            trained = (m.evaluation or {}).get("trained") or {}
            repeated = (
                trained.get("leaks", 0) + trained.get("names", 0) + trained.get("recalled", 0)
            )
            flags = []
            if m.erased_sources:
                flags.append("trained on erased or withdrawn cases")
            if m.autonomous:
                flags.append("autonomous")
            rows.append([
                m.name, m.status, m.trained_by, len(m.example_ids),
                f"{trained['readable']:.0%}" if trained else "",
                f"{trained['agreement']:.0%}" if trained else "",
                ("no" if not repeated else f"yes ({repeated})") if trained else "",
                m.approved_by, "; ".join(flags),
            ])  # fmt: skip
        fill(self.models, rows, ids=[m.model_id for m in found], state_columns=[1])

    def _model_chosen(self) -> None:
        chosen = selected_id(self.models)
        if not chosen:
            return
        m = self.training.model(chosen)
        sheet = json.dumps(m.datasheet, indent=1, ensure_ascii=False)
        figures = (
            json.dumps(m.evaluation, indent=1, ensure_ascii=False) if m.evaluation else "not yet"
        )
        self.model_view.setPlainText(
            f"{m.name} ({m.model_id}) · {m.status}\nTrained by {m.trained_by} on {m.started_at:%d %b %Y %H:%M}"
            f" from {Path(m.base_model).name} (weights {m.base_digest[:16]}…)\n"
            f"Model file: {m.gguf_path or '—'}\nSHA-256: {m.gguf_sha256 or '—'}\n"
            + (f"Failed: {m.failure}\n" if m.failure else "")
            + (f"Approved by {m.approved_by}: {m.approval_reasons}\n" if m.approved_by else "")
            + (f"Trained on cases since erased or withdrawn: {', '.join(m.erased_sources)}\n"
               if m.erased_sources else "")
            + f"\nCHECKS\n{figures}\n\nDATASHEET (what it learnt from)\n{sheet}"
        )  # fmt: skip

    def _show_auto(self, policy: Any) -> None:
        if policy.mode != "autonomous":
            self.auto_text.setText(
                "Autonomous mode is off: the compliance officer chooses it in step 1."
            )
            return
        if policy.auto_set_by:
            self.auto_text.setText(
                f"Autonomous runs start from {Path(policy.auto_base).name} ({policy.auto_recipe}, "
                f"{policy.auto_quantize}), on the instruction of {policy.auto_set_by}. They start "
                f"when {policy.min_examples} new approved examples are waiting, and are checked "
                "when they finish. A person approves each model."
            )
        else:
            self.auto_text.setText(
                "Autonomous mode is on, but the technical officer has not said what it uses: "
                "choose the base model in step 3, then the button below."
            )

    # ── step 1 ───────────────────────────────────────────────────────────────
    def _set_policy(self) -> None:
        dialog = PolicyDialog(self, self.training.policy())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.session.decide(
            self, "change how the organisation trains its model",
            lambda: self.training.set_policy(actor_id=self.actor, **values),
        )  # fmt: skip

    # ── step 2 ───────────────────────────────────────────────────────────────
    def _set_up(self) -> None:
        self.install_log.clear()
        lines: list[str] = []
        hw = self._hw

        def work() -> object:
            return self.training.set_up(actor_id=self.actor, hw=hw, on_line=lines.append)

        flush = QTimer(self)

        def show() -> None:
            while lines:
                self.install_log.appendPlainText(lines.pop(0))

        flush.timeout.connect(show)
        flush.start(500)

        def done(found: object) -> None:
            flush.stop()
            show()
            info = found if isinstance(found, dict) else {}
            self.install_log.appendPlainText(
                "\nReady to train." if info.get("ready") else f"\nNot ready: {info.get('why', '')}"
            )

        def failed(exc: Exception) -> None:
            flush.stop()
            show()
            self.install_log.appendPlainText(f"\nSetting up stopped: {exc}")

        self.session.background("Setting up the training components…", work, done, failed)

    def _check_environment(self) -> None:
        def done(found: object) -> None:
            info = found if isinstance(found, dict) else {}
            packages = ", ".join(f"{k} {v}" for k, v in (info.get("packages") or {}).items() if v)
            self.install_log.appendPlainText(
                ("Ready" if info.get("ready") else f"Not ready: {info.get('why', '')}")
                + (f" · {info.get('accelerator', '')} · {packages}" if packages else "")
            )

        self.session.background(
            "Checking the training components…",
            lambda: self.training.environment_status(actor_id=self.actor),
            done,
            lambda exc: self.install_log.appendPlainText(f"Could not check: {exc}"),
        )

    def _remove_environment(self) -> None:
        if QMessageBox.question(self, "Remove", "Remove the training components from this machine?") \
                != QMessageBox.StandardButton.Yes:  # fmt: skip
            return
        removed = self.session.attempt(
            self,
            lambda: self.session.may(TRAINING_RUN) and environment.remove(self.training.data_dir),
        )
        self.install_log.appendPlainText("Removed." if removed else "Nothing was removed.")

    # ── step 3 ───────────────────────────────────────────────────────────────
    def _choose_base(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "The base model's folder")
        if not folder:
            return
        if not (Path(folder) / "config.json").is_file():
            QMessageBox.warning(self, "Not a model folder", "That folder has no config.json.")
            return
        self._base = folder
        self._show_fit()

    def _show_fit(self) -> None:
        if not self._base:
            return
        try:
            config = json.loads((Path(self._base) / "config.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            config = {}
        seq = {"light": 1024, "standard": 2048, "thorough": 3072}[str(self.recipe.currentData())]
        need = environment.estimate_gb(self._base, four_bit=self.four_bit.isChecked(), seq_len=seq)
        ok, why = environment.fits(self._hw, need) if self._hw is not None else (False, "")
        self.base_label.setText(
            f"<b>{Path(self._base).name}</b> ({config.get('model_type', 'unknown kind')})<br>"
            f"{self._base}<br>{'✓' if ok else '⚠'} {why}"
        )

    # ── step 4 ───────────────────────────────────────────────────────────────
    def _allow(self, allow: bool) -> None:
        matter = self.session.matter
        if matter is None:
            return
        if not allow:
            reason = ReasonDialog.ask(
                self, "Stop this case teaching",
                "Its examples are deleted, and a model trained on it may not be approved or used. "
                "Why is it stopping?", minimum=4,
            )  # fmt: skip
            if reason is None:
                return
            self.session.decide(
                self, "stop this case teaching the model",
                lambda: self.training.allow_matter(matter.matter_id, actor_id=self.actor, allow=False),
            )  # fmt: skip
            return
        consent = QLineEdit()
        consent.setPlaceholderText("Where and when the client consented (real cases only)")
        consent.setEnabled(matter.real)
        basis = ReasonDialog.ask(
            self, "Allow this case to teach",
            "On what basis may this case's approved work train the organisation's model?",
            minimum=20, extra=[("Client's consent", consent)],
        )  # fmt: skip
        if basis is None:
            return
        self.session.decide(
            self, "allow this case to teach the model",
            lambda: self.training.allow_matter(matter.matter_id, actor_id=self.actor, allow=True,
                                               basis=basis, consent=consent.text()),
        )  # fmt: skip

    # ── step 5 ───────────────────────────────────────────────────────────────
    def _build(self) -> None:
        built = self.session.attempt(self, lambda: self.training.build(actor_id=self.actor))
        if built is None:
            return
        skipped = "".join(f"\n· {why}: {n}" for why, n in sorted(built.skipped.items()))
        QMessageBox.information(
            self, "Examples taken",
            f"{built.added} new examples from {built.runs} approved runs of {built.matters} cases"
            f" ({built.approved_by_review} approved by their run's review).{skipped}",
        )  # fmt: skip

    def _decide(self, decision: str) -> None:
        chosen = selected_id(self.examples)
        if not chosen:
            QMessageBox.information(self, "Choose one", "Choose an example in the list first.")
            return
        if decision == "approve":
            self.session.attempt(
                self, lambda: self.training.decide(chosen, actor_id=self.actor, decision="approve")
            )
            return
        answer = QPlainTextEdit()
        if decision == "correct":
            ex = next(
                e for e in self.training.examples(actor_id=self.actor) if e.example_id == chosen
            )
            answer.setPlainText(ex.answer)
        reason = ReasonDialog.ask(
            self,
            "Correct the answer" if decision == "correct" else "Reject the example",
            "Why?" if decision == "reject" else "Correct the answer (JSON, as the step expects), and say why.",
            minimum=4,
            extra=[("Answer", answer)] if decision == "correct" else (),
        )  # fmt: skip
        if reason is None:
            return
        text = answer.toPlainText()
        self.session.attempt(
            self,
            lambda: self.training.decide(chosen, actor_id=self.actor, decision=decision,
                                         reason=reason, answer=text if decision == "correct" else None),
        )  # fmt: skip

    # ── step 6 ───────────────────────────────────────────────────────────────
    def _start(self) -> None:
        if not self._base:
            QMessageBox.information(self, "Base model", "Choose the base model in step 3 first.")
            self.steps.setCurrentIndex(2)
            return
        name = self.model_name.text().strip() or f"Model {len(self.training.models()) + 1}"
        self.train_log.clear()
        started = self.session.decide(
            self, "train the organisation's model",
            lambda: self.training.start(
                actor_id=self.actor, name=name, base=self._base, recipe=str(self.recipe.currentData()),
                four_bit=self.four_bit.isChecked(), quantize=str(self.quant.currentData())),
        )  # fmt: skip
        if started is not None:
            self._timer.start()

    def _cancel(self) -> None:
        for model in self.training.models():
            if model.status == "training":
                self._cancel_one(model.model_id)

    def _cancel_one(self, model_id: str) -> None:
        self.session.attempt(self, lambda: self.training.cancel(model_id, actor_id=self.actor))

    def _poll(self) -> None:
        going = [m for m in self.training.models() if m.status == "training"]
        if not going:
            self._timer.stop()
            self.progress.setValue(0)
            self.progress_text.setText("No training run is going.")
            return
        m = going[0]
        state = jobs.state(Path(m.folder))
        if state.get("status") in ("done", "failed", "cancelled"):
            self.training.refresh(m.model_id)
            self._timer.stop()
            self.session.notify()
            return
        self._timer.start()
        steps = int(state.get("max_steps") or 0)
        self.progress.setMaximum(max(1, steps))
        self.progress.setValue(int(state.get("step") or 0))
        loss = state.get("loss")
        self.progress_text.setText(
            f"{m.name}: {state.get('message', '')}"
            + (f" · step {state.get('step')} of {steps}" if steps else "")
            + (f" · loss {loss:.4f}" if isinstance(loss, (int, float)) else "")
        )
        log = Path(m.folder) / "trainer.log"
        try:
            tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
        except OSError:
            tail = []
        self.train_log.setPlainText("\n".join(tail))

    def _instruct(self) -> None:
        if not self._base:
            QMessageBox.information(self, "Base model", "Choose the base model in step 3 first.")
            return
        self.session.decide(
            self, "set what autonomous training uses",
            lambda: self.training.set_standing_instruction(
                actor_id=self.actor, base=self._base, recipe=str(self.recipe.currentData()),
                quantize=str(self.quant.currentData())),
        )  # fmt: skip

    def _auto_step(self) -> None:
        def done(result: object) -> None:
            info = result if isinstance(result, dict) else {}
            QMessageBox.information(
                self, "Autonomous mode",
                "\n".join(info.get("did") or ["Nothing to do."]) + (f"\n\n{info['why']}" if info.get("why") else ""),
            )  # fmt: skip
            self._timer.start()
            self.session.notify()

        self.session.background(
            "Autonomous training…",
            self.training.autonomous_step,
            done,
            self._failed("Autonomous mode"),
        )

    def _auto_tick(self) -> None:
        policy = self.training.policy()
        if policy.enabled and policy.mode == "autonomous" and not self.session.working:
            self.session.background(
                "Autonomous training…", self.training.autonomous_step,
                lambda _r: self.session.notify(), lambda _e: None,
            )  # fmt: skip

    # ── step 7 ───────────────────────────────────────────────────────────────
    def _chosen_model(self) -> str:
        chosen = selected_id(self.models)
        if not chosen:
            QMessageBox.information(self, "Choose one", "Choose a model in the list first.")
        return chosen

    def _evaluate(self) -> None:
        chosen = self._chosen_model()
        if not chosen:
            return
        self.session.background(
            "Checking the trained model…",
            lambda: self.training.evaluate(chosen, actor_id=self.actor),
            lambda _m: self._checked(),
            self._failed("Could not check it"),
        )

    def _checked(self) -> None:
        self.session.notify()
        self._model_chosen()

    def _failed(self, title: str) -> Any:
        def show(exc: Exception) -> None:
            QMessageBox.warning(self, title, str(exc))

        return show

    def _approve(self) -> None:
        chosen = self._chosen_model()
        if not chosen:
            return
        reasons = ReasonDialog.ask(
            self, "Approve the trained model",
            "Why may this model be used? Say what you read: its checks, its datasheet, and that "
            "it repeated nothing it learnt.", minimum=20,
        )  # fmt: skip
        if reasons is None:
            return
        self.session.decide(
            self, "approve a trained model",
            lambda: self.training.approve(chosen, actor_id=self.actor, reasons=reasons),
        )  # fmt: skip

    def _activate(self) -> None:
        chosen = self._chosen_model()
        if not chosen:
            return
        if QMessageBox.question(
            self, "Put it into use",
            "The approved model becomes the drafting model for every case. Real cases then need a "
            "new deployment authorisation: the one in force covers the model it was given for. "
            "Go on?",
        ) != QMessageBox.StandardButton.Yes:  # fmt: skip
            return
        self.session.decide(
            self, "put a trained model into use",
            lambda: self.training.activate(chosen, actor_id=self.actor),
        )  # fmt: skip

    def _retire(self) -> None:
        chosen = self._chosen_model()
        if not chosen:
            return
        reason = ReasonDialog.ask(self, "Retire the model", "Why is it retired?", minimum=4)
        if reason is None:
            return
        self.session.decide(
            self, "retire a trained model",
            lambda: self.training.retire(chosen, actor_id=self.actor, reason=reason),
        )  # fmt: skip
