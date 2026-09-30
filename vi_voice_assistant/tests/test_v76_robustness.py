"""Test cho bản v7.6 (2) - nhắc nhở chịu được dữ liệu thật, và shim phải như pytest.

Bốn nhóm lỗi bị bắt khi soi lại điểm vào công cộng:

  1. `action_set_reminder` đọc `data["time"]` rồi gọi thẳng `.get("type")`. Model
     (hoặc `--json` người dùng viết) gửi `"time": "3 phút nữa"` - một CHUỖI - là cả
     lệnh chết bằng ``AttributeError: 'str' object has no attribute 'get'``;
     tương tự, `minutes`/`hour` kiểu rác làm ``float()``/``int()`` nổ giữa chừng.
  2. Trợ lý hỏi "nhắc vào lúc nào?", người dùng đáp "5 phút nữa" thì câu đó bị
     phân tích như LỆNH MỚI: lời nhắc mất nội dung, đặt thành "báo thức".
  3. `config.update_config("tts")` chết bằng ``'str' object has no attribute
     'items'`` - lỗi của người gọi nhưng hiện ra như lỗi của thư viện.
  4. shim `raises` trả về exception trần, còn pytest trả `ExceptionInfo`: test viết
     ``e.value``/``e.match()`` chỉ chạy được trên máy có pytest.

Nguyên tắc: đầu vào rác thì từ chối hoặc giải thích, KHÔNG ném traceback của nội bộ.
"""
import datetime
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

