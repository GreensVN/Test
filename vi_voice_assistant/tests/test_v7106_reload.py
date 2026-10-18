"""Profile reload and invocation consent must not silently drift between layers."""

import copy
import threading
import types
from concurrent.futures import ThreadPoolExecutor

import config
import executor
import main
import nlu_advanced as nlu
import pytest


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setattr(executor, "CONFIG", copy.deepcopy(config.DEFAULT_CONFIG))
    monkeypatch.setattr(executor, "CONFIG_ERROR", None)
    monkeypatch.setattr(executor, "CONFIDENCE_THRESHOLD", 0.35)
    monkeypatch.setattr(executor, "DANGEROUS_ACTIONS", {"shutdown", "restart", "logout", "sleep"})
    monkeypatch.setattr(executor, "_ACTIVE_CONFIG_PATH", None, raising=False)
    monkeypatch.setattr(executor, "AUTO_CONFIRM", False)
    monkeypatch.setattr(executor, "SPEAK_ENABLED", False)
    monkeypatch.setattr(nlu, "CONFIDENCE_ACCEPT", 0.4)
    monkeypatch.setattr(nlu, "CONFIDENCE_ASK", 0.25)
    monkeypatch.setattr(nlu, "DANGEROUS_TARGETS", {"shutdown", "restart", "logout", "sleep"})
    return executor


def _profile(path, marker, *, accept=0.8, ask=0.2, threshold=0.6, dangerous=None):
    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg.update(marker=marker, confidence_accept=accept, confidence_ask=ask,
               confidence_threshold=threshold,
               dangerous_actions=["lock"] if dangerous is None else dangerous)
    config.save_config(cfg, path)
    return cfg


def _snapshot():
    return (copy.deepcopy(executor.CONFIG), executor.CONFIDENCE_THRESHOLD,
            set(executor.DANGEROUS_ACTIONS), executor.CONFIG_ERROR,
            nlu.CONFIDENCE_ACCEPT, nlu.CONFIDENCE_ASK, set(nlu.DANGEROUS_TARGETS))


def test_reload_without_path_keeps_last_successful_custom_profile(runtime, tmp_path):
    target = tmp_path / "custom.json"
    _profile(target, "first")
    identity = executor.CONFIG
    executor.reload_config(target)
    _profile(target, "second", accept=0.9, ask=0.7)
    assert executor.reload_config() is identity
    assert executor.CONFIG["marker"] == "second"
    assert nlu.CONFIDENCE_ACCEPT == 0.9 and nlu.CONFIDENCE_ASK == 0.7


def test_relative_profile_is_pinned_after_working_directory_changes(runtime, tmp_path, monkeypatch):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    _profile(first / "custom.json", "chosen")
    monkeypatch.chdir(first)
    executor.reload_config("custom.json")
    monkeypatch.chdir(second)
    executor.reload_config()
    assert executor.CONFIG["marker"] == "chosen"


def test_failed_profile_does_not_replace_active_file_or_runtime_values(runtime, tmp_path):
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    _profile(good, "good")
    bad.write_text("{")
    executor.reload_config(good)
    before = _snapshot()
    with pytest.raises(RuntimeError):
        executor.reload_config(bad)
    assert _snapshot() == before
    _profile(good, "still active")
    executor.reload_config()
    assert executor.CONFIG["marker"] == "still active"


def test_nlu_refresh_failure_is_not_reported_as_success(runtime, tmp_path, monkeypatch):
    target = tmp_path / "new.json"
    _profile(target, "new")
    before = _snapshot()

    def fail(cfg):
        raise RuntimeError("NLU refresh unavailable")

    monkeypatch.setattr(nlu, "refresh_thresholds", fail)
    with pytest.raises(RuntimeError, match="refresh unavailable"):
        executor.reload_config(target)
    assert _snapshot() == before


def test_partial_nlu_failure_rolls_back_known_policy_fields(runtime, tmp_path, monkeypatch):
    target = tmp_path / "new.json"
    _profile(target, "new")
    before = _snapshot()

    def fail(cfg):
        nlu.CONFIDENCE_ACCEPT = 0.99
        nlu.DANGEROUS_TARGETS.add("partial")
        raise RuntimeError("partial refresh")

    monkeypatch.setattr(nlu, "refresh_thresholds", fail)
    with pytest.raises(RuntimeError, match="partial refresh"):
        executor.reload_config(target)
    assert _snapshot() == before


@pytest.mark.parametrize("dangerous", [None, "shutdown", 123, [None], [1], [""]])
def test_bad_nlu_policy_is_rejected_before_mutating_thresholds(runtime, dangerous):
    before = _snapshot()
    with pytest.raises((TypeError, ValueError)):
        nlu.refresh_thresholds({"confidence_accept": 0.9, "confidence_ask": 0.8,
                                "dangerous_actions": dangerous})
    assert _snapshot() == before


