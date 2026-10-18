"""Speech transport is opt-in; local mode must not silently become a cloud request."""

import sys
import types
from array import array

import pytest
import stt
import tts


@pytest.fixture
def speech(monkeypatch):
    calls = []
    sr = types.ModuleType("speech_recognition")
    sr.Recognizer = lambda: object()
    monkeypatch.setattr(stt, "_sr", sr, raising=False)
    monkeypatch.setattr(stt, "_SR_AVAILABLE", True)
    monkeypatch.setattr(stt, "_SD_AVAILABLE", True)
    monkeypatch.setattr(stt, "ENGINE", "auto", raising=False)
    monkeypatch.setattr(stt, "ALLOW_CLOUD", False, raising=False)
    monkeypatch.setattr(stt, "ALLOW_DOWNLOAD", False, raising=False)
    monkeypatch.setattr(stt, "_default_instance", None)
    monkeypatch.setattr(stt, "_offline_available", lambda: True, raising=False)
    monkeypatch.setattr(stt, "_capture_audio", lambda *a, **k: (object(), False))
    monkeypatch.setattr(stt, "_recognize", lambda *a, **k: calls.append("cloud") or "cloud")
    monkeypatch.setattr(tts, "ENGINE", "auto")
    monkeypatch.setattr(tts, "ALLOW_CLOUD", False, raising=False)
    monkeypatch.setattr(tts, "_resolved_engine", None)
    monkeypatch.setattr(tts, "ENABLED", True)
    monkeypatch.setattr(tts, "_speak_cache", lambda text: False)
    monkeypatch.setattr(tts, "_load_voice_cache", lambda: {})
    for name in ("_speak_piper", "_speak_pyttsx3", "_speak_sapi", "_speak_macos"):
        monkeypatch.setattr(tts, name, lambda text: False)
    monkeypatch.setattr(tts, "_vieneu_ready", lambda: False, raising=False)
    return calls


def _offline(monkeypatch, *, broken=False):
    class Local:
        def listen(self, *args, **kwargs):
            if broken:
                raise RuntimeError("no cached model")
            return "local"

    monkeypatch.setattr(stt, "_default_stt", lambda: Local())


def test_default_stt_prefers_local_even_when_google_library_is_installed(speech, monkeypatch):
    _offline(monkeypatch)
    monkeypatch.setattr(stt, "is_available", lambda: True)
    assert stt.listen_once() == "local"
    assert speech == []


def test_default_stt_failure_never_sends_audio_to_google(speech, monkeypatch):
    _offline(monkeypatch, broken=True)
    monkeypatch.setattr(stt, "is_available", lambda: True)
    assert stt.listen_once() == ""
    assert speech == []


def test_google_only_install_is_not_implicitly_available_for_local_policy(speech, monkeypatch):
    monkeypatch.setattr(stt, "_offline_available", lambda: False, raising=False)
    assert stt.is_available() is False
    assert speech == []


def test_explicit_google_engine_is_consent_and_uses_only_google(speech, monkeypatch):
    stt.configure("google")
    monkeypatch.setattr(stt, "_offline_available", lambda: False, raising=False)
    assert stt.listen_once() == "cloud"
    assert speech == ["cloud"]


def test_auto_cloud_fallback_requires_explicit_permission(speech, monkeypatch):
    stt.configure("auto", allow_cloud=True)
    monkeypatch.setattr(stt, "_offline_available", lambda: False, raising=False)
    assert stt.listen_once() == "cloud"
    assert speech == ["cloud"]


@pytest.mark.parametrize("download", [False, True])
def test_local_loader_sets_local_files_only_and_never_trusts_remote_code(monkeypatch, download):
    calls = []
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    tf = types.ModuleType("transformers")

    class Processor:
        @classmethod
        def from_pretrained(cls, name, **kwargs):
            calls.append(("processor", kwargs))
            return types.SimpleNamespace(tokenizer=object(), feature_extractor=object())

    class Model:
        @classmethod
        def from_pretrained(cls, name, **kwargs):
            calls.append(("model", kwargs))
            return object()

    tf.AutoProcessor, tf.AutoModelForSpeechSeq2Seq = Processor, Model
    def pipeline(*args, **kwargs):
        calls.append(("pipeline", kwargs))
        return lambda audio: {"text": "ok"}

    tf.pipeline = pipeline
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", tf)
    instance = stt.STT(allow_download=download)
    instance._load_model()
    assert [name for name, _ in calls] == ["processor", "model", "pipeline"]
    for _, kwargs in calls[:2]:
        assert kwargs["local_files_only"] is (not download)
        assert kwargs["trust_remote_code"] is False
    assert not isinstance(calls[2][1]["model"], str)


