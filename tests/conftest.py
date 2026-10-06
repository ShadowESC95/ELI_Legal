from __future__ import annotations

import json
import os
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from eli_legal.adapters.local.network import NetworkGuard
from eli_legal.application.services import Services, build_services
from eli_legal.demo import build_demo_workspace
from eli_legal.demo_run import ARBITRATOR, SECRETARY, demo_settings, run_demo, setup_demo


class FakeInference:
    """A scripted model. ``script`` maps a task name to a reply or to a function of the prompt."""

    available = True

    def __init__(self, script: dict[str, Any] | None = None, model_id: str = "fake-model") -> None:
        self.model_id = model_id
        self.script = script or {}
        self.prompts: list[str] = []

    def generate(
        self, *, system: str, prompt: str, max_tokens: int = 2048, json_mode: bool = False
    ) -> str:
        self.prompts.append(prompt)
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
def _no_ambient_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Tests never read the developer's .env or leave the network guard installed."""
    for name in list(os.environ):
        if name.startswith("ELI_LEGAL_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    yield
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


__all__ = ["ARBITRATOR", "SECRETARY", "FakeInference", "make_key"]
