#!/usr/bin/env python3
"""
run_tests.py - Bo chay kiem thu KHONG can pytest cai san (v6).
Cach dung:
    python3 run_tests.py            # chay tat ca
    python3 run_tests.py -k time    # chi chay test co 'time' trong ten
    python3 run_tests.py -v         # verbose (in traceback ngay)
v7.4 nâng cấp:
- Không còn in "0 pass, 0 fail" rồi thoát 0 khi thư mục tests trống (bản cài đặt
  không kèm tests): in rõ lý do và thoát 1.
- `VI_TESTS_FORCE_EMBEDDED=1` buộc dùng runner nhúng, để đường không-pytest được
  kiểm tra ngay cả trên máy đã cài pytest.
"""
from __future__ import annotations

import contextlib
import importlib
import importlib.util
import inspect
import io
import logging
import os
import pathlib
import re
import sys
import tempfile
import traceback
import types
from typing import Any


# --- Co pytest that khong? Quyet dinh o main(), KHONG lam luc import ---
# v7.2 - SUA LOI NGHIEM TRONG (lam CI "xanh gia"): ban cu dung
#     sys.exit(os.system(sys.executable + " -m pytest " + ...))
# os.system() tra ve WAIT STATUS (exit_code << 8), kh phai exit code that:
# pytest fail => os.system tra 256 => sys.exit(256) bi cat mask thanh 0
# => CI bao THANH CONG du TOAN BO test do. O Windows thi duong dan
# sys.executable co dau cach (C:\Program Files\...) bi tach roi lenh.
# Dung subprocess.call([list]) de lay dung exit code va kh lo quoting.
#
# v7.3 - 2 lỗi còn lại của chính khối này:
#   * delegate NGAY LUC IMPORT: "import run_tests" (doc cong cu trong test,
#     mo REPL lenh, hay chi mo file) lap tuc chay ca bo test va GOA EXIT;
#   * chi can co mat module "pytest" la delegate, nen co tham so chi cua
#     runner nhu --list bi day thang cho pytest -> "unrecognized arguments".
# Nay delegate trong main(), va bo qua delegate neu co co cua runner.
def _detect_real_pytest() -> bool:
    """Co pytest THAT khong - va khong de bị chính shim cua runner danh lua.

    Chi dung `find_spec("pytest")` la KHONG du: ham nay tra ve `__spec__` cua
    module da nam trong sys.modules, ma runner thi TỰ nhét shim của nó vào đó.
    Kết quả là lần `import run_tests` thu hai (vd mot file test `import
    run_tests`) tin rang "pytest da cai" -> khong lap nua, trong khi toan bo
    `pytest.fixture/parametrize` ma test dang dung lai chinh la cai shim do.
    Danh dau bang __vi_shim__ va kiem tra no truoc khi tin sys.modules.
    """
    existing = sys.modules.get("pytest")
    if existing is not None:
        return not getattr(existing, "__vi_shim__", False)
    try:
        return importlib.util.find_spec("pytest") is not None
    except (ImportError, ValueError):
        return False


# find_spec (khong phai import): chi can biet co module hay khong; import that
# se chay __init__ cua pytest (~chuc ms) ngay khi runner bat dau.
# VI_TESTS_FORCE_EMBEDDED=1: buoc chay bang runner nhung ngay ca khi may co
# pytest. Can cho (a) test chinh runner - neu khong, moi lenh goi vao `main()`
# deu bi day sang pytest that va khong kiem duoc phan nhung; (b) mo phong may
# chua cai gi ca.
_HAS_PYTEST = _detect_real_pytest() and not os.environ.get("VI_TESTS_FORCE_EMBEDDED")

# ---------------------------------------------------------------------------
# PYTEST SHIM
# ---------------------------------------------------------------------------
_MISSING = object()

# _Skip la TIN HIEU DIEU HUONG (de runner bo qua test), khong phai loi ma nguoi
# dung gap phai -> giu ten ngan, khong them duoi "Error" cho day dong.
class _Skip(Exception): pass  # noqa: N818

