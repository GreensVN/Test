"""Data roots stay native, absolute, and coherent across cache races."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import paths
import pytest


@pytest.fixture
def directory_env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    for key in ("VI_ASSISTANT_HOME", "XDG_DATA_HOME", "LOCALAPPDATA"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(paths, "_cached", None)
    monkeypatch.setattr(paths, "_verbose", [])
    monkeypatch.setattr(paths, "is_source_checkout", lambda directory=None: False)
    original = os.path.expanduser
    monkeypatch.setattr(paths.os.path, "expanduser", lambda value: str(home) if value == "~"
                        else original(value))
    return home


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_native_directory_policy_ignores_unrelated_xdg_on_mac_and_windows(directory_env, tmp_path,
                                                                        monkeypatch, platform):
    xdg, windows = tmp_path / "xdg", tmp_path / "local-app-data"
    monkeypatch.setattr(paths.sys, "platform", platform)
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    monkeypatch.setenv("LOCALAPPDATA", str(windows))
    expected = {"linux": xdg, "darwin": directory_env / "Library" / "Application Support",
                "win32": windows}[platform] / "vi_voice_assistant"
    assert paths._user_data_dir() == expected


@pytest.mark.parametrize("value", ["relative", "../escape", "~/.cache", ""])
def test_relative_xdg_values_are_ignored_instead_of_following_cwd(directory_env, monkeypatch,
                                                               value):
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", value)
    expected = directory_env / ".local" / "share" / "vi_voice_assistant"
    assert paths._user_data_dir() == expected
    assert paths.data_dir() == expected and expected.is_absolute()


@pytest.mark.parametrize("value", ["relative", "../escape", ""])
def test_relative_localappdata_does_not_place_data_in_working_directory(directory_env, monkeypatch,
                                                                      value):
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", value)
    assert paths._user_data_dir() == directory_env / "AppData" / "Local" / "vi_voice_assistant"


@pytest.mark.parametrize("relative", [False, True])
def test_explicit_override_stays_pinned_after_cwd_changes(directory_env, tmp_path, monkeypatch,
                                                        relative):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.chdir(first)
    monkeypatch.setenv("VI_ASSISTANT_HOME", "data" if relative else str(first / "data"))
    root = paths.data_dir()
    monkeypatch.chdir(second)
    assert root.is_absolute() and paths.data_dir() == root
    assert paths.data_path("config.json").parent == root


def test_invalid_override_falls_back_without_import_time_value_error(directory_env, monkeypatch):
    # The OS rejects NUL in real environment values; inject an application
    # environment mapping to exercise a ValueError from path creation itself.
    monkeypatch.setattr(paths.os, "environ", dict(os.environ, VI_ASSISTANT_HOME="bad\x00directory"))
    root = paths.data_dir()
    assert root.is_absolute() and root.is_dir()
    assert "\x00" not in str(root)


def test_relative_temp_factory_result_is_pinned_as_absolute(directory_env, tmp_path, monkeypatch):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "fallback").mkdir()
    blocked = tmp_path / "blocked"
    blocked.write_text("file, not a directory")
    monkeypatch.chdir(first)
    monkeypatch.setenv("VI_ASSISTANT_HOME", str(blocked))
    monkeypatch.setattr(paths.tempfile, "mkdtemp", lambda **kwargs: "fallback")
    root = paths.data_dir()
    monkeypatch.chdir(second)
    assert root == first / "fallback" and root.is_absolute()
    assert paths.data_path("config.json").parent == root


@pytest.mark.parametrize("workers", [2, 8])
def test_concurrent_fallback_initialization_selects_only_one_root(directory_env, tmp_path,
                                                                 monkeypatch, workers):
    blocked = tmp_path / "blocked"
    blocked.write_text("file")
    monkeypatch.setenv("VI_ASSISTANT_HOME", str(blocked))
    original = paths.tempfile.mkdtemp
    entered, release, other_done = threading.Event(), threading.Event(), threading.Event()
    barrier, guard, calls = threading.Barrier(workers), threading.Lock(), []

    def create(**kwargs):
        result = original(dir=tmp_path, **kwargs)
        with guard:
            calls.append(result)
            first = len(calls) == 1
        if first:
            entered.set()
            assert release.wait(timeout=5)
        return result

    def choose():
        barrier.wait(timeout=5)
        root = paths.data_dir()
        if not release.is_set():
            other_done.set()
        return root

    monkeypatch.setattr(paths.tempfile, "mkdtemp", create)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(choose) for _ in range(workers)]
        try:
            assert entered.wait(timeout=5)
            other_done.wait(timeout=0.2)
        finally:
            release.set()
        roots = [future.result(timeout=5) for future in futures]
    assert len(set(roots)) == 1 and len(calls) == 1


def test_reset_waits_for_inflight_initialization_instead_of_reviving_old_root(
        directory_env, tmp_path, monkeypatch):
    first, second = tmp_path / "first", tmp_path / "second"
    entered, release, reset_done = threading.Event(), threading.Event(), threading.Event()
    original = Path.mkdir
    monkeypatch.setenv("VI_ASSISTANT_HOME", str(first))

    def mkdir(path, *args, **kwargs):
        if path == first:
            entered.set()
            assert release.wait(timeout=5)
        return original(path, *args, **kwargs)

    def reset():
        paths.reset_cache()
        reset_done.set()

    monkeypatch.setattr(Path, "mkdir", mkdir)
    with ThreadPoolExecutor(max_workers=2) as pool:
        choosing = pool.submit(paths.data_dir)
        assert entered.wait(timeout=5)
        monkeypatch.setenv("VI_ASSISTANT_HOME", str(second))
        resetting = pool.submit(reset)
        reset_done.wait(timeout=0.1)
        release.set()
        assert choosing.result(timeout=5) == first
        resetting.result(timeout=5)
    assert paths.data_dir() == second


def test_foreign_pyproject_beside_installed_package_is_not_a_checkout(tmp_path):
    package = tmp_path / "site-packages" / "vi_voice_assistant"
    package.mkdir(parents=True)
    (package.parent / "pyproject.toml").write_text('[project]\nname="unrelated"')
    (package / "run_tests.py").write_text("# this file also ships in the wheel")
    assert paths.is_source_checkout(package) is False


def test_real_source_layout_with_tests_is_still_detected(tmp_path):
    package = tmp_path / "vi_voice_assistant"
    (package / "tests").mkdir(parents=True)
    (package.parent / "pyproject.toml").write_text('[project]\nname="vi-voice-assistant"')
    assert paths.is_source_checkout(package) is True


def test_failed_fallback_is_not_cached_and_can_retry(directory_env, tmp_path, monkeypatch):
    blocked, valid = tmp_path / "blocked", tmp_path / "valid"
    blocked.write_text("file")
    monkeypatch.setenv("VI_ASSISTANT_HOME", str(blocked))

    def fail(**kwargs):
        raise OSError("no temporary directory")

    monkeypatch.setattr(paths.tempfile, "mkdtemp", fail)
    with pytest.raises(OSError, match="no temporary directory"):
        paths.data_dir()
    assert paths._cached is None
    monkeypatch.setenv("VI_ASSISTANT_HOME", str(valid))
    assert paths.data_dir() == valid
