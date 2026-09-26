from datetime import datetime, timedelta, timezone

import pytest

from loop_agent.aws.backoff import Backoff, due, dump, grow, parse, reset

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("raw", [None, "", "{}", "not json", '{"interval_s": "x"}', '{"next_at": "2026"}'])
def test_missing_or_corrupt_state_is_due(raw):
    assert parse(raw) is None
    assert due(parse(raw), NOW)


def test_dump_parse_round_trip():
    b = Backoff(480, NOW + timedelta(seconds=480))
    assert parse(dump(b)) == b


def test_due_respects_next_at_with_tolerance():
    assert not due(Backoff(240, NOW + timedelta(seconds=60)), NOW)
    assert due(Backoff(240, NOW + timedelta(seconds=5)), NOW)  # within 10 s tolerance
    assert due(Backoff(240, NOW - timedelta(seconds=1)), NOW)


def test_reset_is_base_from_now():
    assert reset(NOW, 120) == Backoff(120, NOW + timedelta(seconds=120))


def test_grows_to_the_sleep_in_four_idle_ticks_and_stays():
    state, seen = reset(NOW, 120), []
    for _ in range(6):
        state = grow(state, NOW, 120, 1920)
        seen.append(state.interval_s)
    assert seen == [240, 480, 960, 1920, 1920, 1920]
    assert state.next_at == NOW + timedelta(seconds=1920)


def test_grow_from_nothing_and_after_config_changes():
    assert grow(None, NOW, 120, 1920).interval_s == 240
    assert grow(Backoff(3840, NOW), NOW, 120, 1920).interval_s == 1920  # sleep lowered
    assert grow(Backoff(30, NOW), NOW, 120, 1920).interval_s == 240     # base raised


def test_naive_timestamp_is_treated_as_corrupt():
    assert parse('{"interval_s": 240, "next_at": "2026-09-26T12:00:00"}') is None