class _Approx:
    def __init__(self, expected, rel=1e-6, abs_tol=None):
        self.expected, self._rel, self._abs = expected, rel, abs_tol
    def __eq__(self, other):
        if self._abs is not None: return abs(other - self.expected) <= self._abs
        return abs(other - self.expected) <= self._rel * max(abs(self.expected), 1e-12)
    def __repr__(self): return "approx(%r)" % self.expected

@contextlib.contextmanager
def _raises(exc_type, match=None):
    try: yield
    except exc_type as e:
        if match and not re.search(match, str(e)):
            raise AssertionError("Msg %r !~ %r" % (str(e), match)) from e
    except Exception as e:
        raise AssertionError(
            "Expected %s, got %s: %s" % (exc_type.__name__, type(e).__name__, e)
        ) from e
    else:
        raise AssertionError("Expected %s but no exception" % exc_type.__name__)

class _MarkParam:
    def __init__(self, argnames, argvalues):
        self.argnames = [n.strip() for n in argnames.split(",")]
        self.argvalues = argvalues
    def __call__(self, fn):
        fn.__parametrize__ = (self.argnames, self.argvalues); return fn

class _MarkSkipif:
    def __init__(self, cond, reason=""):
        self.cond, self.reason = cond, reason
    def __call__(self, fn):
        if not self.cond: return fn
        def _w(*a,**k): raise _Skip(self.reason)
        _w.__name__ = fn.__name__; return _w

class _Mark:
    @staticmethod
    def parametrize(argnames, argvalues, ids=None): return _MarkParam(argnames, argvalues)
    @staticmethod
    def skipif(cond, reason=""): return _MarkSkipif(cond, reason)

def _fixture(fn=None, scope="function", autouse=False, name=None):
    """Dung nhu `pytest.fixture` cho cac cach dung trong du an: truyen so scope
    va `autouse` (fixture tu chay moi test, khong can khai bao trong tham so).

    `autouse` dang duoc ho tro day du: file test moi dung `@pytest.fixture(autouse=True)`
    de don state toan cuc - runner nhung bo qua la test chay voi state rac cua
    test truoc do, lo xanh do trang that hon ca fail.
    """
    def _mark(target):
        target.__is_fixture__ = True
        target.__fscope__ = scope
        target.__fautouse__ = autouse
        if name:
            target.__fname__ = name
        return target

    if fn is None:
        return _mark
    return _mark(fn)

# --- Capsys: captures sys.stdout/stderr LIVE during test ---
class _Capsys:
    """Replace sys.stdout/stderr with StringIO during test so readouterr() works mid-test."""
    def __init__(self):
        self._out_buf = io.StringIO()
        self._err_buf = io.StringIO()
    def _enter(self, real_out, real_err):
        """Install capture buffers, tee to real streams."""
        self._real_out = real_out
        self._real_err = real_err
        self._out_buf = io.StringIO()
        self._err_buf = io.StringIO()
        sys.stdout = _Tee(real_out, self._out_buf)
        sys.stderr = _Tee(real_err, self._err_buf)
    def _exit(self):
        sys.stdout = self._real_out
        sys.stderr = self._real_err
    def readouterr(self):
        out = self._out_buf.getvalue(); self._out_buf.truncate(0); self._out_buf.seek(0)
        err = self._err_buf.getvalue(); self._err_buf.truncate(0); self._err_buf.seek(0)
        return types.SimpleNamespace(out=out, err=err)

class _Tee:
    def __init__(self, real, buf): self._r, self._b = real, buf
    def write(self, s): self._r.write(s); self._b.write(s)
    def flush(self): self._r.flush()
    def fileno(self): return self._r.fileno()
    @property
    def encoding(self): return getattr(self._r, "encoding", "utf-8")

