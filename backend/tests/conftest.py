"""Test setup: a database built by the real Alembic migrations.

Uses a temporary SQLite file by default. Set TEST_DATABASE_URL to run against PostgreSQL
(CI does, with pgvector). The tests delete all rows, so never point it at real data.
"""

import os
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="travel-tests-")
os.environ.update(
    APP_ENV="test",
    DATABASE_URL=os.environ.get("TEST_DATABASE_URL")
    or f"sqlite+aiosqlite:///{Path(_tmp, 'test.db').as_posix()}",
    JWT_SECRET="test-secret-" + "x" * 40,
    LOGIN_MAX_ATTEMPTS="3",
    AUTH_RATE_LIMIT_PER_MINUTE="1000",
    LOG_LEVEL="WARNING",
)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.core import rate_limit  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.database import get_sessionmaker  # noqa: E402
from app.main import app  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
PASSWORD = "correct horse battery"


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["skip_logging_config"] = True
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
async def clean_state():
    yield
    async with get_sessionmaker()() as session:
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(delete(table))
        await session.commit()
    rate_limit.limiter.reset()


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def db_session():
    async with get_sessionmaker()() as session:
        yield session


async def register(client: AsyncClient, email: str = "ana@example.com",
                   password: str = PASSWORD, name: str = "Ana Traveller"):
    return await client.post("/api/auth/register",
                             json={"email": email, "password": password, "full_name": name})


@pytest.fixture
async def user_token(client):
    response = await register(client)
    assert response.status_code == 201, response.text
    client.cookies.clear()  # tests choose bearer or cookie auth explicitly
    return response.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
