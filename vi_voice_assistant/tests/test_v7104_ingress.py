"""Malformed external JSON/objects must be rejected before action dispatch."""

import json

import executor
import pytest


@pytest.fixture
def dispatched(monkeypatch):
    calls = []
    monkeypatch.setitem(executor.HANDLERS, "open_app", lambda target: calls.append(target) or True)
    return calls


@pytest.mark.parametrize("error", [ValueError, RecursionError])
def test_unexpected_json_decoder_rejection_is_not_an_uncaught_exception(monkeypatch, dispatched,
                                                                       error):
    def fail(text):
        raise error("decoder limit")

    monkeypatch.setattr(executor.json, "loads", fail)
    assert executor.execute_command('{"intent":"open_app","target":"safe"}') is False
    assert dispatched == []


@pytest.mark.parametrize("text", [
    "1" * 5000,
    '{"intent":"open_app","target":"safe","metadata":' + "[" * 5000 + "0" + "]" * 5000 + "}",
    "{",
    "[]",
], ids=["integer_limit", "nesting_limit", "malformed", "wrong_root"])
def test_real_bad_or_excessive_json_is_refused(dispatched, text):
    assert executor.execute_command(text) is False
    assert dispatched == []


@pytest.mark.parametrize("error", [ValueError, TypeError, OverflowError,
                                 RecursionError, RuntimeError])
def test_unstringifiable_target_never_turns_into_an_empty_action(dispatched, error):
    class BadText:
        def __str__(self):
            raise error("cannot stringify")

    assert executor.execute_command({"intent": "open_app", "target": BadText(),
                                     "confidence": 1.0}) is False
    assert dispatched == []


@pytest.mark.parametrize("error", [ValueError, TypeError, OverflowError,
                                 RecursionError, RuntimeError])
def test_bad_intent_label_does_not_break_its_rejection_message(dispatched, error):
    class BadLabel:
        def __str__(self):
            raise error("cannot stringify")

    assert executor.execute_command({"intent": BadLabel(), "target": "safe",
                                     "confidence": 1.0}) is False
    assert dispatched == []


@pytest.mark.parametrize("raw,expected", [(None, ""), (123, "123"), (False, "False"),
                                        (["one"], "['one']"), ({"one": 1}, "{'one': 1}"),
                                        (" KeepMe ", "KeepMe")])
def test_existing_target_conversion_rules_are_preserved(dispatched, raw, expected):
    assert executor.execute_command({"intent": "open_app", "target": raw,
                                     "confidence": 1.0}) is True
    assert dispatched == [expected]


@pytest.mark.parametrize("as_json", [False, True])
def test_valid_existing_command_protocol_still_works(dispatched, as_json):
    payload = {"intent": "open_app", "target": "KeepCase", "confidence": 0.9}
    assert executor.execute_command(json.dumps(payload) if as_json else payload) is True
    assert dispatched == ["KeepCase"]