# --- Monkeypatch ---
class _Monkeypatch:
    """Thế chỗ `pytest.MonkeyPatch` - du cac cach goi ma test trong du an dung.

    `raising=False` duoc chap nhan (test cua `tts` set cac engine KHONG ton tai
    tren may chay test): ban cu thieu tham so nay -> `run_tests.py` bao
    TypeError o test hop le, khieng nguoi doc tuong test bi sai.
    """
    def __init__(self):
        self._patches = []
        self._cwd: Any = _MISSING
        self._syspath = None

    def setattr(self, obj_or_dotted, name_or_value=_MISSING, value=_MISSING, raising=True):
        # Support: setattr(obj, 'name', val) OR setattr('mod.name', val)
        if not isinstance(obj_or_dotted, str) and raising and name_or_value is not _MISSING \
                and value is not _MISSING and not hasattr(obj_or_dotted, str(name_or_value)):
            raise AttributeError("%r khong co thuoc tinh %r" % (obj_or_dotted, name_or_value))
        if name_or_value is _MISSING:
            raise TypeError("setattr needs at least 2 args")
        if value is _MISSING:
            # 2-arg form: setattr('builtins.print', fn)
            dotted = obj_or_dotted
            value = name_or_value
            last_dot = dotted.rfind(".")
            if last_dot == -1:
                raise ValueError("No dot in %r" % dotted)
            mod_name, attr = dotted[:last_dot], dotted[last_dot+1:]
            if mod_name == "builtins":
                import builtins
                obj = builtins
            else:
                obj = importlib.import_module(mod_name)
            old = getattr(obj, attr, _MISSING)
            setattr(obj, attr, value)
            self._patches.append((obj, attr, old))
        else:
            obj, name = obj_or_dotted, name_or_value
            old = getattr(obj, name, _MISSING)
            setattr(obj, name, value)
            self._patches.append((obj, name, old))
    def delattr(self, obj, name, raising=True):
        try:
            old = getattr(obj, name)
            delattr(obj, name)
            self._patches.append((obj, name, old, True))
        except AttributeError:
            if raising: raise
    def setitem(self, mapping, key, value):
        old = mapping.get(key, _MISSING)
        mapping[key] = value
        self._patches.append((mapping, key, old, False, "item"))

    def delitem(self, mapping, key, raising=True):
        try:
            old = mapping[key]
            del mapping[key]
            self._patches.append((mapping, key, old, True, "item"))
        except KeyError:
            if raising: raise

    # setenv/delenv: `os.environ` KHONG phai dict, nen khong the dua vet `undo`
    # bang duong cua setitem (no thu `delattr` va nhe nong bo qua) -> bien moi
    # truong da dat la roi sang tat ca cac test chay sau do. Danh dau "item" de
    # undo phuc hoi bang `obj[name] = old` / `obj.pop(name)`.
    def setenv(self, name, value, prepend=None):
        old = os.environ.get(name, _MISSING)
        if prepend:
            value = value + prepend + os.environ.get(name, "")
        os.environ[name] = value
        self._patches.append((os.environ, name, old, False, "item"))

    def delenv(self, name, raising=True):
        try:
            old = os.environ[name]
        except KeyError:
            if raising:
                raise KeyError(name) from None
            return
        del os.environ[name]
        self._patches.append((os.environ, name, old, False, "item"))
    def chdir(self, path) -> None:
        self._cwd = os.getcwd()
        os.chdir(str(path))

    def syspath_prepend(self, path) -> None:
        path = str(path)
        self._syspath = list(sys.path)
        if path not in sys.path:
            sys.path.insert(0, path)

    def undo(self):
        if self._syspath is not None:
            sys.path[:] = self._syspath
            self._syspath = None
        if self._cwd is not _MISSING:
            os.chdir(self._cwd)
            self._cwd = _MISSING
        for item in reversed(self._patches):
            obj, name, old = item[0], item[1], item[2]
            restore_del = len(item) > 3 and item[3]
            if len(item) > 4 and item[4] == "item":
                if restore_del or old is _MISSING:
                    obj.pop(name, None)
                else:
                    obj[name] = old
                continue
            if restore_del:
                setattr(obj, name, old); continue
            if old is _MISSING:
                if isinstance(obj, dict): obj.pop(name, None)
                else:
                    try: delattr(obj, name)
                    except AttributeError: pass
            elif isinstance(obj, dict): obj[name] = old
            else: setattr(obj, name, old)

