"""Invalid analysis/output must fail before dispatch and keep machine JSON valid."""

import contextlib
import io
import json
import logging

import diagnostic
import logging_setup
import main
import platform_utils
import pytest

VALID = {"intent": "chitchat", "target": "mở trình duyệt", "confidence": 1.0, "status": "ok"}


class Model:
    def __init__(self, commands):
        self.commands = commands

    def understand(self, text):
        return self.commands


class AsciiOutput(io.StringIO):
    def write(self, text):
        text.encode("ascii", errors="strict")
        return super().write(text)


@pytest.fixture
def actions(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "execute_command", lambda value: calls.append(value) or True)
    return calls


@pytest.mark.parametrize("bad", [None, {}, "not-list", 123, [None], ["text"], [42], [[{}]]])
@pytest.mark.parametrize("as_json", [False, True])
def test_wrong_analysis_shape_is_rejected_without_dispatch(actions, bad, as_json, capsys):
    assert main.run_once("command", Model(bad), as_json=as_json) == 2
    assert actions == []
    captured = capsys.readouterr()
    if as_json:
        assert json.loads(captured.out)["ok"] is False


@pytest.mark.parametrize("position", [0, 1])
@pytest.mark.parametrize("as_json", [False, True])
def test_entire_batch_is_validated_before_first_action(actions, position, as_json, capsys):
    batch = [dict(VALID)]
    batch.insert(position, None)
    assert main.run_once("command", Model(batch), as_json=as_json) == 2
    assert actions == []
    if as_json:
        assert json.loads(capsys.readouterr().out)["ok"] is False


@pytest.mark.parametrize("problem", ["nan", "infinity", "circular", "unstringifiable"])
@pytest.mark.parametrize("as_json", [False, True])
def test_serialization_failures_are_controlled_and_do_not_dispatch(actions, problem, as_json,
                                                                 capsys):
    class BadText:
        def __str__(self):
            raise ValueError("bad metadata")

    value = dict(VALID)
    if problem == "circular":
        meta = {}
        meta["self"] = meta
    else:
        meta = {"nan": float("nan"), "infinity": float("inf"),
                "unstringifiable": BadText()}[problem]
    value["metadata"] = meta
    assert main.run_once("command", Model([value]), as_json=as_json) == 2
    assert actions == []
    if as_json:
        assert json.loads(capsys.readouterr().out)["ok"] is False


@pytest.mark.parametrize("text", ["mở trình duyệt", "robot 🤖", "\ud800", "\udfff"])
def test_json_round_trips_unicode_even_on_ascii_output(actions, text):
    output = AsciiOutput()
    command = dict(VALID, target=text)
    assert main.run_once(text, Model([command]), as_json=True, json_output=output) == 0
    assert output.getvalue().isascii()
    assert json.loads(output.getvalue()) == [command]
    assert actions == [command]


@pytest.mark.parametrize("bad_exception", [False, True])
def test_analysis_error_json_can_report_unicode_or_unprintable_exception(actions, bad_exception):
    class BadError(Exception):
        def __str__(self):
            raise RuntimeError("cannot format exception")

    class BrokenModel:
        def understand(self, text):
            raise BadError() if bad_exception else ValueError("bad \ud800")

    output = AsciiOutput()
    assert main.run_once("\ud800", BrokenModel(), as_json=True, json_output=output) == 2
    body = json.loads(output.getvalue())
    assert body["ok"] is False and body["raw"] == "\ud800"
    assert body["error"]
    assert actions == []


@pytest.mark.parametrize("error", [OSError, BrokenPipeError, ValueError])
@pytest.mark.parametrize("when", ["write", "flush"])
def test_failed_output_is_flushed_checked_and_never_executes(actions, error, when):
    class BrokenOutput(io.StringIO):
        def write(self, text):
            if when == "write":
                raise error("output unavailable")
            return super().write(text)

        def flush(self):
            if when == "flush":
                raise error("flush unavailable")
            return super().flush()

    assert main.run_once("command", Model([dict(VALID)]), as_json=True,
                         json_output=BrokenOutput()) == 1
    assert actions == []


@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize("dry_run", [False, True])
def test_healthy_command_and_dry_run_semantics_are_preserved(actions, as_json, dry_run, capsys):
    assert main.run_once("command", Model([dict(VALID)]), as_json=as_json, dry_run=dry_run) == 0
    assert len(actions) == int(not dry_run)
    if as_json:
        assert json.loads(capsys.readouterr().out) == [VALID]


@pytest.mark.parametrize("as_json", [False, True])
def test_empty_analysis_batch_is_still_successful(actions, as_json, capsys):
    assert main.run_once("command", Model([]), as_json=as_json) == 0
    assert actions == []
    if as_json:
        assert json.loads(capsys.readouterr().out) == []


