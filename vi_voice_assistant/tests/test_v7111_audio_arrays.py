"""PCM16 and normalized float audio must keep amplitude, rate, and mono shape."""

import importlib
import struct
import sys
import types
import wave
from array import array

import pytest
import stt


def _normalize(audio, rate=16000):
    return importlib.import_module("audio_utils").normalize_mono(audio, sampling_rate=rate)


@pytest.fixture
def numpy_decoder(monkeypatch):
    np = types.ModuleType("numpy")
    np.float32 = "float32"
    np.asarray = lambda value, dtype=None: value
    monkeypatch.setitem(sys.modules, "numpy", np)
    return np


@pytest.mark.parametrize("code,values,expected", [
    ("h", [-32768, 0, 32767], [-1.0, 0.0, 32767 / 32768]),
    ("f", [-1.0, 0.0, 1.0], [-1.0, 0.0, 1.0]),
    ("d", [-0.5, 0.0, 0.5], [-0.5, 0.0, 0.5]),
])
def test_typed_mono_amplitude_is_normalized_without_mutating_input(code, values, expected):
    source = array(code, values)
    before = source.tobytes()
    assert list(_normalize(source)) == pytest.approx(expected)
    assert source.tobytes() == before


def test_float_numpy_style_input_is_not_divided_by_32768_again(numpy_decoder):
    class LegacyFloat(array):
        def astype(self, dtype):
            return self

        def __truediv__(self, scale):
            return array("f", (item / scale for item in self))

    source = LegacyFloat("f", [-1.0, 0.0, 1.0])
    seen = []
    instance = stt.STT()
    instance._pipe = lambda value: seen.append(value) or {"text": "ok"}
    assert instance.transcribe_array(source) == "ok"
    assert list(seen[0]["raw"]) == [-1.0, 0.0, 1.0]
    assert seen[0]["sampling_rate"] == 16000


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 1.01, -1.01])
def test_nonfinite_or_unscaled_float_samples_are_rejected(value):
    with pytest.raises(ValueError):
        _normalize(array("f", [value]))


@pytest.mark.parametrize("audio", [array("i", [1, 2]), array("B", [1, 2]), b"bytes", None,
                                  [0.0, 0.5]])
def test_ambiguous_or_unsupported_audio_format_is_rejected(audio):
    with pytest.raises((ValueError, TypeError)):
        _normalize(audio)


@pytest.mark.parametrize("code", ["h", "f"])
def test_empty_audio_is_rejected_before_backend(code):
    with pytest.raises(ValueError):
        _normalize(array(code))


@pytest.mark.parametrize("rate", [0, -1, True, 16000.0, "16000", 1000000])
def test_invalid_sampling_rate_is_rejected(rate):
    with pytest.raises((ValueError, TypeError)):
        _normalize(array("h", [1]), rate)


@pytest.mark.parametrize("rate", [8000, 16000])
def test_oversized_array_is_refused_instead_of_silently_truncated(rate):
    with pytest.raises(ValueError):
        _normalize(array("h", [0]) * (rate * 15 + 1), rate)


def test_two_dimensional_mono_can_be_squeezed_but_stereo_is_refused():
    raw = array("h", [0, 32767])
    mono = memoryview(raw).cast("B").cast("h", shape=[2, 1])
    assert list(_normalize(mono)) == pytest.approx([0, 32767 / 32768])
    stereo = memoryview(array("h", [0, 1, 2, 3])).cast("B").cast("h", shape=[2, 2])
    with pytest.raises(ValueError):
        _normalize(stereo)


@pytest.mark.parametrize("rate", [8000, 22050])
def test_local_pipeline_gets_actual_sample_rate(numpy_decoder, rate):
    instance = stt.STT()
    seen = []
    instance._pipe = lambda value: seen.append(value) or {"text": "ok"}
    assert instance.transcribe_array(array("h", [0, 100]), sampling_rate=rate) == "ok"
    assert seen[0]["sampling_rate"] == rate
    # These PCM fractions are exactly representable in float32; avoid asking
    # pytest to introspect the deliberately minimal NumPy decoder stub.
    assert list(seen[0]["raw"]) == [0.0, 100 / 32768]


def test_invalid_array_does_not_load_model_or_call_cloud(monkeypatch):
    instance = stt.STT(allow_cloud=True)
    called = []
    monkeypatch.setattr(instance, "_load_model", lambda: called.append("model"))
    monkeypatch.setattr(instance, "_google_from_array", lambda *a, **k: called.append("cloud"))
    assert instance.transcribe_array(array("f", [float("nan")])) == ""
    assert called == []


def test_google_wave_conversion_has_pcm16_bytes_and_requested_rate(monkeypatch):
    seen = []
    module = types.ModuleType("speech_recognition")
    module.UnknownValueError = type("UnknownValueError", (Exception,), {})

    class Recognizer:
        def record(self, source):
            return object()

        def recognize_google(self, audio, language=None):
            return "ok"

    class AudioFile:
        def __init__(self, buffer):
            self.buffer = buffer

        def __enter__(self):
            with wave.open(self.buffer, "rb") as stream:
                seen.append((stream.getframerate(), stream.getsampwidth(), stream.getnchannels(),
                             stream.readframes(stream.getnframes())))
            return self

        def __exit__(self, *args):
            return False

    module.Recognizer, module.AudioFile = Recognizer, AudioFile
    monkeypatch.setitem(sys.modules, "speech_recognition", module)
    instance = stt.STT(allow_cloud=True)
    instance._use_google = True
    assert instance.transcribe_array(array("f", [-1.0, 0.0, 1.0]), sampling_rate=8000) == "ok"
    assert seen[0][:3] == (8000, 2, 1)
    assert struct.unpack("<hhh", seen[0][3]) == (-32768, 0, 32767)


@pytest.mark.parametrize("numpy_present", [False, True])
@pytest.mark.parametrize("kind", ["pcm_buffer", "pcm_bytes", "float_buffer", "empty"])
def test_rms_is_consistent_for_supported_frames_with_or_without_numpy(monkeypatch,
                                                                     numpy_present, kind):
    import math

    monkeypatch.setitem(sys.modules, "numpy", types.ModuleType("numpy") if numpy_present else None)
    if kind == "pcm_buffer":
        signal, expected = array("h", [0, 32767]), (32767 / 32768) / math.sqrt(2)
    elif kind == "pcm_bytes":
        signal, expected = struct.pack("<hh", 0, 32767), (32767 / 32768) / math.sqrt(2)
    elif kind == "float_buffer":
        signal, expected = array("f", [0.0, 0.5]), 0.5 / math.sqrt(2)
    else:
        signal, expected = b"", 0.0
    assert math.isclose(stt._rms(signal), expected, rel_tol=1e-6, abs_tol=1e-9)
