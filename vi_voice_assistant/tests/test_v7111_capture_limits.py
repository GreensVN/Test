"""VAD budgets count waiting time and speaking time independently."""

import math
import sys
import types

import pytest
import stt


@pytest.fixture
def recording(monkeypatch):
    state = {"reads": 0, "entered": 0, "closed": 0, "voice": lambda index: True}

    class Chunk:
        def __init__(self, voiced):
            self.voiced = voiced

        def copy(self):
            return self

    class Joined:
        def __init__(self, length):
            self.length = length

        def flatten(self):
            return self

        def __len__(self):
            return self.length

    class Stream:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            state["entered"] += 1
            return self

        def __exit__(self, *args):
            state["closed"] += 1
            return False

        def read(self, size):
            index = state["reads"]
            state["reads"] += 1
            return Chunk(state["voice"](index)), False

    np = types.ModuleType("numpy")
    size = int(stt.SAMPLE_RATE * stt.CHUNK_DURATION)
    np.concatenate = lambda frames, axis=0: Joined(len(frames) * size)
    monkeypatch.setitem(sys.modules, "numpy", np)
    monkeypatch.setattr(stt, "_rms", lambda chunk: 1.0 if chunk.voiced else 0.0)
    return state, types.SimpleNamespace(InputStream=Stream)


def test_phrase_limit_begins_at_first_speech_not_after_unused_wait_budget(recording):
    state, device = recording
    result = stt._record_pcm_sd(timeout=1.0, phrase_limit=0.3, device=device)
    assert result is not None and state["reads"] == 3
    assert state["closed"] == 1


def test_late_speech_gets_only_its_own_phrase_budget(recording):
    state, device = recording
    state["voice"] = lambda index: index >= 5
    result = stt._record_pcm_sd(timeout=1.0, phrase_limit=0.3, device=device)
    assert result is not None and state["reads"] == 8


def test_initial_silence_stops_at_wait_deadline_without_extra_chunk(recording):
    state, device = recording
    state["voice"] = lambda index: False
    assert stt._record_pcm_sd(timeout=6, phrase_limit=8, device=device) is None
    assert state["reads"] == 60 and state["closed"] == 1


def test_tiny_positive_durations_still_allow_one_hardware_chunk(recording):
    state, device = recording
    assert stt._record_pcm_sd(timeout=0.01, phrase_limit=0.01, device=device) is not None
    assert state["reads"] == 1


def test_silence_threshold_rounds_up_instead_of_stopping_early(recording):
    state, device = recording
    state["voice"] = lambda index: index < 10
    assert stt._record_pcm_sd(timeout=6, phrase_limit=8, device=device) is not None
    assert state["reads"] == 10 + math.ceil(stt.SILENCE_DURATION / stt.CHUNK_DURATION)


@pytest.mark.parametrize("voiced", [False, True])
def test_total_duration_cap_remains_bounded(recording, voiced):
    state, device = recording
    state["voice"] = lambda index: voiced
    stt._record_pcm_sd(timeout=20, phrase_limit=20, device=device)
    assert state["reads"] <= math.ceil(stt.MAX_DURATION / stt.CHUNK_DURATION)
    assert state["closed"] == 1


@pytest.mark.parametrize("duration", [0, -1, float("nan"), True])
def test_invalid_phrase_duration_never_opens_microphone(recording, duration):
    state, device = recording
    with pytest.raises(ValueError):
        stt._record_pcm_sd(timeout=6, phrase_limit=duration, device=device)
    assert state["entered"] == state["reads"] == 0


@pytest.mark.parametrize("expected,actual,options,wanted", [
    ([1.0, 2.0], [1.0, 2.000001], {}, True),
    ((1.0, 2.0), (1.0, 2.000001), {}, True),
    ({"a": 1.0}, {"a": 1.0000001}, {}, True),
    ([1.0], [1.0, 2.0], {}, False),
    ({"a": 1.0}, {"b": 1.0}, {}, False),
    (0.0, 5e-13, {}, True),
    (1e8, 1e8 + 10, {"abs": 1.0}, False),
    (1e8, 1e8 + 10, {"abs": 1.0, "rel": 1e-6}, True),
    (float("inf"), float("inf"), {}, True),
    (float("inf"), 100.0, {}, False),
    (float("nan"), float("nan"), {}, False),
    (float("nan"), float("nan"), {"nan_ok": True}, True),
])
def test_embedded_approx_matches_flat_container_and_scalar_semantics(expected, actual, options,
                                                                  wanted):
    import run_tests

    approximate = run_tests._make_pytest_shim().approx(expected, **options)
    assert bool(actual == approximate) is wanted
    assert bool(actual == pytest.approx(expected, **options)) is wanted


@pytest.mark.parametrize("options", [{"rel": -1}, {"abs": -1}, {"abs": float("nan")}])
def test_embedded_approx_rejects_invalid_tolerances(options):
    import run_tests

    with pytest.raises(ValueError):
        assert 2.0 == run_tests._make_pytest_shim().approx(1.0, **options)


def test_embedded_approx_does_not_pretend_to_support_nested_containers():
    import run_tests

    with pytest.raises(TypeError):
        run_tests._make_pytest_shim().approx([[1.0]])
