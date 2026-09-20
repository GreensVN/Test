"""
Test cho bản v7.4 - toàn vẹn dữ liệu, kiểu được CI kiểm tra, và mấy lỗi mà
chỉ chạy trên Python CŨ / máy KHÔNG có thư viện mới lộ ra.

Ba nhóm lỗi bản này sửa, và test phải đánh đúng vào chỗ đó:

  1. `vi-doctor` chết trước khi in nổi một dòng trên Python >= 3.14
     (`platform.major` không tồn tại) -> một mục hỏng làm hỏng cả báo cáo;
  2. file dữ liệu bị ghi kiểu "mở ra là mất nội dung cũ" (.history.json) và
     mỗi nơi tự viết một kiểu ghi atomic (config có fsync, reminders không);
  3. dispatcher chọn cách gọi handler theo bảng GHI TAY, và `train_phobert`
     chạy huấn luyện chỉ vì bị `import`.

Thêm: `install.py` không được khuyên người đang ở trong venv đi tạo venv;
`monkeypatch.setenv` của runner nhúng phải hoàn tác được (os.environ không phải
dict nên trước đây biến môi trường rò sang mọi test chạy sau).
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent.parent          # .../vi_voice_assistant
REPO_ROOT = PKG_DIR.parent
sys.path.insert(0, str(PKG_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import diagnostic  # noqa: E402
import executor  # noqa: E402
import paths  # noqa: E402
import run_tests  # noqa: E402


def _load_root_module(name: str, filename: str):
    """Nạp module ở thư mục GỐC repo (install.py) - nằm ngoài package."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, str(REPO_ROOT / filename))
    assert spec is not None and spec.loader is not None, f"khong nap duoc {filename}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


install = _load_root_module("vi_install_v74", "install.py")


# ---------------------------------------------------------------------------
# 1. vi-doctor: mục hỏng không được kéo sập cả báo cáo
# ---------------------------------------------------------------------------
def test_doctor_khong_chet_tren_python_moi():
    """`platform.major` (không tồn tại) từng làm --doctor sập trên Python 3.14+.

    Không có cách nào "tình cờ" chạy máy 3.14 trong CI, nên hàm nhận tham số
    version_info để test mô phỏng được mọi bản.
    """
    rows = diagnostic.check_runtime((3, 14, 0))
    assert any(mark.strip() == "[!]" and "3.14" in text for mark, text in rows), rows
    assert not any(mark.strip() == "[X]" for mark, _ in rows)


def test_doctor_bao_bad_tren_python_qua_cu():
    rows = diagnostic.check_runtime((3, 8, 10))
    assert any(mark.strip() == "[X]" and "3.8" in text for mark, text in rows)


def test_doctor_in_du_bao_cao_du_mot_muc_no():
    """Một mục raise (file config hỏng, model lạ...) phải thành dòng [X]."""
    def _boom():
        raise RuntimeError("đọc file model hỏng")

    original = diagnostic.check_config
    diagnostic.check_config = _boom
    try:
        report = diagnostic.run_checks()
    finally:
        diagnostic.check_config = original

    rows = report["sections"]["Cấu hình"]
    assert any(mark.strip() == "[X]" and "đọc file model hỏng" in text for mark, text in rows), rows
    # Phep thu: cac muc khac van duoc in du, khong mat theo muc bi hong.
    assert set(report["sections"]) == {
        "Môi trường", "Dữ liệu", "Cấu hình", "Model", "Thư viện", "Giọng nói"
    }


def test_cli_doctor_khong_bao_bao_loi_ra_lenh():
    """`vi-doctor` chạy toi tan: loi bat ngo cua bo kiem tra -> exit 1, co dong [X]."""
    original = diagnostic.run_checks
    diagnostic.run_checks = lambda: (_ for _ in ()).throw(ValueError("bo kiem tra hong"))
    try:
        code = diagnostic.main(["--json"])
    finally:
        diagnostic.run_checks = original
    assert code == 1


