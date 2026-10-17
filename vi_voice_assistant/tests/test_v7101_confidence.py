"""Ngưỡng cấu hình 0 không được biến từ chối an toàn/NaN/phủ định thành thực thi."""
import executor
import main
import nlu_advanced as nlu
import pytest
from intent_model import predict_intent


@pytest.mark.parametrize("value", [
    0, 0.0, -1, True, False, None, "bad", float("nan"), float("inf"),
])
def test_zero_nlu_thresholds_still_reject_missing_or_zero_evidence(monkeypatch, value):
    monkeypatch.setattr(nlu, "CONFIDENCE_ASK", 0.0)
    monkeypatch.setattr(nlu, "CONFIDENCE_ACCEPT", 0.0)
    assert nlu.NLU._judge({"intent": "system_control", "target": "lock", "confidence": value}) == (
        "unknown")


@pytest.mark.parametrize("value", [
    0, 0.0, -1, True, False, None, "bad", float("nan"), float("inf"),
])
def test_zero_executor_threshold_does_not_bypass_zero_or_invalid_confidence(monkeypatch, value):
    monkeypatch.setattr(executor, "CONFIDENCE_THRESHOLD", 0.0)
    monkeypatch.setattr(executor, "HANDLERS", {
        "system_control": lambda target: pytest.fail("không được thực thi khi thiếu bằng chứng"),
    })
    assert executor.execute_command({"intent": "system_control", "target": "lock",
                                     "confidence": value}) is False


def test_zero_thresholds_still_allow_positive_evidence_when_explicitly_configured(monkeypatch):
    monkeypatch.setattr(nlu, "CONFIDENCE_ASK", 0.0)
    monkeypatch.setattr(nlu, "CONFIDENCE_ACCEPT", 0.0)
    monkeypatch.setattr(executor, "CONFIDENCE_THRESHOLD", 0.0)
    monkeypatch.setattr(executor, "HANDLERS", {"open_website": lambda target: target == "google"})
    result = {"intent": "open_website", "target": "google", "confidence": 0.001}
    assert nlu.NLU._judge(result) == "ok"
    assert executor.execute_command(result) is True


def test_yes_and_zero_thresholds_do_not_execute_negated_system_command(monkeypatch):
    class Model:
        def predict(self, texts):
            return ["system_control"]

        def predict_proba(self, texts):
            return [[1.0]]

    class Understanding:
        def understand(self, text):
            result = predict_intent(text, Model())
            result["status"] = nlu.NLU._judge(result)
            return [result]

    monkeypatch.setattr(nlu, "CONFIDENCE_ASK", 0.0)
    monkeypatch.setattr(nlu, "CONFIDENCE_ACCEPT", 0.0)
    monkeypatch.setattr(executor, "CONFIDENCE_THRESHOLD", 0.0)
    monkeypatch.setattr(executor, "AUTO_CONFIRM", True)
    monkeypatch.setattr(main, "execute_command", lambda result: pytest.fail("phủ định vẫn bị chạy"))
    assert main.run_once("đừng tắt máy tính", Understanding()) == 2