class _Caplog:
    """Bản thu hẹp của fixture `caplog`: gom bản ghi log trong lúc test chạy.

    runner nhung PHAI co thu nay: cac test kiem tra "loi duoc bao nhu the nao"
    (config sai kieu, engine TTS chet, duong dan model...) duoc viet bang
    `caplog.text`. Thieu no thi may CHUA cai pytest chay `run_tests.py` se bao
    "missing 1 required positional argument: 'caplog'" - tuc bo test tu choi
    chay tren chinh moi truong toi thieu ma du an cam ket ho tro.
    """

    def __init__(self, level=logging.WARNING):
        self.records: list = []
        self.handler = None
        self._level = level
        self._saved: tuple = ()

    @staticmethod
    def _to_number(level):
        return logging.getLevelName(level) if isinstance(level, str) else int(level)

    def _enter(self):
        root = logging.getLogger()
        self._saved = (root.level, root.handlers[:])
        self.handler = logging.StreamHandler(io.StringIO())
        self.handler.setLevel(self._level)
        self.handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        # type checker coi day la 'gan vao method' - o day dung y: handler tam
        # nay chi gom record, khong in an gi.
        self.handler.emit = self.records.append  # type: ignore[method-assign,assignment]
        root.addHandler(self.handler)
        root.setLevel(min(root.level or self._level, self._level))

    def _exit(self):
        root = logging.getLogger()
        if self.handler is not None:
            with contextlib.suppress(ValueError):
                root.removeHandler(self.handler)
            self.handler = None
        if self._saved:
            root.level, root.handlers[:] = self._saved[0], self._saved[1]

    @property
    def text(self) -> str:
        return "\n".join(f"{rec.levelname}  {rec.getMessage()}" for rec in self.records)

    def clear(self) -> None:
        self.records.clear()

    @contextlib.contextmanager
    def at_level(self, level=logging.WARNING, logger=None):
        """Hạ mức log của một logger cụ thể xuống đúng mức cần bắt (như pytest)."""
        target = logging.getLogger(logger) if logger else logging.getLogger()
        old_level, old_propagate = target.level, target.propagate
        wanted = self._to_number(level)
        target.setLevel(wanted)
        target.propagate = True
        # Handler cung PHAI duoc ha theo: chi logger ma handler con giu
        # WARNING thi ban ghi DEBUG bi loc ngay tai handler, va test se thay
        # caplog.text rong cho du log da duoc ghi that.
        old_handler_level = self.handler.level if self.handler else 0
        if self.handler is not None:
            self.handler.setLevel(min(old_handler_level or wanted, wanted))
        try:
            yield self
        finally:
            target.setLevel(old_level)
            target.propagate = old_propagate
            if self.handler is not None:
                self.handler.setLevel(old_handler_level)

    def set_level(self, level, logger=None) -> None:
        target = logging.getLogger(logger) if logger else logging.getLogger()
        target.setLevel(self._to_number(level))


def _skip(reason=""):
    raise _Skip(reason)


def _install_pytest_shim() -> None:
    """Thế chỗ module `pytest` cho các file test `import pytest` lấy fixture.

    CHI lap khi KHONG co pytest that. Ban cu gan `sys.modules["pytest"] = shim`
    vo dieu kien: neu pytest that dang chay ma doan nay duoc nap (vi du ai do
    `import run_tests` giua chung một phiên pytest - chinh bo test cung co the
    lam vay) thi module that bi CHE KHUI, toan bo fixture/mark/auto-discovery
    that cua pytest hu theo, báo lỗi ở nơi không liên quan gì tới run_tests.
    """
    # module_from_spec (khong phai ModuleType): module tao tay co __spec__ = None
    # se khien `import pytest` / `from pytest import fixture` trong file test
    # chet bang ValueError "pytest.__spec__ is None" o Python 3.11+ - tuc la
    # nhung file test dung pytest.fixture/parametrize KHONG CHAY DUOC tren chinh
    # runner cua minh, dung cai ma runner sinh ra de phuc vu.
    spec = importlib.util.spec_from_loader("pytest", loader=None)
    assert spec is not None, "khong tao duoc spec cho module gia 'pytest'"
    module = importlib.util.module_from_spec(spec)
    module.__doc__ = "Pytest shim cua run_tests.py (chi dung khi may khong co pytest)"
    # setattr (khong gan truc tiep): ten thuoc tinh duoc tao dong, type checker
    # khong co quyen cho rang module 'pytest' gia phai co dinh nghien cuu.
    for attr, value in (
        ("__vi_shim__", True),        # de lan sau khong nhan nham shim = pytest that
        ("fixture", _fixture),
        ("mark", _Mark()),
        ("raises", _raises),
        ("approx", _Approx),
        ("skip", _skip),
    ):
        setattr(module, attr, value)
    sys.modules["pytest"] = module


