from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker
)
from sqlalchemy.orm import declarative_base
from sqlalchemy import event, text

from app.core.config import settings
from app.utils.logger import create_logger

logger = create_logger("Database")

# Create engine with SQLite-specific settings
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args=connect_args
)



# Enable SQLite foreign key enforcement
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ARG001
    if settings.DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session



_MIGRATIONS = [
    ("clusters", "gpu_type", "VARCHAR(255)"),
    ("clusters", "gpu_allocation_mode", "VARCHAR(20)"),
    ("reservations", "reservation_type", "VARCHAR(20) NOT NULL DEFAULT 'cluster'"),
    ("reservations", "gpu_count", "INTEGER"),
    ("reservations", "enforcement_namespace", "VARCHAR(255)"),
    ("reservations", "enforcement_status", "VARCHAR(50)"),
]


async def _run_migrations(conn):
    """Add new columns to existing tables. Idempotent — silently skips columns that already exist."""
    for table, column, col_type in _MIGRATIONS:
        try:
            await conn.execute(text(
                f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
            ))
            logger.info(f"Migration: added {table}.{column}")
        except Exception:
            pass  # Column already exists


async def init_db():
    from app.models.cluster import Cluster  # noqa: F401
    from app.models.reservation import Reservation  # noqa: F401
    from app.models.user import User  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)
