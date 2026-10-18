"""Timer failures must not erase a saved reminder or revive an old callback."""

import json
from datetime import datetime, timedelta

import executor
import main
import pytest


@pytest.fixture
def scheduler(tmp_path, monkeypatch):
    state = {"timers": [], "messages": [], "output": [], "start_error": None,
             "cancel_error": None}

    class Timer:
        def __init__(self, delay, callback, args=()):
            self.delay, self.callback, self.args = delay, callback, args
            self.daemon = False
            self.started = self.cancelled = False
            state["timers"].append(self)

        def start(self):
            error = state["start_error"]
            if error is not None:
                raise error("thread unavailable")
            self.started = True

        def cancel(self):
            error = state["cancel_error"]
            if error is not None:
                raise error("cancel failed")
            self.cancelled = True

        def fire(self):
            # A cancelled/already-fired thread can still reach its callback.
            self.callback(*self.args)

    monkeypatch.setattr(executor.threading, "Timer", Timer)
    monkeypatch.setattr(executor, "ACTIVE_REMINDERS", [])
    monkeypatch.setattr(executor, "REMINDERS_PATH", tmp_path / "reminders.json")
    monkeypatch.setattr(executor, "respond", state["messages"].append)
    monkeypatch.setattr(executor, "safe_print", state["output"].append)
    monkeypatch.setattr(executor, "_popen", lambda args: None)
    monkeypatch.setattr(executor, "_run_first_available", lambda args: True)
    executor.clear_pending_reminder()
    yield state
    executor.clear_pending_reminder()


def _write_pending(task="saved", rid="saved-id"):
    item = {"id": rid, "task": task,
            "at": (datetime.now() + timedelta(days=3)).isoformat()}
    executor.REMINDERS_PATH.write_text(json.dumps([item]), encoding="utf-8")
    return item


def _saved_rows():
    return json.loads(executor.REMINDERS_PATH.read_text(encoding="utf-8"))


def test_duplicate_continuation_does_not_start_two_successors(scheduler):
    executor._schedule_reminder("long", datetime.now() + timedelta(days=3))
    old = scheduler["timers"][0]
    old.fire()
    current = executor.ACTIVE_REMINDERS[0]["timer"]
    old.fire()
    assert len(scheduler["timers"]) == 2
    assert executor.ACTIVE_REMINDERS[0]["timer"] is current
    assert scheduler["messages"] == []


def test_previous_hop_cannot_deliver_a_later_hop(scheduler):
    executor._schedule_reminder("long", datetime.now() + timedelta(days=3))
    old = scheduler["timers"][0]
    old.fire()
    entry = executor.ACTIVE_REMINDERS[0]
    entry["at"] = datetime.now() - timedelta(seconds=1)
    old.fire()
    assert scheduler["messages"] == []
    assert executor.ACTIVE_REMINDERS == [entry]
    scheduler["timers"][1].fire()
    assert len(scheduler["messages"]) == 1
    assert executor.ACTIVE_REMINDERS == []


@pytest.mark.parametrize("days", [0.01, 3])
def test_old_callback_cannot_touch_restored_reminder_with_same_id(scheduler, days):
    executor._schedule_reminder("saved", datetime.now() + timedelta(days=days))
    old = scheduler["timers"][0]
    saved = executor.REMINDERS_PATH.read_bytes()
    executor.cancel_reminder()
    executor.REMINDERS_PATH.write_bytes(saved)
    assert executor.restore_reminders() == 1
    entry = executor.ACTIVE_REMINDERS[0]
    old.fire()
    assert scheduler["messages"] == []
    assert executor.ACTIVE_REMINDERS == [entry]
    assert len(scheduler["timers"]) == 2


@pytest.mark.parametrize("error", [OSError, RuntimeError, OverflowError])
def test_rearm_failure_is_paused_persisted_and_retryable(scheduler, error):
    rid = executor._schedule_reminder("long", datetime.now() + timedelta(days=3))
    old = scheduler["timers"][0]
    scheduler["start_error"] = error
    old.fire()
    entry = executor.ACTIVE_REMINDERS[0]
    assert entry["id"] == rid and entry["timer"] is None
    assert entry.get("_timer_error")
    assert _saved_rows()[0]["id"] == rid
    assert scheduler["messages"] == []
    assert any("tạm dừng" in line.lower() for line in scheduler["output"])
    scheduler["start_error"] = None
    assert executor.restore_reminders() == 1
    assert len(executor.ACTIVE_REMINDERS) == 1
    resumed = executor.ACTIVE_REMINDERS[0]
    assert resumed["timer"].started and not resumed.get("_timer_error")
    old.fire()
    assert len(scheduler["timers"]) == 3


