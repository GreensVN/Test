"""ISO suffix normalization and numeric/calendar limits do not crash reminders."""

from datetime import datetime, timedelta, timezone

import executor
import pytest


@pytest.mark.parametrize("separator", ["T", " ", "Z"])
@pytest.mark.parametrize("suffix", ["", "Z", "+07:00"])
def test_iso_only_normalizes_a_trailing_utc_designator(separator, suffix):
    text = f"2026-10-18{separator}09:30:00{suffix}"
    expected = datetime(2026, 10, 18, 9, 30)
    if suffix:
        tz = timezone.utc if suffix == "Z" else timezone(timedelta(hours=7))
        expected = expected.replace(tzinfo=tz).astimezone().replace(tzinfo=None)
    assert executor._local_datetime(text) == expected


@pytest.mark.parametrize("value,expected", [(10 ** 1000, 23.0), (-10 ** 1000, 0.0)])
def test_large_integer_is_clamped_without_float_overflow(value, expected):
    assert executor._to_number(value, 7.0, 0.0, 23.0) == expected


@pytest.mark.parametrize("field,expected", [
    ("hour", datetime(2026, 10, 18, 23)),
    ("minute", datetime(2026, 10, 18, 7, 59)),
    ("day_offset", datetime(2026, 10, 18, 7) + timedelta(days=3660)),
])
def test_clock_fields_accept_bounded_huge_integer(field, expected):
    info = {"type": "clock", "hour": 7, "minute": 0, field: 10 ** 1000}
    assert executor._reminder_when(info, datetime(2026, 10, 18, 6)) == expected


def test_large_delay_is_clamped_without_float_overflow():
    now = datetime(2026, 10, 18, 6)
    assert executor._reminder_when({"type": "delay", "minutes": 10 ** 1000}, now) == \
        now + timedelta(days=366)


@pytest.mark.parametrize("info", [
    {"type": "delay", "minutes": 60},
    {"type": "clock", "hour": 23, "minute": 58},
    {"type": "clock", "hour": 7, "day_offset": 1},
    {"type": "clock", "hour": 7, "day_offset": 10 ** 1000},
])
def test_datetime_upper_boundary_returns_none_instead_of_crashing(info):
    assert executor._reminder_when(info, datetime(9999, 12, 31, 23, 59)) is None


@pytest.mark.parametrize("info", [
    {"type": "delay", "minutes": 1},
    {"type": "clock", "hour": 23, "minute": 59},
    {"type": "clock", "hour": 7, "day_offset": 1},
])
def test_last_valid_calendar_day_still_works(info):
    now = datetime(9999, 12, 30, 7)
    result = executor._reminder_when(info, now)
    assert result is not None and result > now
