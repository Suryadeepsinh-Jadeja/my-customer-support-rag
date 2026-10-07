from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core import rate_limit
from app.core.config import get_settings
from app.db.models import AuditLog, User
from tests.conftest import PASSWORD, bearer, register


async def login(client, email="ana@example.com", password=PASSWORD):
    return await client.post("/api/auth/login", json={"email": email, "password": password})


# ---------------------------------------------------------------- registration


async def test_register_creates_account_and_signs_in(client):
    response = await register(client, email="Ana@Example.com")
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "ana@example.com"
    assert body["user"]["role"] == "user"
    assert body["user"]["profile"]["full_name"] == "Ana Traveller"
    assert "password_hash" not in response.text
    assert {"access_token", "csrf_token"} <= set(response.cookies.keys())
    set_cookie = ";".join(response.headers.get_list("set-cookie")).lower()
    assert "httponly" in set_cookie and "samesite=lax" in set_cookie


async def test_duplicate_email_is_rejected(client):
    await register(client)
    response = await register(client, email="ANA@example.com")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_weak_password_rejected_without_echoing_it(client):
    response = await register(client, password="short")
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert body["error"]["fields"][0]["field"] == "password"
    assert "short" not in response.text


async def test_passwords_are_hashed(client, db_session):
    await register(client)
    user = (await db_session.execute(select(User))).scalar_one()
    assert user.password_hash.startswith("$argon2")
    assert PASSWORD not in user.password_hash


# --------------------------------------------------------------------- sign-in


async def test_login_success(client):
    await register(client)
    response = await login(client)
    assert response.status_code == 200
    assert response.json()["user"]["email"] == "ana@example.com"


async def test_wrong_password_and_unknown_email_look_the_same(client):
    await register(client)
    wrong = await login(client, password="not the password")
    unknown = await login(client, email="nobody@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_account_locks_after_repeated_failures(client):
    await register(client)
    for _ in range(get_settings().LOGIN_MAX_ATTEMPTS):
        assert (await login(client, password="wrong password!")).status_code == 401
    # Even the right password is refused while locked.
    response = await login(client)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_attempts"


async def test_lock_expires(client, db_session):
    await register(client)
    for _ in range(get_settings().LOGIN_MAX_ATTEMPTS):
        await login(client, password="wrong password!")
    user = (await db_session.execute(select(User))).scalar_one()
    user.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    assert (await login(client)).status_code == 200


async def test_auth_endpoints_are_rate_limited_per_ip(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "AUTH_RATE_LIMIT_PER_MINUTE", 2)
    rate_limit.limiter.reset()
    await login(client, email="x@example.com")
    await login(client, email="y@example.com")
    response = await login(client, email="z@example.com")
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response.headers["Retry-After"]) >= 1


async def test_auth_events_are_audited_without_secrets(client, db_session):
    await register(client)
    await login(client, password="wrong password!")
    await login(client)
    rows = (await db_session.execute(select(AuditLog).order_by(AuditLog.created_at))).scalars()
    events = [(r.action, r.status) for r in rows]
    assert events == [("auth.register", "success"), ("auth.login", "failure"),
                      ("auth.login", "success")]
    dumped = str([(r.details, r.ip_address) for r in
                  (await db_session.execute(select(AuditLog))).scalars()])
    assert PASSWORD not in dumped and "wrong password" not in dumped


# ------------------------------------------------------------ session handling


async def test_me_requires_authentication(client):
    response = await client.get("/api/users/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


async def test_me_with_bearer_token(client, user_token):
    response = await client.get("/api/users/me", headers=bearer(user_token))
    assert response.status_code == 200
    assert response.json()["email"] == "ana@example.com"


async def test_tampered_token_rejected(client, user_token):
    response = await client.get("/api/users/me", headers=bearer(user_token[:-2] + "xx"))
    assert response.status_code == 401


async def test_cookie_auth_requires_csrf_for_changes(client):
    signed_in = await register(client)
    csrf = signed_in.json()["csrf_token"]
    # Reads work with just the cookie.
    assert (await client.get("/api/users/me")).status_code == 200
    # Writes need the CSRF header.
    missing = await client.patch("/api/users/me/profile", json={"full_name": "Ana B"})
    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "csrf_failed"
    ok = await client.patch("/api/users/me/profile", json={"full_name": "Ana B"},
                            headers={"X-CSRF-Token": csrf})
    assert ok.status_code == 200


async def test_logout_clears_cookies(client):
    await register(client)
    response = await client.post("/api/auth/logout")
    assert response.status_code == 204
    assert (await client.get("/api/users/me")).status_code == 401


async def test_logout_everywhere_revokes_existing_tokens(client, user_token):
    response = await client.post("/api/auth/logout-all", headers=bearer(user_token))
    assert response.status_code == 204
    assert (await client.get("/api/users/me", headers=bearer(user_token))).status_code == 401


async def test_change_password(client, user_token):
    bad = await client.post("/api/users/me/password", headers=bearer(user_token),
                            json={"current_password": "nope", "new_password": "another long one"})
    assert bad.status_code == 401

    response = await client.post(
        "/api/users/me/password", headers=bearer(user_token),
        json={"current_password": PASSWORD, "new_password": "another long one"},
    )
    assert response.status_code == 200
    # Old token is revoked; the new one works, and so does the new password.
    assert (await client.get("/api/users/me", headers=bearer(user_token))).status_code == 401
    new_token = response.json()["access_token"]
    assert (await client.get("/api/users/me", headers=bearer(new_token))).status_code == 200
    assert (await login(client, password="another long one")).status_code == 200
