"""Project Fournos cron expressions in UTC, the same way the operator evaluates them."""

from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from croniter import CroniterError, croniter


def next_start(schedule: str, after: datetime) -> datetime | None:
    try:
        return croniter(schedule, after.astimezone(timezone.utc)).get_next(datetime)
    except (CroniterError, ValueError, OverflowError):
        return None


@lru_cache(maxsize=256)
def calendar_starts(
    schedule: str, day: date, view: str, zone: ZoneInfo, created_at: datetime | None,
) -> dict[str, list[str]]:
    """First daily start in month view; each matching wall-clock minute in day view."""
    days = monthrange(day.year, day.month)[1] if view == "month" else 1
    start = datetime.combine(day, time.min, zone)
    end = (start + timedelta(days=days)).astimezone(timezone.utc)
    cursor = start.astimezone(timezone.utc) - timedelta(seconds=1)
    if created_at is not None:
        cursor = max(cursor, created_at.astimezone(timezone.utc))
    result: dict[str, list[str]] = {}
    try:
        ticks = croniter(schedule, cursor)
        while (tick := ticks.get_next(datetime, start_time=cursor)) < end:
            local = tick.astimezone(zone)
            result.setdefault(local.date().isoformat(), []).append(local.strftime("%H:%M"))
            if view == "month":
                midnight = datetime.combine(local.date() + timedelta(days=1), time.min, zone)
                cursor = midnight.astimezone(timezone.utc) - timedelta(seconds=1)
            else:
                # The calendar renders minutes. Sub-minute cron ticks share one entry.
                cursor = tick.replace(second=59, microsecond=0)
    except (CroniterError, ValueError, OverflowError):
        pass  # Invalid schedules or no further matching dates.
    return result
