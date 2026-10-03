"""Test cho phần nhắc nhở LẶP LẠI của bản v7.9.

"mỗi ngày" là câu người dùng hỏi rất nhiều mà bản trước không có nơi để lưu.
Hệ quả im lặng: nhắc đến giờ thì báo xong là **xoá hẳn khỏi danh sách**, nên
"uống thuốc mỗi ngày" chỉ nhắc đúng MỘT lần rồi thôi. Người dùng tin là đã
hẹn cả tháng - và cũng tin đúng, vì bản cũ chỉ hẹn một lần.

Lỗi tìm được khi viết phần này đều thuộc họ quen thuộc: **tầng trên hiểu, tầng
dưới không, hoặc làm được đúng một lần rồi hỏng**:

  1. `_reminder_task` không gỡ được "mỗi ngày", nên trợ lý đọc thành
     "Nhắc bạn: uống thuốc mỗi ngày". Tệ hơn: "đặt báo thức 6 giờ sáng mỗi
     ngày" để lại nội dung rỗng và rơi về mặc định một cách may mắn.
  2. Nhắc lặp tự hẹn lại được, nhưng **không truyền `repeat` vào lịch mới**:
     nhắc hằng ngày chạy đúng HAI LẦN rồi hạ xuống thành nhắc một lần. Cả tháng
     đầu vẫn ngon nên rất khó phát hiện bằng tay.
  3. Lịch dài hơn trần của `threading.Timer` phải chia chặng; nếu mỗi chặng
     đều được coi là lần nhắc thật thì lặp hằng tháng bắn vài lần mỗi tháng.
  4. Mở lại máy thì mốc giỏ đã trôi qua: không cuộn tới lần kế thì cả chuỗi
     "mỗi ngày" biến mất.
  5. "mỗi ngày" mà chưa nói giờ thì trợ lý hỏi "mấy giờ?" - nhưng phải GIỮ nhịp
     lặp qua câu hỏi, nếu không câu trả lời sau sẽ ra một lời nhắc một lần.
  6. `reminders.json` do người dùng sửa tay có thể mang bất kỳ thứ gì trong
     `repeat`; lỗi đó phải bị chặn ở lúc ĐỌC, không phải lúc nhắc nổ.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

PKG_DIR = Path(__file__).resolve().parent.parent          # .../vi_voice_assistant
REPO_ROOT = PKG_DIR.parent
sys.path.insert(0, str(PKG_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# 1. Đọc nhịp lặp từ câu nói.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("nhắc tôi uống thuốc mỗi ngày lúc 8 giờ", {"kind": "daily"}),
    ("nhắc tôi tập gym hằng tuần", {"kind": "weekly"}),
    ("nhắc tôi trả tiền mỗi tháng", {"kind": "monthly"}),
    ("nhắc tôi gọi mẹ mỗi sáng", {"kind": "daily"}),
    ("nhắc tôi họp mỗi thứ hai", {"kind": "weekly", "weekday": 0}),
    ("nhắc tôi họp mỗi thứ 3", {"kind": "weekly", "weekday": 1}),
    ("nhắc tôi họp mỗi chủ nhật", {"kind": "weekly", "weekday": 6}),
    # gõ không dấu phải ra CÙNG kết quả (điều README quảng cáo)
    ("nhac toi uong thuoc moi ngay", {"kind": "daily"}),
    ("nhac toi hoc moi thu hai", {"kind": "weekly", "weekday": 0}),
])
def test_doc_nhip_lap(text, expected):
    from intent_model import parse_repeat

    assert parse_repeat(text) == expected


@pytest.mark.parametrize("text", [
    "nhắc tôi họp lúc 3 giờ chiều",     # có mốc giờ nhưng KHÔNG lặp
    "nhắc tôi họp sáng mai",            # "sáng mai" là MỘT buổi, không lặp
    "thứ hai tuần này là thứ mấy",      # câu hỏi lịch, không phải lịch lặp
    "hôm nay thứ mấy",
    "nhắc tôi gọi Mai lúc 7 giờ",       # "Mai" là TÊN NGƯỜI
])
def test_khong_bep_nhip_lap_vao_cau_khong_co(text):
    """Chốt chặn quan trọng nhất: bắt nhầm thì "sáng mai" thành "mỗi sáng", và
    một câu hỏi lịch biến thành lịch hẹn cả đời."""
    from intent_model import parse_repeat

    assert parse_repeat(text) is None


# ---------------------------------------------------------------------------
# 2. Nhịp lặp KHÔNG được dính vào nội dung nhắc.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("nhắc tôi uống thuốc mỗi ngày lúc 8 giờ sáng", "uống thuốc"),
    ("nhắc tôi họp mỗi thứ hai 9 giờ sáng", "họp"),
    ("nhắc tôi tập gym hằng tuần 7 giờ", "tập gym"),
    # "đặt báo thức 6 giờ sáng mỗi ngày" bản cũ để lại nội dung "mỗi ngày" -
    # tức trợ lý đọc thành "Nhắc bạn: mỗi ngày", đúng cái người dùng KHÔNG
    # muốn nghe. Gỡ hết thì rơi về mặc định "báo thức", vẫn đúng nghĩa.
    ("đặt báo thức 6 giờ sáng mỗi ngày", "báo thức"),
    ("nhắc tôi gọi mẹ mỗi sáng", "gọi mẹ"),
])
def test_noi_dung_nhac_khong_con_nhip_lap(text, expected):
    from intent_model import _reminder_task

    assert _reminder_task(text) == expected


# ---------------------------------------------------------------------------
# 3. Toán lịch lặp - kể cả ngày 31 không tồn tại ở tháng 2.
# ---------------------------------------------------------------------------
def test_lan_ke_tiep_cua_moi_nhip():
    from executor import _next_occurrence

    wed = datetime(2026, 9, 30, 8, 0)          # thứ Tư
    assert _next_occurrence(wed, {"kind": "daily"}) == datetime(2026, 10, 1, 8, 0)
    assert _next_occurrence(wed, {"kind": "weekly"}) == datetime(2026, 10, 7, 8, 0)
    assert _next_occurrence(wed, {"kind": "monthly"}) == datetime(2026, 10, 30, 8, 0)
    # "mỗi thứ hai" phải về đúng thứ HAI kế tiếp (5/10), không phải cộng 7 ngày
    assert _next_occurrence(wed, {"kind": "weekly", "weekday": 0}) == \
        datetime(2026, 10, 5, 8, 0)
    # đang đứng đúng thứ được chỉ định -> phải tới tuần SAU, không phải hôm nay
    assert _next_occurrence(wed, {"kind": "weekly", "weekday": 2}) == \
        datetime(2026, 10, 7, 8, 0)


def test_ngay_31_khong_ton_tai_o_thang_2_thi_khong_duoc_no():
    """31/1 -> 28/2 chứ không được nổ `ValueError` khi tạo ngày 31 tháng 2."""
    from executor import _next_occurrence

    jan31 = datetime(2026, 1, 31, 8, 0)
    feb = _next_occurrence(jan31, {"kind": "monthly"})
    assert feb == datetime(2026, 2, 28, 8, 0)
    assert _next_occurrence(feb, {"kind": "monthly"}) == datetime(2026, 3, 28, 8, 0)


def test_lan_ke_tiep_luon_sau_moc_cu():
    from executor import _next_occurrence

    base = datetime(2026, 9, 30, 8, 0)
    for repeat in ({"kind": "daily"}, {"kind": "weekly"},
                   {"kind": "weekly", "weekday": 3}, {"kind": "monthly"}):
        assert _next_occurrence(base, repeat) > base
    assert _next_occurrence(base, {"kind": "khong ton tai"}) is None


# ---------------------------------------------------------------------------
# 4. Rác trong `reminders.json` phải bị chặn lúc ĐỌC, không phải lúc nhắc nổ.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("junk", [
    {"kind": "khong ton tai"}, "daily", None, 123, [],
    {"kind": "weekly", "weekday": 99},          # ngoài 0..6
    {"kind": "weekly", "weekday": True},        # bool là int trong Python!
    {"kind": "weekly", "weekday": "0"},         # chuỗi, không phải số
])
def test_rac_trong_repeat_bi_lo(junk):
    from executor import _coerce_repeat

    assert _coerce_repeat(junk) in (None, {"kind": "weekly"})


def test_repeat_hop_le_duoc_giu_nguyen():
    from executor import _coerce_repeat

    assert _coerce_repeat({"kind": "daily"}) == {"kind": "daily"}
    assert _coerce_repeat({"kind": "weekly", "weekday": 0}) == \
        {"kind": "weekly", "weekday": 0}
    # "mỗi tuần" chưa chốt thứ mấy thì giữ kind, bỏ weekday
    assert _coerce_repeat({"kind": "weekly"}) == {"kind": "weekly"}


# ---------------------------------------------------------------------------
# 5. Đặt nhắc lặp: lưu xuống đĩa và NÓ RA trong câu xác nhận.
# ---------------------------------------------------------------------------
@pytest.fixture
def ex(tmp_path, monkeypatch):
    """Executor cô lập: timer thật nhưng lịch xa, và ghi vào thư mục tạm."""
    import executor

    monkeypatch.setattr(executor, "REMINDERS_PATH", str(tmp_path / "reminders.json"))
    monkeypatch.setattr(executor, "ACTIVE_REMINDERS", [])
    executor.clear_pending_reminder()
    yield executor
    for item in list(executor.ACTIVE_REMINDERS):
        timer = item.get("timer")
        if getattr(timer, "cancel", None):
            timer.cancel()
    executor.clear_pending_reminder()


def test_dat_nhac_lap_luu_duoc_nhip_lap_xuong_dia(ex):
    import json

    run_at = datetime.now() + timedelta(hours=2)
    rid = ex._schedule_reminder("uống thuốc", run_at, repeat={"kind": "daily"})
    assert rid
    data = json.loads(Path(ex.REMINDERS_PATH).read_text(encoding="utf-8"))
    assert data[0]["repeat"] == {"kind": "daily"}
    assert data[0]["task"] == "uống thuốc"


def test_dat_nhac_lap_no_ra_nhip_lap_trong_cau_xac_nhan(ex, capsys):
    """Không nói ra thì người dùng tưởng mình đã hẹn cả tháng."""
    run_at = (datetime.now() + timedelta(hours=2)).replace(minute=0, second=0)
    ex.action_set_reminder("uống thuốc", {"time": {"type": "clock", "hour": run_at.hour,
                                                   "minute": 0},
                                           "repeat": {"kind": "daily"}})
    assert "Lặp lại mỗi ngày" in capsys.readouterr().out


def test_nhac_mot_lan_khong_them_cau_lap(ex, capsys):
    """Lời nhắc thường phải GIỮ NGUYÊN từng chữ - v7.8 đã hứa vậy."""
    run_at = (datetime.now() + timedelta(hours=2)).replace(minute=0, second=0)
    ex.action_set_reminder("họp", {"time": {"type": "clock", "hour": run_at.hour,
                                            "minute": 0}})
    out = capsys.readouterr().out
    assert "Lặp lại" not in out
    assert "Đã đặt nhắc nhở họp" in out


# ---------------------------------------------------------------------------
# 6. Lỗi âm thầm đắt nhất: lần sau phải GIỮ NHỊP LẶP.
# ---------------------------------------------------------------------------
def test_nhac_lap_tu_hen_lai_va_van_giu_nhip_lap(ex):
    """Bản đầu tính mốc kế tiếp rồi QUÊN truyền `repeat`: nhắc hằng ngày chạy
    đúng hai lần rồi hạ xuống thành nhắc một lần."""
    now = datetime.now()
    rid = ex._schedule_reminder("uống thuốc", now + timedelta(seconds=1),
                                repeat={"kind": "daily"})
    ex._fire_reminder("uống thuốc", rid, {"kind": "daily"})

    assert len(ex.ACTIVE_REMINDERS) == 1, "lời nhắc phải tự hẹn lại"
    entry = ex.ACTIVE_REMINDERS[0]
    assert entry.get("repeat") == {"kind": "daily"}, \
        "lần sau mất nhịp lặp thì nhắc chỉ chạy đúng hai lần"
    assert entry["at"] > now
    entry["timer"].cancel()


def test_nhac_mot_lan_khong_tu_hen_lai(ex):
    now = datetime.now()
    rid = ex._schedule_reminder("họp", now + timedelta(seconds=1))
    ex._fire_reminder("họp", rid)

    assert ex.ACTIVE_REMINDERS == []


def test_chang_noi_tiep_khong_ban_nhac_va_khong_hen_lai(ex):
    """Lịch dài hơn trần `threading.Timer` phải chia chặng. Nếu mỗi chặng bị
    coi là lần nhắc thật thì nhắc hằng tháng bắn vài lần mỗi tháng."""
    called = []
    ex.respond = lambda msg: called.append(msg)
    ex._fire_reminder("x", "id-khong-co", {"kind": "daily"}, continuation=True)
    assert called == [], "chặng nối tiếp không được phát ra tiếng"
    # chặng nối tiếp chỉ được bật chặng kế tiếp, không đụng danh sách
    assert ex.ACTIVE_REMINDERS == []


def test_huy_nhac_lap_roi_het_luon(ex):
    run_at = datetime.now() + timedelta(hours=2)
    ex._schedule_reminder("uống thuốc", run_at, repeat={"kind": "daily"})
    removed = ex.cancel_reminder("uống thuốc")
    assert len(removed) == 1
    assert ex.ACTIVE_REMINDERS == []


# ---------------------------------------------------------------------------
# 7. Mở lại máy: mốc giờ lặp đã trôi qua phải cuộn tới lần kế.
# ---------------------------------------------------------------------------
def test_may_tat_den_sau_thi_cuon_ti_lan_ke(ex):
    import json

    quá_khứ = (datetime.now() - timedelta(days=1)).replace(microsecond=0)
    Path(ex.REMINDERS_PATH).write_text(
        json.dumps([{"id": "x", "task": "uống thuốc",
                     "at": quá_khứ.isoformat(),
                     "repeat": {"kind": "daily"}}], ensure_ascii=False),
        encoding="utf-8")

    assert ex.restore_reminders() == 1
    entry = ex.ACTIVE_REMINDERS[0]
    assert entry["at"] > datetime.now(), \
        "không cuộn thì cả chuỗi 'mỗi ngày' biến mất"
    assert entry.get("repeat") == {"kind": "daily"}
    entry["timer"].cancel()


def test_khoi_phuc_vao_reminders_json_cu_khong_co_repeat_van_chay(ex):
    """Tương thích ngược: file do bản cũ ghi ra không có trường `repeat`."""
    import json

    Path(ex.REMINDERS_PATH).write_text(
        json.dumps([{"id": "x", "task": "họp",
                     "at": (datetime.now() + timedelta(hours=2)).isoformat()}]),
        encoding="utf-8")
    assert ex.restore_reminders() == 1
    assert "repeat" not in ex.ACTIVE_REMINDERS[0]
    ex.ACTIVE_REMINDERS[0]["timer"].cancel()


# ---------------------------------------------------------------------------
# 8. Nhịp lặp phải SỐNG SÓT qua câu hỏi "mấy giờ?".
# ---------------------------------------------------------------------------
def test_nhip_lap_song_sot_qua_cau_hoi_gi(ex, capsys):
    """"uống thuốc mỗi ngày" chưa nói giờ -> hỏi lại; trả lời "23 giờ" phải ra
    lịch HÀNG NGÀY. Bỏ sót thì ra một lời nhắc một lần - đúng thứ người dùng
    đã tin là cả tháng."""
    ex.action_set_reminder("uống thuốc", {"time": None, "repeat": {"kind": "daily"}})
    assert ex.pending_reminder() is not None

    ok = ex.try_complete_pending_reminder(
        {"type": "clock", "hour": 23, "minute": 0})
    assert ok is True
    entry = ex.ACTIVE_REMINDERS[0]
    assert entry.get("repeat") == {"kind": "daily"}
    entry["timer"].cancel()


def test_noi_cau_khong_lien_quan_thi_huy_cau_hoi_dang_cho(ex):
    """Hành vi CỐ Ý từ trước: người dùng nói sang chuyện khác thì bỏ câu hỏi
    đang treo, không biến "mở nhạc" thành giờ nhắc. Nhịp lặp phải đi theo cả
    hành vi này, không được tự ý giữ lại."""
    ex.action_set_reminder("uống thuốc", {"time": None, "repeat": {"kind": "daily"}})
    assert ex.try_complete_pending_reminder("mở nhạc giúp tôi") is None
    assert ex.pending_reminder() is None


# ---------------------------------------------------------------------------
# 9. Cả đường tròn: câu nói -> intent -> lịch trên đĩa.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,task,repeat,kind", [
    ("nhắc tôi uống thuốc mỗi ngày lúc 8 giờ sáng", "uống thuốc", "daily", "daily"),
    ("nhắc tôi họp mỗi thứ hai 9 giờ sáng", "họp", "weekly", "weekly"),
    ("nhắc tôi trả tiền mỗi tháng", "trả tiền", "monthly", "monthly"),
])
def test_tu_cau_noi_den_y_dinh_co_nhip_lap(text, task, repeat, kind):
    from nlu_advanced import NLU

    result = NLU().understand(text)[0]
    assert result["intent"] == "set_reminder"
    assert result.get("repeat", {}).get("kind") == kind