PKG_DIR = Path(__file__).resolve().parent.parent          # .../vi_voice_assistant
REPO_ROOT = PKG_DIR.parent
sys.path.insert(0, str(PKG_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def iso(tmp_path, monkeypatch):
    """Cô lập lịch nhắc: KHÔNG bật timer thật, không ghi vào repo.

    `monkeypatch` `_schedule_reminder` vì các test ở đây đặt lịch "3 phút nữa";
    timer thật sẽ NỔ giữa phiên pytest (in "[TRỢ LÝ] Đến giờ rồi", gọi
    notify-send, kéo phiên test dài thêm hàng phút) - tức là test tự gây nhiễu
    cho chính nó và cho test khác chạy song song.
    """
    import executor

    scheduled: list[dict] = []

    # v7.9: `repeat` thêm vào sau `persist` (có giá trị mặc định) - hậu bối phải
    # khớp chữ ký với hàm thật, nếu không lệnh `đặt nhắc nhở` nổ TypeError ngay
    # trong test. Cũng ghi luôn `repeat` vào bản ghi để test đọc lại được.
    def fake_schedule(task, run_at, persist=True, repeat=None):
        scheduled.append({"task": task, "at": run_at, "repeat": repeat,
                          "id": f"id{len(scheduled)}"})
        return f"id{len(scheduled) - 1}"

    monkeypatch.setattr(executor, "REMINDERS_PATH", str(tmp_path / "reminders.json"))
    monkeypatch.setattr(executor, "_schedule_reminder", fake_schedule)
    monkeypatch.setattr(executor, "ACTIVE_REMINDERS", scheduled)
    executor.clear_pending_reminder()
    yield executor
    executor.clear_pending_reminder()


def _scheduled(executor):
    return [r["task"] for r in executor.ACTIVE_REMINDERS]


# ---------------------------------------------------------------------------
# 1. `time` MOI kieu: khong crash, khong bia thoi diem
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["3 phút nữa", "5 phút", "7 giờ 15 phút", "1 tiếng nữa"])
def test_time_la_chuoi_van_dat_lich_duoc(iso, value):
    """Truoc day cac gia tri nay nem AttributeError (chuoi khong co .get)."""
    assert iso.action_set_reminder("uống nước", {"time": value}) is True
    assert _scheduled(iso) == ["uống nước"], _scheduled(iso)


@pytest.mark.parametrize("value", ["bất kỳ", "", "   ", None, [1, 2], {"type": None}, "sai_kieu"])
def test_time_khong_ro_thi_hoi_lai_khong_chet(iso, value):
    assert iso.action_set_reminder("uống nước", {"time": value}) is False
    assert _scheduled(iso) == []


@pytest.mark.parametrize("value", [3, 3.5, "3", "3,5"])
def test_cong_so_duoc_hieu_la_phut(iso, value):
    assert iso.action_set_reminder("đọc sách", {"time": value}) is True
    entry = iso.ACTIVE_REMINDERS[-1]
    delay = (entry["at"] - datetime.datetime.now()).total_seconds()
    assert 55 <= delay <= 245, (value, delay)             # ~3 phut, co dung sai


def test_thoi_diem_da_qua_thi_tu_choi(iso):
    assert iso.action_set_reminder("việc", {"time": 0}) is False
    assert iso.action_set_reminder("việc", {"time": -5}) is False
    assert _scheduled(iso) == []


@pytest.mark.parametrize("minutes", ["5 phút", None, "abc", float("nan"), float("inf"), {}, []])
def test_minutes_kieu_rac_ve_mac_dinh_khong_no(iso, minutes):
    assert iso.action_set_reminder("việc", {"time": {"type": "delay", "minutes": minutes}}) is True


def test_minutes_vuot_nguong_duoc_chan_lai(iso):
    """10^9 phút mà tin là thật thì timer ngủ tới... 1900 năm sau; chặn ở biên."""
    assert iso.action_set_reminder("việc", {"time": {"type": "delay", "minutes": 10 ** 9}}) is True
    entry = iso.ACTIVE_REMINDERS[-1]
    assert entry["at"] <= datetime.datetime.now() + datetime.timedelta(days=367), entry["at"]


@pytest.mark.parametrize("hour, minute", [("23", "30"), (99, -7), (None, None), ("x", "y")])
def test_clock_ep_kieu_va_chan_trong_gio(iso, hour, minute):
    assert iso.action_set_reminder("việc", {"time": {"type": "clock", "hour": hour,
                                                    "minute": minute}}) is True
    entry = iso.ACTIVE_REMINDERS[-1]
    assert 0 <= entry["at"].hour <= 23 and 0 <= entry["at"].minute <= 59, entry["at"]


@pytest.mark.parametrize("day_offset", ["hom kia", None, -3, 10 ** 9])
def test_day_offset_rac_khong_lam_no_lich(iso, day_offset):
    assert iso.action_set_reminder("việc", {"time": {"type": "clock", "hour": 7,
                                                    "day_offset": day_offset}}) is True


def test_dict_chuan_khong_bien_doi_gi_ca_is_keep_identity(iso):
    """Ép kiểu KHÔNG được nhân bản dict chuẩn: `time_info` là chính object đó."""
    raw = {"type": "delay", "minutes": 5}
    assert iso._coerce_time_info(raw) is raw


def test_luong_cu_dict_van_cho_ket_qua_nhu_cu(iso):
    """Parity với hành vi v7.5: dict hop le -> cung thoi diem, cung chuoi phan hoi."""
    import datetime

    target = datetime.datetime.now() + datetime.timedelta(hours=2)
    ok = iso.action_set_reminder("uống nước", {"time": {
        "type": "clock", "hour": target.hour, "minute": target.minute}})
    assert ok is True
    assert iso.ACTIVE_REMINDERS
    entry = iso.ACTIVE_REMINDERS[-1]
    assert (entry["at"] - target).total_seconds() < 61, (entry["at"], target)


# ---------------------------------------------------------------------------
# 2. hoi "luc nao?" -> dap "5 phut nua": phai giu lai NOI DUNG
# ---------------------------------------------------------------------------
def test_pending_giu_dung_noi_dung_can_nhac(iso):
    assert iso.action_set_reminder("uống nhiều nước", {"time": None}) is False
    pending = iso.pending_reminder()
    assert pending and pending["task"] == "uống nhiều nước", pending
    assert pending["until"] > time.monotonic()


def test_noi_cau_tra_loi_vao_loi_nhac_dang_cho(iso):
    iso.action_set_reminder("uống nhiều nước", {"time": None})
    assert iso.try_complete_pending_reminder("2 phút nữa") is True
    assert _scheduled(iso) == ["uống nhiều nước"], _scheduled(iso)
    assert iso.pending_reminder() is None                 # da tieu thu xong


def test_cau_khong_chua_thoi_diem_tra_ve_none_va_bo_trong(iso):
    """Phai de lug cho NLU: cau khac chu de khong bi 'noi' vao loi nhac cu."""
    iso.action_set_reminder("đọc sách", {"time": None})
    assert iso.try_complete_pending_reminder("mở youtube giúp tôi") is None
    assert iso.pending_reminder() is None                 # khong de treo
    assert iso.try_complete_pending_reminder("1 phút nữa") is None


def test_pending_khong_con_de_nang_het_han(iso, monkeypatch):
    iso.action_set_reminder("việc cũ", {"time": None})
    with iso._PENDING_LOCK:
        iso.PENDING_REMINDER["until"] = time.monotonic() - 1
    assert iso.try_complete_pending_reminder("2 phút nữa") is None
    assert _scheduled(iso) == []


def test_dat_nhac_moi_thi_xoa_pending(iso):
    iso.action_set_reminder("việc cũ", {"time": None})
    assert iso.pending_reminder() is not None
    iso.action_set_reminder("việc mới", {"time": "4 phút"})
    assert iso.pending_reminder() is None
    assert _scheduled(iso)[-1] == "việc mới"


def test_dry_run_khong_dat_lich_nhung_van_bao_cho_biet(iso, capsys):
    iso.action_set_reminder("uống thuốc", {"time": None})
    before = len(iso.ACTIVE_REMINDERS)
    assert iso.try_complete_pending_reminder("9 phút nữa", dry_run=True) is True
    assert len(iso.ACTIVE_REMINDERS) == before
    assert "[TEST]" in capsys.readouterr().out


def test_luong_cu_khong_pending_thi_khong_hieu_ung_gi(iso):
    assert iso.try_complete_pending_reminder("5 phút nữa") is None
    assert _scheduled(iso) == []


# ---------------------------------------------------------------------------
# 3. REPL: _complete_pending_reminder khong duoc phep lam chet vong lap
# ---------------------------------------------------------------------------
def test_repl_noi_thoi_diem_va_in_ket_qua(iso, tmp_path, monkeypatch):
    import main as assistant_main

    state = assistant_main.ReplState()
    iso.action_set_reminder("tắt máy", {"time": None})
    assert assistant_main._complete_pending_reminder("6 phút nữa", state) is True
    assert _scheduled(iso)[-1] == "tắt máy"


def test_repl_khong_co_pending_thi_tra_ve_none(iso):
    import main as assistant_main

    state = assistant_main.ReplState()
    assert assistant_main._complete_pending_reminder("5 phút nữa", state) is None


def test_repl_nuot_loi_cua_executor_de_khong_chet_vong(iso, monkeypatch):
    """Mot loi nhac phu khong duoc lam chet REPL: log roi xu ly nhu khong co gi."""
    import main as assistant_main

    iso.action_set_reminder("việc gì đó", {"time": None})

    def boom(text, dry_run=False):
        raise RuntimeError("executor hong")

    monkeypatch.setattr(iso, "try_complete_pending_reminder", boom)
    state = assistant_main.ReplState()
    assert assistant_main._complete_pending_reminder("5 phút nữa", state) is None
    assert iso.pending_reminder() is None                 # da don de, khong treo


def test_repl_dry_run_danh_dau_test_mode(iso, capsys):
    import main as assistant_main

    state = assistant_main.ReplState(dry_run=True)
    iso.action_set_reminder("uống nước", {"time": None})
    assert assistant_main._complete_pending_reminder("7 phút nữa", state) is True
    out = capsys.readouterr().out
    assert "[TEST]" in out and "không đặt lịch" in out, out


# ---------------------------------------------------------------------------
# 4. config: kieu sai phai duoc bao dung noi
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["tts", 42, ["a"], None, object()])
def test_update_config_tu_choi_kieu_khac_dict(tmp_path, bad):
    import config

    with pytest.raises(TypeError, match="cần dict"):
        config.update_config(bad, tmp_path / "config.json")


