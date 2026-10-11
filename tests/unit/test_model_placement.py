"""A model is placed on the machine it finds: what the card and memory hold now, what the model's
own file says it costs, and a llama.cpp that has shown it can use the card."""

import json
import os
import subprocess
import sys
import types
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from eli_legal.adapters.inference import (
    fit,
    gguf,
    gguf_sizes,
    gpu_runtime,
    hardware,
    load_diagnostics,
)
from eli_legal.adapters.inference.gguf import GgufInference
from eli_legal.adapters.inference.hardware import Hardware
from eli_legal.domain.errors import InferenceUnavailable, InvalidInput
from tests.conftest import real_vram_holders
from tests.gguf_files import MIB, dense_model, experts_model, gguf_file

SRC = Path(__file__).resolve().parents[2] / "src"

# An 8 GB card with the desktop already on it, and a machine with none.
CARD = Hardware(
    cpu_threads=12,
    ram_gb=32.0,
    available_ram_gb=20.0,
    has_gpu=True,
    gpu_name="Test Card 8G",
    gpu_vendor="nvidia",
    gpu_count=1,
    total_vram_mb=8192,
    free_vram_mb=7000,
    vram_measured=True,
)
NO_CARD = Hardware(cpu_threads=8, ram_gb=16.0, available_ram_gb=12.0)
WORKING = 10496


def _plan(path, hw=CARD, **kw):
    kw.setdefault("gpu_offload", hw.has_gpu)
    kw.setdefault("working_ctx", WORKING)
    return fit.plan(path, hw, **kw)


# ── what a model costs, from its own file ────────────────────────────────────


def test_a_model_s_costs_are_read_from_its_own_file(tmp_path):
    path = dense_model(tmp_path / "m.gguf", blocks=28, block_mib=150, embedding_mib=300)
    cost = fit.model_cost(path)
    assert cost.blocks == 28 and cost.slots == 29
    # 4 KV heads of 128 on 28 layers, keys and values, two bytes each: 56 KiB a token
    assert cost.kv_bytes_per_token == 56 * 1024 and cost.kv_source == "estimated"
    assert gguf_sizes.trained_context(path) == 32768
    # the embedding lookups never go to the card; the output head goes last
    assert cost.gpu_weights_mb(28) == 28 * 150
    assert cost.gpu_weights_mb(29) == 28 * 150 + 300
    assert cost.cpu_weights_mb(29) == 300
    tied = fit.model_cost(dense_model(tmp_path / "t.gguf", tied=True))
    assert tied.weights.output_bytes == 300 * MIB, "tied embeddings: the output is a copy"
    assert fit.model_cost(tmp_path / "missing.gguf") is None


def test_llama_cpp_s_own_report_replaces_the_estimate(tmp_path):
    path = dense_model(tmp_path / "m.gguf")
    line = "llama_kv_cache: size = 448.00 MiB (  4096 cells,  28 layers,  1/1 seqs), K (f16):  224.00 MiB, V (f16):  224.00 MiB\n"
    assert gguf_sizes.record_load_report(path, [line]) == (28672, 28672)
    cost = fit.model_cost(path)
    assert cost.kv_source == "measured" and cost.kv_bytes_per_token == 112 * 1024
    assert json.loads((tmp_path / "runtime" / "model_sizes.json").read_text())
    assert gguf_sizes.record_load_report(path, ["nothing about the cache\n"]) is None


# ── what the machine has ─────────────────────────────────────────────────────


def _answers(monkeypatch, answers: dict[str, str], smi: str | None = "/usr/bin/nvidia-smi"):
    monkeypatch.setattr(hardware, "nvidia_smi_path", lambda: smi)
    monkeypatch.setattr(
        hardware,
        "_run",
        lambda args, timeout: next((v for k, v in answers.items() if k in " ".join(args)), ""),
    )
    monkeypatch.setattr(hardware, "_memory_bytes", lambda: (32 * 1024**3, 20 * 1024**3))
    monkeypatch.setattr(hardware, "vulkan_loader_present", lambda: True)