@pytest.mark.parametrize("error", [OSError, RuntimeError, OverflowError])
def test_restore_failure_keeps_future_record_and_can_retry(scheduler, error):
    original = _write_pending()
    scheduler["start_error"] = error
    assert executor.restore_reminders() == 0
    assert _saved_rows() == [original]
    assert len(executor.ACTIVE_REMINDERS) == 1
    assert executor.ACTIVE_REMINDERS[0]["timer"] is None
    assert executor.restore_reminders() == 0
    assert _saved_rows() == [original]
    assert len(executor.ACTIVE_REMINDERS) == 1
    scheduler["start_error"] = None
    assert executor.restore_reminders() == 1
    assert executor.restore_reminders() == 0
    assert len(executor.ACTIVE_REMINDERS) == 1
    assert executor.ACTIVE_REMINDERS[0]["timer"].started


def test_partial_restore_retains_failed_rows_without_restarting_live_timer(scheduler,
                                                                         monkeypatch):
    first = _write_pending("one", "one")
    second = dict(first, id="two", task="two")
    executor.REMINDERS_PATH.write_text(json.dumps([first, second]), encoding="utf-8")
    original_start = executor._start_reminder_timer

    def start(entry, delay):
        scheduler["start_error"] = RuntimeError if entry["id"] == "two" else None
        return original_start(entry, delay)

    monkeypatch.setattr(executor, "_start_reminder_timer", start)
    assert executor.restore_reminders() == 1
    assert {row["id"] for row in _saved_rows()} == {"one", "two"}
    live = next(entry["timer"] for entry in executor.ACTIVE_REMINDERS if entry["id"] == "one")
    monkeypatch.setattr(executor, "_start_reminder_timer", original_start)
    scheduler["start_error"] = None
    assert executor.restore_reminders() == 1
    assert len(executor.ACTIVE_REMINDERS) == 2
    assert next(entry["timer"] for entry in executor.ACTIVE_REMINDERS
                if entry["id"] == "one") is live
    assert sum(timer.started for timer in scheduler["timers"]) == 2


@pytest.mark.parametrize("kind", ["daily", "weekly", "monthly"])
def test_next_recurrence_survives_timer_start_failure(scheduler, kind):
    old_id = executor._schedule_reminder("repeat", datetime.now() + timedelta(minutes=5),
                                        repeat={"kind": kind})
    scheduler["start_error"] = RuntimeError
    scheduler["timers"][0].fire()
    assert len(scheduler["messages"]) == 1
    assert len(executor.ACTIVE_REMINDERS) == 1
    entry = executor.ACTIVE_REMINDERS[0]
    assert entry["id"] != old_id and entry["timer"] is None
    assert entry["at"] > datetime.now()
    assert _saved_rows()[0]["repeat"] == {"kind": kind}
    scheduler["start_error"] = None
    assert executor.restore_reminders() == 1
    assert executor.ACTIVE_REMINDERS[0]["timer"].started


def test_paused_reminder_can_be_cancelled_without_resurrection(scheduler):
    _write_pending()
    scheduler["start_error"] = RuntimeError
    assert executor.restore_reminders() == 0
    assert len(executor.cancel_reminder("saved-id")) == 1
    assert executor.ACTIVE_REMINDERS == [] and _saved_rows() == []
    scheduler["start_error"] = None
    assert executor.restore_reminders() == 0


@pytest.mark.parametrize("error", [OSError, RuntimeError, OverflowError])
def test_new_schedule_failure_still_rolls_back(scheduler, error):
    scheduler["start_error"] = error
    assert executor.action_set_reminder("new", {"time": "5 phút nữa"}) is False
    assert executor.ACTIVE_REMINDERS == []
    assert not any("Đã đặt" in line for line in scheduler["messages"])
    assert all(timer.cancelled for timer in scheduler["timers"])


@pytest.mark.parametrize("repeat", [None, {"kind": "daily"}])
@pytest.mark.parametrize("error", [OSError, RuntimeError])
def test_cancel_error_does_not_block_due_notification(scheduler, repeat, error):
    executor._schedule_reminder("due", datetime.now() + timedelta(minutes=5), repeat=repeat)
    scheduler["cancel_error"] = error
    scheduler["timers"][0].fire()
    assert len(scheduler["messages"]) == 1
    assert len(executor.ACTIVE_REMINDERS) == int(repeat is not None)
    scheduler["timers"][0].fire()
    assert len(scheduler["messages"]) == 1