def test_bao_cao_khong_noi_moi_thu_on_khi_con_muc_x(tmp_path, capsys):
    """Trước: không có dòng 'fix' nào là in 'Mọi thứ ổn' dù exit code = 1."""
    report = {
        "ok": False, "problems": 1, "warnings": 0,
        "sections": {"Model": [("[X]  ", "lite_model.pkl khong doc duoc")]},
        "fixes": [],
    }
    diagnostic.print_report(report)
    out = capsys.readouterr().out
    assert "Mọi thứ ổn" not in out
    assert "cần chú ý" in out

    clean = {"ok": True, "problems": 0, "warnings": 0, "sections": {"A": []}, "fixes": []}
    diagnostic.print_report(clean)
    assert "Mọi thứ ổn" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 2. Dispatcher: chuc nang phai duoc suy ra chu khong ghi tay
# ---------------------------------------------------------------------------
def test_bang_handler_duoc_suy_ra_tu_chu_ky():
    assert executor._HANDLERS_WITH_DATA == {"set_reminder", "calculate"}


def test_muon_nhan_du_toan_intent_phai_co_2_tham_so():
    assert executor._handler_wants_data(lambda t, data: True) is True
    assert executor._handler_wants_data(lambda t: True) is False
    assert executor._handler_wants_data(lambda *a, **k: True) is True

    def with_keyword_only(target, *, extra=None):
        return True

    def with_self(method):                       # builtin/C: khong doc duoc chu ky
        return False

    assert executor._handler_wants_data(with_keyword_only) is False
    assert executor._handler_wants_data(with_self) is False


def test_handler_moi_khong_biet_ten_van_duoc_truyen_du_du_lieu(monkeypatch):
    """Them handler 2 tham số mà KHÔNG kèp ghi tên vào bảng: phải vẫn chạy đúng.

    Đây chính là cái bẫy của bảng ghi tay ở v7.2-v7.3 - thiếu tên thì
    dispatcher gọi handler(target) và người dùng nhận TypeError.
    """
    seen = {}

    def fake(target, intent_json):
        seen["target"] = target
        seen["data"] = intent_json
        return True

    monkeypatch.setitem(executor.HANDLERS, "intent_moi", fake)
    ok = executor.execute_command({"intent": "intent_moi", "target": "abc", "confidence": 1.0})
    assert ok is True
    assert seen["target"] == "abc"
    assert seen["data"]["intent"] == "intent_moi"


def test_intent_khong_phai_chuoi_thi_tu_choi_le_pha_not_loi(monkeypatch):
    for bad in (None, 42, ["open_app"], object()):
        ok = executor.execute_command({"intent": bad, "confidence": 1.0})
        assert ok is False, bad


def test_target_khong_phai_chuoi_van_xu_ly_duoc(monkeypatch):
    calls = []
    monkeypatch.setitem(executor.HANDLERS, "get_datetime", lambda t: calls.append(t) or True)
    assert executor.execute_command({"intent": "get_datetime", "target": 2026, "confidence": 1.0})
    assert calls == ["2026"]