def test_free_graphics_memory_is_read_from_the_driver_not_taken_from_the_card_s_size(monkeypatch):
    _answers(
        monkeypatch,
        {"query-gpu": "Card A, 8192, 1200\nCard B, 24576, 20000\n"},
    )
    hw = hardware._detect()
    assert hw.has_gpu and hw.gpu_vendor == "nvidia" and hw.vram_measured
    assert (hw.free_vram_mb, hw.total_vram_mb, hw.gpu_count) == (20000, 24576, 2)
    assert "Card B" in hw.gpu_name and "20000 of 24576 MB free" in hw.describe()
    assert round(hw.available_ram_gb) == 20


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the Linux probes")
def test_a_card_that_cannot_be_asked_is_an_estimate_or_unknown_never_a_reading(monkeypatch):
    _answers(monkeypatch, {}, smi=None)
    monkeypatch.setattr(hardware, "_nvidia_driver_loaded", lambda: True)
    monkeypatch.setattr(hardware, "_nvidia_name_from_proc", lambda: "GeForce RTX 2060 SUPER")
    known = hardware._detect()
    assert known.has_gpu and known.total_vram_mb == 8192 and not known.vram_measured
    assert "estimated" in known.describe()
    monkeypatch.setattr(hardware, "_nvidia_name_from_proc", lambda: "A Card Nobody Has Listed")
    unknown = hardware._detect()
    assert not unknown.has_gpu and unknown.uncertain and unknown.free_vram_mb == 0
    assert "could not be read" in unknown.describe()


def test_other_programs_holding_the_card_are_named(monkeypatch):
    _answers(
        monkeypatch,
        {
            "query-compute-apps": "4242, /usr/bin/llama-server --port 1, 5146\n77, /usr/bin/files, 12\n"
        },
    )
    monkeypatch.setattr(
        hardware, "_service_of", lambda pid: "ollama.service" if pid == 4242 else ""
    )
    monkeypatch.setattr(hardware, "Path", _NoKernelCounters)
    found = real_vram_holders()
    assert [h["pid"] for h in found] == [4242, 77]
    said = hardware.describe_vram_holders(found, total_mb=8192)
    assert said == "llama-server (ollama.service, pid 4242) 5146 MB", (
        "a few megabytes are not named"
    )


class _NoKernelCounters(type(Path())):
    """This machine's own per-process graphics counters are not part of the test."""

    def is_dir(self) -> bool:
        return False if "kfd" in str(self) else super().is_dir()