@pytest.mark.parametrize("message", ["lỗi tiếng Việt", "bad \ud800"])
def test_startup_error_json_is_ascii_safe(message):
    output = AsciiOutput()
    main._json_error(message, output)
    assert json.loads(output.getvalue()) == {"ok": False, "error": message}


@pytest.mark.parametrize("bad", [None, [], {"ok": "yes"}, {"ok": True, "extra": float("nan")}])
def test_doctor_rejects_invalid_or_nonfinite_reports(monkeypatch, bad):
    monkeypatch.setattr(diagnostic, "run_checks", lambda: bad)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert diagnostic.main(["--json"]) == 1
    body = json.loads(output.getvalue(), parse_constant=lambda value: pytest.fail(value))
    assert body["ok"] is False


def test_doctor_json_preserves_unicode_on_narrow_output(monkeypatch):
    report = {"ok": True, "sections": {}, "meta": "tiếng Việt \ud800"}
    monkeypatch.setattr(diagnostic, "run_checks", lambda: report)
    monkeypatch.setattr(diagnostic, "setup_console", lambda: None)
    output = AsciiOutput()
    with contextlib.redirect_stdout(output):
        assert diagnostic.main(["--json"]) == 0
    assert json.loads(output.getvalue()) == report


@pytest.mark.parametrize("message", ["tiếng Việt", "bad \ud800"])
def test_json_log_formatter_is_encoding_safe(message):
    record = logging.LogRecord("test", logging.WARNING, __file__, 1, message, (), None)
    encoded = logging_setup.JsonFormatter().format(record)
    assert encoded.isascii()
    assert json.loads(encoded)["msg"] == message


def test_safe_print_can_target_stderr_without_touching_stdout(capsys):
    import sys

    platform_utils.safe_print("warning tiếng Việt\nline two", file=sys.stderr)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "warning tiếng Việt\nline two\n"


def test_safe_print_fallback_stays_on_requested_stream(capsys):
    output = AsciiOutput()
    platform_utils.safe_print("mở trình duyệt", file=output)
    assert output.getvalue() == "mo trinh duyet\n"
    assert capsys.readouterr().out == ""


def test_short_writes_are_completed_before_dispatch(actions):
    class ShortOutput(io.StringIO):
        def write(self, text):
            return super().write(text[:3])

    output = ShortOutput()
    assert main.run_once("command", Model([dict(VALID)]), as_json=True, json_output=output) == 0
    assert json.loads(output.getvalue()) == [VALID]
    assert actions == [VALID]


@pytest.mark.parametrize("count", [None, False, 0, -1, "excessive"])
def test_invalid_or_zero_write_progress_refuses_execution(actions, count):
    class InvalidOutput(io.StringIO):
        def write(self, text):
            return len(text) + 1 if count == "excessive" else count

    assert main.run_once("command", Model([dict(VALID)]), as_json=True,
                         json_output=InvalidOutput()) == 1
    assert actions == []


def test_embedded_capture_write_returns_character_count():
    import run_tests

    real, captured = io.StringIO(), io.StringIO()
    stream = run_tests._Tee(real, captured)
    assert stream.write("abc") == 3
    assert real.getvalue() == captured.getvalue() == "abc"


def test_embedded_capture_preserves_short_write_progress(actions):
    import run_tests

    class Short(io.StringIO):
        def write(self, text):
            return super().write(text[:2])

    real, captured = Short(), io.StringIO()
    output = run_tests._Tee(real, captured)
    assert main.run_once("command", Model([dict(VALID)]), as_json=True, json_output=output) == 0
    assert real.getvalue() == captured.getvalue()
    assert json.loads(captured.getvalue()) == [VALID]
    assert actions == [VALID]


@pytest.mark.parametrize("count", [0, False, -1, "excessive"])
def test_embedded_capture_does_not_acknowledge_invalid_progress(actions, count):
    import run_tests

    class Invalid(io.StringIO):
        def write(self, text):
            return len(text) + 1 if count == "excessive" else count

    captured = io.StringIO()
    output = run_tests._Tee(Invalid(), captured)
    assert main.run_once("command", Model([dict(VALID)]), as_json=True, json_output=output) == 1
    assert captured.getvalue() == ""
    assert actions == []


def test_embedded_capture_keeps_legacy_none_returning_real_stream():
    import run_tests

    class Legacy(io.StringIO):
        def write(self, text):
            super().write(text)
            return None

    real, captured = Legacy(), io.StringIO()
    assert run_tests._Tee(real, captured).write("abc") == 3
    assert real.getvalue() == captured.getvalue() == "abc"
