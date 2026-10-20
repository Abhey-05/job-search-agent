"""Translates the DB-backed `schedule` settings (days/time/IANA timezone)
into the two forms the rest of the system needs:

  - `apscheduler_trigger_args`: a timezone-aware cron trigger for the
    optional local scheduler (`python -m app scheduler`) -- correct through
    DST changes because APScheduler evaluates the IANA timezone directly.
  - `compute_utc_cron`: a plain 5-field UTC cron expression, for pasting
    into Render's or Railway's cron-job schedule field -- both platforms
    only accept UTC cron expressions with no timezone/DST awareness, so
    this is a point-in-time conversion. For Asia/Kolkata (no DST) it's
    exact and permanent; for a DST-observing timezone it will be off by an
    hour for part of the year and needs updating twice a year, or you
    should use `python -m app scheduler` instead of platform cron.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

_DAY_INDEX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_CRON_DOW = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 0}


def apscheduler_trigger_args(schedule: dict) -> dict:
    days = schedule.get("days", ["mon", "wed", "fri"])
    hour, minute = schedule.get("time", "08:00").split(":")
    return {
        "day_of_week": ",".join(days),
        "hour": int(hour),
        "minute": int(minute),
        "timezone": schedule.get("timezone", "Asia/Kolkata"),
    }


def compute_utc_cron(schedule: dict, reference_date: datetime | None = None) -> str:
    days = schedule.get("days", ["mon", "wed", "fri"])
    hour, minute = (int(x) for x in schedule.get("time", "08:00").split(":"))
    tz = ZoneInfo(schedule.get("timezone", "Asia/Kolkata"))

    ref = reference_date or datetime.now(tz)
    local_dt = ref.replace(hour=hour, minute=minute, second=0, microsecond=0, tzinfo=tz)
    utc_dt = local_dt.astimezone(ZoneInfo("UTC"))

    # Day-of-week shifts by +-1 if the UTC conversion crosses midnight.
    day_shift = (utc_dt.date() - local_dt.date()).days
    cron_days = sorted((_CRON_DOW[d] + day_shift) % 7 for d in days)

    return f"{utc_dt.minute} {utc_dt.hour} * * {','.join(str(d) for d in cron_days)}"