def test_a_system_program_is_not_given_an_installed_copy_s_libraries(monkeypatch, tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(sys, "executable", str(bundle / "eli-legal"))
    monkeypatch.setenv("LD_LIBRARY_PATH", f"{bundle}{os.pathsep}/opt/driver")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/opt/driver")
    env = hardware.host_env()
    assert env["LD_LIBRARY_PATH"] == "/opt/driver" and "LD_LIBRARY_PATH_ORIG" not in env


# ── how the model is placed ──────────────────────────────────────────────────


def test_a_model_that_fits_goes_wholly_on_the_card_with_the_context_the_work_needs(tmp_path):
    path = dense_model(tmp_path / "m.gguf")
    plan = _plan(path)
    assert plan.n_gpu_layers == 29 and plan.on_card == "all 29 layers on the graphics card"
    assert plan.n_ctx == WORKING, "what the work needs, and no more of the card than that"
    assert plan.n_threads == 10 and plan.notes == ()
    cost = fit.model_cost(path)
    assert fit.needed_mb(cost, plan.n_ctx, plan.n_gpu_layers, plan.n_batch) <= 7000 - 700


def test_when_not_everything_fits_layers_give_way_and_the_working_context_stays(tmp_path):
    path = dense_model(tmp_path / "m.gguf")
    tight = replace(CARD, free_vram_mb=4000)
    plan = _plan(path, tight)
    assert plan.n_ctx == WORKING and 0 < plan.n_gpu_layers < 29
    assert "of 29 layers on the graphics card" in plan.on_card
    layers_first = _plan(path, tight, priority="max_gpu")
    assert layers_first.n_gpu_layers > plan.n_gpu_layers and layers_first.n_ctx < WORKING
    assert any("context reduced" in n for n in layers_first.notes)


def test_less_free_memory_never_gives_a_larger_plan_and_every_plan_fits_what_it_was_given(tmp_path):
    path = dense_model(tmp_path / "m.gguf")
    cost = fit.model_cost(path)
    previous = None
    for free in range(8000, 0, -250):
        plan = _plan(path, replace(CARD, free_vram_mb=free))
        if plan.n_gpu_layers > 0:
            needed = fit.needed_mb(cost, plan.n_ctx, plan.n_gpu_layers, plan.n_batch)
            assert needed <= free - 700, f"{free} MB free: planned {needed:.0f} MB"
        if previous is not None:
            assert plan.n_gpu_layers <= previous.n_gpu_layers, f"at {free} MB free"
        previous = plan
    assert previous.n_gpu_layers == 0, "a card with nothing free takes nothing"


def test_the_administrator_s_numbers_are_ceilings_not_instructions_to_overfill(tmp_path):
    path = dense_model(tmp_path / "m.gguf", trained_context=16384)
    assert _plan(path, want_layers=10).n_gpu_layers == 10
    assert _plan(path, want_layers=10, hw=replace(CARD, free_vram_mb=1600)).n_gpu_layers < 10
    assert _plan(path, want_layers=0).n_gpu_layers == 0
    asked = _plan(path, want_ctx=8192)
    assert asked.n_ctx == 8192 and asked.n_gpu_layers == 29
    over = _plan(path, want_ctx=65536)
    assert over.n_ctx == 16384 and any("trained for 16384" in n for n in over.notes)
    assert _plan(path, want_threads=3).n_threads == 3


def test_a_card_with_no_graphics_runtime_runs_the_processor_and_says_why(tmp_path):
    path = dense_model(tmp_path / "m.gguf")
    plan = _plan(path, gpu_offload=False)
    assert plan.n_gpu_layers == 0 and plan.on_card == "processor only"
    assert any("has no graphics support" in n and "Test Card 8G" in n for n in plan.notes)
    assert plan.n_threads == 11, "the processor does the work: one core is left for the desktop"
    assert _plan(path, NO_CARD).notes == ()


def test_on_the_processor_the_context_follows_the_memory_free(tmp_path):
    path = dense_model(tmp_path / "m.gguf")
    assert _plan(path, NO_CARD).n_ctx == WORKING
    small = _plan(path, replace(NO_CARD, ram_gb=8.0, available_ram_gb=5.0))
    assert small.n_ctx == fit.MIN_CTX
    assert any("more than the memory a model may take here" in n for n in small.notes)


def test_a_mixture_of_experts_model_keeps_its_experts_in_memory(tmp_path):
    path = experts_model(tmp_path / "e.gguf")
    plan = _plan(path, expert_offload=True)
    assert plan.experts_in_ram and plan.n_gpu_layers == 41 and plan.n_ctx == WORKING
    assert any("experts (17.6 GB) stay in system memory" in n for n in plan.notes)
    # a llama.cpp that cannot be told where tensors go: whole layers, as many as fit
    plain = _plan(path, expert_offload=False)
    assert not plain.experts_in_ram and 0 < plain.n_gpu_layers < 41
    # not enough memory for the experts either: the same
    assert not _plan(path, replace(CARD, available_ram_gb=6.0), expert_offload=True).experts_in_ram


def test_a_file_that_is_not_gguf_is_given_the_smallest_request_and_nothing_is_assumed(tmp_path):
    path = tmp_path / "zeros.gguf"
    path.write_bytes(b"\0" * 4096)
    plan = _plan(path)
    assert (plan.n_ctx, plan.blocks) == (fit.MIN_CTX, 0)
    assert any("header could not be read" in n for n in plan.notes)


# ── a llama.cpp that can use the card ────────────────────────────────────────

_FAKE_PACK = """
__version__ = "{version}"
class _Native:
    @staticmethod
    def llama_backend_init():
        pass
llama_cpp = _Native
def llama_supports_gpu_offload():
    return {offload}
class Llama:
    pass
"""


def _pack(folder: Path, *, version: str = "9.9.9", offload: bool = True, backend: str = "cuda"):
    (folder / "llama_cpp" / "lib").mkdir(parents=True)
    (folder / "llama_cpp" / "__init__.py").write_text(
        _FAKE_PACK.format(version=version, offload=offload), encoding="utf-8"
    )
    (folder / "llama_cpp" / "lib" / f"libggml-{backend}.so").write_bytes(b"")
    return folder


@pytest.fixture
def no_llama_yet(monkeypatch, tmp_path):
    """A process that has not imported llama.cpp, on a machine with a card and ELI v3's folder."""
    for name in [k for k in sys.modules if k == "llama_cpp" or k.startswith("llama_cpp.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(gpu_runtime, "_state", None)
    monkeypatch.setattr(gpu_runtime, "_builtin", None)
    monkeypatch.setattr(gpu_runtime, "_failed", {})
    monkeypatch.setenv("ELI_LEGAL_GPU", "auto")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "share"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ELI_V3_ROOT", raising=False)
    monkeypatch.setattr(hardware, "detect", lambda force=False: replace(CARD))
    yield tmp_path / "share" / "ELI_v3" / "runtime" / "gpu"
    for name in [k for k in sys.modules if k == "llama_cpp" or k.startswith("llama_cpp.")]:
        sys.modules.pop(name, None)


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS uses the built-in Metal support")
def test_a_graphics_pack_is_switched_on_only_after_it_has_shown_it_can_use_the_card(
    no_llama_yet, monkeypatch
):
    pack_dir = _pack(no_llama_yet)
    found = gpu_runtime.installed()
    assert [(p.origin, p.backend, p.version) for p in found] == [("ELI v3", "cuda", "9.9.9")]

    monkeypatch.setattr(gpu_runtime, "verify", lambda pack, again=False: (False, "it crashed"))
    monkeypatch.setattr(gpu_runtime, "_import_llama", lambda: (_ for _ in ()).throw(ImportError()))
    refused = gpu_runtime._activate()
    assert not refused.available and str(pack_dir.resolve()) not in sys.path
    assert "did not start on this card: it crashed" in refused.notes[0]


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS uses the built-in Metal support")
def test_a_pack_that_passes_is_the_llama_cpp_in_use_and_is_named_with_whose_it_is(no_llama_yet):
    pack_dir = _pack(no_llama_yet)
    module = gpu_runtime.llama()
    assert module is not None and Path(module.__file__).parent == pack_dir.resolve() / "llama_cpp"
    runtime = gpu_runtime.current()
    assert runtime.offload and (runtime.origin, runtime.backend, runtime.version) == (
        "ELI v3",
        "cuda",
        "9.9.9",
    )
    assert runtime.describe() == "llama.cpp 9.9.9 (cuda, ELI v3's): graphics card"
    remembered = json.loads((Path("runtime") / "gpu_verified.json").read_text())
    assert len(remembered) == 1, "a pass is remembered; the next start does not probe again"


def test_the_probe_runs_in_a_process_of_its_own_and_fails_a_pack_that_cannot_place_layers(
    tmp_path,
):
    env = os.environ | {"PYTHONPATH": str(SRC), "ELI_LEGAL_HOME": str(tmp_path / "home")}

    def probe(folder: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "eli_legal", "gpu", "probe", str(folder)],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            check=False,
        )

    good = probe(_pack(tmp_path / "good"))
    assert good.returncode == 0 and gpu_runtime.PROBE_OK + " 9.9.9" in good.stdout, good.stderr
    bad = probe(_pack(tmp_path / "bad", offload=False))
    assert bad.returncode == 2 and gpu_runtime.PROBE_OK not in bad.stdout


def test_in_an_installed_copy_a_pack_of_another_llama_cpp_version_is_refused(monkeypatch, tmp_path):
    pack = gpu_runtime.Pack(tmp_path, "cuda", "0.3.35", "ELI v3")
    assert gpu_runtime._fits_this_copy(pack, "0.3.36") == "", (
        "a source checkout: the pack replaces it whole"
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert "cannot share a process" in gpu_runtime._fits_this_copy(pack, "0.3.36")
    assert gpu_runtime._fits_this_copy(pack, "0.3.35") == ""


def test_a_card_from_another_maker_is_not_offered_the_nvidia_pack(tmp_path):
    packs = [
        gpu_runtime.Pack(tmp_path / "c", "cuda", "1", "ELI v3"),
        gpu_runtime.Pack(tmp_path / "v", "vulkan", "1", "ELI Legal"),
    ]
    assert [p.backend for p in gpu_runtime._order(packs, CARD)] == ["cuda", "vulkan"]
    amd = replace(CARD, gpu_vendor="amd")
    assert [p.backend for p in gpu_runtime._order(packs, amd)] == ["vulkan"]


def _wheel(path: Path, members: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return path


def test_a_pack_is_installed_from_a_file_and_one_that_reaches_outside_itself_is_refused(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(gpu_runtime, "_builtin", "")
    init = _FAKE_PACK.format(version="9.9.9", offload=True)
    name = "vulkan-llama_cpp_python-9.9.9-py3-none-linux_x86_64.whl"
    pack = gpu_runtime.install(_wheel(tmp_path / name, {"llama_cpp/__init__.py": init}))
    assert (pack.backend, pack.version, pack.origin) == ("vulkan", "9.9.9", "ELI Legal")
    manifest = json.loads((gpu_runtime.own_dir() / ".gpu_pack.json").read_text())
    assert manifest["source"] == name and len(manifest["sha256"]) == 64
    assert gpu_runtime.installed()[0].path == pack.path

    (tmp_path / "x").mkdir()
    reaching = _wheel(
        tmp_path / "x" / name, {"../../escaped.py": "x", "llama_cpp/__init__.py": init}
    )
    with pytest.raises(InvalidInput, match="outside itself"):
        gpu_runtime.install(reaching)
    assert not (tmp_path / "escaped.py").exists()
    assert gpu_runtime.installed()[0].version == "9.9.9", "the pack that was there is still there"
    with pytest.raises(InvalidInput, match="a graphics pack is a file named"):
        gpu_runtime.install(_wheel(tmp_path / "something-else.whl", {"a": "b"}))
    wrong = "cuda-llama_cpp_python-1.2.3-py3-none-linux_x86_64.whl"
    (tmp_path / "y").mkdir()
    with pytest.raises(InvalidInput, match="does not hold the llama.cpp version"):
        gpu_runtime.install(_wheel(tmp_path / "y" / wrong, {"llama_cpp/__init__.py": init}))


# ── loading ──────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_llama(monkeypatch):
    """A llama.cpp that records what it is asked for and can refuse a load."""
    calls = {"loads": [], "refuse": lambda kw: None, "reply": {}}

    class Llama:
        def __init__(self, **kw):
            calls["loads"].append(kw)
            problem = calls["refuse"](kw)
            if problem:
                raise RuntimeError(problem)
            self.kw = kw
            self.closed = False

        def n_ctx(self):
            return self.kw["n_ctx"]

        def tokenize(self, raw, add_bos=False, special=False):
            return list(range(len(raw) // 4))

        def close(self):
            self.closed = True

        def create_chat_completion(self, **kw):
            calls["asked"] = kw
            if isinstance(calls["reply"], Exception):
                raise calls["reply"]
            base = {
                "choices": [
                    {"message": {"content": '{"answer": "green"}'}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 6},
            }
            return base | calls["reply"]

    module = types.SimpleNamespace(
        Llama=Llama, llama_supports_gpu_offload=lambda: True, __version__="0.0-test"
    )
    monkeypatch.setitem(sys.modules, "llama_cpp", module)
    monkeypatch.setattr(gguf, "_LOADED", {})
    monkeypatch.setattr(gpu_runtime, "_state", None)
    monkeypatch.setattr(hardware, "detect", lambda force=False: replace(CARD))
    return calls


def test_the_model_is_loaded_as_placed_and_what_loaded_is_what_is_reported(tmp_path, fake_llama):
    model = GgufInference(dense_model(tmp_path / "m.gguf"), working_ctx=WORKING)
    seen = []
    model.on_load = seen.append
    assert model.report is None, "nothing is loaded until it is used"
    assert model.generate(system="s", prompt="p", json_mode=True) == '{"answer": "green"}'
    asked = fake_llama["loads"][0]
    assert (asked["n_ctx"], asked["n_gpu_layers"], asked["n_batch"]) == (WORKING, 29, 512)
    report = model.report
    assert seen == [report] and report.n_ctx == WORKING
    assert (report.layers_on_card, report.layers_total) == (29, 29)
    assert report.describe().startswith(
        f"{WORKING} tokens of context, all 29 layers on the graphics card, llama.cpp 0.0-test"
    )
    GgufInference(dense_model(tmp_path / "m.gguf"), working_ctx=WORKING).generate(
        system="s", prompt="p"
    )
    assert len(fake_llama["loads"]) == 1, "the same file with the same settings is loaded once"
    assert model.context_tokens() == WORKING and model.count_tokens("x" * 40) == 10 + 20


def test_a_load_llama_cpp_refuses_is_planned_again_with_more_room_then_on_the_processor(
    tmp_path, fake_llama
):
    fake_llama["refuse"] = lambda kw: (
        "CUDA error: out of memory" if kw["n_gpu_layers"] > 20 else None
    )
    model = GgufInference(dense_model(tmp_path / "m.gguf"), working_ctx=WORKING)
    report = model.warm()
    tried = [kw["n_gpu_layers"] for kw in fake_llama["loads"]]
    assert tried[0] == 29 and tried == sorted(tried, reverse=True) and 0 < tried[-1] <= 20
    assert report.layers_on_card == tried[-1]
    assert any("refused" in n for n in report.notes), "what was tried is part of the report"

    fake_llama["refuse"] = lambda kw: "no memory" if kw["n_gpu_layers"] > 0 else None
    gguf.release()
    on_processor = GgufInference(dense_model(tmp_path / "n.gguf"), working_ctx=WORKING).warm()
    assert on_processor.layers_on_card == 0 and on_processor.describe().count("processor only")


def test_a_file_llama_cpp_cannot_read_is_not_tried_again_smaller(tmp_path, fake_llama, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def said(module):
        yield ["llama_model_load: error loading model: unknown model architecture: 'future9'\n"]

    monkeypatch.setattr(load_diagnostics, "capture", said)
    fake_llama["refuse"] = lambda kw: "Failed to load model from file"
    model = GgufInference(dense_model(tmp_path / "m.gguf"), working_ctx=WORKING)
    with pytest.raises(InferenceUnavailable, match="does not support its architecture"):
        model.warm()
    assert len(fake_llama["loads"]) == 1


def test_a_model_no_longer_chosen_gives_its_memory_back(tmp_path, fake_llama):
    first = GgufInference(dense_model(tmp_path / "a.gguf"), working_ctx=WORKING)
    second = GgufInference(dense_model(tmp_path / "b.gguf"), working_ctx=WORKING)
    first.warm(), second.warm()
    kept = gguf._LOADED[second._key].llm
    dropped = gguf._LOADED[first._key].llm
    gguf.release({second.path})
    assert dropped.closed and not kept.closed and first.report is None and second.report


def test_a_reply_cut_off_or_material_that_does_not_fit_is_said_in_plain_words(tmp_path, fake_llama):
    model = GgufInference(dense_model(tmp_path / "m.gguf"), working_ctx=WORKING)
    fake_llama["reply"] = {
        "choices": [{"message": {"content": '{"sentences": [{"te'}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 9000, "completion_tokens": 700},
    }
    with pytest.raises(InferenceUnavailable, match="reply was cut off after 700 tokens"):
        model.generate(system="s", prompt="p", max_tokens=700, json_mode=True)
    fake_llama["reply"] = ValueError("Requested tokens (12000) exceed context window of 10496")
    with pytest.raises(InferenceUnavailable, match="does not fit the 10496 tokens of context"):
        model.generate(system="s", prompt="p", json_mode=True)


# ── the application ──────────────────────────────────────────────────────────


def test_each_step_states_what_it_needs_and_the_working_context_covers_the_largest():
    from eli_legal.legal import llm
    from eli_legal.legal.frameworks import MAX_CONTEXT_CHARS

    need = llm.working_context_tokens()
    assert set(llm._STEP_NEEDS) == {
        "fact_select",
        "issue_propose",
        "fact_issue_link",
        "arguments",
        "support_check",
    }
    system = len(llm.SYSTEM_BASE) + MAX_CONTEXT_CHARS
    for chars, reply in llm._STEP_NEEDS.values():
        assert need >= (system + chars) / llm.CHARS_PER_TOKEN + reply - 1
    assert fit.MIN_CTX < need < 32768


def test_the_model_is_told_to_write_literally_and_the_change_is_on_every_run_s_record():
    from eli_legal.legal import llm

    assert llm.REGISTER in llm.SYSTEM_BASE and llm.SYSTEM_BASE.endswith(
        "Answer with a single JSON object and nothing else."
    )
    for word in ("literally", "No greeting", "no opinion", "no feeling", "nothing about yourself"):
        assert word in llm.REGISTER
    assert llm.PROMPT_VERSIONS["system"] == "system/2"


def test_automatic_is_the_default_and_a_context_is_nought_or_a_real_length(demo):
    from eli_legal.settings import Settings

    fresh = Settings(_env_file=None)
    assert (fresh.gguf_context, fresh.gguf_gpu_layers, fresh.gguf_threads) == (0, -1, 0)
    sv, _mid = demo
    with pytest.raises(InvalidInput, match="0 .sized to the model and this machine. or between"):
        sv.config.set_model(actor_id="admin", backend="none", gguf_context=512)


def test_each_load_is_recorded_as_llama_cpp_reported_it(tmp_path, fake_llama):
    from eli_legal.application.services import build_services
    from eli_legal.demo import build_demo_workspace
    from eli_legal.demo_run import demo_settings

    path = dense_model(tmp_path / "m.gguf")
    workspace = build_demo_workspace(tmp_path / "demo")
    settings = demo_settings(tmp_path, workspace, inference="gguf", inference_model=str(path))
    sv = build_services(settings, install_network_guard=False)
    assert sv.config.loaded() == {"model": {}, "verifier": {}}
    assert sv.ctx.model.ask("probe", "p") == {"answer": "green"}
    event = [e for e in sv.ctx.audit.events() if e["event_type"] == "model_loaded"][-1]
    assert event["actor_id"] == "system" and event["model_id"].startswith("gguf:m.gguf@")
    assert event["payload"]["layers_on_card"] == 29 and event["payload"]["n_ctx"] > fit.MIN_CTX
    loaded = sv.config.loaded()["model"]
    assert loaded["summary"].startswith(f"{loaded['n_ctx']} tokens of context, all 29 layers")
    machine = sv.config.machine()
    assert machine["hardware"]["gpu_name"] == "Test Card 8G" and str(tmp_path) not in json.dumps(
        machine
    )
    preview = sv.config.preview(str(path), gguf_gpu_layers=0)
    assert preview["summary"].endswith("processor only") and str(tmp_path) not in json.dumps(
        preview
    )


def test_chat_gives_the_model_the_sources_that_fit_and_says_which_it_did_not_draw_on(held_run):
    from eli_legal.demo_run import ARBITRATOR
    from eli_legal.legal.llm import LegalModel
    from tests.conftest import FakeInference

    class Windowed(FakeInference):
        """A model whose context holds the system message and about one source."""

        window = 0

        def context_tokens(self) -> int:
            return self.window

        def count_tokens(self, text: str) -> int:
            return len(text) // 4

    sv, mid, rid = held_run
    question = "when was the notice of termination received?"
    model = Windowed({"chat_answer": {"sentences": []}})
    sv.ctx.model = LegalModel(model)
    whole = sv.chat.ask(mid, actor_id=ARBITRATOR, question=question, run_id=rid)
    usable = [s for s in whole.sources if s.usable]
    assert len(usable) >= 3, "the question matches several passages"
    model.window = 10**6
    sv.chat.ask(mid, actor_id=ARBITRATOR, question=question, run_id=rid)
    assert all(f"\n{s.label} [" in model.prompts[-1] for s in usable)

    system = len(model.systems[-1]) // 4  # with the law and standards that apply to the matter
    model.window = system + 700 + (len(model.prompts[-1]) // 4) // 2
    trimmed = sv.chat.ask(mid, actor_id=ARBITRATOR, question=question, run_id=rid)
    shown = [s.label for s in usable if f"\n{s.label} [" in model.prompts[-1]]
    assert 0 < len(shown) < len(usable) and shown == [s.label for s in usable[: len(shown)]]
    note = next(n for n in trimmed.notes if "model's context holds" in n)
    assert f"{len(shown)} of the {len(usable)} sources" in note and usable[-1].label in note
    assert len(trimmed.sources) == len(whole.sources), "every source is still shown to the person"


def test_a_failed_summary_says_why_in_the_model_runner_s_words(held_run):
    from eli_legal.demo_run import ARBITRATOR
    from eli_legal.legal.llm import LegalModel
    from tests.conftest import FakeInference

    class Failing(FakeInference):
        def generate(self, **kw):
            raise InferenceUnavailable("m.gguf's reply was cut off after 700 tokens")

    sv, mid, rid = held_run
    sv.ctx.model = LegalModel(Failing())
    answer = sv.chat.ask(
        mid, actor_id=ARBITRATOR, question="when was the notice received?", run_id=rid
    )
    assert answer.mode == "passages" and answer.sources
    assert any(
        "(m.gguf's reply was cut off after 700 tokens); showing the sources" in n
        for n in answer.notes
    )


def test_a_small_shape_is_not_mistaken_for_a_large_one(tmp_path):
    """The planner knows no model by name or size class: a tiny file of an unusual shape is
    placed by its own header like any other."""
    path = gguf_file(
        tmp_path / "tiny.gguf",
        "novel",
        {
            "block_count": 3,
            "context_length": 1024,
            "embedding_length": 64,
            "attention.head_count": 2,
        },
        {
            "token_embd.weight": MIB,
            "blk.0.w": MIB,
            "blk.1.w": MIB,
            "blk.2.w": MIB,
            "output.weight": MIB,
        },
    )
    plan = _plan(path)
    assert plan.n_ctx == 1024, "trained for 1024: neither the working context nor the usual floor"
    assert plan.n_gpu_layers == 4 and plan.on_card == "all 4 layers on the graphics card"


def test_installing_a_graphics_runtime_is_an_administrator_s_recorded_decision(
    demo, tmp_path, monkeypatch
):
    from eli_legal.domain.errors import PolicyDenied

    sv, _mid = demo
    monkeypatch.setattr(gpu_runtime, "_builtin", "")
    monkeypatch.setattr(gpu_runtime, "verify", lambda pack, again=False: (True, "ok"))
    name = "vulkan-llama_cpp_python-9.9.9-py3-none-linux_x86_64.whl"
    wheel = _wheel(
        tmp_path / name,
        {"llama_cpp/__init__.py": _FAKE_PACK.format(version="9.9.9", offload=True)},
    )
    with pytest.raises(PolicyDenied):
        sv.config.install_gpu_runtime(actor_id="arb.keane", wheel=wheel)
    assert not gpu_runtime.installed(), "nothing was unpacked for someone not permitted"
    done = sv.config.install_gpu_runtime(actor_id="admin", wheel=wheel)
    assert done["usable"] and "used from the next start" in done["summary"]
    event = [e for e in sv.ctx.audit.events() if e["event_type"] == "configuration_changed"][-1]
    assert event["subject_id"] == "inference_runtime" and event["outcome"] == "installed"
    assert event["payload"]["file"] == name and len(event["payload"]["sha256"]) == 64


def test_the_pack_an_installer_ships_is_the_built_in_llama_cpp_s_version_and_is_checked():
    """One file names the llama.cpp version; the build pins to it and checks each pack against
    its checksum. A pack of another version could not be used by an installed copy at all."""
    root = Path(__file__).resolve().parents[2]
    packs = json.loads((root / "packaging" / "gpu_packs.json").read_text(encoding="utf-8"))
    version = packs["llama_cpp_python"]
    for pack in packs["shipped"].values():
        named = gpu_runtime._WHEEL_NAME.match(pack["file"])
        assert named and named.group(1) == "vulkan" and named.group(2) == version
        assert len(pack["sha256"]) == 64 and int(pack["sha256"], 16) >= 0
    workflow = (root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    pinned = 'pip install "llama-cpp-python==$(python scripts/fetch_gpu_pack.py --version)"'
    assert workflow.count(pinned) == 3 and "llama-cpp-python>=" not in workflow
    assert workflow.count("- run: python scripts/fetch_gpu_pack.py\n") == 2, "Linux and Windows"
    spec = (root / "packaging" / "pyinstaller" / "eli_legal.spec").read_text(encoding="utf-8")
    assert 'copy_metadata("llama-cpp-python")' in spec and '"gpu-packs"' in spec
    # from the frozen archive the built-in copy would always be the one imported
    assert 'module_collection_mode={"llama_cpp": "py"}' in spec
    out = subprocess.run(
        [sys.executable, str(root / "scripts" / "fetch_gpu_pack.py"), "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == version
