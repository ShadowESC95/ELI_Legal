"""ELI Legal as an edition ELI v3 can load. The contract is checked here against a stand-in for
v3's own loader, and against a real v3 checkout when ELI_V3_ROOT points at one."""

import ast
import json
import os
from importlib import metadata
from pathlib import Path

import pytest

from eli_legal import edition
from eli_legal.adapters.eli_v3.compat import ALLOWED_HOST_MODULES, EliV3Unavailable, import_attr
from eli_legal.demo_run import ARBITRATOR, SECRETARY
from eli_legal.domain.errors import EliLegalError, EntitlementDenied
from eli_legal.edition import policy
from eli_legal.edition.capabilities import CAPABILITIES, DECISIONS_NOT_EXPOSED, dispatch

SRC = Path(edition.__file__).resolve().parents[1]
# The fields ELI v3's edition loader reads from a pack's manifest.
V3_MANIFEST_FIELDS = {
    "edition",
    "label",
    "status",
    "summary",
    "default_persona",
    "adds_capability_categories",
    "report_templates",
    "policy_module",
    "requires_core",
    "suggested_tiers",
}

V3_LOADER_STANDIN = """
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
_EDITIONS_DIR = Path(__file__).resolve().parent

@dataclass(frozen=True)
class Edition:
    pkg: str
    name: str
    label: str
    status: str
    summary: str
    default_persona: str
    capability_categories: tuple[str, ...]
    report_templates: tuple[str, ...]
    policy_module: str
    suggested_tiers: tuple[str, ...]
    manifest: dict[str, Any]

def _load(manifest_path: Path):
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    pkg = manifest_path.parent.name
    return Edition(pkg=pkg, name=str(m.get("edition") or pkg), label=str(m.get("label") or pkg.title()),
        status=str(m.get("status") or "scaffold"), summary=str(m.get("summary") or ""),
        default_persona=str(m.get("default_persona") or "eli_neutral"),
        capability_categories=tuple(m.get("adds_capability_categories") or ()),
        report_templates=tuple(m.get("report_templates") or ()),
        policy_module=str(m.get("policy_module") or f"eli.editions.{pkg}.policy"),
        suggested_tiers=tuple(m.get("suggested_tiers") or ()), manifest=m)

def discover_editions():
    out = {}
    for child in sorted(_EDITIONS_DIR.iterdir()):
        if child.is_dir() and (child / "manifest.json").exists():
            ed = _load(child / "manifest.json")
            out[ed.name] = ed
    return out
"""


def _fake_eli(tmp_path: Path) -> Path:
    root = tmp_path / "ELI_v3"
    editions = root / "eli" / "editions"
    (editions / "legal").mkdir(parents=True)
    (editions / "base").mkdir()
    (editions / "__init__.py").write_text(V3_LOADER_STANDIN, encoding="utf-8")
    (editions / "legal" / "manifest.json").write_text(
        json.dumps({"edition": "legal", "status": "scaffold"}), encoding="utf-8"
    )
    (editions / "legal" / "policy.py").write_text(
        "def blocked_actions():\n    return set()\n", encoding="utf-8"
    )
    (editions / "base" / "policy.py").write_text(
        "def system_prompt_addendum():\n    return ''\n\ndef output_disclaimer():\n    return None\n\ndef blocked_actions():\n    return set()\n",
        encoding="utf-8",
    )
    return root


def test_manifest_has_every_field_the_host_loader_reads():
    manifest = edition.manifest()
    assert V3_MANIFEST_FIELDS <= set(manifest)
    assert (
        manifest["edition"] == "legal" and manifest["policy_module"] == "eli_legal.edition.policy"
    )
    assert manifest["capabilities"] == [c.name for c in CAPABILITIES]
    assert manifest["isolation"]["decisions_exposed_to_host"] is False


def test_the_package_advertises_itself_to_eli_through_an_entry_point():
    entries = {e.name: e.value for e in metadata.entry_points(group="eli.editions")}
    assert entries.get("legal") == "eli_legal.edition:register"


def test_policy_hooks_have_the_shape_the_host_calls():
    assert "LEGAL_" in policy.system_prompt_addendum()
    assert "does not give legal advice" in policy.output_disclaimer()
    assert isinstance(policy.blocked_actions(), set)


def test_everything_but_conversation_and_status_is_refused_while_legal_is_active():
    blocked = policy.blocked_actions()
    for action in (
        "RUN_CMD",
        "SHELL_EXEC",
        "COMPUTER_USE",
        "KEYBOARD",
        "MOUSE_CONTROL",
        "SCREENSHOT",
        "READ_FILE",
        "LIST_DIR",
        "WRITE_DOCUMENT",
        "DATA_FABRICATOR",
        "WEB_SEARCH",
        "OPEN_URL",
        "MCP_CALL",
        "PLUGIN_INSTALL",
        "MEMORY_STORE",
        "MEMORY_RECALL",
        "PROACTIVE_START",
        "SELF_PATCH",
        "SELF_IMPROVE",
        "LORA_TRAIN",
        "SCHEDULE_TASK",
    ):
        assert action in blocked, action
    assert not blocked & policy.ALLOWED_HOST_ACTIONS
    assert "SOMETHING_THE_HOST_ADDS_NEXT_YEAR" in policy.blocked_actions(
        {"CHAT", "SOMETHING_THE_HOST_ADDS_NEXT_YEAR", "LEGAL_STATUS"}
    )
    assert (
        policy.is_allowed("LEGAL_RUN_STATUS")
        and policy.is_allowed("CHAT")
        and not policy.is_allowed("RUN_CMD")
    )