# ---------------------------------------------------------------------------
# 3. Ghi file du lieu: atomic + fsync o mot cho duy nhat
# ---------------------------------------------------------------------------
def test_atomic_write_json_tao_thu_muc_cha(tmp_path):
    target = tmp_path / "chua" / "ton" / "tai.json"
    paths.atomic_write_json(target, {"ok": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": 1}


def test_atomic_write_json_khong_bao_gi_nguyen_khi_ghi_hong(tmp_path):
    """Payload không serialize được (model, datetime...) trước đây để lại file rỗng."""
    target = tmp_path / "data.json"
    paths.atomic_write_json(target, {"truoc": "con du"})

    class NotSerializable:
        pass

    try:
        paths.atomic_write_json(target, {"hong": NotSerializable()})
    except TypeError:
        pass
    else:
        raise AssertionError("phai nem TypeError khi payload khong serialize duoc")

    assert json.loads(target.read_text(encoding="utf-8")) == {"truoc": "con du"}
    # File tam phai duoc don sach, khong de rac trong thu muc
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != target.name]
    assert leftovers == [], leftovers


def test_save_config_luu_duoc_unicode_va_json_hop_le(tmp_path):
    import config

    target = tmp_path / "config.json"
    config.save_config({"website_map": {"báo mới": "https://baomoi.com"}}, target)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["website_map"]["báo mới"] == "https://baomoi.com"
    assert target.read_text(encoding="utf-8").endswith("}\n")


def test_reminders_luu_duoc_ca_khi_thu_muc_cha_chua_ton_tai(tmp_path, monkeypatch):
    """mkstemp trong thu muc chua co -> FileNotFoundError, bi `except OSError` an mat.

    Nhắc nhở biến mất im lặng là loại lỗi không ai báo cáo vì không có thông báo nào.
    """
    target = tmp_path / "chua" / "co" / "reminders.json"
    monkeypatch.setattr(executor, "REMINDERS_PATH", str(target))
    monkeypatch.setattr(executor, "ACTIVE_REMINDERS",
                        [{"id": "x1", "task": "uống thuốc",
                          "at": "2026-09-21T08:00:00"}])
    executor._save_reminders()
    assert target.is_file(), "phai tu tao thu muc cha"
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data[0]["task"] == "uống thuốc"


def test_history_khong_de_lai_file_tam(tmp_path, monkeypatch):
    import main as assistant_main

    history = tmp_path / ".history.json"
    monkeypatch.setattr(assistant_main, "HISTORY_PATH", history)
    for text in ("mở youtube", "tắt máy", "hẹn 7 giờ sáng"):
        assistant_main.save_history_entry(text)
    entries = json.loads(history.read_text(encoding="utf-8"))
    assert entries == ["mở youtube", "tắt máy", "hẹn 7 giờ sáng"]
    assert sorted(p.name for p in tmp_path.iterdir()) == [".history.json"]


# ---------------------------------------------------------------------------
# 3b. _ResilientStream: bao console khong duoc sinh ra loi moi
# ---------------------------------------------------------------------------
def test_stream_boc_duoc_ghi_khong_tra_so(tmp_path, monkeypatch):
    """`write()` phai tra ve SO KY TU, ke ca khi stream ben trong tra None.

    Ban v7.4 ep `int(self._stream.write(s))` de mypy im lang - va do la loi:
    moi doi tuong gia lap stdout (test dung, va ca vai stream cua ben thu ba) tra
    ve None, `int(None)` nang TypeError ngay giua luc in bao cao. Lop boc phai
    chju duoc dieu do, khong duoc bi no lam chet lenh in.
    """
    import io

    import platform_utils

    class SilentStream(io.StringIO):
        def write(self, s):          # co y khong tra gi ca
            io.StringIO.write(self, s)
            return None

    sink = SilentStream()
    wrapped = platform_utils._ResilientStream(sink)
    assert wrapped.write("xin chào") == len("xin chào")
    assert "xin chào" in sink.getvalue()
    assert wrapped.isatty() is False


# ---------------------------------------------------------------------------
# 4. install.py: loi khuyen dung theo hoan canh
# ---------------------------------------------------------------------------
def test_trong_venv_khong_duoc_khuyen_tao_venv():
    err = "error: externally-managed-environment\n\n" \
          "Read more about this behavior here: <https://peps.python.org/pep-0668/>"
    assert install.retry_flags_for(err, []) == ["--user"]
    assert install.retry_flags_for(err, [], in_venv=True) is None
    assert install.retry_flags_for("Permission denied: '/usr/lib/python3'", [],
                                   in_venv=True) is None
    assert "tạo môi trường riêng" not in install.fix_hint(True)
    assert "venv" in install.fix_hint(False)


def test_in_virtualenv_nhan_du_cach_khai_bao(monkeypatch, tmp_path):
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    monkeypatch.setattr(sys, "prefix", "/usr")
    monkeypatch.setattr(sys, "base_prefix", "/usr")
    assert install.in_virtualenv() is False

    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / ".venv"))
    assert install.in_virtualenv() is True

    monkeypatch.delenv("VIRTUAL_ENV")
    monkeypatch.setenv("CONDA_PREFIX", str(tmp_path / "envs"))
    assert install.in_virtualenv() is True

    monkeypatch.delenv("CONDA_PREFIX")
    monkeypatch.setattr(sys, "prefix", str(tmp_path / ".venv"))
    monkeypatch.setattr(sys, "base_prefix", "/usr")
    assert install.in_virtualenv() is True


