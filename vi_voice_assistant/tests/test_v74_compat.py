"""
Test tương thích Python cho bản v7.4 - "chạy được trên bản MINH HỨA hỗ trợ".

Vì sao có file này: dự án khai báo ``requires-python = ">=3.9"`` và CI có cả
job 3.9, nhưng ``intent_model.py`` + ``nlu_advanced.py`` dùng annotation kiểu
PEP 604 (``str | None``) mà KHÔNG có ``from __future__ import annotations``.
Trên Python 3.9, biểu thức đó được đánh giá lúc định nghĩa hàm nên
``import intent_model`` chết ngay bằng

    TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'

tức là TOÀN BỘ trợ lý sập trên đúng cái bản Python mà README nói là hỗ trợ.
Lỗi sống sót qua nhiều bản vì CI chưa từng chạy (workflow chưa nằm trên
nhánh mặc định) và bộ test chỉ chạy trên 3.11.

Nên ở đây kiểm tra bằng AST, không cần có mặt Python 3.9:

  1. annotation đánh giá lúc chạy (chữ ký hàm, biến cấp module/lớp) mà dùng
     ``|`` thì file đó PHẢI có future import;
  2. không dùng cú pháp cần bản mới hơn ``requires-python`` (match, isinstance
     với union, và ast.parse(feature_version=...));
  3. mọi module phải import được bằng THUẦN stdlib - đây là hợp đồng cốt lõi
     của dự án và cũng là chỗ từng hỏng (``from utils import ...`` ở v7.1);
  4. ``requires-python`` và ma trận CI không được lệch nhau.

Riêng máy quét ở (1) có thêm test "cắm bug giả" để đảm bảo nó thật sự bắt
được lỗi chứ không xanh vì không tìm thấy gì.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

# v7.4: chinh file nay tung vi pham rule no kiem (dung `tuple[int, int] | None` trong
# chu ky ma thieu `from __future__ import annotations`) -> tren Python 3.9 chinh no
# khong import duoc. Vi vay ben duoi may quat AST quet ca thu muc tests/.

PKG_DIR = Path(__file__).resolve().parent.parent          # .../vi_voice_assistant
REPO_ROOT = PKG_DIR.parent
sys.path.insert(0, str(PKG_DIR))

# Thu vien NANG duoc phep thieu: du an co y chay duoc thu stdlib, model ML/voice
# la duong chon cai them (xem [tool.project.optional-dependencies]).
OPTIONAL_THIRD_PARTY = (
    "numpy", "sklearn", "joblib", "rapidfuzz", "pyttsx3", "speech_recognition",
    "sounddevice", "torch", "transformers", "piper", "TTS", "edge_tts",
    "pyaudio", "wikipedia", "requests",
)


def _sources():
    """Mọi file .py của dự án - KỂ CẢ tests/: test cũng chạy trên bản 3.9.

    `conftest.py` vẫn được quét AST (nó không có annotation nào), nhưng bị loại
    ở bước nạp-module-bằng-stdlib bên dưới vì pytest mới import nó đúng ngữ cảnh.
    """
    files = sorted(p for p in PKG_DIR.rglob("*.py") if p.name != "conftest.py")
    root_install = REPO_ROOT / "install.py"
    if root_install.is_file():
        files.append(root_install)
    return files


def _has_future_annotations(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            if any(alias.name == "annotations" for alias in node.names):
                return True
    return False


def _has_pep604_union(node: ast.expr) -> bool:
    return any(isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr)
               for sub in ast.walk(node))


def _runtime_annotations(tree: ast.Module):
    """Yield tung annotation ma Python DANH GIA LUC CHAY (PEP 604 do 3.10+).

    Gom chu ky ham (ca tham so lan kieu tra ve) va AnnAssign o cap module/lop.
    Annotation cua bien ben TRONG than ham khong duoc danh gia nen bo qua -
    viet sai o do thi van chay duoc tren 3.9, khong can bao dong.
    """
    for node in [tree, *ast.walk(tree)]:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            args = [*a.posonlyargs, *a.args, *a.kwonlyargs]
            args += [extra for extra in (a.vararg, a.kwarg) if extra is not None]
            for arg in args:
                if arg.annotation is not None:
                    yield arg.annotation
            if node.returns is not None:
                yield node.returns
        elif isinstance(node, (ast.Module, ast.ClassDef)):
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and stmt.annotation is not None:
                    yield stmt.annotation


def _runtime_annotation_lines(tree: ast.Module) -> list[int]:
    return sorted({node.lineno for node in _runtime_annotations(tree)
                   if _has_pep604_union(node)})


def _scan_sources(paths):
    """Chay ca ba kiem tra tren mot danh sach file -> (loi_pep604, loi_syntax)."""
    min_version = _requires_python()[0]
    feature = (int(min_version[0]), int(min_version[1]))
    pep604, syntax = [], []
    for path in paths:
        src = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src, feature_version=feature)
        except SyntaxError as e:
            need = ".".join(map(str, feature))
            syntax.append(f"{path.name}: can Python > {need} ({e.msg} dong {e.lineno})")
            continue
        for node in ast.walk(tree):
            if type(node).__name__ == "Match":
                line = getattr(node, "lineno", 0)
                syntax.append(f"{path.name}:{line} - lenh match chi co tu 3.10")
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("isinstance", "issubclass")
                    and len(node.args) > 1):
                for sub in ast.walk(node.args[1]):
                    if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr):
                        syntax.append(
                            f"{path.name}:{node.lineno} - isinstance(x, A | B) chi co tu 3.10")
        if not _has_future_annotations(tree):
            lines = _runtime_annotation_lines(tree)
            if lines:
                pep604.append(f"{path.name} (dong {lines})")
    return pep604, syntax


def _requires_python() -> tuple[tuple[int, int], tuple[int, int] | None]:
    """(toi_thieu, toi_da) tu pyproject.toml - khong dung thu vien TOML."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'requires-python\s*=\s*"([^"]+)"', text)
    assert m, "pyproject.toml phai khai bao requires-python"
    low = re.search(r">=\s*(\d+)\.(\d+)", m.group(1))
    assert low, f"khong doc duoc requires-python: {m.group(1)!r}"
    high = re.search(r"<\s*(\d+)\.(\d+)", m.group(1))
    return (int(low.group(1)), int(low.group(2))), \
        (int(high.group(1)), int(high.group(2))) if high else None


# ---------------------------------------------------------------------------
# 1. PEP 604 trong annotation can future import
# ---------------------------------------------------------------------------
def test_annotation_union_khong_lam_sap_python_cu():
    pep604, _ = _scan_sources(_sources())
    assert not pep604, (
        "Nhung file dung `A | B` trong annotation ma thieu "
        "'from __future__ import annotations' -> se nang TypeError luc import "
        f"tren ban Python cu nhat duoc ho tro: {pep604}"
    )


# ---------------------------------------------------------------------------
# 2. Khong dung cú pháp của bản mới hơn bản tối thiểu
# ---------------------------------------------------------------------------
def test_khong_dung_cuc_phap_can_python_moi():
    _, syntax = _scan_sources(_sources())
    assert not syntax, f"Cú pháp vượt bản tối thiểu: {syntax}"


def test_moi_file_dich_duoc_tren_python_toi_thieu():
    low, _ = _requires_python()
    bad = []
    for path in _sources():
        try:
            ast.parse(path.read_text(encoding="utf-8"), feature_version=low)
        except SyntaxError as e:
            bad.append(f"{path.name}: {e.msg} (dong {e.lineno})")
    assert not bad, f"File khong dich duoc voi Python {low[0]}.{low[1]}: {bad}"


# ---------------------------------------------------------------------------
# 3. May quat phai that su bat duoc loi (chung minh rang, khong phai do trach)
# ---------------------------------------------------------------------------
def test_may_quat_bat_duoc_bug_cam_san(tmp_path):
    """Cam hai file gia dinh: mot co bug, mot sach -> may quat phai thay dung."""
    bug = tmp_path / "co_bug.py"
    bug.write_text("def f(x: str | None) -> int | None:\n    return 1\n", encoding="utf-8")
    clean = tmp_path / "da_sua.py"
    clean.write_text("from __future__ import annotations\n\n\n"
                     "def g(x: str | None) -> int | None:\n    return 1\n", encoding="utf-8")
    inside = tmp_path / "trong_ham.py"
    inside.write_text("def h(v):\n    y: str | None = v\n    return y\n", encoding="utf-8")

    pep604, _ = _scan_sources([bug, clean, inside])
    assert pep604 == [f"{bug.name} (dong [1])"], pep604


# ---------------------------------------------------------------------------
# 4. Thu tuc: moi module phai nap duoc khi may CHANG co thu vien nao
# ---------------------------------------------------------------------------
_LOAD_ALL = (
    "import importlib, json, sys\n"
    "res = {}\n"
    "for name in sys.argv[1:]:\n"
    "    try:\n"
    "        importlib.import_module(name)\n"
    "        res[name] = 'OK'\n"
    "    except BaseException as exc:      # bat ca loi khong phai Exception\n"
    "        res[name] = type(exc).__name__ + ':' + str(getattr(exc, 'name', '') or exc)\n"
    "print(json.dumps(res))\n"
)


def _runtime_sources():
    """Chi module cap nhat cua package (khong quet tests/): test duoc phep co
    line `sys.path.insert(...)` o dau file, day la thiet le cua pytest."""
    return sorted(p for p in PKG_DIR.glob("*.py") if p.name != "conftest.py")


def _module_names():
    return [p.stem for p in _runtime_sources()]


def test_moi_module_import_duoc_bang_thuan_stdlib(tmp_path):
    """Thay vì đoán: nạp thật cả 22 module trong MỘT tiến trình rồi đọc kết quả.

    Day la lop phong cho ca loi o v7.1 (``from utils import ...`` - module khong
    ton tai) lan loi o v7.3 (package thieu ``__init__.py``): test don vi chi nap
    module ma no can, nen module khong duoc gi nap den thi hong vo can.
    """
    names = _module_names()
    assert len(names) >= 15, f"quet sai thu muc? {names}"
    proc = subprocess.run(
        [sys.executable, "-c", _LOAD_ALL, *names],
        cwd=str(PKG_DIR), capture_output=True, text=True, timeout=240,
        env={**dict(__import__("os").environ), "PYTHONPATH": str(PKG_DIR),
             "PYTHONDONTWRITEBYTECODE": "1",
             "VI_ASSISTANT_HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, f"lenh nap module chet: {proc.stderr[-600:]}"
    results = json.loads(proc.stdout.strip().splitlines()[-1])
    that = {}
    for name, outcome in results.items():
        if outcome == "OK":
            continue
        kind, _, missing = outcome.partition(":")
        if kind == "ModuleNotFoundError" and missing.strip() in OPTIONAL_THIRD_PARTY:
            continue                     # thu vien nang duoc phep thieu
        that[name] = outcome
    assert not that, (
        f"Module khong nap duoc tren moi truong thuan stdlib: {that}. "
        "Ngoài ra: kiểm tra tên module được import có tồn tại thật không, "
        "hoac them thu vien nang vao OPTIONAL_THIRD_PARTY neu dung la duong chon phu tung."
    )


def test_danh_sach_thu_vien_tuy_chon_khong_lech_requirements():
    """OPTIONAL_THIRD_PARTY phai phu bao ten trong requirements.txt (duong nang)."""
    req = (PKG_DIR / "requirements.txt")
    if not req.is_file():
        return
    names = set()
    for line in req.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        m = re.match(r"^([A-Za-z0-9_.-]+)", line)
        if m:
            names.add(m.group(1).lower().replace("-", "_"))
    # ten goi module khac ten goi package o vai noi: day chi la kiem tra bo sung,
    # cho phep lech da biet, but khong duoc co ten o requirements ma test bo het.
    # ten goi PACKAGE khac ten MODULE o vai noi (scikit-learn -> sklearn), nen
    # doi chieu ca hai cach viet truoc khi bao la lech.
    known = {o.lower() for o in OPTIONAL_THIRD_PARTY} | {
        "typing_extensions", "comtypes", "pycaw", "soundcard", "gtts", "librosa",
        "sentencepiece", "num2words", "vnstatus", "scikit_learn", "python_speech_files",
    }
    unknown = {n for n in names if n not in known}
    assert not unknown, f"requirements.txt co thu vien chua duoc test biet: {sorted(unknown)}"


# ---------------------------------------------------------------------------
# 5. Import mot module KHONG duoc bat dau lam viec gi
# ---------------------------------------------------------------------------
_SIDE_EFFECT_ALLOWLIST = {
    # (ten file, ten ham duoc goi o cap module) - da xem ky, vo hai:
    "main.py": {"setup_console"},   # chi doi ma trang/encoding console
    "train_nlu.py": {"seed"},       # random.seed de ket qua huan luyen on dinh
}


def test_import_khong_khien_chuong_trinh_tu_chay():
    """`import train_phobert` tung bat dau ... huan luyen model.

    O cuoi file, `main()` nam NGOAI khoai `if __name__ == "__main__":` (thut le
    lech mot cap) nen moi lenh import deu lan ra chay full pipeline: CLI khac
    goi vao thi bi epoch tran qua mat, con pytest thi SystemExit(2) vi argparse
    doc phai dong dya cua chinh no. Day la cung lop loi da gap voi run_tests.py
    o v7.3 (uy quyen cho pytest luc import), nen gio khoa bang may quat AST.
    """
    offenders = []
    for path in _runtime_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        guarded: set[int] = set()
        for node in tree.body:
            if isinstance(node, ast.If):
                names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
                if "__name__" in names:
                    guarded.update(id(st) for st in node.body)
        for st in tree.body:
            is_module_call = isinstance(st, ast.Expr) and isinstance(st.value, ast.Call)
            if id(st) in guarded or not is_module_call:
                continue
            fn = st.value.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", "")
            if name in _SIDE_EFFECT_ALLOWLIST.get(path.name, ()):
                continue
            offenders.append(f"{path.name}:{st.lineno} goi {name}()")
    where = 'khoai if __name__ == "__main__"'
    assert not offenders, (
        f"Goi ham o cap module ngoai {where} - tac dung phu luc import: {offenders}"
    )


# ---------------------------------------------------------------------------
# 5. requires-python va ma tran CI khong duoc doi dau nhau
# ---------------------------------------------------------------------------
def test_ma_tran_ci_phu_dung_ban_python_toi_thieu():
    workflow = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    if not workflow.is_file():
        return
    text = workflow.read_text(encoding="utf-8")
    m = re.search(r"python-version:\s*\[([^\]]*)\]", text)
    assert m, "khong tim thay dong `python-version: [...]` trong ci.yml"
    matrix = [tuple(int(x) for x in v.split(".")) for v in re.findall(r"(\d+\.\d+)", m.group(1))]
    assert matrix, "khong doc duoc python-version ma tran trong ci.yml"
    low, _ = _requires_python()
    assert min(matrix) == low, (
        f"CI kiem tra tu {min(matrix)[0]}.{min(matrix)[1]} trong khi "
        f"requires-python ghi >= {low[0]}.{low[1]} - moi ben phai biet ban kia"
    )
    assert all(v >= low for v in matrix), f"CI test ca ban duoi requires-python: {matrix}"
