"""Báo lỗi trung thực, xác suất fail-closed và cache model không thực thi mã."""
import json
import pickle

import diagnostic
import executor
import lite_model
import pytest
from intent_model import predict_intent
from nlu_advanced import NLU


@pytest.mark.parametrize("action,target", [
    ("action_open_website", "google"), ("action_search_web", "thông tin"),
    ("action_play_media", "nhạc"), ("action_get_weather", "hà nội"),
])
def test_browser_failure_is_propagated(action, target, monkeypatch):
    monkeypatch.setattr(executor, "_open_url", lambda url: False)
    assert getattr(executor, action)(target) is False


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", "https://",
                                 "http://example.com\nInjected", "https://[bad"])
def test_browser_only_opens_valid_http_urls(url, monkeypatch):
    monkeypatch.setattr(executor.webbrowser, "open", lambda u: pytest.fail("URL không an toàn"))
    assert executor._open_url(url) is False


def test_empty_website_target_asks_instead_of_searching_unknown(monkeypatch):
    monkeypatch.setattr(executor, "_open_url", lambda u: pytest.fail("mở trang unknown"))
    for target in ("", "unknown"):
        assert executor.action_open_website(target) is False


@pytest.mark.parametrize("name", ["danger.desktop", "danger.url", "danger.command", "danger.exe."])
def test_file_open_blocks_additional_executable_shortcuts(name, monkeypatch):
    monkeypatch.setattr(executor, "_open_path", lambda p: pytest.fail("mở file thực thi"))
    assert executor.action_open_file(name) is False


def test_file_open_checks_symlink_destination(tmp_path, monkeypatch):
    executable = tmp_path / "danger.sh"
    executable.write_text("echo không chạy\n", encoding="utf-8")
    alias = tmp_path / "notes.txt"
    try:
        alias.symlink_to(executable)
    except OSError:
        pytest.skip("Máy không cho phép tạo symlink")
    monkeypatch.setattr(executor, "_open_path", lambda p: pytest.fail("mở symlink tới script"))
    assert executor.action_open_file(str(alias)) is False


@pytest.mark.parametrize("row", [[], [float("nan")], [float("inf")], [2.0], [-1.0], [True], [None]])
def test_bad_probability_never_becomes_full_confidence(row):
    class Broken:
        def predict(self, texts):
            return ["open_website"]

        def predict_proba(self, texts):
            return [row]

    result = predict_intent("mở google", Broken())
    assert result["confidence"] == 0.0
    assert NLU._judge(result) == "unknown"
    json.dumps(result, allow_nan=False)


def test_missing_probability_is_not_a_guarantee():
    class NoProbability:
        def predict(self, texts):
            return ["open_website"]

    assert predict_intent("mở google", NoProbability())["confidence"] == 0.0


def test_lite_cache_never_executes_pickle_globals(tmp_path):
    marker = tmp_path / "executed"

    class Payload:
        def __reduce__(self):
            return eval, (f"open({str(marker)!r}, 'w').close()",)

    cache = tmp_path / "lite.pkl"
    cache.write_bytes(pickle.dumps(Payload()))
    assert lite_model.load_lite_model(cache) is None
    assert not marker.exists()


@pytest.mark.parametrize("field,value", [
    ("log_prob", {"open_app": None}), ("log_prior", {"open_app": "rác"}),
    ("log_default", {"open_app": float("nan")}),
])
def test_corrupted_lite_tables_trigger_retraining_not_a_prediction_crash(tmp_path, field, value):
    model = lite_model.LiteIntentModel().fit(["mở chrome"], ["open_app"])
    state = model.to_state()
    state[field] = value
    cache = tmp_path / "lite.pkl"
    cache.write_bytes(pickle.dumps(state))
    assert lite_model.load_lite_model(cache) is None


@pytest.mark.parametrize("field,value", [
    ("alpha", float("nan")), ("temperature", float("inf")),
    ("format_version", float("nan")), ("alpha", -1), ("temperature", 0),
])
def test_lite_numeric_settings_reject_nonfinite_and_invalid_values(field, value):
    model = lite_model.LiteIntentModel.from_state({field: value})
    assert model.alpha > 0 and model.temperature > 0
    assert isinstance(model.format_version, int)


def test_doctor_looks_up_import_name_not_distribution_name(monkeypatch):
    names = []

    def find(name):
        names.append(name)
        return object() if name == "speech_recognition" else None

    monkeypatch.setattr(diagnostic.importlib.util, "find_spec", find)
    assert diagnostic._module_available("SpeechRecognition") is True
    assert names == ["speech_recognition"]


def test_doctor_json_keeps_check_output_on_stderr(monkeypatch, capsys):
    def check():
        print("mục kiểm tra đang đọc dữ liệu")
        return {"ok": True, "sections": {"thử": []}}

    monkeypatch.setattr(diagnostic, "run_checks", check)
    assert diagnostic.main(["--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["ok"]
    assert "đang đọc" in captured.err


def test_doctor_retrain_command_is_package_qualified_and_saves_cache():
    assert "vi_voice_assistant.lite_model" in diagnostic.LITE_RETRAIN
    assert "get_lite_model" in diagnostic.LITE_RETRAIN
    assert "force_retrain=True" in diagnostic.LITE_RETRAIN
    assert "vi_voice_assistant" in diagnostic.CONFIG_WRITE