def test_ke_hoach_cai_dat_chi_go_pip_mot_len_moi_profile():
    plan = install.plan_commands(("numpy",), editable=False)
    assert all(cmd[:3] == [sys.executable, "-m", "pip"] for cmd in plan), plan
    joined = " ".join(" ".join(c) for c in plan)
    assert "numpy" in joined
    plan_edit = install.plan_commands((), editable=True)
    assert any("-e" in cmd for cmd in plan_edit), plan_edit


# ---------------------------------------------------------------------------
# 4b. Runner nhung: khong co test nao thi PHAI bao, khong duoc xanh gia
# ---------------------------------------------------------------------------
def test_khong_co_test_thi_exit_1_va_giai_thich(tmp_path, monkeypatch):
    """Ban cai bang pip khong kem tests/ -> runner tung in "0 pass, 0 fail" exit 0.

    Xanh kiểu đó còn hại hơn đỏ: CI (va ca nguoi dung) tuong bo kiem tra da chay.
    """
    pkg = tmp_path / "vi_voice_assistant"
    pkg.mkdir(parents=True)
    shutil.copy(PKG_DIR / "run_tests.py", pkg / "run_tests.py")
    proc = subprocess.run([sys.executable, "run_tests.py", "-q"], cwd=str(pkg),
                          capture_output=True, text=True, timeout=180,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                               "VI_TESTS_FORCE_EMBEDDED": "1"})
    assert proc.returncode == 1, (proc.returncode, proc.stdout[-400:])
    assert "KHONG tim thay file test" in proc.stdout
    assert "0 pass" not in proc.stdout      # khong in tong ket cua mot bo trong rong


