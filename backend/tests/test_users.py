"""
tests/test_users.py

Covers GET /users/me, and the admin-only user management endpoints
(list/create/change-password/deactivate), including role-based access
control (RBAC) — a SCIENTIST must be forbidden from admin actions.
"""
import uuid

import pytest

from app.core.security import create_access_token

pytestmark = pytest.mark.asyncio


def _auth_header(user_id) -> dict:
    token = create_access_token(subject=str(user_id))
    return {"Authorization": f"Bearer {token}"}


async def test_users_me_returns_current_profile(client, make_user):
    """A logged-in user can fetch their own profile via /users/me."""
    user, _ = await make_user(username="gina")

    resp = await client.get("/api/v1/users/me", headers=_auth_header(user.id))

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["username"] == "gina"


async def test_users_me_rejects_unknown_user_id(client):
    """A structurally-valid JWT for a user that doesn't exist must be rejected."""
    fake_id = uuid.uuid4()
    resp = await client.get("/api/v1/users/me", headers=_auth_header(fake_id))
    assert resp.status_code == 401


async def test_scientist_cannot_list_users(client, make_user):
    """RBAC: a SCIENTIST-role user must be forbidden from the admin-only list endpoint."""
    from app.models.user import UserRole

    user, _ = await make_user(username="harry", role=UserRole.SCIENTIST)

    resp = await client.get("/api/v1/users", headers=_auth_header(user.id))
    assert resp.status_code == 403


async def test_admin_can_list_users(client, make_user):
    """RBAC: an ADMIN-role user can access the admin-only list endpoint."""
    from app.models.user import UserRole

    admin, _ = await make_user(username="irene_admin", role=UserRole.ADMIN)

    resp = await client.get("/api/v1/users", headers=_auth_header(admin.id))
    assert resp.status_code == 200


async def test_scientist_cannot_deactivate_users(client, make_user):
    """RBAC: a SCIENTIST must not be able to deactivate another user's account."""
    from app.models.user import UserRole

    actor, _ = await make_user(username="jack", role=UserRole.SCIENTIST)
    target, _ = await make_user(username="kim", role=UserRole.SCIENTIST)

    resp = await client.delete(
        f"/api/v1/users/{target.id}", headers=_auth_header(actor.id)
    )
    assert resp.status_code == 403
