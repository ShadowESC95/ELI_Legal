import pytest

from eli_legal.domain.errors import PolicyDenied
from eli_legal.domain.policy import RuntimePolicy


def test_prohibited_general_shell():
    p = RuntimePolicy(frozenset({"report.draft"}), frozenset({"shell.general"}))
    with pytest.raises(PolicyDenied):
        p.require_action("shell.general")
