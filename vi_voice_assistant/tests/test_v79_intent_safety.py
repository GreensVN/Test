"""
v7.9 (bổ sung 7) - Đừng biến lời nói thường thành LỆNH trên máy thật.

Cả ba lỗi dưới đây đều có cùng một hình dạng: trợ lý làm MỘT VIỆC KHÁC
với điều người dùng nói, và người dùng không có tín hiệu nào để biết.

1. `SYSTEM_KEYWORDS` không có ranh giới từ: "lock" khớp nằm trong "clock" và
   "unlock" -> "alarm clock" bị KHOÁ MÁY thật.
2. `smart_normalize` tự sửa lỗi gõ thành từ khoá hệ thống: "alarm clock" ->
   "alarm lock", "tôi đang asleep" -> "tôi đang sleep" -> máy ngủ thật.
3. "đọc báo hôm nay" bị đoán `get_weather` 0.70 -> "Đang xem thời tiết đọc báo".
"""

import pytest
from intent_model import _system_action, predict_intent
from nlu_advanced import smart_normalize


# ---------------------------------------------------------------------------
# 1. Ranh giới từ cho từ khoá hệ thống
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "alarm clock",        # "lock" nằm trong "clock"
    "unlock máy",         # "lock" nằm trong "unlock"
    "block máy",          # "lock" nằm trong "block"
    "tôi đang asleep",    # "sleep" nằm trong "asleep"
])
def test_tu_khoa_he_thong_khong_khop_nam_trong_tu_khac(text):
    assert _system_action(text, text) == "unknown"


@pytest.mark.parametrize("text,expected", [
    ("khoá máy", "lock"),
    ("khoá màn hình", "lock"),
    ("khóa màn hình", "lock"),
    ("lock máy", "lock"),
    ("khoá máy tính", "lock"),
    # Còn đây thì vẫn phải nhận: ranh giới từ chỉ chặn khớp NẰM TRONG, không
    # chặn từ đứng riêng.
    ("ngủ đi", "sleep"),
    ("tôi muốn ngủ", "sleep"),
    ("tắt máy", "shutdown"),
    ("shutdown máy", "shutdown"),
    ("khởi động lại", "restart"),
    ("restart máy", "restart"),
    ("thoát khỏi máy", "logout"),
    ("im lặng", "mute"),
    ("tăng âm lượng", "volume_up"),
    ("giảm âm lượng", "volume_down"),
    ("chụp màn hình", "screenshot"),
])
def test_lenh_he_thong_that_van_nhan_duoc(text, expected):
    assert _system_action(text, text) == expected


# ---------------------------------------------------------------------------
# 2. Không tự sửa lỗi gõ thành từ khoá hệ thống
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "alarm clock", "clock", "block máy", "tôi đang asleep",
    "asleep", "locks", "stock market",
])
def test_tu_tieng_anh_khong_bi_sua_thanh_lenh(text):
    out = smart_normalize(text)
    assert out == text, f"{text!r} bị đổi thành {out!r}"
    assert _system_action(out, out) == "unknown"


def test_sua_loi_go_thuong_van_phai_chay():
    """Chặn đúng nhóm nguy hiểm, không chặn cả nhánh sửa lỗi gõ."""
    assert smart_normalize("mo chorme") == "mở chrome"
    assert smart_normalize("chorme") == "chrome"
    assert smart_normalize("mo file") == "mở file"
    # "tắt" là từ ĐÚNG, không phải lỗi gõ của "tạt" - nhánh sửa lỗi gõ vẫn
    # chạy bình thường ở đây, chỉ là kết quả tình cờ trùng một từ hợp lệ.
    assert smart_normalize("mo taht") == "mở tắt"


# ---------------------------------------------------------------------------
# 3. Cụm động từ không thể nhầm thì cãi model
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("đọc báo hôm nay", "search_web"),
    ("đọc tin tức", "search_web"),
    ("đọc báo cho tôi nghe", "search_web"),
])
def test_doc_bao_khong_bi_doan_thanh_thoi_tiet(text, expected):
    assert predict_intent(text)["intent"] == expected


@pytest.mark.parametrize("text,expected", [
    # "hôm nay" nằm trong cả hai câu, nhưng chỉ câu nào có từ khoá thời tiết mới
    # là câu hỏi thời tiết. Đây là lý do "hôm nay" KHÔNG được dùng làm từ khoá
    # không thể nhầm.
    ("thời tiết hà nội", "get_weather"),
    ("thời tiết đà nẵng hôm nay", "get_weather"),
    ("thời tiết hôm nay thế nào", "get_weather"),
    ("hà nội trời thế nào", "get_weather"),
    # Và "đọc" ở đây là động từ, không phải "đọc báo".
    ("mở file báo cáo", "open_file"),
    ("đọc file báo cáo", "open_file"),
])
def test_khong_duoc_cu_theo_qua_ngang(text, expected):
    assert predict_intent(text)["intent"] == expected


def test_duc_bao_khong_duoc_dua_vao_loat_cu_theo_qua_ngang():
    """Guard cho chính bộ test này: ai đó thêm "đọc báo" vào danh sách intent
    khác thì phải bỏ dấu chống va chạm, chứ không để nó nuốt luôn câu hỏi
    thời tiết."""
    assert predict_intent("thời tiết hà nội")["intent"] == "get_weather"
    assert predict_intent("đọc báo hôm nay")["intent"] == "search_web"
