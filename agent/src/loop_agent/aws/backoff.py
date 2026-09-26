"""Intake backoff: poll at the base interval while there is work, double the wait
while idle up to a configurable sleep, and let wake-ups reset it."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

TOLERANCE_S = 10  # scheduler ticks jitter; a tick a few seconds early still counts


@dataclass(frozen=True)
class Backoff:
    interval_s: int
    next_at: datetime


def parse(raw: str | None) -> Backoff | None:
    try:
        data = json.loads(raw)
        return Backoff(int(data["interval_s"]), datetime.fromisoformat(data["next_at"]))
    except (TypeError, ValueError, KeyError):
        return None


def dump(b: Backoff) -> str:
    return json.dumps({"interval_s": b.interval_s, "next_at": b.next_at.isoformat()})


def due(state: Backoff | None, now: datetime) -> bool:
    return state is None or now + timedelta(seconds=TOLERANCE_S) >= state.next_at


def reset(now: datetime, base_s: int) -> Backoff:
    return Backoff(base_s, now + timedelta(seconds=base_s))


def grow(state: Backoff | None, now: datetime, base_s: int, sleep_s: int) -> Backoff:
    current = max(state.interval_s if state else base_s, base_s)
    interval = min(current * 2, sleep_s)
    return Backoff(interval, now + timedelta(seconds=interval))
