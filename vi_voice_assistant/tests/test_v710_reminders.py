"""Không đợi nhiều ngày: timer giả kiểm đúng deadline, huỷ và khôi phục."""
import json
from datetime import datetime, timedelta, timezone

import executor
import pytest


@pytest.fixture
def reminders(tmp_path, monkeypatch):
    timers, messages = [], []

    class Timer:
        def __init__(self, delay, callback, args=()):
            self.delay, self.callback, self.args = delay, callback, args
            self.cancelled = False
            self.daemon = False
            timers.append(self)

        def start(self):
            pass

        def cancel(self):
            self.cancelled = True

        def fire(self):
            # Cố ý bắn được cả khi cancel: mô phỏng callback đã bắt đầu.
            self.callback(*self.args)

    monkeypatch.setattr(executor.threading, "Timer", Timer)
    monkeypatch.setattr(executor, "ACTIVE_REMINDERS", [])
    monkeypatch.setattr(executor, "REMINDERS_PATH", tmp_path / "reminders.json")
    monkeypatch.setattr(executor, "respond", messages.append)
    monkeypatch.setattr(executor, "_popen", lambda args: None)
    monkeypatch.setattr(executor, "_run_first_available", lambda args: True)
    executor.clear_pending_reminder()
    yield timers, messages
    executor.clear_pending_reminder()


@pytest.mark.parametrize("days", [2, 3, 30, 365])
def test_long_schedule_starts_only_one_bounded_timer(reminders, days):
    timers, _ = reminders
    executor._schedule_reminder("việc xa", datetime.now() + timedelta(days=days, hours=2))
    assert len(timers) == 1
    assert timers[0].delay == executor._MAX_TIMER_SECONDS
    assert timers[0].args[-1] is True
    assert executor.ACTIVE_REMINDERS[0]["timer"] is timers[0]


def test_continuation_recomputes_remaining_deadline_and_tracks_handle(reminders):
    timers, messages = reminders
    executor._schedule_reminder("việc xa", datetime.now() + timedelta(days=3, hours=2))
    entry = executor.ACTIVE_REMINDERS[0]
    entry["at"] = datetime.now() + timedelta(hours=2)
    timers[0].fire()
    assert len(timers) == 2 and messages == []
    assert 7190 < timers[1].delay <= 7200
    assert timers[1].args[-1] is False
    assert entry["timer"] is timers[1]
    timers[1].fire()
    assert len(messages) == 1 and executor.ACTIVE_REMINDERS == []


def test_cancel_long_reminder_prevents_orphan_continuations(reminders):
    timers, messages = reminders
    rid = executor._schedule_reminder("việc xa", datetime.now() + timedelta(days=30))
    assert len(executor.cancel_reminder(rid)) == 1
    assert timers[0].cancelled
    timers[0].fire()
    assert len(timers) == 1 and messages == []
    assert json.loads(executor.REMINDERS_PATH.read_text(encoding="utf-8")) == []


def test_cancelled_final_callback_does_not_notify(reminders):
    timers, messages = reminders
    executor._schedule_reminder("đã huỷ", datetime.now() + timedelta(minutes=5))
    executor.cancel_reminder()
    timers[0].fire()
    assert messages == []


def test_callback_only_fires_once_and_does_not_remove_next_recurrence(reminders):
    timers, messages = reminders
    executor._schedule_reminder("uống thuốc", datetime.now() + timedelta(minutes=5),
                                repeat={"kind": "daily"})
    timers[0].fire()
    next_id = executor.ACTIVE_REMINDERS[0]["id"]
    timers[0].fire()
    assert len(messages) == 1
    assert len(executor.ACTIVE_REMINDERS) == 1
    assert executor.ACTIVE_REMINDERS[0]["id"] == next_id


def test_late_daily_callback_keeps_series_alive(reminders):
    timers, messages = reminders
    executor._schedule_reminder("uống thuốc", datetime.now() + timedelta(minutes=5),
                                repeat={"kind": "daily"})
    executor.ACTIVE_REMINDERS[0]["at"] = datetime.now() - timedelta(days=3, minutes=5)
    timers[0].fire()
    assert len(messages) == 1
    assert len(executor.ACTIVE_REMINDERS) == 1
    assert executor.ACTIVE_REMINDERS[0]["at"] > datetime.now()


def test_continuation_after_sleep_past_deadline_notifies_once(reminders):
    timers, messages = reminders
    executor._schedule_reminder("đã đến giờ", datetime.now() + timedelta(days=3))
    executor.ACTIVE_REMINDERS[0]["at"] = datetime.now() - timedelta(minutes=1)
    timers[0].fire()
    assert len(messages) == 1 and executor.ACTIVE_REMINDERS == []


def test_restore_preserves_id_and_is_idempotent(reminders):
    timers, _ = reminders
    executor.REMINDERS_PATH.write_text(json.dumps([
        {"id": "stable-id", "task": "họp", "at": (datetime.now() + timedelta(days=3)).isoformat()}
    ]), encoding="utf-8")
    assert executor.restore_reminders() == 1
    assert executor.restore_reminders() == 0
    assert len(timers) == 1
    assert executor.ACTIVE_REMINDERS[0]["id"] == "stable-id"


def test_restore_accepts_timezone_and_skips_bad_items(reminders):
    aware = datetime.now(timezone.utc) + timedelta(hours=2)
    executor.REMINDERS_PATH.write_text(json.dumps([
        None, {"at": "rác"},
        {"id": "utc", "task": "họp", "at": aware.isoformat()},
    ]), encoding="utf-8-sig")
    assert executor.restore_reminders() == 1
    at = executor.ACTIVE_REMINDERS[0]["at"]
    assert at.tzinfo is None
    assert at == aware.astimezone().replace(tzinfo=None)


def test_invalid_reminder_root_is_not_overwritten(reminders):
    original = '{"khong_phai": "list"}'
    executor.REMINDERS_PATH.write_text(original, encoding="utf-8")
    assert executor.restore_reminders() == 0
    assert executor.REMINDERS_PATH.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("kind,days", [("daily", 1), ("weekly", 7), ("monthly", 31)])
def test_recurrence_survives_years_offline(kind, days):
    then = datetime(2020, 1, 15, 9)
    now = datetime(2026, 10, 17, 8)
    nxt = executor._next_future_occurrence(then, {"kind": kind}, now)
    assert now < nxt <= now + timedelta(days=days)
    assert nxt.hour == 9


def test_datetime_overflow_stops_recurrence_without_crash():
    for kind in ("daily", "weekly", "monthly"):
        assert executor._next_occurrence(datetime(9999, 12, 31), {"kind": kind}) is None


def test_timer_start_failure_rolls_back_and_does_not_claim_success(reminders, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("không tạo được luồng")

    monkeypatch.setattr(executor, "_arm_timer", fail)
    assert executor.action_set_reminder("họp", {"time": "5 phút nữa"}) is False
    assert executor.ACTIVE_REMINDERS == []
    assert not any("Đã đặt" in text for text in reminders[1])


def test_confirmation_does_not_say_next_week_for_this_week():
    monday = datetime(2026, 10, 12, 8)
    thursday = datetime(2026, 10, 15, 9)
    assert "tuần này" in executor._reminder_when_phrase(thursday, monday)