def test_update_config_van_chay_dung_voi_dict(tmp_path):
    import config

    merged = config.update_config({"tts": {"enabled": False}}, tmp_path / "config.json")
    assert merged["tts"]["enabled"] is False
    assert config.load_config(tmp_path / "config.json")["tts"]["enabled"] is False


def test_update_config_khong_chia_se_object_voi_nguoi_goi(tmp_path):
    """Sua `updates` sau khi cap nhat khong duoc doi config DA LUU (aliasing)."""
    import config

    updates = {"website_map": {"youtube": "https://youtube.com"}}
    merged = config.update_config(updates, tmp_path / "config.json")
    updates["website_map"]["youtube"] = "https://DU-DOI"
    assert merged["website_map"]["youtube"] == "https://youtube.com"
    assert config.load_config(tmp_path / "config.json")["website_map"]["youtube"] == \
        "https://youtube.com"


def test_deep_merge_khong_sua_base(tmp_path):
    import config

    base = {"a": {"b": 1}}
    out = config._deep_merge(base, {"a": {"c": 2}})
    assert base == {"a": {"b": 1}} and out == {"a": {"b": 1, "c": 2}}


# ---------------------------------------------------------------------------
# 5. shim `raises`: hai duong chay (pytest that / runner) phai nhu mot
# ---------------------------------------------------------------------------
@pytest.fixture
def shim():
    import run_tests

    return run_tests._make_pytest_shim()


def test_shim_raises_tra_exception_info(shim):
    boom = RuntimeError("nope")

    def fn():
        raise boom

    info = shim.raises(RuntimeError, fn)
    assert info.value is boom and info.type is RuntimeError
    assert info.match(r"^no") is True
    with pytest.raises(AssertionError, match="did not match"):
        info.match(r"^xy")                            # lech -> do, khong phai False


def test_shim_raises_dang_context_co_value(shim):
    with shim.raises(KeyError) as info:
        raise KeyError("duong-dan")
    assert isinstance(info.value, KeyError)
    assert info.match("duong") is True