@pytest.mark.parametrize("cfg", [1, [], False, "text"])
def test_wrong_refresh_root_does_not_partially_reset_state(runtime, cfg):
    before = _snapshot()
    with pytest.raises(TypeError):
        nlu.refresh_thresholds(cfg)
    assert _snapshot() == before


@pytest.mark.parametrize("dangerous", [[], ["lock"], ["shutdown", "custom"]])
def test_explicit_dangerous_policy_is_identical_in_both_layers(runtime, tmp_path, dangerous):
    target = tmp_path / "profile.json"
    _profile(target, "policy", dangerous=dangerous)
    executor.reload_config(target)
    assert executor.DANGEROUS_ACTIONS == nlu.DANGEROUS_TARGETS == set(dangerous)
    assert nlu.NLU._judge({"intent": "system_control", "target": "shutdown", "confidence": 0}) \
        == "unknown"
    if not dangerous:
        assert nlu.NLU._judge({"intent": "system_control", "target": "shutdown",
                               "confidence": 1}) == "ok"


def test_unavailable_nlu_cannot_leave_executor_on_a_new_policy(runtime, tmp_path, monkeypatch):
    import sys

    target = tmp_path / "profile.json"
    _profile(target, "new")
    before = _snapshot()
    monkeypatch.setitem(sys.modules, "nlu_advanced", None)
    with pytest.raises(ImportError):
        executor.reload_config(target)
    assert _snapshot() == before


def test_judgment_waits_for_a_cooperating_reload_to_commit(runtime, tmp_path, monkeypatch):
    target = tmp_path / "profile.json"
    _profile(target, "strict", accept=0.9, ask=0.8)
    original = nlu.refresh_thresholds
    entered, release, judged = threading.Event(), threading.Event(), threading.Event()

    def refresh(cfg):
        entered.set()
        assert release.wait(timeout=5)
        return original(cfg)

    def judge():
        result = nlu.NLU._judge({"intent": "chitchat", "target": "hello", "confidence": 0.5})
        judged.set()
        return result

    monkeypatch.setattr(nlu, "refresh_thresholds", refresh)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reloading = pool.submit(executor.reload_config, target)
        assert entered.wait(timeout=5)
        reading = pool.submit(judge)
        before_commit = judged.wait(timeout=0.1)
        release.set()
        reloading.result(timeout=5)
        status = reading.result(timeout=5)
    assert not before_commit and status == "unknown"
    assert executor.CONFIG["marker"] == "strict"


@pytest.mark.parametrize("yes", [False, True])
def test_cli_applies_current_confirmation_flag_not_previous_invocation(runtime, monkeypatch, yes):
    monkeypatch.setattr(executor, "AUTO_CONFIRM", True)
    args = types.SimpleNamespace(yes=yes, config=None, engine=None)
    assert main._apply_cli_options(args) is None
    assert executor.AUTO_CONFIRM is yes


def test_repeated_cli_options_do_not_leak_yes(runtime):
    args = types.SimpleNamespace(yes=True, config=None, engine=None)
    assert main._apply_cli_options(args) is None
    assert executor.AUTO_CONFIRM is True
    args = types.SimpleNamespace(yes=False, config=None, engine=None)
    assert main._apply_cli_options(args) is None
    assert executor.AUTO_CONFIRM is False


@pytest.mark.parametrize("yes", [False, True])
def test_failed_cli_config_never_leaves_auto_confirm_armed(runtime, tmp_path, monkeypatch, yes):
    target = tmp_path / "bad.json"
    target.write_text("{")
    monkeypatch.setattr(executor, "AUTO_CONFIRM", True)
    args = types.SimpleNamespace(yes=yes, config=str(target), engine=None)
    assert main._apply_cli_options(args) == 1
    assert executor.AUTO_CONFIRM is False


@pytest.mark.parametrize("speak", [False, True])
def test_speech_is_not_enabled_by_a_previous_invocation(runtime, monkeypatch, speak):
    import sys

    monkeypatch.setattr(executor, "SPEAK_ENABLED", True)
    monkeypatch.setitem(sys.modules, "tts", types.SimpleNamespace(is_available=lambda: False))
    main._warn_missing_optional_features(types.SimpleNamespace(voice=False, speak=speak))
    assert executor.SPEAK_ENABLED is False


def test_missing_dangerous_key_retains_safe_default_policy(runtime):
    nlu.refresh_thresholds({})
    assert {"shutdown", "restart", "logout", "sleep"} <= nlu.DANGEROUS_TARGETS


def test_current_config_source_is_available_as_an_absolute_path(runtime):
    assert executor.current_config_path().is_absolute()
