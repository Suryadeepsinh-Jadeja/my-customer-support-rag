import pytest

from app.core.config import Settings, get_settings
from app.core.logging import mask, mask_email


async def test_health(client):
    for path in ("/health", "/api/health"):
        response = await client.get(path)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


async def test_ready_checks_database(client):
    response = await client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    backend = get_settings().database_backend
    assert body["checks"]["database"] == {"ok": True, "backend": backend}
    if backend == "postgresql":
        assert body["checks"]["vector_store"] == {"ok": True, "backend": "pgvector"}
    assert "secret" not in response.text.lower()


async def test_request_id_and_security_headers(client):
    response = await client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["x-request-id"] == "abc-123"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"

    generated = await client.get("/health", headers={"X-Request-ID": "bad id\nwith newline"})
    assert generated.headers["x-request-id"] != "bad id\nwith newline"


async def test_unknown_route_uses_error_shape(client):
    response = await client.get("/api/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_openapi_docs_available(client):
    assert (await client.get("/docs")).status_code == 200
    schema = (await client.get("/openapi.json")).json()
    assert "/api/auth/login" in schema["paths"]


def test_production_requires_strong_jwt_secret(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "")
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings()
    monkeypatch.setenv("JWT_SECRET", "too-short")
    with pytest.raises(ValueError, match="32 characters"):
        Settings()
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    settings = Settings()
    assert settings.cookie_secure is True
    assert settings.log_format == "json"


def test_masking():
    assert mask("X1234567") == "****4567"
    assert mask("12") == "**"
    assert mask_email("ana@example.com") == "a***@example.com"