def test_class_default_cannot_switch_to_google_after_load_failure(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("offline model missing")

    monkeypatch.setattr(stt, "_build_offline_pipeline", fail, raising=False)
    monkeypatch.setitem(sys.modules, "torch", None)
    instance = stt.STT()
    with pytest.raises(RuntimeError):
        instance._load_model()
    assert instance._use_google is False


@pytest.mark.parametrize("kwargs", [{"allow_cloud": "false"}, {"allow_download": "false"}])
def test_class_policy_flags_reject_truthy_strings(kwargs):
    with pytest.raises(TypeError):
        stt.STT(**kwargs)


@pytest.mark.parametrize("kwargs,error", [({"engine": "unknown"}, ValueError),
                                         ({"allow_cloud": "false"}, TypeError),
                                         ({"allow_download": 1}, TypeError),
                                         ({"engine": "offline", "allow_cloud": True}, ValueError)])
def test_stt_configuration_validates_policy(speech, kwargs, error):
    with pytest.raises(error):
        stt.configure(**kwargs)


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), True, "bad"])
def test_invalid_timeout_never_records_or_transmits(speech, monkeypatch, timeout):
    _offline(monkeypatch)
    monkeypatch.setattr(stt, "is_available", lambda: True)
    assert stt.listen_once(timeout=timeout) == ""
    assert speech == []


@pytest.mark.parametrize("result", [None, [], {"text": 3}, {"text": True}])
def test_bad_decoder_result_is_not_a_command(monkeypatch, result):
    np = types.ModuleType("numpy")
    np.float32 = "float32"
    np.asarray = lambda value, dtype=None: value
    monkeypatch.setitem(sys.modules, "numpy", np)

    instance = stt.STT()
    instance._pipe = lambda audio: result
    assert instance.transcribe_array(array("h", [0, 100])) == ""


@pytest.mark.parametrize("url", ["http://example.com/audio.wav", "https://example.com/audio.wav"])
def test_offline_file_api_refuses_url_before_pipeline(monkeypatch, url):
    instance = stt.STT()
    called = []
    instance._pipe = lambda audio: called.append(audio) or {"text": "unexpected"}
    assert instance.transcribe_file(url) == ""
    assert called == []


def test_local_file_inference_still_works(tmp_path):
    target = tmp_path / "audio.wav"
    target.write_bytes(b"fake audio for mocked decoder")
    instance = stt.STT()
    instance._pipe = lambda audio: {"text": " local "}
    assert instance.transcribe_file(target) == "local"


def test_model_is_prepared_before_opening_microphone(monkeypatch):
    instance = stt.STT()
    calls = []

    def fail():
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(instance, "_load_model", fail)
    monkeypatch.setattr(instance, "_record", lambda *a, **k: calls.append("mic"))
    assert instance.listen() == ""
    assert calls == []


def test_stt_reconfiguration_revokes_old_cloud_and_cached_instance(speech):
    stt.configure("google")
    stt._default_instance = object()
    stt.configure("auto")
    assert stt.ALLOW_CLOUD is False and stt.ALLOW_DOWNLOAD is False
    assert stt._default_instance is None


def test_tts_auto_does_not_fall_back_to_cloud(speech, monkeypatch):
    monkeypatch.setattr(tts, "_speak_gtts", lambda text: speech.append("text upload") or True)
    tts.speak("private text", show=False)
    assert speech == []


def test_cached_cloud_tts_cannot_bypass_revocation(speech, monkeypatch):
    def cloud(text):
        speech.append("text upload")
        return True

    monkeypatch.setattr(tts, "_speak_gtts", cloud)
    monkeypatch.setattr(tts, "_resolved_engine", cloud)
    tts.speak("private text", show=False)
    assert speech == []


@pytest.mark.parametrize("engine,allow", [("gtts", False), ("auto", True)])
def test_cloud_tts_is_available_when_explicitly_selected_or_allowed(speech, monkeypatch, engine,
                                                                  allow):
    monkeypatch.setattr(tts, "ENGINE", engine)
    monkeypatch.setattr(tts, "ALLOW_CLOUD", allow, raising=False)
    monkeypatch.setattr(tts, "_speak_gtts", lambda text: speech.append("cloud") or True)
    tts.speak("explicit", show=False)
    assert speech == ["cloud"]


