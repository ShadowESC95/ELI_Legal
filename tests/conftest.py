from __future__ import annotations

import json
import os
import secrets
import tempfile
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from eli_legal.adapters.inference import hardware
from eli_legal.adapters.local.network import NetworkGuard
from eli_legal.adapters.local.renditions import windowless_fonts
from eli_legal.application.services import Services, build_services
from eli_legal.demo import build_demo_workspace
from eli_legal.demo_run import ARBITRATOR, SECRETARY, demo_settings, run_demo, setup_demo
from eli_legal.security import authn

# The desktop application remembers the size a person chose to read at. The tests keep their own,
# set before any test creates the application, so a test run never changes a real person's
# choice and two runs never meet.
os.environ["ELI_LEGAL_GUI_SETTINGS"] = str(
    Path(tempfile.mkdtemp(prefix="eli-legal-gui-")) / "settings.ini"
)

# The probe itself, for the test that gives it its answers.
real_vram_holders = hardware.vram_holders

# The machine every test runs on unless it says otherwise: no graphics card.
NO_CARD = hardware.Hardware(cpu_threads=8, ram_gb=16.0, available_ram_gb=12.0)


class FakeInference:
    """A scripted model. ``script`` maps a task name to a reply or to a function of the prompt."""

    available = True

    def __init__(self, script: dict[str, Any] | None = None, model_id: str = "fake-model") -> None:
        self.model_id = model_id
        self.script = script or {}
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def generate(
        self, *, system: str, prompt: str, max_tokens: int = 2048, json_mode: bool = False
    ) -> str:
        self.prompts.append(prompt)
        self.systems.append(system)
        for task, reply in self.script.items():
            if f"Task {task}/" in prompt:
                value = reply(prompt) if callable(reply) else reply
                return value if isinstance(value, str) else json.dumps(value)
        return "{}"


def make_key(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(secrets.token_hex(32))
    return path


@pytest.fixture(autouse=True)
def _licence_checked_by_the_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every copy of ELI Legal needs a licence, a source checkout too. The tests run as a copy ELI
    v3 opened, having checked the licence itself, so no test starts a trial in the account's own
    folders; the licensing tests set this back (licensing._hosted = False) and check for real."""
    from eli_legal import licensing

    monkeypatch.setattr(licensing, "_hosted", True)


@pytest.fixture(autouse=True)
def _no_ambient_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Tests never read the developer's .env or leave the network guard installed."""
    for name in list(os.environ):
        if name.startswith("ELI_LEGAL_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    # No test asks the developer's graphics card anything, or switches on a graphics pack
    # that happens to be installed on the developer's machine. A test of the probes gives
    # them their answers; a test of placement states the machine it is placing on.
    monkeypatch.setenv("ELI_LEGAL_GPU", "off")
    # Nor does a test see the models and graphics packs installed on that machine: the places
    # they are looked for are empty folders of the test's own.
    (tmp_path / "home").mkdir(exist_ok=True)
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(tmp_path / "home"))
    for name in ("XDG_DATA_HOME", "LOCALAPPDATA"):
        monkeypatch.setenv(name, str(tmp_path / "home" / "data"))
    for name in ("ELI_MODELS_DIR", "ELI_V3_ROOT"):
        monkeypatch.delenv(name, raising=False)
    # The trial's record and the data that shows earlier use are the test's own folders, never
    # this account's (eli_sdk finds those from the account itself, whatever HOME says).
    from eli_legal import licensing

    monkeypatch.setattr(
        licensing, "_trial_locations", [tmp_path / "trial" / "a", tmp_path / "trial" / "b"]
    )
    monkeypatch.setattr(
        licensing, "_default_data_folders", lambda: [tmp_path / "home" / "data" / "eli-legal"]
    )
    monkeypatch.setenv("ELI_KEYS_DIR", str(tmp_path / "keys"))
    monkeypatch.setattr(hardware, "detect", lambda force=False: replace(NO_CARD))
    monkeypatch.setattr(hardware, "vram_holders", lambda: [])
    # Tests call the services directly as several people. The harness vouches for each name
    # and is what the ledger records; tests of authentication itself remove it.
    authn.clear()
    authn.install_harness("test-harness")
    yield
    authn.remove_harness()
    authn.clear()
    NetworkGuard().uninstall()


@pytest.fixture
def services(tmp_path: Path) -> Services:
    """Empty runtime: demo jurisdiction pack, no users, no matter."""
    workspace = build_demo_workspace(tmp_path / "demo")
    return build_services(demo_settings(tmp_path, workspace), install_network_guard=False)


@pytest.fixture
def demo(tmp_path: Path) -> tuple[Services, str]:
    """Users, approved source, matter and seven documents; no run yet."""
    workspace = build_demo_workspace(tmp_path / "demo")
    sv = build_services(demo_settings(tmp_path, workspace), install_network_guard=False)
    return sv, setup_demo(sv, workspace)


@pytest.fixture
def held_run(demo: tuple[Services, str]) -> tuple[Services, str, str]:
    """The synthetic matter after its first run: held, with every planted defect caught."""
    sv, mid = demo
    run = sv.runs.start(mid, actor_id=SECRETARY)
    return sv, mid, run.run_id


@pytest.fixture(scope="session")
def lifecycle(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """The whole lifecycle, run once: ingest to approved release and evidence pack."""
    root = tmp_path_factory.mktemp("lifecycle")
    return run_demo(root, say=lambda _line: None, install_network_guard=False)


__all__ = ["ARBITRATOR", "NO_CARD", "SECRETARY", "FakeInference", "make_key"]


def pytest_configure(config: pytest.Config) -> None:
    """Before any test makes the window toolkit: on Windows its windowless form needs the
    system's fonts, or a PDF copy would have no text."""
    windowless_fonts()


def case_file(sv: Services, path: str | Path) -> bytes:
    """A case file as ELI Legal's own readers see it: sealed on disk under its matter's key
    (security/sealed.py), opened with it. Only that matter's key opens it."""
    from eli_legal.domain.errors import AuditIntegrityError

    for matter in sv.ctx.store.list_matters():
        try:
            return sv.ctx.files.read(matter.matter_id, path)
        except AuditIntegrityError:
            continue
    return Path(path).read_bytes()


def case_text(sv: Services, path: str | Path) -> str:
    return case_file(sv, path).decode("utf-8")