if not _HAS_PYTEST:
    _install_pytest_shim()

# ---------------------------------------------------------------------------
# RUNNER
# ---------------------------------------------------------------------------
def _load_module(path):
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    assert spec is not None and spec.loader is not None, f"khong nap duoc {path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod
    spec.loader.exec_module(mod)
    return mod

def _collect_fixtures(mod):
    return {n: o for n,o in vars(mod).items() if callable(o) and getattr(o,"__is_fixture__",False)}

_MOD_CACHE: dict = {}


def _resolve(name, fixtures, mp, capsys, tmp_path, finalizers=None, depth=0, caplog=None):
    """Cấp một tham số cho test/fixture: builtin, hoặc fixture khác (đệ quy).

    v7.3 - hai lỗi của bản cũ, cả hai đều làm runner nhúng SẬP những test mà
    pytest chạy bình thường (tức mất đúng lý do tồn tại của nó - máy không có
    pytest thì không test nào chạy được):

      1. ``fn()`` gọi fixture với KHÔNG tham số -> mọi fixture có tham số
         (``def iso(tmp_path, monkeypatch)``) chết bằng TypeError. Nay giải
         quyết đệ quy, có chặn độ sâu để báo "vòng tròn fixture" rõ ràng.
      2. fixture dạng ``yield`` (setup/teardown) bị trả về thẳng một generator
         -> test nhận generator thay vì giá trị, và teardown KHÔNG bao giờ chạy
         (đường dẫn tạm không được dọn, monkeypatch không được undo). Nay: lấy
         giá trị từ generator rồi đăng ký teardown chạy SAU test - fixture
         scope "module" chạy teardown một lần ở CUỐI file, giống pytest.
    """
    if name == "monkeypatch": return mp
    if name == "capsys": return capsys
    if name == "caplog": return caplog
    if name == "tmp_path": return tmp_path
    if name in _MOD_CACHE: return _MOD_CACHE[name]
    if name in fixtures:
        if depth > 6:
            raise RuntimeError(f"fixture '{name}' tham chieu vong tron (do sau > 6)")
        fn = fixtures[name]
        scope = getattr(fn, "__fscope__", "function")
        kwargs = {}
        for pname, param in inspect.signature(fn).parameters.items():
            value = _resolve(pname, fixtures, mp, capsys, tmp_path, finalizers,
                             depth + 1, caplog)
            if value is None and param.default is inspect.Parameter.empty:
                raise RuntimeError(f"fixture '{name}' can '{pname}' - khong tim thay")
            if value is not None:
                kwargs[pname] = value
        v = fn(**kwargs)
        if inspect.isgenerator(v):
            # GIU generator vao bien rieng `gen` roi MOI gan v = next(gen):
            # viet `lambda gen=v: ...` sau khi v da bi gan lai la loi kinh dien
            # - finalizer se goi next() tren CHINH GIA TRI tra ve (PosixPath)
            # va che do tai cho.
            gen = v
            v = next(gen)
            if finalizers is not None and scope != "module":
                finalizers.append(lambda g=gen: next(g, None))
        if scope == "module":
            _MOD_CACHE[name] = v
        return v
    return None

def _count_test_files(test_dir) -> int:
    """Bao nhieu file test trong thu muc (khong nem loi neu thu muc khong ton tai)."""
    directory = pathlib.Path(test_dir)
    if not directory.is_dir():
        return 0
    return len(sorted(directory.glob("test_*.py")))


