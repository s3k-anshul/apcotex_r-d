"""
tests/test_auth.py

Implements the AUTH-00x test cases from
qa-audit/02_test-cases/backend/AUTH-test-cases.md against the real
FastAPI app (in-process, isolated in-memory DB — no external services hit).
"""
import pytest

pytestmark = pytest.mark.asyncio


async def test_auth_001_valid_login_returns_tokens(client, make_user):
    """AUTH-001: valid credentials return an access + refresh token."""
    user, password = await make_user(username="alice", password="s3cure-pass!")

    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": password},
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"


async def test_auth_002_wrong_password_rejected(client, make_user):
    """AUTH-002: correct username, wrong password -> 401, no token issued."""
    await make_user(username="bob", password="correct-password")

    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "bob", "password": "wrong-password"},
    )

    assert resp.status_code == 401
    assert "access_token" not in resp.text


async def test_auth_003_unknown_user_rejected_without_enumeration(client):
    """
    AUTH-003: logging in as a user that doesn't exist should fail the same
    way as a wrong password (401), not leak via a different status code or
    error message that would let an attacker enumerate valid usernames.
    """
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "does-not-exist", "password": "whatever"},
    )
    assert resp.status_code == 401


async def test_auth_004_refresh_issues_new_access_token(client, make_user):
    """AUTH-004: a valid refresh token can be exchanged for a new access token."""
    user, password = await make_user(username="carol", password="another-pass")

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "carol", "password": password},
    )
    refresh_token = login_resp.json()["data"]["refresh_token"]

    refresh_resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert refresh_resp.status_code == 200
    assert "access_token" in refresh_resp.json()["data"]


async def test_auth_005_expired_or_missing_token_rejected_on_protected_route(client):
    """AUTH-005 (partial — missing token case): protected routes require auth."""
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code in (401, 403)


async def test_auth_006_brute_force_login_is_not_rate_limited(client, make_user):
    """
    AUTH-006: documents the current gap identified in the security findings —
    there is no rate limiting on /login. This test currently asserts the
    KNOWN-BAD behavior (all attempts return 401, none get throttled to 429)
    so that once rate limiting is implemented, this test will start failing
    and needs to be flipped to assert 429 kicks in after N attempts.
    """
    await make_user(username="dave", password="real-password")

    statuses = []
    for _ in range(20):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "dave", "password": "wrong-guess"},
        )
        statuses.append(resp.status_code)

    # TODO: once rate limiting is added, change this to
    # `assert 429 in statuses`
    assert all(s == 401 for s in statuses), (
        "If this assertion fails because a 429 appeared, that's GOOD NEWS — "
        "rate limiting has been implemented. Update this test to require it."
    )


async def test_auth_007_refresh_token_rejected_as_access_token(client, make_user):
    """
    AUTH-007: a refresh token has `type=refresh` in its JWT claims and must
    not be usable as a bearer access token on protected routes.
    """
    user, password = await make_user(username="erin", password="pw-erin-123")

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "erin", "password": password},
    )
    refresh_token = login_resp.json()["data"]["refresh_token"]

    resp = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )
    assert resp.status_code == 401


async def test_auth_008_inactive_account_cannot_log_in(client, make_user):
    """Deactivated users must not be able to obtain new tokens."""
    user, password = await make_user(
        username="frank", password="pw-frank-123", is_active=False
    )

    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "frank", "password": password},
    )
    assert resp.status_code == 401
