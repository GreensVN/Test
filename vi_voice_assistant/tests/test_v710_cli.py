"""Đường CLI thật, stdout JSON độc lập, mã thoát và dry-run không có tác dụng phụ."""
import json
import os
import subprocess
import sys
from pathlib import Path

import executor
import main
import pytest

ROOT = Path(__file__).resolve().parents[2]


class ScriptedNLU:
    def __init__(self, commands):
        self.commands = commands

    def understand(self, text):
        print("model đang phân tích")
        return self.commands


@pytest.mark.parametrize("entry", ["module", "script"])
@pytest.mark.parametrize("text", ["15 + 27", "", "   "])
def test_real_json_cli_produces_exactly_one_json_value(tmp_path, entry, text):
    env = dict(os.environ, VI_ASSISTANT_HOME=str(tmp_path / "private"), PYTHONUTF8="1")
    command = [sys.executable]
    command += (["-m", "vi_voice_assistant"] if entry == "module"
                else [str(ROOT / "vi_voice_assistant" / "main.py")])
    result = subprocess.run([*command, "--once", text, "--dry-run", "--json"],
                            cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert data[0]["result"] == 42 if text.strip() else data == []


def test_json_mode_separates_executor_messages(capsys, monkeypatch):
    commands = [{"intent": "chitchat", "target": "xin chào", "status": "ok", "confidence": 1}]

    def execute(result):
        print("đang thực thi")
        return True

    monkeypatch.setattr(main, "execute_command", execute)
    assert main.run_once("xin chào", ScriptedNLU(commands), as_json=True) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == commands
    assert "model đang phân tích" in captured.err
    assert "đang thực thi" in captured.err


def test_once_catches_execution_exception_and_returns_nonzero(monkeypatch, capsys):
    def fail(result):
        raise RuntimeError("handler hỏng")

    monkeypatch.setattr(main, "execute_command", fail)
    commands = [{"intent": "chitchat", "status": "ok", "confidence": 1}]
    assert main.run_once("xin chào", ScriptedNLU(commands), as_json=True) == 1
    assert json.loads(capsys.readouterr().out) == commands


def test_once_does_not_execute_low_confidence_even_above_executor_threshold(monkeypatch):
    monkeypatch.setattr(main, "execute_command", lambda r: pytest.fail("thực thi thiếu xác nhận"))
    commands = [{"intent": "open_website", "status": "low_confidence", "confidence": 0.4}]
    assert main.run_once("lệnh mơ hồ", ScriptedNLU(commands)) == 2


def test_dry_run_does_not_prompt_teach_or_execute(monkeypatch):
    class NLU:
        def teach(self, *args):
            pytest.fail("dry-run không được học")

    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("dry-run không được hỏi"))
    monkeypatch.setattr(main, "execute_command", lambda r: pytest.fail("dry-run không được chạy"))
    main.handle_result({"status": "need_confirm", "confidence": 1.0}, NLU(), dry_run=True)


def test_cli_dry_run_does_not_restore_or_fire_saved_reminders(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["assistant", "--dry-run", "--once", "xin chào"])
    monkeypatch.setattr(main, "NLU", lambda: ScriptedNLU([]))
    monkeypatch.setattr(main, "setup_signal_handlers", lambda: None)
    monkeypatch.setattr(main, "setup_logging", lambda **kw: None)
    monkeypatch.setattr(main, "save_history_entry", lambda text: None)
    monkeypatch.setattr(executor, "restore_reminders", lambda: pytest.fail("đã bật timer thật"))
    assert main.main() == 0


def test_cli_rejects_json_without_one_shot_or_doctor(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["assistant", "--json"])
    with pytest.raises(SystemExit) as error:
        main.parse_args()
    assert error.value.code == 2


def test_json_cli_reports_bad_custom_config_without_traceback(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "vi_voice_assistant", "--once", "mở google", "--dry-run",
         "--json", "--config", str(bad)], cwd=str(ROOT),
        env=dict(os.environ, VI_ASSISTANT_HOME=str(tmp_path / "home")),
        capture_output=True, text=True, timeout=120)
    assert result.returncode == 1
    assert json.loads(result.stdout)["ok"] is False
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("dry_run,code", [(True, 0), (False, 2)])
def test_negated_json_has_unknown_status_and_mode_specific_exit_code(tmp_path, dry_run, code):
    command = [sys.executable, "-m", "vi_voice_assistant", "--once", "đừng tắt máy tính", "--json"]
    if dry_run:
        command.append("--dry-run")
    result = subprocess.run(
        command, cwd=str(ROOT), env=dict(os.environ, VI_ASSISTANT_HOME=str(tmp_path)),
        capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == code, result.stdout + result.stderr
    body = json.loads(result.stdout)
    assert len(body) == 1 and body[0]["status"] == "unknown"
    assert body[0]["confidence"] == 0.0
