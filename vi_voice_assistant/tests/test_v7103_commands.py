"""Short utilities must finish successfully; GUI launch requests remain async."""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

import executor
import pytest

PLATFORMS = [
    ("Linux", "volume_up", False), ("Linux", "lock", False),
    ("Darwin", "mute", False), ("Darwin", "lock", False),
    ("Windows", "mute", False), ("Windows", "lock", False),
    ("Linux", "volume_up", True), ("Linux", "lock", True),
    ("Darwin", "screenshot", False), ("Windows", "screenshot", False),
    ("Linux", "screenshot", False), ("Linux", "screenshot", True),
]


@pytest.fixture
def runner(monkeypatch, tmp_path):
    state = {"calls": [], "async": [], "results": [], "output": []}

    def run(cmd, **kwargs):
        state["calls"].append((cmd, kwargs))
        result = state["results"].pop(0) if state["results"] else 0
        if isinstance(result, BaseException):
            raise result
        if kwargs.get("check") and type(result) is int and result != 0:
            raise subprocess.CalledProcessError(result, cmd)
        return subprocess.CompletedProcess(cmd, result, stdout="mock-screenshot.png")

    def popen(cmd, **kwargs):
        state["async"].append(cmd)
        return object()

    monkeypatch.setattr(executor.subprocess, "run", run)
    monkeypatch.setattr(executor.subprocess, "Popen", popen)
    monkeypatch.setattr(executor, "safe_print", state["output"].append)
    monkeypatch.setattr(executor, "_confirm", lambda prompt: True)
    monkeypatch.setattr(executor, "_volume_via_pycaw", lambda target: None)
    monkeypatch.setattr(executor, "HOME", str(tmp_path))
    return state


@pytest.mark.parametrize("codes,expected,count", [([1, 0], True, 2), ([0, 1], True, 1),
                                                ([3, 4], False, 2)])
def test_fallback_observes_exit_codes_not_just_process_creation(runner, codes, expected, count):
    runner["results"] = codes
    assert executor._run_first_available([["one"], ["two"]]) is expected
    assert len(runner["calls"]) == count
    assert runner["async"] == []


@pytest.mark.parametrize("code", [1, 7, 19])
def test_real_failed_python_utility_is_not_reported_as_success(code):
    assert executor._run_first_available([
        [sys.executable, "-c", f"raise SystemExit({code})"]
    ]) is False


def test_real_successful_python_utility_still_works():
    assert executor._run_first_available([[sys.executable, "-c", "pass"]]) is True


