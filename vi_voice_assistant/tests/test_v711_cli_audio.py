"""Speech controls must apply to the same modules and not leak network consent."""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import main
import pytest
import stt
import tts

ROOT = Path(__file__).resolve().parents[2]


def _args(**changes):
    values = {"yes": False, "config": None, "engine": None, "voice": False, "speak": False,
              "stt_engine": "auto", "allow_cloud_stt": False, "stt_download": False,
              "allow_cloud_tts": False}
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.fixture
def audio_state(monkeypatch):
    for module in (stt, tts):
        monkeypatch.setattr(module, "ENGINE", "auto", raising=False)
        monkeypatch.setattr(module, "ALLOW_CLOUD", False, raising=False)
    monkeypatch.setattr(stt, "ALLOW_DOWNLOAD", False, raising=False)
    monkeypatch.setattr(stt, "_default_instance", None)
    monkeypatch.setattr(tts, "_resolved_engine", None)


@pytest.mark.parametrize("flags,field,value", [
    (["--stt-engine", "offline"], "stt_engine", "offline"),
    (["--stt-engine", "google"], "stt_engine", "google"),
    (["--stt-download"], "stt_download", True),
    (["--engine", "vieneu"], "engine", "vieneu"),
])
def test_cli_accepts_explicit_audio_policy_flags(monkeypatch, flags, field, value):
    monkeypatch.setattr(sys, "argv", ["assistant", *flags])
    assert getattr(main.parse_args(), field) == value


def test_cli_rejects_offline_cloud_stt_contradiction(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["assistant", "--stt-engine", "offline", "--allow-cloud-stt"])
    with pytest.raises(SystemExit) as error:
        main.parse_args()
    assert error.value.code == 2


@pytest.mark.parametrize("name", ["stt", "tts"])
@pytest.mark.parametrize("first", ["flat", "package"])
def test_speech_policy_modules_share_state_across_import_styles(tmp_path, name, first):
    package = ROOT / "vi_voice_assistant"
    code = f"""
import sys, importlib
sys.path.insert(0, {str(package)!r})
name = {name!r}
if {first!r} == "flat":
    a = importlib.import_module(name)
    b = importlib.import_module("vi_voice_assistant." + name)
else:
    b = importlib.import_module("vi_voice_assistant." + name)
    a = importlib.import_module(name)
assert a is b
assert a.__spec__.name == name
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                            env=dict(os.environ, VI_ASSISTANT_HOME=str(tmp_path)), timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_new_cli_options_revoke_previous_cloud_and_model_download_consent(audio_state, monkeypatch):
    monkeypatch.setattr(stt, "ENGINE", "google")
    monkeypatch.setattr(stt, "ALLOW_CLOUD", True, raising=False)
    monkeypatch.setattr(stt, "ALLOW_DOWNLOAD", True, raising=False)
    monkeypatch.setattr(tts, "ENGINE", "gtts")
    monkeypatch.setattr(tts, "ALLOW_CLOUD", True, raising=False)
    assert main._apply_cli_options(_args()) is None
    assert stt.ENGINE == tts.ENGINE == "auto"
    assert stt.ALLOW_CLOUD is stt.ALLOW_DOWNLOAD is tts.ALLOW_CLOUD is False


def test_explicit_google_and_gtts_selection_are_applied_without_loading_models(audio_state):
    assert main._apply_cli_options(_args(stt_engine="google", engine="gtts")) is None
    assert stt.ENGINE == "google" and stt.ALLOW_CLOUD is True
    assert tts.ENGINE == "gtts"


def test_failed_config_does_not_leave_previous_cloud_consent_active(audio_state, tmp_path,
                                                                  monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    monkeypatch.setattr(stt, "ENGINE", "google")
    monkeypatch.setattr(stt, "ALLOW_CLOUD", True, raising=False)
    monkeypatch.setattr(tts, "ENGINE", "gtts")
    monkeypatch.setattr(tts, "ALLOW_CLOUD", True, raising=False)
    assert main._apply_cli_options(_args(config=str(bad))) == 1
    assert stt.ENGINE == tts.ENGINE == "auto"
    assert stt.ALLOW_CLOUD is tts.ALLOW_CLOUD is False


def test_invalid_private_audio_options_fail_closed(audio_state):
    assert main._apply_cli_options(_args(stt_engine="unknown")) == 1
    assert stt.ALLOW_CLOUD is tts.ALLOW_CLOUD is False


def test_explicit_vieneu_engine_is_not_mislabeled_as_piper(audio_state):
    assert main._apply_cli_options(_args(engine="vieneu")) is None
    assert tts.ENGINE == "vieneu"


@pytest.mark.parametrize("module", ["stt", "tts"])
def test_canonical_speech_module_help_is_runnable_without_audio(tmp_path, module):
    result = subprocess.run([sys.executable, "-m", f"vi_voice_assistant.{module}", "--help"],
                            cwd=ROOT, env=dict(os.environ, VI_ASSISTANT_HOME=str(tmp_path)),
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "usage:" in result.stdout.lower()


@pytest.mark.parametrize("mode", ["plain", "optional", "dependency", "module"])
def test_embedded_runner_accepts_none_fixture_values(tmp_path, mode):
    import textwrap

    import run_tests

    (tmp_path / "run_tests.py").write_text(Path(run_tests.__file__).read_text(encoding="utf-8"),
                                           encoding="utf-8")
    directory = tmp_path / "tests"
    directory.mkdir()
    scope = "module" if mode == "module" else "function"
    fixture = f"""
        import pytest
        calls = []

        @pytest.fixture(scope={scope!r})
        def empty():
            calls.append(1)
            return None
    """
    bodies = {
        "plain": "def test_value(empty):\n    assert empty is None\n",
        "optional": "def test_value(empty='fallback'):\n    assert empty is None\n",
        "dependency": ("@pytest.fixture\ndef dependent(empty):\n    assert empty is None\n"
                       "    return 42\n\ndef test_value(dependent):\n    assert dependent == 42\n"),
        "module": ("def test_a(empty):\n    assert empty is None and len(calls) == 1\n"
                   "\ndef test_b(empty):\n    assert empty is None and len(calls) == 1\n"),
    }
    (directory / "test_none.py").write_text(textwrap.dedent(fixture) + "\n" + bodies[mode],
                                             encoding="utf-8")
    result = subprocess.run([sys.executable, "run_tests.py", "-q"], cwd=tmp_path,
                            env=dict(os.environ, VI_TESTS_FORCE_EMBEDDED="1"),
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 fail, 0 skip" in result.stdout


def test_embedded_fixture_setup_error_is_a_named_failure_not_a_runner_crash(tmp_path):
    import textwrap

    import run_tests

    (tmp_path / "run_tests.py").write_text(Path(run_tests.__file__).read_text(encoding="utf-8"),
                                           encoding="utf-8")
    directory = tmp_path / "tests"
    directory.mkdir()
    (directory / "test_setup.py").write_text(textwrap.dedent("""
        import pytest

        @pytest.fixture
        def broken():
            raise ValueError("fixture setup failed")

        def test_using_fixture(broken):
            pass
    """), encoding="utf-8")
    result = subprocess.run([sys.executable, "run_tests.py", "-q"], cwd=tmp_path,
                            env=dict(os.environ, VI_TESTS_FORCE_EMBEDDED="1"),
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 1
    assert "0 pass, 1 fail, 0 skip" in result.stdout
    assert "test_using_fixture" in result.stdout and "fixture setup failed" in result.stdout
