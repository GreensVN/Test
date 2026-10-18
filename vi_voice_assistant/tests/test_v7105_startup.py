"""Pre-argument import and logging failures must never prefix JSON on stdout."""

import json
import os
import subprocess
import sys
from pathlib import Path

import config
import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_config_creation_warning_uses_stderr(tmp_path, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise OSError("exclusive publication unavailable")

    monkeypatch.setattr(config, "create_json_if_absent", fail)
    assert config.load_config(tmp_path / "missing.json") == config.DEFAULT_CONFIG
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Không tạo được" in captured.err


@pytest.mark.parametrize("entry", ["module", "script", "canonical"])
@pytest.mark.parametrize("mode", ["once", "doctor"])
def test_import_time_config_failure_keeps_stdout_json(tmp_path, entry, mode):
    flags = (["--once", "15 + 27", "--dry-run", "--json"] if mode == "once"
             else ["--doctor", "--json"])
    code = f"""
import runpy, sys
from pathlib import Path
import vi_voice_assistant
import paths

def fail(*args, **kwargs):
    raise OSError("simulated no-replace failure")

paths.create_json_if_absent = fail
sys.argv = ["assistant", *{flags!r}]
entry = {entry!r}
if entry == "module":
    runpy.run_module("vi_voice_assistant", run_name="__main__")
elif entry == "script":
    runpy.run_path(str(Path(vi_voice_assistant.__file__).parent / "main.py"), run_name="__main__")
else:
    import vi_voice_assistant.main as cli
    raise SystemExit(cli.main())
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                            env=dict(os.environ, VI_ASSISTANT_HOME=str(tmp_path / "private"),
                                     PYTHONUTF8="1"), capture_output=True, text=True, timeout=120)
    assert result.returncode in (0, 1), result.stderr
    body = json.loads(result.stdout)
    if mode == "once":
        assert result.returncode == 0 and body[0]["result"] == 42
    else:
        assert "sections" in body
    assert "Không tạo được" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("custom", [False, True])
@pytest.mark.parametrize("as_json", [False, True])
def test_logging_uses_requested_parent_and_falls_back_to_stderr(tmp_path, custom, as_json):
    code = f"""
import json, logging
from pathlib import Path
import vi_voice_assistant
import logging_setup as logs

base = Path({str(tmp_path)!r})
blocked = base / "blocked"
blocked.write_text("not a directory")
logs.LOG_DIR = blocked
logs.LOG_FILE = blocked / "assistant.log"
custom = {custom!r}
target = base / "custom" / "assistant.log"
logs.setup_logging(log_file=target if custom else None, use_json={as_json!r})
logging.getLogger("probe").warning("mở trình duyệt")
for handler in logging.getLogger().handlers:
    handler.flush()
assert logs._configured
if custom:
    text = target.read_text(encoding="utf-8")
    assert text and ("probe" in text)
    if {as_json!r}:
        assert json.loads(text)["msg"] == "mở trình duyệt"
print(json.dumps({{"configured": logs._configured, "file": target.exists()}}))
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                            env=dict(os.environ, VI_ASSISTANT_HOME=str(tmp_path / "data"),
                                     PYTHONUTF8="1"), capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout) == {"configured": True, "file": custom}
    assert result.stderr
