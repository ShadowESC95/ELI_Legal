import pytest

from eli_legal.domain.errors import MatterAccessDenied
from eli_legal.domain.models import Matter
from eli_legal.security.matter_guard import require_matter_access


def test_cross_matter_access_denied():
    m = Matter(name="A", purpose="ADR", jurisdiction="IE", owner_user_id="owner")
    with pytest.raises(MatterAccessDenied):
        require_matter_access(m, "other")