def test_paused_reminder_is_explicit_in_list_output(scheduler):
    entry = {"task": "important", "at": datetime.now(), "timer": None,
             "_timer_error": "thread unavailable"}
    line = main._format_reminder(entry)
    assert "important" in line
    assert "tạm dừng" in line.lower()
    assert "khởi động lại" in line.lower()


def test_private_timer_state_does_not_leak_into_saved_json(scheduler):
    executor._schedule_reminder("saved", datetime.now() + timedelta(days=3))
    assert set(_saved_rows()[0]) == {"id", "task", "at"}
    scheduler["start_error"] = RuntimeError
    scheduler["timers"][0].fire()
    assert set(_saved_rows()[0]) == {"id", "task", "at"}


@pytest.mark.parametrize("repeat", [None, {"kind": "daily"}])
def test_retry_cleans_expired_paused_one_shot_but_retains_recurrence(scheduler, repeat):
    _write_pending()
    scheduler["start_error"] = RuntimeError
    assert executor.restore_reminders() == 0
    entry = executor.ACTIVE_REMINDERS[0]
    entry["at"] = datetime.now() - timedelta(days=2)
    if repeat:
        entry["repeat"] = repeat
    executor._save_reminders()
    scheduler["start_error"] = None
    assert executor.restore_reminders() == int(repeat is not None)
    assert len(executor.ACTIVE_REMINDERS) == int(repeat is not None)
    assert len(_saved_rows()) == int(repeat is not None)
    if repeat:
        assert executor.ACTIVE_REMINDERS[0]["at"] > datetime.now()


def test_retry_failure_never_discards_an_already_registered_paused_record(scheduler):
    _write_pending()
    scheduler["start_error"] = RuntimeError
    assert executor.restore_reminders() == 0
    entry = executor.ACTIVE_REMINDERS[0]
    assert executor._schedule_reminder(entry["task"], entry["at"],
                                       reminder_id=entry["id"]) is None
    assert len(executor.ACTIVE_REMINDERS) == 1
    executor._save_reminders()
    assert len(_saved_rows()) == 1


def test_pause_and_save_failure_do_not_claim_success(scheduler, monkeypatch):
    executor._schedule_reminder("saved", datetime.now() + timedelta(days=3))
    original = executor.REMINDERS_PATH.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(executor, "atomic_write_json", fail)
    scheduler["start_error"] = RuntimeError
    scheduler["timers"][0].fire()
    assert executor.REMINDERS_PATH.read_bytes() == original
    assert executor.ACTIVE_REMINDERS[0]["_timer_error"]
    assert not any("đã lưu" in line.lower() for line in scheduler["output"])


def test_empty_start_exception_still_marks_record_as_paused(scheduler, monkeypatch):
    _write_pending()

    def fail(*args, **kwargs):
        raise RuntimeError

    monkeypatch.setattr(executor, "_arm_timer", fail)
    assert executor.restore_reminders() == 0
    assert executor.ACTIVE_REMINDERS[0]["_timer_error"] == "RuntimeError"
    assert "tạm dừng" in main._format_reminder(executor.ACTIVE_REMINDERS[0]).lower()


@pytest.mark.parametrize("retry_first", [False, True])
def test_callback_from_failed_start_is_ignored_before_and_after_retry(scheduler, retry_first):
    _write_pending()
    scheduler["start_error"] = RuntimeError
    assert executor.restore_reminders() == 0
    old = scheduler["timers"][0]
    assert old.cancelled
    if retry_first:
        scheduler["start_error"] = None
        assert executor.restore_reminders() == 1
    current = executor.ACTIVE_REMINDERS[0]["timer"]
    old.fire()
    assert executor.ACTIVE_REMINDERS[0]["timer"] is current
    assert scheduler["messages"] == []
    assert len(scheduler["timers"]) == 1 + int(retry_first)


@pytest.mark.parametrize("workers", [2, 8])
def test_concurrent_callbacks_start_exactly_one_successor(scheduler, workers):
    import threading

    executor._schedule_reminder("long", datetime.now() + timedelta(days=3))
    old = scheduler["timers"][0]
    barrier, errors = threading.Barrier(workers), []

    def invoke():
        try:
            barrier.wait(timeout=5)
            old.fire()
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=invoke, daemon=True) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert not any(thread.is_alive() for thread in threads)
    assert not errors
    assert len(scheduler["timers"]) == 2
    assert len(executor.ACTIVE_REMINDERS) == 1
    assert scheduler["messages"] == []
