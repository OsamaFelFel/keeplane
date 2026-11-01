"""Django identities, role restrictions and infrastructure credential rotation."""

import pytest
from accounts.contracts import IdentityError, public_user
from accounts.models import User
from accounts.services import DjangoIdentity


def test_acct_21_fresh_install_first_admin_signs_in_as_managed_break_glass(
    domain_services,
):
    identity = domain_services.identity
    assert list(User.objects.values_list("username", "role")) == [
        ("first-admin", "admin")
    ]
    user = identity.session(identity.login("first-admin", "first-test-password-123"))
    assert user["role"] == "admin"
    listed = identity.users({"search": ["first-admin"]})["users"]
    assert listed == [public_user(user)]
    assert listed[0]["managed"] is True
    assert listed[0]["sign_in"] == "break-glass"


def test_acct_22_rotation_preserves_identity_and_revokes_sessions(domain_services):
    service = domain_services
    token = service.identity.login("first-admin", "first-test-password-123")
    original = service.identity.session(token)
    service.secret.write_text("rotated-first-test-password-456\n")
    rotated = DjangoIdentity(service.secret, service.audit)
    assert rotated.session(token) is None
    with pytest.raises(IdentityError, match="Invalid username"):
        rotated.login("first-admin", "first-test-password-123")
    token = rotated.login("first-admin", "rotated-first-test-password-456")
    assert rotated.session(token)["id"] == original["id"]


def test_acct_17_infrastructure_admin_cannot_be_changed_or_removed(domain_services):
    identity = domain_services.identity
    token = identity.login("first-admin", "first-test-password-123")
    user = identity.session(token)
    for change in (
        lambda: identity.change_role(user["id"], "developer"),
        lambda: identity.delete_user(user["id"]),
    ):
        with pytest.raises(IdentityError) as error:
            change()
        assert error.value.status == 403
    assert identity.session(token) == user