def run(keyword=None, verbose=False, quiet=False):
    test_dir = pathlib.Path(__file__).parent / "tests"
    files = sorted(test_dir.glob("test_*.py"))
    total = passed = failed = skipped = 0
    failures = []

    for path in files:
        _MOD_CACHE.clear()
        try:
            mod = _load_module(path)
        except Exception as e:
            print("\n[LOAD ERROR] %s: %s" % (path.name, e))
            traceback.print_exc()
            failed += 1; continue

        fixtures = _collect_fixtures(mod)
        autouse_names = [n for n, f in fixtures.items() if getattr(f, "__fautouse__", False)]
        fns = [(n,o) for n,o in vars(mod).items() if n.startswith("test_") and callable(o)]
        if not fns: continue

        if not quiet:
            print("\n" + "=" * 58)
            print("  %s  (%d tests)" % (path.name, len(fns)))
            print("=" * 58)

        file_start = (passed, failed, skipped)
        for name, fn in fns:
            if keyword and keyword.lower() not in name.lower(): continue

            cases: list[Any] = [(name, fn, {})]
            if hasattr(fn, "__parametrize__"):
                arg_names, arg_values = fn.__parametrize__
                cases = []
                for vals in arg_values:
                    # MOT tham so thi gia tri duoc truyen NGUYEN VAN: dung quy
                    # tac cua pytest. Ban cu dung `isinstance(vals,(list,tuple))`
                    # de tach ra -> voi @parametrize("flags", [["--version"],
                    # ["--doctor"]]) no tang chu "--version" thanh 10 ki tu cho
                    # 10 tham so, test goi main.py bang ["-", "h", "i", ...] va
                    # che do -q cua CI chay fail khong giai thich duoc.
                    if len(arg_names) == 1:
                        pkw = {arg_names[0]: vals}
                        shown = (vals,)
                    else:
                        seq = tuple(vals) if isinstance(vals, (list, tuple)) else (vals,)
                        pkw = dict(zip(arg_names, seq))
                        shown = seq
                    cid = "-".join(str(v)[:18] for v in shown)
                    cases.append(("%s[%s]" % (name, cid), fn, pkw))

            for case_name, test_fn, extra_kw in cases:
                total += 1
                mp = _Monkeypatch()
                capsys = _Capsys()
                caplog = _Caplog()
                finalizers: list[Any] = []   # teardown cua fixture dang yield
                with tempfile.TemporaryDirectory() as td:
                    tmp_path = pathlib.Path(td)
                    # caplog/capsys PHAI vao cuoi TRUOC khi giai tham so: test
                    # goi `caplog.at_level(...)` ngay trong than ham, ma fixture
                    # thi duoc cap luc... de nhat la bo vao cung luc lap kwargs.
                    caplog._enter()
                    real_out, real_err = sys.stdout, sys.stderr
                    capsys._enter(real_out, real_err)
                    sig = inspect.signature(test_fn)
                    kwargs = dict(extra_kw)
                    # fixture autouse: giai (de setup + dang ky teardown) nhung
                    # KHONG truyen vao kwargs - test khong khai bao tham so.
                    for auto_name in autouse_names:
                        _resolve(auto_name, fixtures, mp, capsys, tmp_path,
                                 finalizers, 0, caplog)
                    for pname in sig.parameters:
                        if pname not in kwargs:
                            v = _resolve(pname, fixtures, mp, capsys, tmp_path,
                                         finalizers, 0, caplog)
                            if v is not None: kwargs[pname] = v
                    outcome, detail = "pass", None
                    try:
                        test_fn(**kwargs)
                    except _Skip as e:
                        outcome, detail = "skip", str(e)
                    except Exception:
                        outcome, detail = "fail", traceback.format_exc()
                    finally:
                        caplog._exit()
                        capsys._exit()
                        # teardown cua fixture chay TRUOC mp.undo(): theo thu tu
                        # pytest - fixture day du "khoi phuc sau khi test xong".
                        for fin in reversed(finalizers):
                            try:
                                fin()
                            except Exception:
                                if outcome == "pass":
                                    outcome, detail = "fail", traceback.format_exc()
                        mp.undo()
                    # QUAN TRỌNG: chỉ in kết quả SAU KHI mp.undo() đã gỡ mọi bản vá.
                    # Nếu in ngay khi builtins.print còn bị test vá (vd các test của
                    # platform_utils thay print bằng hàm luôn ném lỗi), chính lệnh
                    # print của runner sẽ ném lỗi và làm SẬP toàn bộ runner.
                    if outcome == "pass":
                        passed += 1
                        if not quiet:
                            print("  PASS  %s" % case_name)
                    elif outcome == "skip":
                        skipped += 1
                        print("  SKIP  %s  (%s)" % (case_name, detail))
                    else:
                        failed += 1
                        failures.append((case_name, detail))
                        print("  FAIL  %s" % case_name)
                        if verbose:
                            print(detail)

        if quiet:
            p_, f_, s_ = (passed - file_start[0], failed - file_start[1], skipped - file_start[2])
            print("%-32s %3d pass%s" % (
                path.name, p_,
                (", %d FAIL" % f_) if f_ else ("", ", %d skip" % s_)[bool(s_)]))

    print("\n" + "=" * 58)
    print("Ket qua: %d pass, %d fail, %d skip  (tong %d)" % (passed, failed, skipped, total))
    if failures:
        print("\n" + "=" * 58 + "\nCac test that bai:")
        for fname, tb in failures:
            print("\n--- %s ---\n%s" % (fname, tb))
    return failed

