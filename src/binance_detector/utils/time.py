from __future__ import annotations

from datetime import datetime, timedelta, timezone


def floor_to_5m(ts: datetime) -> datetime:
    ts = ts.astimezone(timezone.utc)
    floored_minute = ts.minute - (ts.minute % 5)
    return ts.replace(minute=floored_minute, second=0, microsecond=0)


def next_round_end(ts: datetime) -> datetime:
    return floor_to_5m(ts) + timedelta(minutes=5)

