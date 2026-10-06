import json
from pathlib import Path


def test_personal_assistant_capabilities_are_prohibited():
    policy = json.loads(Path("config/policy.default.json").read_text())
    prohibited = set(policy["prohibited_actions"])
    assert {"shell.general", "desktop.control", "personal_memory", "self_modify"} <= prohibited