def test_no_decision_can_be_taken_through_a_host_capability():
    names = {c.name for c in CAPABILITIES}
    assert all(n.startswith("LEGAL_") for n in names)
    for word in (
        "APPROVE",
        "REVIEW",
        "RESOLVE",
        "VERIFY_CLAIM",
        "RELEASE",
        "SEND",
        "RESUME",
        "RESTART",
        "CLOSE",
        "WAIVE",
        "EXCLUDE",
    ):
        assert not any(word in n for n in names), word
    assert DECISIONS_NOT_EXPOSED


def test_the_adapters_may_import_three_host_modules_and_nothing_else():
    assert ALLOWED_HOST_MODULES == {
        "eli.cognition.gguf_inference",
        "eli.core.netguard",
        "eli.tools.registry.capability_registry",
    }
    with pytest.raises(EliV3Unavailable, match="may not import"):
        import_attr("eli.kernel.engine", "Engine")
    imported: set[str] = set()
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported |= {
                    a.name for a in node.names if a.name == "eli" or a.name.startswith("eli.")
                }
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and (node.module == "eli" or node.module.startswith("eli."))
            ):
                imported.add(node.module)
            elif (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "import_attr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                imported.add(str(node.args[0].value))
    assert imported <= ALLOWED_HOST_MODULES, imported - ALLOWED_HOST_MODULES


def test_runs_standalone_with_no_eli_installed(lifecycle):
    import importlib.util

    assert importlib.util.find_spec("eli") is None, (
        "these tests are meant to run without ELI present"
    )
    assert lifecycle.final_status == "approved_for_reliance"


def test_activation_is_refused_when_the_licence_does_not_include_the_edition(held_run):
    sv, _mid, _rid = held_run
    with pytest.raises(EntitlementDenied):
        edition.register(object(), entitled={"general", "research"}, services=sv)
    assert (
        edition.register(object(), entitled={"general", "legal"}, services=sv)["edition"] == "legal"
    )
    assert edition.register(object(), entitled={"enterprise"}, services=sv)["capabilities"]
    assert (
        edition.register(None, services=sv)["contract_version"] == 1
    )  # standalone: host did not say


def test_capabilities_act_as_a_named_user_and_return_no_document_content(held_run):
    sv, mid, rid = held_run
    registered = edition.register(object(), entitled={"legal"}, services=sv)
    handlers = registered["handlers"]
    assert handlers["LEGAL_RUN_STATUS"]({"matter_id": mid, "run_id": rid})["error"] == "no_actor"
    status = handlers["LEGAL_RUN_STATUS"]({"user_id": ARBITRATOR, "matter_id": mid, "run_id": rid})
    assert status["ok"] and status["status"] == "held" and status["open_holds"] >= 5
    outsider = handlers["LEGAL_RUN_STATUS"]({"user_id": "admin", "matter_id": mid, "run_id": rid})
    assert not outsider["ok"] and outsider["error"] == "MatterAccessDenied"
    assert not handlers["LEGAL_AUDIT_VERIFY"]({"user_id": SECRETARY})["ok"], (
        "role checks apply to capabilities too"
    )
    outputs = [
        handlers[c.name]({"user_id": ARBITRATOR, "matter_id": mid, "run_id": rid})
        for c in CAPABILITIES
        if c.name not in {"LEGAL_MATTER_CREATE", "LEGAL_INGEST", "LEGAL_RUN_START"}
    ]
    text = json.dumps(outputs)
    for content in ("Aldergate", "containers", "Okafor", "€184,500"):
        assert content not in text, f"capability output leaked matter content: {content}"
    assert dispatch(sv, "LEGAL_APPROVE", ARBITRATOR, {})["error"] == "unknown_capability"


def test_install_writes_a_three_file_shim_and_backs_up_what_it_replaces(tmp_path):
    root = _fake_eli(tmp_path)
    with pytest.raises(EliLegalError, match="--force"):
        edition.install_into_eli(root)
    written = edition.install_into_eli(root, force=True)
    target = root / "eli" / "editions" / "legal"
    assert {p.name for p in written} == {"manifest.json", "__init__.py", "policy.py"}
    backups = list(target.glob(".replaced_*"))
    assert (
        len(backups) == 1
        and json.loads((backups[0] / "manifest.json").read_text(encoding="utf-8"))["status"]
        == "scaffold"
    )
    assert "from eli_legal.edition import register" in (target / "__init__.py").read_text(
        encoding="utf-8"
    )
    with pytest.raises(EliLegalError, match="no ELI edition registry"):
        edition.install_into_eli(tmp_path / "not_eli")


def test_the_host_loader_reads_the_installed_shim(tmp_path):
    import importlib.util

    root = _fake_eli(tmp_path)
    edition.install_into_eli(root, force=True)
    spec = importlib.util.spec_from_file_location(
        "fake_eli_editions", root / "eli" / "editions" / "__init__.py"
    )
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        legal = module.discover_editions()["legal"]
    finally:
        del sys.modules[spec.name]
    assert (legal.status, legal.policy_module) == ("beta", "eli_legal.edition.policy")
    assert legal.report_templates == (
        "Bench Memorandum",
        "Mediation Brief",
        "Case Preparation Memorandum",
    )
    lines = edition.verify_against_eli(root)
    assert not [
        line for line in lines if line.startswith("FAIL") and "host provides" not in line
    ], lines


@pytest.mark.skipif(
    not os.environ.get("ELI_V3_ROOT"),
    reason="set ELI_V3_ROOT to check against a real ELI v3 checkout",
)
def test_against_a_real_eli_v3_checkout():
    lines = edition.verify_against_eli(os.environ["ELI_V3_ROOT"])
    assert not [line for line in lines if line.startswith("FAIL")], "\n".join(lines)
