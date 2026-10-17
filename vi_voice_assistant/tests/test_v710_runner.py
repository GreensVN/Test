"""Cả runner nhúng phải chạy đủ số trường hợp như pytest."""
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import run_tests


def test_stacked_parametrize_runs_all_cartesian_cases():
    shim = run_tests._make_pytest_shim()
    seen = []

    @shim.mark.parametrize("entry", ["module", "script"])
    @shim.mark.parametrize("text", ["15 + 27", "", "   "])
    def example(entry, text):
        seen.append((entry, text))

    cases = run_tests._parametrize_cases("example", example)
    for _, function, kwargs in cases:
        function(**kwargs)
    assert len(cases) == 6
    assert len(set(seen)) == 6


def test_stacked_empty_parametrize_does_not_silently_pass():
    shim = run_tests._make_pytest_shim()

    @shim.mark.parametrize("a", [1, 2])
    @shim.mark.parametrize("b", [])
    def example(a, b):
        pass

    cases = run_tests._parametrize_cases("example", example)
    assert len(cases) == 1
    assert "empty-parametrize" in cases[0][0]
    with pytest.raises(AssertionError):
        cases[0][1]()


def test_invalid_stacked_parameter_names_fail_instead_of_overwriting():
    shim = run_tests._make_pytest_shim()

    @shim.mark.parametrize("a", [1])
    @shim.mark.parametrize("a", [2])
    def example(a):
        pass

    case_name, function, kwargs = run_tests._parametrize_cases("example", example)[0]
    assert "invalid-parametrize" in case_name
    with pytest.raises(AssertionError):
        function(**kwargs)


def test_parametrize_supports_list_names_and_preserves_single_list_argument():
    shim = run_tests._make_pytest_shim()

    @shim.mark.parametrize(["a", "b"], [(1, 2)])
    @shim.mark.parametrize("flags", [["--dry-run", "--json"]])
    def example(a, b, flags):
        assert a == 1 and b == 2
        assert flags == ["--dry-run", "--json"]

    cases = run_tests._parametrize_cases("example", example)
    assert len(cases) == 1
    cases[0][1](**cases[0][2])


def test_real_embedded_runner_executes_every_stacked_combination(tmp_path):
    package = Path(run_tests.__file__).resolve().parent
    (tmp_path / "run_tests.py").write_text((package / "run_tests.py").read_text(encoding="utf-8"),
                                           encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_stacked.py").write_text(textwrap.dedent("""
        import pytest

        @pytest.mark.parametrize("a", [1, 2])
        @pytest.mark.parametrize("b", [3, 4, 5])
        def test_product(a, b):
            assert (a, b) in ((1, 3), (1, 4), (1, 5), (2, 3), (2, 4), (2, 5))
    """), encoding="utf-8")
    result = subprocess.run([sys.executable, "run_tests.py", "-q"], cwd=str(tmp_path),
                            env=dict(os.environ, VI_TESTS_FORCE_EMBEDDED="1"),
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"6 pass, 0 fail, 0 skip", result.stdout)


@pytest.mark.parametrize("values", [1, (1,), (1, 2, 3)])
def test_invalid_multi_argument_values_become_named_failures(values):
    shim = run_tests._make_pytest_shim()

    @shim.mark.parametrize("a,b", [values])
    def example(a, b):
        pass

    name, function, kwargs = run_tests._parametrize_cases("example", example)[0]
    assert "invalid-parametrize" in name
    with pytest.raises(AssertionError):
        function(**kwargs)