def test_real_fallback_runs_after_installed_tool_fails(tmp_path):
    marker = tmp_path / "fallback.txt"
    assert executor._run_first_available([
        [sys.executable, "-c", "raise SystemExit(7)"],
        [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('ok')"],
    ]) is True
    assert marker.read_text() == "ok"


def test_timeout_stops_instead_of_repeating_an_ambiguous_action(runner):
    runner["results"] = [subprocess.TimeoutExpired("one", 0.1), 0]
    assert executor._run_first_available([["one"], ["two"]]) is False
    assert [cmd for cmd, _ in runner["calls"]] == [["one"]]
    assert runner["async"] == []


def test_real_timeout_is_bounded(monkeypatch):
    monkeypatch.setattr(executor, "_COMMAND_TIMEOUT", 0.02, raising=False)
    assert executor._run_first_available([
        [sys.executable, "-c", "import time; time.sleep(0.2)"]
    ]) is False


def test_fallback_chain_shares_one_monotonic_time_budget(runner, monkeypatch):
    ticks = iter([100.0, 101.0, 104.0])
    monkeypatch.setattr(executor, "_COMMAND_TIMEOUT", 15.0, raising=False)
    monkeypatch.setattr(executor.time, "monotonic", lambda: next(ticks))
    runner["results"] = [1, 0]
    assert executor._run_first_available([["one"], ["two"]]) is True
    assert [options["timeout"] for _, options in runner["calls"]] == [14.0, 11.0]
    for _, options in runner["calls"]:
        assert options["stdout"] is subprocess.DEVNULL
        assert options["stderr"] is subprocess.DEVNULL
        assert options.get("check", False) is False
        assert not options.get("shell", False)


@pytest.mark.parametrize("code", [None, False, True, "0", 0.0])
def test_unreadable_exit_status_fails_closed_without_running_fallback(runner, code):
    runner["results"] = [code, 0]
    assert executor._run_first_available([["one"], ["two"]]) is False
    assert len(runner["calls"]) == 1


@pytest.mark.parametrize("error,count,expected", [
    (FileNotFoundError("missing"), 2, True),
    (PermissionError("denied"), 2, True),
    (RuntimeError("unknown execution state"), 1, False),
])
def test_known_spawn_failures_can_fall_back_but_unknown_failures_stop(runner, error, count,
                                                                   expected):
    runner["results"] = [error, 0]
    assert executor._run_first_available([["one"], ["two"]]) is expected
    assert len(runner["calls"]) == count
    assert runner["async"] == []


@pytest.mark.parametrize("system,target,wsl", PLATFORMS)
def test_platform_utilities_propagate_nonzero_exit_status(runner, monkeypatch, system,
                                                         target, wsl):
    monkeypatch.setattr(executor, "SYSTEM", system)
    monkeypatch.setattr(executor, "is_wsl", lambda: wsl)
    runner["results"] = [1] * 20
    assert executor.action_system_control(target) is False
    assert runner["calls"] and runner["async"] == []
    assert not any("Đã chụp" in line for line in runner["output"])


@pytest.mark.parametrize("system,target,wsl", PLATFORMS)
def test_platform_utilities_still_accept_successful_exit(runner, monkeypatch, system,
                                                        target, wsl):
    monkeypatch.setattr(executor, "SYSTEM", system)
    monkeypatch.setattr(executor, "is_wsl", lambda: wsl)
    assert executor.action_system_control(target) is True
    assert runner["calls"] and runner["async"] == []


def test_declined_confirmation_never_starts_a_utility(runner, monkeypatch):
    monkeypatch.setattr(executor, "SYSTEM", "Linux")
    monkeypatch.setattr(executor, "_confirm", lambda prompt: False)
    assert executor.action_system_control("shutdown") is False
    assert runner["calls"] == runner["async"] == []


@pytest.mark.parametrize("system,kind", [
    ("Linux", "app"), ("Darwin", "app"), ("Windows", "app"),
    ("Linux", "wsl_url"), ("Linux", "wsl_file"),
])
def test_gui_launch_requests_do_not_wait_for_app_exit(runner, monkeypatch, tmp_path, system, kind):
    monkeypatch.setattr(executor, "SYSTEM", system)
    monkeypatch.setattr(executor, "is_wsl", lambda: kind.startswith("wsl"))
    if kind == "app":
        assert executor.action_open_app("chrome") is True
    elif kind == "wsl_url":
        assert executor._open_url("https://example.com") is True
    else:
        path = tmp_path / "document.txt"
        path.write_text("safe")
        assert executor._open_path(str(path)) is True
    assert len(runner["async"]) == 1
    assert runner["calls"] == []


def test_type_error_never_retries_the_same_launch(monkeypatch):
    calls = []

    def fail(cmd, **kwargs):
        calls.append(cmd)
        raise TypeError("invalid process argument")

    monkeypatch.setattr(executor.subprocess, "Popen", fail)
    with pytest.raises(TypeError):
        executor._popen(["application"])
    assert calls == [["application"]]


def test_screenshot_names_cannot_collide_within_same_clock_tick(monkeypatch, tmp_path):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 18, 12, 30, 45)

    monkeypatch.setattr(executor.datetime, "datetime", Frozen)
    monkeypatch.setattr(executor, "HOME", str(tmp_path))
    paths = [executor._screenshot_path() for _ in range(4)]
    assert len(set(paths)) == 4
    assert all(path.parent == Path(tmp_path) / "Pictures" for path in paths)


def test_exhausted_chain_budget_does_not_start_another_tool(runner, monkeypatch):
    ticks = iter([100.0, 100.0, 116.0])
    monkeypatch.setattr(executor.time, "monotonic", lambda: next(ticks))
    runner["results"] = [1, 0]
    assert executor._run_first_available([["one"], ["two"]]) is False
    assert [cmd for cmd, _ in runner["calls"]] == [["one"]]


def test_wsl_screenshot_uses_random_suffix_and_checks_process_status(runner, monkeypatch):
    monkeypatch.setattr(executor, "SYSTEM", "Linux")
    monkeypatch.setattr(executor, "is_wsl", lambda: True)
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="C:\\Pictures\\screenshot.png\n")

    monkeypatch.setattr(executor.subprocess, "run", run)
    assert executor.action_system_control("screenshot") is True
    assert "[Guid]::NewGuid().ToString('N')" in calls[0][0][-1]
    assert calls[0][1]["check"] is True
    assert 0 < calls[0][1]["timeout"] <= 15
    assert runner["async"] == []


def test_wsl_browser_fallback_still_only_launches_apps(runner, monkeypatch):
    monkeypatch.setattr(executor, "SYSTEM", "Linux")
    monkeypatch.setattr(executor, "is_wsl", lambda: True)
    calls = []

    def popen(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "wslview":
            raise FileNotFoundError("wslview")
        return object()

    monkeypatch.setattr(executor.subprocess, "Popen", popen)
    assert executor._open_url("https://example.com") is True
    assert [cmd[0] for cmd in calls] == ["wslview", "explorer.exe"]
    assert runner["calls"] == []


def test_windows_screenshot_cannot_leak_child_output_into_json_stdout(runner):
    assert executor._windows_screenshot() is True
    _, options = runner["calls"][0]
    assert options["stdout"] is subprocess.DEVNULL
    assert options["stderr"] is subprocess.DEVNULL
    assert 0 < options["timeout"] <= 15