def _delegate_to_pytest(argv: list[str]) -> int | None:
    """Uỷ quyền cho pytest nếu có; trả về None nếu phải tự chạy bằng runner nhúng.

    Bỏ qua uỷ quyền khi có cờ CHỈ CỦA RUNNER (``--list``) - pytest không hiểu
    những cờ đó và sẽ báo lỗi thay vì in danh sách file test.
    """
    if not _HAS_PYTEST or "--list" in argv:
        return None
    import subprocess

    return subprocess.call([sys.executable, "-m", "pytest", *argv])


def main(argv=None) -> int:
    """Điểm vào CLI (mới v7.3) - cũng là console script ``vi-tests``.

    Tách khỏi khối ``__main__`` để: (a) ``pip install .`` tạo được lệnh
    ``vi-tests``, (b) test khác gọi lại được runner mà không cần spawn tiến
    trình con, (c) nhận ``argv`` tường minh cho test.
    """
    import argparse

    argv = list(sys.argv[1:] if argv is None else argv)
    delegate = _delegate_to_pytest(argv)
    if delegate is not None:
        return delegate

    ap = argparse.ArgumentParser(description="Bộ kiểm thử KHÔNG cần pytest")
    ap.add_argument("-k", dest="keyword", default=None, help="chỉ chạy test tên chứa chuỗi này")
    ap.add_argument("-v", "--verbose", action="store_true", help="in lỗi chi tiết khi fail")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="in mỗi file một dòng tổng kết (giống `pytest -q`)")
    ap.add_argument("--list", action="store_true", help="liệt kê file test rồi thoát")
    # parse_known_args (khong phai parse_args): CI va install.py goi
    #     python run_tests.py -q
    # lenh nay hop le voi pytest nhung truoc day FAI o may khong co pytest, vi
    # runner tu dung argparse khong biet co -q -> "unrecognized arguments" va
    # ca buoc kiem tra trong CI no-deps chet ma khong co test nao chay.
    # Mo -q that + bo qua co laanh -> runner chay duoc voi moi cach goi.
    a, unknown = ap.parse_known_args(argv)
    if unknown:
        print(f"(bỏ qua cờ không thuộc runner: {' '.join(unknown)})")
    test_dir = pathlib.Path(__file__).resolve().parent / "tests"
    if a.list:
        for path in sorted(test_dir.glob("test_*.py")):
            print(path.name)
        return 0
    if _count_test_files(test_dir) == 0:
        # v7.4: "0 pass, 0 fail, exit 0" la MAU XANH GIA. Ban cai bang pip khong
        # kem tests/ (co y, de wheel nhe), nen chay runner tu do la khong chay
        # gi ca - cung kieu loi `|| echo passed` da phat hien o CI. Bao ro ly do
        # va tra ma loi de CI/khong ai tuong la da kiem.
        print("KHONG tim thay file test nao trong:")
        print(f"  {test_dir}")
        print("  - Neu day la ban cai bang pip: wheel co y KHONG dong tests/.")
        print("    Chay bo test tu thu muc nguon:")
        print("      cd <Thu>Muc/source && python vi_voice_assistant/run_tests.py -q")
        print("  - Neu chay trong thu muc source ma van 0: thu muc `tests/` bi")
        print("    doi ten/ma mat.")
        return 1
    return 1 if run(keyword=a.keyword, verbose=a.verbose, quiet=a.quiet) else 0


if __name__ == "__main__":
    sys.exit(main())
