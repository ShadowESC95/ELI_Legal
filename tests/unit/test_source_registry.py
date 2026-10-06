import pytest

from eli_legal.domain.errors import PolicyDenied
from eli_legal.legal.source_registry import RegisteredSource, SourceRegistry


def test_unapproved_source_rejected():
    r = SourceRegistry([RegisteredSource("s1", "x", False, frozenset({"IE"}), "none")])
    with pytest.raises(PolicyDenied):
        r.require_approved("s1", "IE")
