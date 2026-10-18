"""Cloud opt-in does not imply unbounded requests or public/leaked temp audio."""

import os
import sys
import types
from pathlib import Path

import pytest
import stt
import tts


@pytest.fixture
def recognition(monkeypatch):
    calls = []
    module = types.ModuleType("speech_recognition")
    module.UnknownValueError = type("UnknownValueError", (Exception,), {})
    module.RequestError = type("RequestError", (Exception,), {})

    class Recognizer:
        operation_timeout = None

        def recognize_google(self, audio, language=None):
            calls.append((self.operation_timeout, language))
            assert isinstance(self.operation_timeout, (int, float))
            assert 0 < self.operation_timeout <= 15
            return "recognized"

    module.Recognizer = Recognizer
    monkeypatch.setitem(sys.modules, "speech_recognition", module)
    monkeypatch.setattr(stt, "_sr", module)
    monkeypatch.setattr(stt, "ENGINE", "google")
    monkeypatch.setattr(stt, "ALLOW_CLOUD", True)
    return module, calls


def test_module_google_recognizer_has_finite_network_timeout(recognition):
    module, calls = recognition
    assert stt._recognize(module.Recognizer(), object(), "vi-VN") == "recognized"
    assert len(calls) == 1 and calls[0][1] == "vi-VN"


def test_class_google_timeout_is_reapplied_to_cached_recognizer(recognition):
    module, calls = recognition
    instance = stt.STT(allow_cloud=True)
    instance._recognizer = module.Recognizer()
    assert instance._google_transcribe(object()) == "recognized"
    instance._recognizer.operation_timeout = None
    assert instance._google_transcribe(object()) == "recognized"
    assert len(calls) == 2


@pytest.mark.parametrize("route", ["module", "class"])
def test_cloud_is_refused_if_timeout_cannot_be_applied(recognition, route):
    _, calls = recognition

    class NoDeadline:
        __slots__ = ()

        def recognize_google(self, audio, language=None):
            calls.append((None, language))
            return "should not send"

    if route == "module":
        assert stt._recognize(NoDeadline(), object(), "vi-VN") == ""
    else:
        instance = stt.STT(allow_cloud=True)
        instance._recognizer = NoDeadline()
        assert instance._google_transcribe(object()) == ""
    assert calls == []


def test_timeout_is_soft_failure_without_an_automatic_network_retry(recognition):
    module, calls = recognition

    class TimedOut(module.Recognizer):
        def recognize_google(self, audio, language=None):
            calls.append((self.operation_timeout, language))
            raise TimeoutError("cloud timed out")

    instance = stt.STT(allow_cloud=True)
    instance._recognizer = TimedOut()
    assert instance._google_transcribe(object()) == ""
    assert len(calls) == 1 and 0 < calls[0][0] <= 15
    assert instance._google_failures == 1


def test_denied_cloud_does_not_construct_or_call_recognizer(recognition):
    _, calls = recognition
    assert stt.STT()._google_transcribe(object()) == ""
    assert calls == []


@pytest.fixture
def gtts_backend(monkeypatch, tmp_path):
    calls = {"options": [], "paths": [], "played": [], "failure": None}
    module = types.ModuleType("gtts")

    class GoogleTTS:
        def __init__(self, **kwargs):
            calls["options"].append(kwargs)

        def save(self, name):
            path = Path(name)
            calls["paths"].append(path)
            path.write_bytes(b"partial mp3")
            if calls["failure"] == "save":
                raise TimeoutError("HTTP timeout")
            if calls["failure"] == "cancel":
                raise KeyboardInterrupt("cancelled")

    module.gTTS = GoogleTTS
    monkeypatch.setitem(sys.modules, "gtts", module)
    monkeypatch.setattr(tts, "ENGINE", "gtts")
    monkeypatch.setattr(tts, "ALLOW_CLOUD", True)
    monkeypatch.setattr(tts, "SYSTEM", "Linux")
    monkeypatch.setattr(tts.tempfile, "tempdir", str(tmp_path))

    def play(path):
        calls["played"].append(path)
        if calls["failure"] == "play":
            raise OSError("player unavailable")
        return True

    monkeypatch.setattr(tts, "_play_audio", play)
    return calls


@pytest.mark.parametrize("route", ["speak", "cache"])
def test_gtts_receives_connect_and_read_timeout(gtts_backend, tmp_path, route):
    if route == "speak":
        assert tts._speak_gtts("explicit text") is True
    else:
        assert tts._write_gtts("explicit text", tmp_path / "cache.mp3") is True
    value = gtts_backend["options"][0].get("timeout")
    durations = value if isinstance(value, tuple) else (value,)
    assert durations
    assert all(isinstance(item, (int, float)) and 0 < item <= 15 for item in durations)


@pytest.mark.parametrize("failure", ["save", "play", "cancel"])
def test_transient_gtts_audio_is_cleaned_after_failure_or_cancel(gtts_backend, tmp_path, failure):
    gtts_backend["failure"] = failure
    if failure == "cancel":
        with pytest.raises(KeyboardInterrupt):
            tts._speak_gtts("private text")
    else:
        assert tts._speak_gtts("private text") is False
    assert gtts_backend["paths"]
    assert not any(path.exists() for path in gtts_backend["paths"])
    assert list(tmp_path.iterdir()) == []


def test_successful_transient_audio_has_private_owner_directory(gtts_backend, monkeypatch,
                                                              tmp_path):
    public = tmp_path / "shared-temp"
    public.mkdir()
    if os.name != "nt":
        public.chmod(0o777)
    monkeypatch.setattr(tts.tempfile, "tempdir", str(public))

    def play(path):
        if os.name != "nt":
            assert path.parent.stat().st_mode & 0o077 == 0
        return True

    monkeypatch.setattr(tts, "_play_audio", play)
    assert tts._speak_gtts("private text") is True
    assert not gtts_backend["paths"][0].exists()


def test_revoked_cloud_allocates_no_audio_and_makes_no_request(gtts_backend, monkeypatch):
    monkeypatch.setattr(tts, "ENGINE", "auto")
    monkeypatch.setattr(tts, "ALLOW_CLOUD", False)
    assert tts._speak_gtts("must not upload") is False
    assert gtts_backend["paths"] == gtts_backend["options"] == []


def test_failed_cloud_cache_writer_removes_partial_output(gtts_backend, monkeypatch, tmp_path):
    gtts_backend["failure"] = "save"
    monkeypatch.setattr(tts, "_WRITERS", (("gtts", ".mp3", tts._write_gtts, lambda: True),))
    directory = tmp_path / "cache"
    result = tts.prewarm("explicit text", engine="gtts", out_dir=directory)
    assert result["failed"] == 1 and result["written"] == 0
    assert list(directory.iterdir()) == []
    assert gtts_backend["played"] == []
