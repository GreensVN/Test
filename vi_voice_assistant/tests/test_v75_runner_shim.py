"""Test cho shim `pytest` cua run_tests.py - phan ma CHỈ chay tren may chua cai pytest.

Nhóm lỗi này nguy hiểm theo kiểu khó thấy: shim thiếu thuộc tính hoặc hỗ trợ nửa
chừng thì máy có pytest vẫn xanh (vì dùng pytest thật), còn người dùng chưa cài gì
- đúng đối tượng mà runner sinh ra phục vụ - lại chạy phải code lỗi. Ba chỗ v7.5
đã sửa:

  1. `raises(E, fn)` (dạng gọi thẳng): shim chỉ là `@contextmanager` nên lời gọi
     trả về generator, `fn` KHÔNG BAO GIỜ được chạy => test PASS mà không kiểm tra
     gì cả;
  2. `importorskip` không tồn tại trong shim => file test dùng nó chết bằng
     `AttributeError` khi chạy bằng runner;
  3. `@parametrize` với danh sách RỖNG => vòng lặp chạy 0 lần, test biến "không có
     gì để kiểm tra" thành PASS;
  4. v7.6: `raises` PHẢI trả `ExceptionInfo` (`.value`/`.type`/`.match()`) cho cả
     hai dạng gọi, nếu không test viết đúng theo pytest chỉ chạy được một đường.

Kiểm tra cuối cùng là bắt buộc với tương lai: mọi `pytest.X` mà file test dùng phải
có trong shim - đó là lỗi duy nhất ở đây mà người ta rất dễ mắc lại.
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
    """`raises(E, fn)` phai GOI fn va bat E - khong tra ve generator roi im lang.

    v7.6 that chat them buoc: ket qua phai la `ExceptionInfo` (co `.value`,
    `.type`, `.match()`) nhu pytest. Tra ve tran exception thi test viet theo
    pytest chay xanh tren may co pytest nhung do tren runner - hai duong chay
    phai cho cung mot ket qua.
    """
    import pytest as _p  # module nay KHONG import pytest o dinh (xem ghi chu dau file)

    shim, _ = _shim()
    boom = RuntimeError("nope")

    def fn():
        raise boom

    caught = shim.raises(RuntimeError, fn)
    assert caught.value is boom
    assert caught.type is RuntimeError
    assert str(caught.value) == "nope"
    assert caught.match(r"^no") is True                   # pytest: khop -> True
    with _p.raises(AssertionError, match="did not match"):
        caught.match(r"^yes")
    assert "ExceptionInfo" in repr(caught)


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
    info = shim.raises(ValueError, fn, match=r"^no")
    assert info is not None and info.match(r"^no") is True
    try:
        shim.raises(ValueError, fn, match=r"^yes")
    except AssertionError as e:
        assert "Regex pattern did not match" in str(e), e
    else:
        raise AssertionError("match sai ma van xanh")


def test_raises_dang_context_co_value_sau_khi_thoat_with():
    """`with raises(E) as ei:` của pytest cho phép đọc `ei.value` SAU khối `with`.

    shim cũ chỉ ``yield`` (không trả gì) nên tính năng này mất hẳn: mọi test đọc
    `ei.value`/`ei.match` trong khối `with` chết bằng AttributeError trên runner,
    mà runner mới là nơi bộ test này bắt buộc phải chạy được.
    """
    import pytest as _p

    shim, _ = _shim()
    boom = KeyError("duong-dan-hong")
    seen = {}
    with shim.raises(KeyError) as ei:
        raise boom
    seen["value"] = ei.value
    assert seen["value"] is boom
    assert ei.type is KeyError
    assert ei.match("duong") is True
    with _p.raises(AssertionError, match="did not match"):
        ei.match("^khong")


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
