"""Coordinate on-demand observations across backend workers and replicas."""
import asyncio
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.utils.logger import create_logger

logger = create_logger("Snapshots")
LEASE = timedelta(minutes=3)
RETRY_DELAY = timedelta(seconds=10)


async def refresh(db, model, key, *, fresh_for, columns, collect, initial=None, clock=datetime.utcnow):
    """Run collect once per due key. A crashed or superseded writer cannot publish late."""
    started = clock()
    match = and_(*(getattr(model, name) == value for name, value in key.items()))
    due = or_(model.checked_at.is_(None), model.checked_at <= started - fresh_for)
    if hasattr(model, "failed_at"):
        due = or_(and_(model.failed_at.is_(None), due), model.failed_at <= started - RETRY_DELAY)
    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
    claim = insert(model).values(**key, **(initial or {}), checking_since=started).on_conflict_do_update(
        index_elements=list(key), set_={"checking_since": started},
        where=due & or_(model.checking_since.is_(None), model.checking_since <= started - LEASE),
    ).returning(*columns)
    owned = (await db.execute(claim)).first()
    await db.commit()

    if owned is None:
        delay = 0.2
        while True:
            checking = await db.scalar(select(model.checking_since).where(match))
            await db.commit()
            if checking is None or checking <= clock() - LEASE:
                return
            await asyncio.sleep(delay)
            delay = min(delay * 2, 2)

    try:
        values = await collect(owned)
    except Exception as exc:
        logger.warning(f"{model.__tablename__} check failed: {type(exc).__name__}")
        values = {"last_check_failed": True}
        if hasattr(model, "failed_at"):
            values["failed_at"] = clock()
    else:
        values.update(checked_at=clock(), last_check_failed=False)
        if hasattr(model, "failed_at"):
            values["failed_at"] = None
    await db.execute(update(model).where(match, model.checking_since == started).values(**values, checking_since=None))
    await db.commit()
