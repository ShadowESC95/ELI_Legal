import pytest

from eli_legal.domain.errors import MatterAccessDenied, PolicyDenied
from eli_legal.domain.models import Matter
from eli_legal.security.authorizer import MatterAuthorizer
from eli_legal.security.rbac import ROLE_SOLICITOR, RoleBindings


def test_role_and_matter_membership_are_both_required():
    matter = Matter(name="M", purpose="ADR", jurisdiction="IE", owner_user_id="owner")
    matter.authorised_user_ids.add("sol1")
    bindings = RoleBindings()
    bindings.bind("sol1", ROLE_SOLICITOR)
    MatterAuthorizer(bindings).require_matter(matter, "sol1", "document.read")


def test_role_without_matter_membership_is_denied():
    matter = Matter(name="M", purpose="ADR", jurisdiction="IE", owner_user_id="owner")
    bindings = RoleBindings()
    bindings.bind("outsider", ROLE_SOLICITOR)
    with pytest.raises(MatterAccessDenied):
        MatterAuthorizer(bindings).require_matter(matter, "outsider", "document.read")


def test_matter_membership_without_role_permission_is_denied():
    matter = Matter(name="M", purpose="ADR", jurisdiction="IE", owner_user_id="owner")
    matter.authorised_user_ids.add("reader")
    bindings = RoleBindings(user_roles={"reader": {"unknown"}})
    with pytest.raises(PolicyDenied):
        MatterAuthorizer(bindings).require_matter(matter, "reader", "document.read")
