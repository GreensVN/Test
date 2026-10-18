"""Huge or out-of-range confidence must fail closed, not crash or become 100%."""

import csv
import json

import executor
import main
import nlu_advanced as nlu
import pytest

BAD = [10 ** 1000, -10 ** 1000, 1.5, -0.1, "1.5", True]
IDS = ["huge", "negative_huge", "over_one", "negative", "over_one_string", "bool"]


@pytest.mark.parametrize("value", BAD, ids=IDS)
def test_nlu_normalization_never_promotes_invalid_confidence(value):
    assert nlu._as_confidence(value) == 0.0


@pytest.mark.parametrize("value", BAD, ids=IDS)
def test_judge_refuses_invalid_confidence_even_with_zero_thresholds(monkeypatch, value):
    monkeypatch.setattr(nlu, "CONFIDENCE_ACCEPT", 0.0)
    monkeypatch.setattr(nlu, "CONFIDENCE_ASK", 0.0)
    assert nlu.NLU._judge({"intent": "system_control", "target": "lock",
                           "confidence": value}) == "unknown"


@pytest.mark.parametrize("value", BAD, ids=IDS)
def test_executor_confidence_conversion_never_raises(value):
    assert executor._read_confidence(value) == -1.0


@pytest.mark.parametrize("value", BAD, ids=IDS)
@pytest.mark.parametrize("as_json", [False, True])
def test_execute_command_rejects_invalid_numbers_without_dispatch(monkeypatch, value, as_json):
    ran = []
    monkeypatch.setitem(executor.HANDLERS, "system_control", lambda target: ran.append(target))
    monkeypatch.setattr(executor, "CONFIDENCE_THRESHOLD", 0.0)
    monkeypatch.setattr(executor, "AUTO_CONFIRM", True)
    payload = {"intent": "system_control", "target": "lock", "confidence": value}
    assert executor.execute_command(json.dumps(payload) if as_json else payload) is False
    assert ran == []


@pytest.mark.parametrize("value", BAD, ids=IDS)
def test_cli_does_not_display_invalid_confidence_as_fully_certain(value):
    assert main._confidence_percent({"confidence": value}) == 0.0


@pytest.mark.parametrize("value", BAD, ids=IDS)
def test_feedback_records_invalid_confidence_as_zero(tmp_path, monkeypatch, value):
    path = tmp_path / "feedback.csv"
    monkeypatch.setattr(nlu, "FEEDBACK_PATH", str(path))
    assert nlu.log_feedback("example", "open_app", value) is True
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1 and float(rows[0]["confidence"]) == 0.0
    assert rows[0]["verified"] == "0"


@pytest.mark.parametrize("value", [10 ** 1000, -10 ** 1000], ids=["huge", "negative_huge"])
def test_threshold_reader_uses_safe_defaults_on_integer_overflow(value):
    assert nlu._read_thresholds({"confidence_accept": value, "confidence_ask": value}) == \
        (nlu._DEFAULT_ACCEPT, nlu._DEFAULT_ASK)


@pytest.mark.parametrize("value,expected", [(0, 0.0), (0.25, 0.25), (1, 1.0), ("0.8", 0.8)])
def test_valid_confidence_is_unchanged(value, expected):
    assert nlu._as_confidence(value) == expected
    assert executor._read_confidence(value) == expected
    assert main._confidence_percent({"confidence": value}) == expected