def test_dem_file_test_khong_nem_loi_tren_duong_dan_khong_ton_tai(tmp_path):
    assert run_tests._count_test_files(tmp_path / "khong" / "co" / "day") == 0
    assert run_tests._count_test_files(tmp_path) == 0
    (tmp_path / "test_a.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    (tmp_path / "khong_phai_test.py").write_text("", encoding="utf-8")
    assert run_tests._count_test_files(tmp_path) == 1


# ---------------------------------------------------------------------------
# 4c. voice_cache: duoc tim o THU MUC DU LIEU, va khong tin duong dan ao
# ---------------------------------------------------------------------------
def test_voice_cache_doc_o_thu_muc_du_lieu_truoc(tmp_path, monkeypatch):
    """Ban cai dat khong duoc bat nguoi dung nhet mp3 vao site-packages."""
    import tts

    user_dir = tmp_path / "data" / "voice_cache"
    legacy_dir = tmp_path / "site-packages" / "vi_voice_assistant" / "voice_cache"
    for d in (user_dir, legacy_dir):
        d.mkdir(parents=True)
        (d / "index.csv").write_text("xin chao,hello.mp3\n", encoding="utf-8")
    (user_dir / "hello.mp3").write_bytes(b"user")
    (legacy_dir / "hello.mp3").write_bytes(b"legacy")

    monkeypatch.setattr(tts, "VOICE_CACHE_DIR", user_dir)
    monkeypatch.setattr(tts, "VOICE_CACHE_DIR_LEGACY", legacy_dir)
    monkeypatch.setattr(tts, "_voice_cache_index", None)
    index = tts._load_voice_cache()
    assert index["xin chao"].read_bytes() == b"user", "phai uu tien thu muc du lieu"


def test_voice_cache_bo_qua_duong_dan_khong_ton_tai(tmp_path, monkeypatch):
    """Dong lech trong index.csv khong duoc tao Path ao trong bang tra.

    Truoc day duong dan chi duoc kiem tra luc phat, nen loi hien ra giua luc doc
    - kho truy hon nhieu so voi loai no ngay khi nap bang.
    """
    import tts

    cache = tmp_path / "voice_cache"
    cache.mkdir()
    (cache / "index.csv").write_text("ma hong,khong_ton_tai.mp3\nchup,có file.mp3\n",
                                     encoding="utf-8")
    (cache / "có file.mp3").write_bytes(b"ok")
    monkeypatch.setattr(tts, "VOICE_CACHE_DIR", cache)
    monkeypatch.setattr(tts, "VOICE_CACHE_DIR_LEGACY", tmp_path / "khong_co_gi_dau")
    monkeypatch.setattr(tts, "_voice_cache_index", None)
    index = tts._load_voice_cache()
    assert set(index) == {"chup"}, index


# ---------------------------------------------------------------------------
# 5. Import khong duoc lam viec gi - va mot file JSON hong khong duoc lam sap CLI
# ---------------------------------------------------------------------------
def test_huan_luyen_phobert_khong_chay_luc_import(tmp_path):
    """`main()` nam NGOAI `if __name__ == "__main__":` -> import la huan luyen."""
    proc = subprocess.run(
        [sys.executable, "-c", "import train_phobert; print('OK')", "--co-ai-do"],
        cwd=str(PKG_DIR), capture_output=True, text=True, timeout=180,
        env={**os.environ, "PYTHONPATH": str(PKG_DIR),
             "VI_ASSISTANT_HOME": str(tmp_path),
             "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "OK" in proc.stdout


def test_file_dong_y_giay_phep_hong_khong_lam_sap_cli(tmp_path, monkeypatch):
    import giong_nc

    model_key = sorted(giong_nc.NC_MODELS)[0]          # ten that trong bang mo hinh
    consent = tmp_path / "DA_DONG_Y.json"
    consent.write_text('["day la list, khong phai dict"]', encoding="utf-8")
    monkeypatch.setattr(giong_nc, "CONSENT_FILE", str(consent))
    assert giong_nc._load_consent() == {}
    assert giong_nc.da_dong_y(model_key) is False


# ---------------------------------------------------------------------------
# 6. Runner nhung: monkeypatch phai hoan tac duoc moi loai doi tuong
# ---------------------------------------------------------------------------
def test_monkeypatch_setenv_hoan_tac_dung():
    """os.environ khong phai dict -> undo tung thu `delattr` va nhe nong bo qua."""
    key = "VI_ASSISTANT_TEST_ENV_V74"
    os.environ.pop(key, None)
    mp = run_tests._Monkeypatch()
    mp.setenv(key, "1")
    assert os.environ[key] == "1"
    mp.undo()
    assert key not in os.environ, "bien moi truong ro sang cac test chay sau"


def test_monkeypatch_delenv_va_lai():
    key = "VI_ASSISTANT_TEST_ENV_V74_B"
    os.environ[key] = "ban dau"
    mp = run_tests._Monkeypatch()
    mp.delenv(key)
    assert key not in os.environ
    mp.undo()
    assert os.environ[key] == "ban dau"


def test_monkeypatch_delenv_khong_ton_tai_phai_bao_ro():
    mp = run_tests._Monkeypatch()
    try:
        mp.delenv("VI_ASSISTANT_KHONG_BAO_GIO_CO")
    except KeyError:
        pass
    else:
        raise AssertionError("delenv mac dinh phai nem KeyError nhu pytest")
    mp.undo()
    mp2 = run_tests._Monkeypatch()
    mp2.delenv("VI_ASSISTANT_KHONG_BAO_GIO_CO", raising=False)   # khong nem
    mp2.undo()


def test_monkeypatch_setitem_tren_dict_hoan_tac_dung():
    holder = {"a": 1}
    mp = run_tests._Monkeypatch()
    mp.setitem(holder, "a", 2)
    mp.setitem(holder, "moi", 3)
    mp.undo()
    assert holder == {"a": 1}
