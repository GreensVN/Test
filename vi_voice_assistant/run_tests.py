#!/usr/bin/env python3
"""
run_tests.py - Bo chay kiem thu KHONG can pytest cai san (v6).
Cach dung:
    python3 run_tests.py            # chay tat ca
    python3 run_tests.py -k time    # chi chay test co 'time' trong ten
    python3 run_tests.py -v         # verbose (in traceback ngay)
"""
from __future__ import annotations

import contextlib
import importlib
import importlib.util
import inspect
import io
import os
import pathlib
import re
import sys
import tempfile
import traceback
import types

# --- Thu pytest that truoc ---
# v7.2 - SUA LOI NGHIEM TRONG (lam CI "xanh gia"): ban cu dung
#     sys.exit(os.system(sys.executable + " -m pytest " + ...))
# os.system() tra ve WAIT STATUS (exit_code << 8), kh phai exit code that:
# pytest fail => os.system tra 256 => sys.exit(256) bi cat mask thanh 0
# => CI bao THANH CONG du TOAN BO test do. O Windows thi duong dan
# sys.executable co dau cach (C:\Program Files\...) bi tach roi lenh.
# Dung subprocess.call([list]) de lay dung exit code va kh lo quoting.
try:
    import pytest as _rp  # noqa

    import subprocess

    sys.exit(subprocess.call([sys.executable, "-m", "pytest", *sys.argv[1:]]))
except ImportError:
    pass

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

def _fixture(fn=None, scope="function"):
    if fn is None:
        def _d(f): f.__is_fixture__=True; f.__fscope__=scope; return f
        return _d
    fn.__is_fixture__=True; fn.__fscope__="function"; return fn

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
    def __init__(self): self._patches = []
    def setattr(self, obj_or_dotted, name_or_value=_MISSING, value=_MISSING):
        # Support: setattr(obj, 'name', val) OR setattr('mod.name', val)
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
        self._patches.append((mapping, key, old))
    def delitem(self, mapping, key, raising=True):
        try:
            old = mapping[key]
            del mapping[key]
            self._patches.append((mapping, key, old, True))
        except KeyError:
            if raising: raise
    def setenv(self, name, value, prepend=None):
        old = os.environ.get(name, _MISSING)
        os.environ[name] = (value + prepend + os.environ.get(name,"")) if prepend else value
        self._patches.append((os.environ, name, old))
    def undo(self):
        for item in reversed(self._patches):
            obj, name, old = item[0], item[1], item[2]
            restore_del = len(item) > 3 and item[3]
            if restore_del:
                setattr(obj, name, old); continue
            if old is _MISSING:
                if isinstance(obj, dict): obj.pop(name, None)
                else:
                    try: delattr(obj, name)
                    except AttributeError: pass
            elif isinstance(obj, dict): obj[name] = old
            else: setattr(obj, name, old)

# Install shim
pytest = types.ModuleType("pytest")
pytest.fixture = _fixture
pytest.mark = _Mark()
pytest.raises = _raises
pytest.approx = _Approx
def _skip(reason=""): raise _Skip(reason)
pytest.skip = _skip
sys.modules["pytest"] = pytest

# ---------------------------------------------------------------------------
# RUNNER
# ---------------------------------------------------------------------------
def _load_module(path):
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod
    spec.loader.exec_module(mod)
    return mod

def _collect_fixtures(mod):
    return {n: o for n,o in vars(mod).items() if callable(o) and getattr(o,"__is_fixture__",False)}

_MOD_CACHE: dict = {}

def _resolve(name, fixtures, mp, capsys, tmp_path):
    if name == "monkeypatch": return mp
    if name == "capsys": return capsys
    if name == "tmp_path": return tmp_path
    if name in _MOD_CACHE: return _MOD_CACHE[name]
    if name in fixtures:
        fn = fixtures[name]
        v = fn()
        if getattr(fn,"__fscope__","function") == "module": _MOD_CACHE[name] = v
        return v
    return None

def run(keyword=None, verbose=False):
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
        fns = [(n,o) for n,o in vars(mod).items() if n.startswith("test_") and callable(o)]
        if not fns: continue

        print("\n" + "=" * 58)
        print("  %s  (%d tests)" % (path.name, len(fns)))
        print("=" * 58)

        for name, fn in fns:
            if keyword and keyword.lower() not in name.lower(): continue

            cases = [(name, fn, {})]
            if hasattr(fn, "__parametrize__"):
                arg_names, arg_values = fn.__parametrize__
                cases = []
                for vals in arg_values:
                    if not isinstance(vals, (list, tuple)): vals = (vals,)
                    pkw = dict(zip(arg_names, vals))
                    cid = "-".join(str(v)[:18] for v in vals)
                    cases.append(("%s[%s]" % (name, cid), fn, pkw))

            for case_name, test_fn, extra_kw in cases:
                total += 1
                mp = _Monkeypatch()
                capsys = _Capsys()
                with tempfile.TemporaryDirectory() as td:
                    tmp_path = pathlib.Path(td)
                    sig = inspect.signature(test_fn)
                    kwargs = dict(extra_kw)
                    for pname in sig.parameters:
                        if pname not in kwargs:
                            v = _resolve(pname, fixtures, mp, capsys, tmp_path)
                            if v is not None: kwargs[pname] = v
                    real_out, real_err = sys.stdout, sys.stderr
                    capsys._enter(real_out, real_err)
                    outcome, detail = "pass", None
                    try:
                        test_fn(**kwargs)
                    except _Skip as e:
                        outcome, detail = "skip", str(e)
                    except Exception:
                        outcome, detail = "fail", traceback.format_exc()
                    finally:
                        capsys._exit()
                        mp.undo()
                    # QUAN TRỌNG: chỉ in kết quả SAU KHI mp.undo() đã gỡ mọi bản vá.
                    # Nếu in ngay khi builtins.print còn bị test vá (vd các test của
                    # platform_utils thay print bằng hàm luôn ném lỗi), chính lệnh
                    # print của runner sẽ ném lỗi và làm SẬP toàn bộ runner.
                    if outcome == "pass":
                        passed += 1
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

    print("\n" + "=" * 58)
    print("Ket qua: %d pass, %d fail, %d skip  (tong %d)" % (passed, failed, skipped, total))
    if failures:
        print("\n" + "=" * 58 + "\nCac test that bai:")
        for fname, tb in failures:
            print("\n--- %s ---\n%s" % (fname, tb))
    return failed

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", dest="keyword", default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    sys.exit(run(keyword=a.keyword, verbose=a.verbose))
