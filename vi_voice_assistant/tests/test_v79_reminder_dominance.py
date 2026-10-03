"""
v7.9 (bổ sung 9f) - "nhắc tôi X" phải NHẮC, không phải LÀM LUÔN X.

Người nói "nhắc tôi thời tiết hà nội" và nghe phản hồi hợp lý. Máy kiểm tra
thời tiết NGAY, báo xong - và **không có lời nhắc nào được tạo**. Người dùng
tưởng đã đặt nhắc. Đây là lỗi nguy hiểm nhất tìm được trong đợt này: không có
dấu hiệu báo lỗi, chỉ có hành động sai, và không có cách nào phát hiện ngoài
việc đợi mãi không thấy nhắc.

| Người gõ | Trước | Việc máy làm thật |
|---|---|---|
| `nhắc tôi thời tiết hà nội` | `get_weather` **0.99** | xem thời tiết ngay |
| `nhắc tôi tính 5 cộng 7` | `calculate` **0.95** | tính ngay |
| `nhắc tôi tìm giá vé` | `search_web` **0.93** | tìm ngay |
| `nhắc tôi mở file hóa đơn` | `open_file` **0.81** | mở file thật |

Lý do: nội dung của lời nhắc chứa từ khoá của lệnh khác, và model bị từ đó
kéo đi. "Nhắc tôi ..." là DỮ LIỆU TRỰC TIẾP của lệnh nhắc nhở, mạnh hơn bất kỳ
từ nào trong phần nội dung.

Phần hai của bổ sung này: khi mốc giờ ĐỨNG TRƯỚC, động từ "nhắc tôi" bị mốc
giờ che nên sống sót trong nội dung - máy tự nhắc mình nhắc lại.
"""

import pytest
from intent_model import _reminder_task, predict_intent


# ---------------------------------------------------------------------------
# 1. Động từ "nhắc tôi" thắng mọi từ khoá trong nội dung
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,before_intent", [
    ("nhắc tôi thời tiết hà nội", "get_weather"),
    ("nhắc tôi tính 5 cộng 7", "calculate"),
    ("nhắc tôi tìm giá vé", "search_web"),
    ("nhắc tôi mở file hóa đơn", "open_file"),
    ("nhắc tôi mở youtube giúp tôi", "play_media"),
    ("nhắc tôi tảo file báo cáo", "open_file"),
])
def test_dong_tu_nhac_thang_tu_khoa_trong_noi_dung(text, before_intent):
    """Ghi lại cả intent CŨ, để khi ai đó phá lại rule này thì thấy ngay mức lỗi."""
    assert predict_intent(text)["intent"] == "set_reminder", (
        f"{text!r} trước đây rơi vào {before_intent}")


@pytest.mark.parametrize("text", [
    "nhớ tôi mua sữa",
    "nhắc tôi soạn thư gửi sếp",
    "nhắc bạn gọi điện cho mẹ",
    "đặt lịch hẹn khách 14 giờ mai",
    "set a reminder for tomorrow",
])
def test_cac_dang_dong_tu_nhac_deu_theo(text):
    assert predict_intent(text)["intent"] == "set_reminder"


# ---------------------------------------------------------------------------
# 2. Nội dung nhắc phải là VIỆC, không phải câu lệnh
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("nhắc tôi tảo file báo cáo", "tảo file báo cáo"),
    ("nhắc tôi mở file hóa đơn", "mở file hóa đơn"),
    ("nhắc tôi thời tiết hà nội", "thời tiết hà nội"),
])
def test_noi_dung_giu_nguyen_vi_va(text, expected):
    assert predict_intent(text)["target"] == expected


# ---------------------------------------------------------------------------
# 3. Mốc giờ đứng TRƯỚC không được giữ lại động từ "nhắc tôi"
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("mai nhắc tôi họp", "họp"),
    ("tối mai nhắc tôi họp", "họp"),
    ("2 ngày nữa nhắc tôi đi chợ", "đi chợ"),
    ("sau 3 ngày nhắc tôi đi chợ", "đi chợ"),
    ("ngày kia nhắc tôi nộp báo cáo", "nộp báo cáo"),
])
def test_moc_gio_dung_truoc_khong_an_ngot_dong_tu(text, expected):
    """`_REMINDER_LEAD_RE` neo `^`, nên mốc giờ đứng đầu che mất động từ.

    Trước đây nội dung là "nhắc tôi họp" - trợ lý đọc thành *"Nhắc bạn: nhắc
    tôi họp"*: máy tự nhắc mình nhắc lại.
    """
    assert _reminder_task(text) == expected


def test_bo_lai_dong_tu_khong_duoc_an_vao_noi_dung_that():
    """Bóc thêm lần nữa là mất cả nghĩa của câu.

    "nhắc tôi tảo file báo cáo": lần đầu ăn "nhắc tôi", nếu bóc tiếp vô điều
    kiện thì lần hai ăn "tảo file" và nội dung còn "báo cáo" - trong khi
    "tảo file báo cáo" mới đúng là VIỆC CẦN LÀM.
    """
    assert _reminder_task("nhắc tôi tảo file báo cáo") == "tảo file báo cáo"
    assert _reminder_task("mai nhắc tôi tảo file báo cáo") == "tảo file báo cáo"


# ---------------------------------------------------------------------------
# 4. Không được nuốt câu hỏi ngày giờ, không được phá lệnh khác
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,intent", [
    ("nhắc tôi hôm nay là thứ mấy", "get_datetime"),
    ("hôm nay ngày mấy", "get_datetime"),
    ("mở file abc.txt", "open_file"),
    ("đọc file abc.txt", "open_file"),
    ("thời tiết hà nội", "get_weather"),
    ("mở youtube", "play_media"),
    ("tìm giá vàng", "search_web"),
    ("đọc báo hôm nay", "search_web"),
    ("5 cộng 7", "calculate"),
])
def test_khong_anh_huong_cau_hoi_va_lenh_khac(text, intent):
    assert predict_intent(text)["intent"] == intent
