"""GGUF models found and run on this machine, and ELI Legal as a bundle ELI v3 can open."""

import json
import os
import sys
import types
from pathlib import Path

import pytest

from eli_legal.adapters.inference import gguf
from eli_legal.adapters.inference.gguf import GgufInference, discover
from eli_legal.domain.errors import InvalidInput


def _model(path: Path, size_mb: int = 60) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.truncate(size_mb * 1024 * 1024)
    return path


@pytest.fixture
def fake_llama(monkeypatch):
    calls = {"loads": 0, "kwargs": []}

    class Llama:
        def __init__(self, **kw):
            calls["loads"] += 1
            calls["init"] = kw

        def create_chat_completion(self, **kw):
            calls["kwargs"].append(kw)
            return {
                "choices": [{"message": {"content": '<think>pondering</think>{"answer": "green"}'}}]
            }

    monkeypatch.setitem(sys.modules, "llama_cpp", types.SimpleNamespace(Llama=Llama))
    monkeypatch.setattr(gguf, "_LOADED", {})
    return calls


def test_models_are_found_in_the_folders_eli_keeps_them_in(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ELI_MODELS_DIR", raising=False)
    monkeypatch.delenv("ELI_LEGAL_MODELS_DIR", raising=False)
    _model(tmp_path / "share" / "ELI_v3" / "models" / "Qwen3-8B-Q4_K_M.gguf")
    _model(tmp_path / "share" / "ELI_v2" / "models" / "nested" / "Qwen2.5-7B.gguf")
    _model(tmp_path / "share" / "ELI_v3" / "models" / "mmproj-F16.gguf")
    _model(tmp_path / "share" / "ELI_v3" / "models" / "nomic-embed-text.gguf")
    _model(tmp_path / "share" / "ELI_v3" / "models" / "tiny.gguf", size_mb=1)
    _model(tmp_path / "extra" / "Mine.gguf")
    if sys.platform == "darwin" or os.name == "nt":
        pytest.skip("folder layout checked on Linux")
    found = {m.name: m.location for m in discover(str(tmp_path / "extra"), tmp_path / "eli-home")}
    assert found == {
        "Qwen3-8B-Q4_K_M.gguf": "ELI v3",
        "Qwen2.5-7B.gguf": "ELI v2",
        "Mine.gguf": "added by the administrator",
    }


def test_a_gguf_model_runs_in_process_and_its_reasoning_is_never_the_answer(tmp_path, fake_llama):
    path = _model(tmp_path / "m.gguf")
    model = GgufInference(path, n_ctx=4096, n_gpu_layers=-1)
    assert model.model_id.startswith("gguf:m.gguf@")
    assert model.generate(system="s", prompt="p", json_mode=True) == '{"answer": "green"}'
    assert fake_llama["kwargs"][0]["response_format"] == {"type": "json_object"}
    assert fake_llama["kwargs"][0]["messages"][0] == {"role": "system", "content": "s"}
    GgufInference(path, n_ctx=4096, n_gpu_layers=-1).generate(system="s", prompt="p")
    assert fake_llama["loads"] == 1, "the same file with the same settings is loaded once"
    # no graphics card on the machine the tests state, so nothing is asked of one
    assert fake_llama["init"]["n_gpu_layers"] == 0 and fake_llama["init"]["model_path"] == str(
        path.resolve()
    )
    with pytest.raises(InvalidInput):
        GgufInference(tmp_path / "missing.gguf")


def test_a_configured_model_that_cannot_be_used_is_reported_not_fatal(tmp_path):
    from eli_legal.application.services import build_services
    from eli_legal.demo import build_demo_workspace
    from eli_legal.demo_run import demo_settings

    workspace = build_demo_workspace(tmp_path / "demo")
    settings = demo_settings(
        tmp_path, workspace, inference="gguf", inference_model=str(tmp_path / "gone.gguf")
    )
    sv = build_services(settings, install_network_guard=False)
    assert not sv.ctx.model.available
    assert "cannot" in sv.ctx.model.inference.reason


def test_a_gguf_model_is_chosen_by_reference_and_the_server_never_shows_its_path(
    held_run, tmp_path, fake_llama, monkeypatch
):
    from fastapi.testclient import TestClient

    from eli_legal.api.app import create_app
    from eli_legal.application.matter_service import hash_passphrase
    from tests.api.helpers import Browser

    sv, _mid, _rid = held_run
    secret_dir = tmp_path / "very-private-folder"
    first, second = _model(secret_dir / "first.gguf"), _model(secret_dir / "second.gguf")
    sv.ctx.settings.models_dirs = str(secret_dir)
    admin = sv.ctx.user("admin")
    admin.passphrase_hash = hash_passphrase("administrator phrase")
    sv.ctx.store.put_user(admin)
    browser = Browser(create_app(sv), "admin", "administrator phrase")
    listed = browser.get("/v1/config/models")
    assert listed.status_code == 200 and "very-private-folder" not in listed.text
    refs = {m["name"]: m["ref"] for m in listed.json()["gguf"]}
    same = browser.decide(
        "POST",
        "/v1/config/model",
        {"backend": "gguf", "model": refs["first.gguf"], "verifier_model": refs["first.gguf"]},
    )
    assert same.status_code == 422 and "different model" in same.text
    chosen = browser.decide(
        "POST",
        "/v1/config/model",
        {
            "backend": "gguf",
            "model": refs["first.gguf"],
            "verifier_model": refs["second.gguf"],
            "gguf_context": 4096,
        },
    )
    assert chosen.status_code == 200 and "very-private-folder" not in chosen.text
    assert sv.ctx.model.model_id.startswith(
        "gguf:first.gguf"
    ) and sv.ctx.verifier_model.model_id.startswith("gguf:second.gguf")
    unknown = browser.decide("POST", "/v1/config/model", {"backend": "gguf", "model": "0" * 16})
    assert unknown.status_code == 422
    assert str(first) and str(second) and TestClient


def test_eli_v3_s_model_is_offered_only_when_eli_v3_hosts_eli_legal(demo):
    sv, _mid = demo
    with pytest.raises(InvalidInput, match="launched from ELI v3"):
        sv.config.set_model(actor_id="admin", backend="eli_v3")


def test_hosted_by_eli_v3_the_model_is_held_to_json_and_a_prompt_that_does_not_fit_is_refused(
    monkeypatch,
):
    from eli_legal.adapters.eli_v3.inference import EliV3Inference
    from eli_legal.domain.errors import InferenceUnavailable
    from eli_legal.legal.llm import LegalModel

    calls = []
    host = types.ModuleType("eli.cognition.gguf_inference")
    host.get_model_path = lambda: "/models/Host-Model.gguf"
    host.context_window = lambda: 4096
    # as ELI v3 counts: what is left for the reply once this text is in the context
    host.available_generation_tokens = lambda text, system=None: max(0, 4096 - len(text) // 4 - 128)
    host.generate = lambda **kw: calls.append(("plain", kw)) or "plain text"
    host.generate_json = lambda **kw: calls.append(("json", kw)) or {"answer": "green"}
    for name in ("eli", "eli.cognition"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "eli.cognition.gguf_inference", host)

    model = EliV3Inference()
    assert model.model_id == "eli:Host-Model.gguf" and model.context_tokens() == 4096
    assert LegalModel(model).ask("probe", "p", max_tokens=60) == {"answer": "green"}
    kind, sent = calls[-1]
    assert kind == "json" and sent["temperature"] == 0.0 and sent["max_tokens"] == 60
    assert "legal case-preparation system" in sent["system"], "ELI Legal's own instructions"
    assert LegalModel(model).reply_room("x" * 400) < 4096
    with pytest.raises(InferenceUnavailable, match="does not fit the context ELI v3's model"):
        model.generate(system="s", prompt="x" * 40000, json_mode=True)
    assert len(calls) == 1, "the host is not asked to shorten it"

    del host.generate_json, host.context_window, host.available_generation_tokens
    assert model.generate(system="s", prompt="p", json_mode=True) == "plain text"
    assert LegalModel(model).reply_room("p") is None, "an older host cannot say: nothing is trimmed"


@pytest.mark.skipif(
    not os.environ.get("ELI_LEGAL_TEST_GGUF"),
    reason="set ELI_LEGAL_TEST_GGUF to a GGUF file to run",
)
def test_a_real_gguf_model_answers_in_json():
    from eli_legal.legal.llm import LegalModel

    model = LegalModel(GgufInference(os.environ["ELI_LEGAL_TEST_GGUF"], n_ctx=4096))
    assert model.ask(
        "probe", 'Reply as {"answer": "<one word>"}: what colour is grass?', max_tokens=80
    )


def test_eli_legal_describes_itself_to_eli_v3_and_launches_on_its_core(monkeypatch, tmp_path):
    from eli_legal import bundle

    described = bundle.describe()
    assert (
        described["contract"] == 1
        and described["id"] == "legal"
        and described["launch"] == "eli_legal.bundle:launch"
    )
    monkeypatch.delenv("ELI_LEGAL_HOME", raising=False)
    monkeypatch.delenv("ELI_LEGAL_INFERENCE", raising=False)
    monkeypatch.delenv("ELI_LEGAL_INFERENCE_MODEL", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    seen = {}
    import eli_legal.cli

    monkeypatch.setattr(
        eli_legal.cli, "main", lambda argv: seen.update(argv=argv, env=dict(os.environ)) or 0
    )
    assert bundle.launch(["doctor"], host={"name": "ELI v3", "version": "3.0"}) == 0
    env = seen["env"]
    assert env["ELI_LEGAL_MODE"] == "eli_v3" and env["ELI_LEGAL_INFERENCE"] == "eli_v3"
    if os.name != "nt" and sys.platform != "darwin":
        assert env["ELI_LEGAL_HOME"] == str(tmp_path / "share" / "eli-legal"), (
            "never ELI v3's folders"
        )
    for key in (
        "ELI_LEGAL_MODE",
        "ELI_LEGAL_HOME",
        "ELI_LEGAL_INFERENCE",
        "ELI_LEGAL_INFERENCE_MODEL",
        "ELI_LEGAL_HOST",
    ):
        monkeypatch.delenv(key, raising=False)


def test_a_separate_copy_registers_with_eli_v3_and_unregisters(tmp_path):
    from eli_legal import bundle

    path = bundle.register(tmp_path / "bundles")
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["id"] == "legal" and record["command"] and record["contract"] == 1
    assert bundle.unregister(tmp_path / "bundles") == [path] and not path.exists()


def test_eli_v3_is_kept_pointing_at_the_newest_copy_on_this_machine(tmp_path, monkeypatch):
    """ELI v3 starts whichever copy its record names: each installed copy, when it starts,
    takes the record over from a copy that is older or gone, and from no other."""
    from eli_legal import __version__, bundle

    # Wherever ELI v3 keeps its data on this system (the tests point it into the test's folder).
    folder = bundle.v3_bundle_dirs()[0]
    assert str(folder).startswith(str(tmp_path))
    monkeypatch.setenv("APPIMAGE", str(tmp_path / f"ELI_Legal-{__version__}-linux-x86_64.AppImage"))
    (tmp_path / f"ELI_Legal-{__version__}-linux-x86_64.AppImage").write_bytes(b"")
    assert bundle.refresh_registration() is None, "ELI v3 is not on this machine: nothing made"
    assert not folder.parent.exists()
    folder.parent.mkdir(parents=True)
    path = bundle.refresh_registration()
    assert path == folder / "legal.json"

    def names() -> str:
        return str(json.loads(path.read_text(encoding="utf-8"))["command"][0])

    assert names().endswith(f"ELI_Legal-{__version__}-linux-x86_64.AppImage")
    older = tmp_path / "ELI_Legal-0.6.1-linux-x86_64.AppImage"
    older.write_bytes(b"")
    path.write_text(json.dumps({"id": "legal", "version": "0.6.1", "command": [str(older)]}))
    bundle.refresh_registration()
    assert names().endswith(f"{__version__}-linux-x86_64.AppImage"), "an older copy gives way"
    newer = tmp_path / "ELI_Legal-9.0.0-linux-x86_64.AppImage"
    newer.write_bytes(b"")
    path.write_text(json.dumps({"id": "legal", "version": "9.0.0", "command": [str(newer)]}))
    assert bundle.refresh_registration() is None and names() == str(newer), "a newer one stays"
    newer.unlink()
    bundle.refresh_registration()
    assert names().endswith(f"{__version__}-linux-x86_64.AppImage"), "a removed copy gives way"
    monkeypatch.setenv("ELI_LEGAL_MODE", "eli_v3")
    path.write_text(json.dumps({"id": "legal", "version": "0.1", "command": [str(older)]}))
    assert bundle.refresh_registration() is None, "ELI v3's own process is not a copy"
    monkeypatch.delenv("ELI_LEGAL_MODE")
    monkeypatch.delenv("APPIMAGE")
    assert bundle.refresh_registration() is None, "a source checkout registers only when told"


def test_an_uninstaller_removes_only_the_record_of_its_own_copy(tmp_path, monkeypatch):
    from eli_legal import bundle

    path = bundle.register(tmp_path / "bundles")
    other = tmp_path / "another" / "eli-legal-gui"
    other.parent.mkdir()
    other.write_bytes(b"")
    path.write_text(json.dumps({"id": "legal", "version": "1.0", "command": [str(other)]}))
    assert bundle.unregister(tmp_path / "bundles", this_copy=True) == [] and path.exists()
    bundle.register(tmp_path / "bundles")
    assert bundle.unregister(tmp_path / "bundles", this_copy=True) == [path]