def test_shim_raises_khop_pytest_that(shim):
    """So sanh truc tiep voi `ExceptionInfo` cua pytest (neu may co cai pytest)."""
    pytest_mod = pytest.importorskip("pytest")
    boom = ValueError("thong bao")

    def fn():
        raise boom

    real = pytest_mod.raises(ValueError, fn)
    mine = shim.raises(ValueError, fn)
    assert real.value is mine.value is boom
    assert real.type is mine.type is ValueError
    # `match()` khớp -> True ở CẢ HAI; lệch -> AssertionError ở CẢ HAI. shim ban
    # đầu trả False khi lệch (test "xanh" trên runner, đỏ trên pytest): chính
    # so sánh truc tiep nay bat duoc lech hop dong do.
    assert real.match("thong") is True and mine.match("thong") is True
    for info in (real, mine):
        with pytest.raises(AssertionError):
            info.match("^khong")


def _interpreter_without_pytest():
    """Tim mot tien trinh Python MAI KHONG import duoc pytest (de test runner nhúng).

    `sys.executable` trong moi truong dev/CI thuong CO pytest -> runner se uy quyen
    cho pytest va test nay khong con kiem duoc duong chay stdlib-nua. Tim dung
    interpreter, khong tim thay thi bo qua (khong bao do gian).
    """
    candidates = [sys.executable, "/usr/bin/python3", "python3"]
    for exe in dict.fromkeys(candidates):
        try:
            probe = subprocess.run([exe, "-c", "import pytest"], capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode != 0:
            return exe
    return None


def test_luu_lich_that_ghi_file_va_huy_duoc(tmp_path, monkeypatch):
    """Đường THẬT của `_schedule_reminder`: có timer, có file `reminders.json`, huỷ được.

    Các test ở trên chặn hàm này để lịch nhắc không nổ giữa phiên pytest, nên ở
    đây gọi thẳng một lần với lịch xa (1 giờ) rồi huỷ - nếu không, phần ghi đĩa
    của nhắc nhở thành code "không ai chạy bao giờ" mà vẫn được tính là đã kiểm.
    """
    import datetime

    import executor

    monkeypatch.setattr(executor, "REMINDERS_PATH", str(tmp_path / "reminders.json"))
    monkeypatch.setattr(executor, "ACTIVE_REMINDERS", [])
    run_at = datetime.datetime.now() + datetime.timedelta(hours=1)
    reminder_id = executor._schedule_reminder("việc xa", run_at)
    assert reminder_id
    saved = Path(executor.REMINDERS_PATH)
    assert saved.is_file(), "lịch nhắc phải được lưu xuống đĩa"
    assert "việc xa" in saved.read_text(encoding="utf-8")
    entry = executor.ACTIVE_REMINDERS[-1]
    assert entry["timer"].daemon is True, "timer không daemon sẽ giữ tiến trình sống"
    entry["timer"].cancel()
    executor.ACTIVE_REMINDERS.remove(entry)
    assert executor.ACTIVE_REMINDERS == []


def test_bo_runner_khong_can_pytest_van_xong_bo_test(tmp_path):
    """`python run_tests.py` trên máy KHÔNG cài pytest phải in ra "0 fail".

    Đây là lời hứa của cả bộ test (stdlib-only) nên phải được kiểm bằng cách CHẠY
    THẬT runner - CI `no-deps` làm việc này, nhưng test cũng phải tự biết, nếu
    không lời hứa chỉ do một file YAML ngoài repo giữ.
    """
    import run_tests

    for name in ("raises", "fixture", "mark", "approx", "skip", "importorskip"):
        assert hasattr(run_tests._make_pytest_shim(), name), name

    # CHONG DE QUY: khi chinh runner nhung dang chay, `sys.modules["pytest"]` la
    # cai shim (co __vi_shim__) -> dung spawn nua, neu khong runner goi runner
    # vo tan (loai de quy nay lam ca phien test treo hang chuc phut).
    if getattr(sys.modules.get("pytest"), "__vi_shim__", False):
        return

    exe = _interpreter_without_pytest()
    if exe is None:
        return                       # moi truong deu co pytest: kiem shim la du

    # `-k v76` de phien long chi chay phan lien quan: loi muon kiem o day la
    # "runner khong can pytest van chay duoc test va bao 0 fail", khong phai
    # cho ca bo chay hai lan moi lan pytest.
    proc = subprocess.run(
        [exe, str(PKG_DIR / "run_tests.py"), "-q", "-k", "v76"],
        cwd=str(PKG_DIR), capture_output=True, text=True, timeout=600,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "VI_ASSISTANT_HOME": str(tmp_path),
             "PYTHONPATH": ""},
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-2000:]
    assert "0 fail" in out, out[-600:]
    assert "tong 0" not in out, "runner chay 0 test la MAU XANH GIA"
