from datetime import datetime, time

from ..config import config
from . import settings


def _parse(value: str, default: time) -> time:
    try:
        hh, mm = str(value).split(":")
        return time(int(hh), int(mm))
    except (ValueError, TypeError):
        return default


def is_working(now: datetime | None = None) -> bool:
    if not settings.get("work_enabled"):
        return True
    now = (now or datetime.now(config.tz)).astimezone(config.tz)
    start = _parse(settings.get("work_from"), time(10, 0))
    end = _parse(settings.get("work_to"), time(2, 0))
    cur = now.time()
    if start == end:
        return True
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end  # смена через полночь
