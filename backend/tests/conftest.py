import os


# Configuration is validated while application modules are imported. Tests use
# an explicit non-production key rather than relying on an application default.
os.environ.setdefault(
    "SECRET_KEY",
    "test-only-session-signing-key-32-characters-minimum",
)
os.environ.setdefault("ADMIN_USERNAME", "test-admin")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("USER_USERNAME", "test-user")
os.environ.setdefault("USER_PASSWORD", "test-user-password")


import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.cluster import Cluster, ResourceObservation
from app.models.gpu_pod_history import ClusterGpuSnapshot


@pytest_asyncio.fixture
async def observation_db(tmp_path):
    url = os.getenv("OBSERVATION_TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tmp_path / 'views.db'}"
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            for model in (Cluster, ResourceObservation, ClusterGpuSnapshot):
                await conn.run_sync(lambda sync, table=model.__table__: table.create(sync, checkfirst=True))
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
