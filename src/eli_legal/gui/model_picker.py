"""Choosing the model: a GGUF file on this machine (as ELI v2 and v3 use), a model server on this
machine, ELI v3's own model when launched from ELI v3, or none."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from eli_legal.application.services import Services
from eli_legal.domain.errors import EliLegalError
from eli_legal.gui.widgets import button, label, row

NONE_TEXT = "(none)"


class ModelPicker(QWidget):
    def __init__(self, services: Services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.sv = services
        current = services.config.current()
        self.backend = QComboBox()
        self.backend.addItem("A GGUF model file on this machine (as ELI v2 and v3 use)", "gguf")
        self.backend.addItem(
            "A model server on this machine (Ollama, llama.cpp server, LM Studio)", "openai_compat"
        )
        if current["hosted_by_eli_v3"]:
            self.backend.addItem("ELI v3's model (the one ELI v3 has loaded)", "eli_v3")
        self.backend.addItem("No model: every step that needs none still runs", "none")
        self.pages = QStackedWidget()

        # GGUF
        gguf = QWidget()
        self.gguf_model = QComboBox()
        self.gguf_model.setEditable(True)
        self.gguf_verifier = QComboBox()
        self.gguf_verifier.setEditable(True)
        self.context = QSpinBox()
        self.context.setRange(0, 262144)
        self.context.setSingleStep(2048)
        self.context.setSpecialValueText("automatic")
        self.context.setToolTip(
            "Automatic: what the steps of the work need, where this machine can hold it. "
            "A number is your choice and is reduced only if it cannot be held."
        )
        self.gpu = QSpinBox()
        self.gpu.setRange(-1, 999)
        self.gpu.setSpecialValueText("automatic")
        self.gpu.setToolTip(
            "Automatic: as many layers as fit the graphics memory free when the model loads. "
            "0: the processor only. A number: at most that many."
        )
        self.threads = QSpinBox()
        self.threads.setRange(0, 256)
        self.threads.setSpecialValueText("automatic")
        self.machine = label("", "muted", wrap=True)
        self.placement = label("", wrap=True)
        self.gguf_note = label("", "muted", wrap=True)
        form = QFormLayout(gguf)
        form.addRow("This machine", self.machine)
        form.addRow(
            "Model",
            row(
                self.gguf_model,
                button("Browse…", lambda: self._browse(self.gguf_model)),
                stretch_last=False,
            ),
        )
        form.addRow(
            "Verifier (optional, a different model)",
            row(self.gguf_verifier, button("Browse…", lambda: self._browse(self.gguf_verifier))),
        )
        form.addRow("Context length (tokens)", self.context)
        form.addRow("Layers on the graphics card", self.gpu)
        form.addRow("Processor threads", self.threads)
        form.addRow("If loaded now", self.placement)
        form.addRow(self.gguf_note)
        form.addRow(row(button("Find GGUF models again", self.refresh_gguf), None))
        self.pages.addWidget(gguf)

        # server
        server = QWidget()
        self.url = QLineEdit()
        self.server_model = QComboBox()
        self.server_model.setEditable(True)
        self.server_verifier = QComboBox()
        self.server_verifier.setEditable(True)
        form = QFormLayout(server)
        form.addRow("Server address (this machine only)", self.url)
        form.addRow("Model", self.server_model)
        form.addRow("Verifier (optional, a different model)", self.server_verifier)
        form.addRow(row(button("List the server's models", self.refresh_server), None))
        self.pages.addWidget(server)

        host = QWidget()
        QVBoxLayout(host).addWidget(
            label(
                "ELI Legal uses the model ELI v3 has loaded, with ELI v3's own settings for it. "
                "Nothing is sent anywhere. Running both at once keeps one copy of the model in memory.",
                "muted",
                wrap=True,
            )
        )
        none = QWidget()
        QVBoxLayout(none).addWidget(
            label(
                "Without a model, facts are selected by rule and no arguments are drafted. Every check, "
                "hold and gate works the same.",
                "muted",
                wrap=True,
            )
        )
        self.pages.addWidget(host)
        self.pages.addWidget(none)
        self._page = {"gguf": 0, "openai_compat": 1, "eli_v3": 2, "none": 3}
        self.backend.currentIndexChanged.connect(
            lambda _i: self.pages.setCurrentIndex(self._page.get(self.backend.currentData(), 3))
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.backend)
        layout.addWidget(self.pages)
        self.load(current)
        self.gguf_model.currentIndexChanged.connect(lambda _i: self.show_placement())
        for box in (self.context, self.gpu, self.threads):
            box.valueChanged.connect(lambda _v: self.show_placement())
        self.show_placement()

    # ── filling ──────────────────────────────────────────────────────────────
    def load(self, current: dict[str, Any]) -> None:
        self.refresh_gguf(quiet=True)
        backend = current["backend"]
        index = self.backend.findData(backend)
        self.backend.setCurrentIndex(index if index >= 0 else self.backend.findData("none"))
        self.pages.setCurrentIndex(self._page.get(self.backend.currentData(), 3))
        self.context.setValue(int(current["gguf_context"]))
        self.gpu.setValue(int(current["gguf_gpu_layers"]))
        self.threads.setValue(int(current["gguf_threads"]))
        self.url.setText(current["url"])
        if backend == "gguf":
            self._select(self.gguf_model, current["model"])
            self._select(self.gguf_verifier, current["verifier_model"])
        elif backend == "openai_compat":
            self.server_model.setEditText(current["model"])
            self.server_verifier.setEditText(current["verifier_model"])

    def refresh_gguf(self, quiet: bool = False) -> None:
        # "(none)" is no verifier, not a file of that name to look for again
        keep = (self._value(self.gguf_model), self._value(self.gguf_verifier))
        found = self.sv.config.gguf_models()
        for combo, wanted in ((self.gguf_model, keep[0]), (self.gguf_verifier, keep[1])):
            combo.clear()
            if combo is self.gguf_verifier:
                combo.addItem(NONE_TEXT, "")
            for m in found:
                combo.addItem(f"{m.name}  ·  {m.size / 1e9:.1f} GB  ·  {m.location}", str(m.path))
                combo.setItemData(combo.count() - 1, str(m.path), 3)  # tooltip: where it is
            if wanted:
                self._select(combo, str(wanted))
        supported = self.sv.config.current()["gguf_supported"]
        self.gguf_note.setText(
            (
                f"{len(found)} GGUF model(s) found in ELI's model folders and ELI Legal's own. "
                if found
                else "No GGUF model was found in ELI's model folders; choose a file with Browse. "
            )
            + (
                ""
                if supported
                else "llama.cpp for Python is not installed in this copy, so a GGUF model cannot run here."
            )
        )

    def show_placement(self) -> None:
        """What this machine has, and how the chosen GGUF file would be placed on it now. Read
        from the machine and the file each time; nothing is loaded."""
        try:
            machine = self.sv.config.machine()
        except EliLegalError as exc:
            self.machine.setText(str(exc))
            return
        others = machine["others_on_the_card"]
        self.machine.setText(
            f"{machine['summary']}.\n{machine['runtime']['summary']}."
            + (f"\nAlso using the graphics card: {others}." if others else "")
            + "".join(f"\n{note}." for note in machine["runtime"]["notes"])
        )
        path = self._value(self.gguf_model)
        if not path or not Path(path).is_file():
            self.placement.setText("")
            return
        try:
            plan = self.sv.config.preview(
                path,
                gguf_context=self.context.value(),
                gguf_gpu_layers=self.gpu.value(),
                gguf_threads=self.threads.value(),
            )
        except EliLegalError as exc:
            self.placement.setText(str(exc))
            return
        self.placement.setText(
            plan["summary"][:1].upper()
            + plan["summary"][1:]
            + "."
            + "".join(f"\n{note[:1].upper()}{note[1:]}." for note in plan["notes"])
        )

    def refresh_server(self) -> None:
        try:
            models = self.sv.config.available_models(self.url.text().strip())
        except EliLegalError as exc:
            self.gguf_note.setText(str(exc))
            return
        for combo in (self.server_model, self.server_verifier):
            text = combo.currentText()
            combo.clear()
            combo.addItems(["", *models])
            combo.setEditText(text)

    def _browse(self, combo: QComboBox) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a GGUF model", str(Path.home()), "GGUF models (*.gguf)"
        )
        if path:
            self._select(combo, path)

    @staticmethod
    def _select(combo: QComboBox, path: str) -> None:
        if not path:
            combo.setCurrentIndex(0 if combo.count() else -1)
            return
        index = combo.findData(path)
        if index < 0:
            combo.addItem(f"{Path(path).name}  ·  {Path(path).parent}", path)
            index = combo.count() - 1
        combo.setCurrentIndex(index)

    @staticmethod
    def _value(combo: QComboBox) -> str:
        data = combo.currentData()
        text = combo.currentText().strip()
        if data is not None and combo.itemText(combo.currentIndex()) == text:
            return str(data)
        return "" if text == NONE_TEXT else text

    # ── result ───────────────────────────────────────────────────────────────
    def values(self) -> dict[str, Any]:
        """Arguments for ConfigService.set_model."""
        backend = self.backend.currentData()
        out: dict[str, Any] = {"backend": backend, "url": self.url.text().strip()}
        if backend == "gguf":
            out.update(
                model=self._value(self.gguf_model),
                verifier_model=self._value(self.gguf_verifier),
                gguf_context=self.context.value(),
                gguf_gpu_layers=self.gpu.value(),
                gguf_threads=self.threads.value(),
            )
        elif backend == "openai_compat":
            out.update(
                model=self.server_model.currentText().strip(),
                verifier_model=self.server_verifier.currentText().strip(),
            )
        elif backend == "eli_v3":
            out.update(model="eli_v3", verifier_model="")
        else:
            out.update(model="", verifier_model="")
        return out
