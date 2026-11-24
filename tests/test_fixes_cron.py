from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from openagent.alwayson import timers


def test_cron_dow_7_ranges():
    sunday = datetime(2026, 3, 8, 9, 0, tzinfo=UTC)  # Sunday
    assert timers.cron_matches(sunday, "0 9 * * 1-7")
    assert timers.cron_matches(sunday, "0 9 * * 0-7")
    assert timers.cron_matches(sunday, "0 9 * * 7")


def test_cron_leap_day_and_impossible_date():
    nxt = timers.next_cron("0 0 29 2 *", "UTC", datetime(2024, 3, 1, tzinfo=UTC))
    assert nxt == datetime(2028, 2, 29, 0, 0, tzinfo=UTC)
    t0 = time.perf_counter()
    with pytest.raises(ValueError):
        timers.next_cron("0 0 31 2 *", "UTC", datetime(2026, 3, 2, tzinfo=UTC))
    assert time.perf_counter() - t0 < 0.5


def test_cron_dst_fall_back_monotonic():
    # America/New_York 2026-11-01: 02:00 EDT -> 01:00 EST. 06:00Z is 01:00 EST (fold 1)
    after = datetime(2026, 11, 1, 5, 45, tzinfo=UTC)  # 01:45 EDT
    nxt = timers.next_cron("*/15 * * * *", "America/New_York", after)
    assert nxt == datetime(2026, 11, 1, 6, 0, tzinfo=UTC)
    after_fold1 = datetime(2026, 11, 1, 6, 10, tzinfo=UTC)  # 01:10 EST fold 1
    nxt2 = timers.next_cron("15 1 * * *", "America/New_York", after_fold1)
    assert nxt2 > after_fold1
