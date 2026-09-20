"""Test cho shim `pytest` cua run_tests.py - phan ma CHỈ chay tren may chua cai pytest.

Nhóm lỗi này nguy hiểm theo kiểu khó thấy: shim thiếu thuộc tính hoặc hỗ trợ nửa
chừng thì máy có pytest vẫn xanh (vì dùng pytest thật), còn người dùng chưa cài gì
- đúng đối tượng mà runner sinh ra phục vụ - lại chạy phải code lỗi. Ba chỗ v7.5
đã sửa:

  1. `raises(E, fn)` (dang goi thang): shim chi la `@contextmanager` nen loi tra ve
     generator, `fn` KHONG BAO GIO duoc goi => test PASS ma khong kiem gi ca;
  2. `importorskip` khong ton tai trong shim => file test dung no che bang
     `AttributeError` khi chay bang runner nhung;
  3. `@parametrize` voi danh sach RONG => vong lap chay 0 lan, testbien "khong co
     gi de kiem tra" thanh PASS.

Kiem tra cuoi la bat buoc tuong lai: moi `pytest.X` ma file test dung phai co trong
shim - do la loi duy nhat o day ma nguoi ta rat de mac lai.
"""
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent.parent          # .../vi_voice_assistant
TESTS_DIR = PKG_DIR / "tests"
sys.path.insert(0, str(PKG_DIR))


def _shim():
    import run_tests
    return run_tests._make_pytest_shim(), run_tests


def test_raises_dang_goi_thang_bat_duoc_loi():
    """`raises(E, fn)` phai GOI fn va bat E - khong tra ve generator roi im lang."""
    shim, _ = _shim()
    boom = RuntimeError("nope")

    def fn():
        raise boom

    caught = shim.raises(RuntimeError, fn)
    assert str(caught) == "nope", caught


def test_raises_dang_goi_thang_bao_sai_khi_khong_co_loi():
    shim, _ = _shim()
    try:
        shim.raises(ValueError, lambda: None)
    except AssertionError as e:
        assert "no exception" in str(e), e
    else:
        raise AssertionError("raises() khong bao sai khi fn khong nem ra loi nao")


def test_raises_dang_goi_thang_de_loi_khac_nguyen_ven():
    """Loi SAI LOAI phai bay ra that (pytest cung lam vay) de con thay traceback."""
    shim, _ = _shim()

    def fn():
        raise KeyError("duong-dan")

    try:
        shim.raises(ValueError, fn)
    except KeyError as e:
        assert "duong-dan" in str(e)
    else:
        raise AssertionError("loi sai loai bi nuot mat trong shim")


def test_raises_match_dung_regex_nhung_dang_goi_thang():
    import pytest as _p  # noqa: F401  (chi de chac chan `import pytest` khong che)

    shim, _ = _shim()
    fn = lambda: (_ for _ in ()).throw(ValueError("nope"))  # noqa: E731
    assert shim.raises(ValueError, fn, match=r"^no") is not None
    try:
        shim.raises(ValueError, fn, match=r"^yes")
    except AssertionError as e:
        assert "!~" in str(e), e
    else:
        raise AssertionError("match sai ma van xanh")


def test_importorskip_tra_module_hoac_bao_skip_khong_that_bai():
    shim, run_tests = _shim()
    assert shim.importorskip("json").loads("{}") == {}
    try:
        shim.importorskip("module_khong_bao_gi_co_dau")
    except run_tests._Skip as e:
        assert "chưa cài" in str(e), e
    else:
        raise AssertionError("thieu module phai SKIP, khong duoc PASS cung khong fail")


def test_parametrize_rong_bai_thanh_that_bai_khong_phai_xanh_gia(tmp_path):
    """`@parametrize("x", [])` khong duoc tro thanh "0 truong hop = PASS".

    Test bang cach chay runner nhung that su (subprocess, python thuan) vi loi nam
    o vong lap sinh case trong `main()`, khong the thay neu chi goi shim.
    """
    pkg = tmp_path / "pkg"
    (pkg / "tests").mkdir(parents=True)
    (pkg / "run_tests.py").write_text((PKG_DIR / "run_tests.py").read_text(encoding="utf-8"),
                                      encoding="utf-8")
    (pkg / "tests" / "test_rong.py").write_text(textwrap.dedent("""\n        import pytest

        @pytest.mark.parametrize("value", [])
        def test_khong_co_gi(value):
            assert False

        def test_that():
            assert 1 + 1 == 2
    """), encoding="utf-8")

    proc = subprocess.run([sys.executable, "run_tests.py", "-q"], cwd=str(pkg),
                          capture_output=True, text=True, timeout=180,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                               "VI_TESTS_FORCE_EMBEDDED": "1"})
    assert proc.returncode == 1, (proc.returncode, proc.stdout[-300:])
    assert "empty-parametrize" in proc.stdout, proc.stdout[-300:]
    assert "1 fail" in proc.stdout and "1 pass" in proc.stdout, proc.stdout[-300:]


def test_shim_phai_co_du_moi_pytest_attr_ma_test_dang_dung():
    """Ranh gioi cho tuong lai: them `pytest.X` vao test thi shim phai co X."""
    shim, _ = _shim()
    used = set()
    for f in sorted(TESTS_DIR.glob("test_*.py")):
        text = f.read_text(encoding="utf-8")
        used.update(re.findall(r"\bpytest\.([a-z_][a-z0-9_]*)", text))
        used.update(re.findall(r"from pytest import ([a-z_][a-z0-9_]*)", text))
    missing = sorted(a for a in used if not hasattr(shim, a))
    assert not missing, f"shim thieu {missing} - may chua cai pytest se che"
    assert used >= {"raises", "mark"}, used