def test_print_engine_never_plays_cached_audio(speech, monkeypatch):
    monkeypatch.setattr(tts, "ENGINE", "print")
    monkeypatch.setattr(tts, "_speak_cache", lambda text: speech.append("audio played") or True)
    tts.speak("print only", show=False)
    assert speech == []


def test_vieneu_has_a_real_explicit_engine(speech, monkeypatch):
    monkeypatch.setattr(tts, "ENGINE", "vieneu")
    monkeypatch.setattr(tts, "_speak_vieneu", lambda text: speech.append("vieneu") or True,
                        raising=False)
    tts.speak("local model", show=False)
    assert speech == ["vieneu"]


def test_tts_configuration_clears_previous_resolution_and_cloud(speech):
    tts.configure("gtts")
    tts._resolved_engine = lambda text: True
    tts.configure("print")
    assert tts.ALLOW_CLOUD is False and tts._resolved_engine is None
    assert tts.is_available() is False


@pytest.mark.parametrize("kwargs,error", [({"engine": "unknown"}, ValueError),
                                         ({"allow_cloud": "false"}, TypeError)])
def test_tts_configuration_rejects_invalid_values(speech, kwargs, error):
    with pytest.raises(error):
        tts.configure(**kwargs)


def test_automatic_cache_warming_does_not_upload_text(speech, monkeypatch, tmp_path):
    def cloud(text, out):
        speech.append("upload")
        out.write_bytes(b"audio" * 100)
        return True

    monkeypatch.setattr(tts, "_WRITERS", (("gtts", ".mp3", cloud, lambda: True),))
    result = tts.prewarm("private text", out_dir=tmp_path / "cache")
    assert result["failed"] == 1 and result["written"] == 0
    assert speech == []


def test_explicit_cloud_cache_writer_is_preserved(speech, monkeypatch, tmp_path):
    def cloud(text, out):
        speech.append("upload")
        out.write_bytes(b"audio" * 100)
        return True

    monkeypatch.setattr(tts, "_WRITERS", (("gtts", ".mp3", cloud, lambda: True),))
    result = tts.prewarm("explicit text", out_dir=tmp_path / "cache", engine="gtts")
    assert result["written"] == 1 and speech == ["upload"]


def test_piper_engine_invokes_real_piper_with_explicit_local_model(monkeypatch, tmp_path):
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"fake model")
    monkeypatch.setenv("PIPER_MODEL", str(model))
    monkeypatch.setattr(tts, "_binary_present", lambda *args: True)
    monkeypatch.setattr(tts, "_play_audio", lambda path: path.is_file())
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        output = cmd[cmd.index("--output_file") + 1]
        __import__("pathlib").Path(output).write_bytes(b"audio" * 100)
        return True

    monkeypatch.setattr(tts, "_run_hidden", run)
    assert tts._speak_piper("local text") is True
    assert calls[0][0] == "piper"
    assert calls[0][calls[0].index("--model") + 1] == str(model)


def test_only_gtts_installed_is_not_auto_speech_availability(speech, monkeypatch):
    monkeypatch.setattr(tts, "SYSTEM", "Linux")
    monkeypatch.setattr(tts, "is_wsl", lambda: False)
    monkeypatch.setattr(tts, "_module_present", lambda name: name == "gtts")
    monkeypatch.setattr(tts, "_binary_present", lambda *args: False)
    assert tts.is_available() is False
    tts.configure("gtts")
    assert tts.is_available() is True


@pytest.mark.parametrize("warm", [False, True])
def test_auto_vieneu_only_reuses_prepared_instance_not_a_cold_download(monkeypatch, warm):
    backend = types.ModuleType("giong_noi_ai")
    calls = []
    backend._vieneu_cache = object() if warm else None
    backend.is_available = lambda: True
    backend.speak = lambda text: calls.append(text) or True
    monkeypatch.setitem(sys.modules, "giong_noi_ai", backend)
    monkeypatch.setattr(tts, "ENGINE", "auto")
    monkeypatch.setattr(tts, "ALLOW_CLOUD", False)
    monkeypatch.setattr(tts, "_resolved_engine", None)
    monkeypatch.setattr(tts, "ENABLED", True)
    monkeypatch.setattr(tts, "_speak_cache", lambda text: False)
    for name in ("_speak_piper", "_speak_pyttsx3", "_speak_sapi", "_speak_macos"):
        monkeypatch.setattr(tts, name, lambda text: False)
    tts.speak("local text", show=False)
    assert calls == (["local text"] if warm else [])
