"""Core package and historical flat imports must share one runtime state."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "vi_voice_assistant"
CORE = ["paths", "config", "executor", "nlu_advanced"]


def _run(code, tmp_path):
    prefix = f"import sys; sys.path.insert(0, {str(PACKAGE)!r})\n"
    result = subprocess.run([sys.executable, "-c", prefix + textwrap.dedent(code)], cwd=ROOT,
                            env=dict(os.environ, VI_ASSISTANT_HOME=str(tmp_path / "data"),
                                     PYTHONUTF8="1"), capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("name", CORE)
@pytest.mark.parametrize("first", ["flat", "package"])
def test_core_import_orders_return_the_same_module(tmp_path, name, first):
    _run(f"""
        import importlib
        name = {name!r}
        if {first!r} == "flat":
            flat = importlib.import_module(name)
            packaged = importlib.import_module("vi_voice_assistant." + name)
        else:
            packaged = importlib.import_module("vi_voice_assistant." + name)
            flat = importlib.import_module(name)
        assert packaged is flat, (packaged, flat)
        token = object()
        flat._bridge_probe = token
        assert packaged._bridge_probe is token
        assert flat.__spec__.name == name
    """, tmp_path)


@pytest.mark.parametrize("workers", [2, 8])
def test_parallel_core_imports_do_not_initialize_duplicate_modules(tmp_path, workers):
    _run(f"""
        import importlib
        from concurrent.futures import ThreadPoolExecutor
        import vi_voice_assistant
        names = {CORE!r}
        imports = names + ["vi_voice_assistant." + name for name in names]
        with ThreadPoolExecutor(max_workers={workers}) as pool:
            modules = dict(zip(imports, pool.map(importlib.import_module, imports)))
        for name in names:
            assert modules[name] is modules["vi_voice_assistant." + name], name
    """, tmp_path)


def test_package_reload_reaches_the_executor_and_nlu_used_by_cli(tmp_path):
    _run("""
        import json
        from pathlib import Path
        import vi_voice_assistant.executor as executor
        import vi_voice_assistant.main as cli
        import vi_voice_assistant.nlu_advanced as nlu
        import vi_voice_assistant.config as config
        target = Path(__import__("os").environ["VI_ASSISTANT_HOME"]) / "profile.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        cfg = dict(config.DEFAULT_CONFIG, confidence_threshold=0.8,
                   confidence_accept=0.9, confidence_ask=0.7, dangerous_actions=["lock"])
        target.write_text(json.dumps(cfg))
        executor.reload_config(target)
        assert cli.executor is executor
        assert cli.NLU is nlu.NLU
        assert cli.executor.CONFIDENCE_THRESHOLD == 0.8
        assert nlu.CONFIDENCE_ACCEPT == 0.9 and nlu.CONFIDENCE_ASK == 0.7
        assert executor.DANGEROUS_ACTIONS == nlu.DANGEROUS_TARGETS == {"lock"}
    """, tmp_path)


def test_package_and_flat_paths_share_the_same_fallback_root(tmp_path):
    _run("""
        import importlib, os, shutil
        from pathlib import Path
        blocked = Path(os.environ["VI_ASSISTANT_HOME"])
        blocked.write_text("not a directory")
        roots = set()
        try:
            packaged = importlib.import_module("vi_voice_assistant.paths")
            roots.add(packaged.data_dir())
            flat = importlib.import_module("paths")
            roots.add(flat.data_dir())
            assert len(roots) == 1
        finally:
            for root in roots:
                shutil.rmtree(root)
    """, tmp_path)


def test_canonical_import_refuses_foreign_short_name_without_replacing_it(tmp_path):
    _run("""
        import importlib, types, sys
        import vi_voice_assistant
        foreign = types.ModuleType("paths")
        foreign.__file__ = "/unrelated_application/paths.py"
        sys.modules["paths"] = foreign
        try:
            importlib.import_module("vi_voice_assistant.paths")
        except ImportError:
            pass
        else:
            raise AssertionError("foreign short-name module was silently accepted")
        assert sys.modules["paths"] is foreign
    """, tmp_path)


def test_version_only_import_stays_lazy_and_bridge_registration_is_idempotent(tmp_path):
    _run("""
        import sys, importlib, os, subprocess
        from pathlib import Path

        def forbidden(*args, **kwargs):
            raise AssertionError("version import must not launch a process")

        subprocess.Popen = forbidden
        os.system = forbidden
        import vi_voice_assistant as package
        assert package.__version__
        assert not Path(os.environ["VI_ASSISTANT_HOME"]).exists()
        names = ("paths", "config", "executor", "nlu_advanced", "stt", "tts")
        assert not any(name in sys.modules for name in names)
        count = len(sys.meta_path)
        importlib.reload(package)
        assert len(sys.meta_path) == count
        assert not any(name in sys.modules for name in names)
        assert not Path(os.environ["VI_ASSISTANT_HOME"]).exists()
        assert callable(package.main)
    """, tmp_path)


def test_module_reload_uses_original_flat_spec_not_a_noop_alias_loader(tmp_path):
    _run("""
        import importlib
        flat = importlib.import_module("paths")
        packaged = importlib.import_module("vi_voice_assistant.paths")
        assert packaged is flat
        original = flat.reset_cache
        assert flat.__spec__.name == "paths"
        assert importlib.reload(packaged) is flat
        assert flat.reset_cache is not original
        assert flat.__spec__.name == "paths"
    """, tmp_path)


def test_embedded_monkeypatch_multiple_chdir_restores_original(tmp_path):
    import run_tests

    original = Path.cwd()
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    patch = run_tests._Monkeypatch()
    try:
        patch.chdir(first)
        patch.chdir(second)
        patch.undo()
        assert Path.cwd() == original
    finally:
        os.chdir(original)


def test_embedded_monkeypatch_multiple_path_prepends_restore_original(tmp_path):
    import run_tests

    original = list(sys.path)
    patch = run_tests._Monkeypatch()
    try:
        patch.syspath_prepend(tmp_path / "first")
        patch.syspath_prepend(tmp_path / "second")
        patch.undo()
        assert sys.path == original
    finally:
        sys.path[:] = original


def test_embedded_monkeypatch_prepend_existing_path_really_moves_to_front(tmp_path):
    import run_tests

    original = list(sys.path)
    marker = str(tmp_path / "existing")
    sys.path.append(marker)
    expected = list(sys.path)
    patch = run_tests._Monkeypatch()
    try:
        patch.syspath_prepend(marker)
        assert sys.path[0] == marker
        patch.undo()
        assert sys.path == expected
    finally:
        sys.path[:] = original


def test_embedded_monkeypatch_real_runner_survives_repeated_chdir(tmp_path):
    import run_tests

    (tmp_path / "run_tests.py").write_text(Path(run_tests.__file__).read_text(encoding="utf-8"),
                                           encoding="utf-8")
    folder = tmp_path / "tests"
    folder.mkdir()
    (folder / "test_cwd.py").write_text(textwrap.dedent("""
        import os
        from pathlib import Path

        ROOT = Path(__file__).resolve().parent.parent

        def test_a(monkeypatch, tmp_path):
            first, second = tmp_path / "first", tmp_path / "second"
            first.mkdir()
            second.mkdir()
            monkeypatch.chdir(first)
            monkeypatch.chdir(second)

        def test_b():
            assert Path(os.getcwd()) == ROOT
    """), encoding="utf-8")
    result = subprocess.run([sys.executable, "run_tests.py", "-q"], cwd=tmp_path,
                            env=dict(os.environ, VI_TESTS_FORCE_EMBEDDED="1"),
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 pass, 0 fail, 0 skip" in result.stdout
