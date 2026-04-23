import asyncio
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import NullPool
from app.database import Base, get_db
from app.main import app
from app.config import settings
from httpx import AsyncClient, ASGITransport

TEST_DB_URL = (
    settings.test_database_url
    or "postgresql+asyncpg://postgres:7392@localhost:5432/prescribe_assist_test"
)


def _sync_run(coro):
    """Run an async coroutine synchronously using a dedicated event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _create_tables():
    eng = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await eng.dispose()


async def _drop_tables():
    eng = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture(scope="session")
def setup_test_db():
    """Create tables once per session; drop them at the end."""
    _sync_run(_create_tables())
    yield
    _sync_run(_drop_tables())


@pytest_asyncio.fixture
async def db_session(setup_test_db):
    """
    Per-test isolated session.
    Engine is created fresh so the connection belongs to the test's own event loop.
    join_transaction_mode=create_savepoint turns session.commit() into savepoints,
    and conn.rollback() undoes all changes after the test.
    """
    eng = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
    conn = await eng.connect()
    trans = await conn.begin()
    session = AsyncSession(
        bind=conn,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    yield session
    await session.close()
    await trans.rollback()
    await conn.close()
    await eng.dispose()


@pytest_asyncio.fixture
async def client(db_session):
    """HTTP test client sharing the same DB session as db_session."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
