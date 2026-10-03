"""
v7.9 (bổ sung 8) - Động từ mở đầu lời nhắc và câu đặt lịch bị đoán thành hỏi lịch.

Hai lỗi, đều làm trợ lý đọc sai nội dung người dùng vừa nói:

1. `_REMINDER_LEAD_RE` liệt kê 8 cụm cố định nên sót những cách nói rất
   phổ biến: "đặt nhắc", "tạo nhắc nhở", "nhắc việc", "nhắc bạn" (7/18 câu mở
   đầu bị lỗi). Trợ lý đọc *"Đã đặt nhắc nhở đặt nhắc uống nước"* - tự nhắc
   lại chính động từ đặt nhắc.

2. "đặt lịch hẹn khách 14 giờ ngày mai" bị model đoán `get_datetime` ở 0.72,
   tức trợ lý đọc ra *"Hôm nay là thứ Bảy, ngày 3 tháng 10"* cho một câu người
   dùng rõ ràng đang đặt lịch.
"""

import datetime

import pytest
from intent_model import _reminder_task, parse_time_expression, predict_intent


# ---------------------------------------------------------------------------
# 1. Động từ mở đầu: đo trên 18 cách nói phổ biến
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("lead", [
    "nhắc tôi", "nhắc mình", "nhắc bạn",
    "đặt nhắc", "đặt nhắc nhở", "tạo nhắc nhở", "tạo lời nhắc", "đặt lời nhắc",
    "nhắc việc", "tạo việc nhắc", "nhắc lịch",
    "hẹn giờ", "đặt hẹn giờ", "nhớ nhắc tôi",
    "đặt báo thức", "báo thức", "đặt đồng hồ đếm ngược",
])
def test_dong_tu_mo_dau_bi_boc_het(lead):
    assert _reminder_task(f"{lead} uống nước") == "uống nước"


# ---------------------------------------------------------------------------
# 2. Nội dung cần làm PHẢI ĐƯỢC GIỮ - đây là chỗ dễ hỏng nhất
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    # "tạo" ở đây là VIỆC CẦN LÀM, không phải động từ mở đầu. Nếu bóc theo
    # từng từ thì "nhắc tôi tạo file" sẽ thành "file" - mất hẳn việc.
    ("nhắc tôi tạo file báo cáo", "tạo file báo cáo"),
    # "nhắn" khác "nhắc": khớp trọn từ nên dừng lại đúng chỗ.
    ("nhắc tôi nhắn tin cho Lan", "nhắn tin cho Lan"),
    ("nhắc tôi gọi mẹ", "gọi mẹ"),
    ("nhắc tôi hỏi thăm sức khỏe bà", "hỏi thăm sức khỏe bà"),
    ("nhắc tôi đi mua đồ trước khi về nhà", "đi mua đồ trước khi về nhà"),
    ("nhắc tôi nghỉ trưa", "nghỉ trưa"),
    # "nhớ" ở giữa là vô nghĩa, không phải việc cần nhớ.
    ("nhắc tôi nhớ gọi mẹ", "gọi mẹ"),
    ("nhắc tôi nhớ uống nước", "uống nước"),
])
def test_noi_dung_can_lam_giu_nguyen(text, expected):
    assert _reminder_task(text) == expected


def test_he_giữ_ten_lời_nhắc():
    """Test v6.1 chốt: "hẹn" là TÊN lời nhắc ("cuộc hẹn"), không phải động từ
    bỏ đi. Vì vậy mẫu chỉ có cụm "hẹn giờ", KHÔNG có "hẹn" đứng riêng."""
    assert _reminder_task("hẹn 8 giờ kém 15") == "hẹn"
    assert _reminder_task("hẹn giờ 10 phút nữa") == "báo thức"


# ---------------------------------------------------------------------------
# 3. Câu đặt lịch bị đoán nhầm thành câu hỏi lịch
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "đặt lịch hẹn khách 14 giờ ngày mai",
    "hẹn khách 14 giờ ngày mai",
    "đặt lịch gặp khách 10 giờ sáng mai",
])
def test_dat_lich_khong_bi_doan_thanh_hoi_lich(text):
    assert predict_intent(text)["intent"] == "set_reminder"


@pytest.mark.parametrize("text", [
    "hôm nay là thứ mấy",
    "ngày kia là thứ mấy",
    "mai là ngày mấy",
    "thứ hai tuần sau là thứ mấy",
    "mấy giờ rồi",
    "bây giờ là mấy giờ",
    "hôm nay ngày bao nhiêu",
])
def test_cau_hoi_ve_ngay_gio_van_dung(text):
    """Chốt chặn ngược: mở ngưỡng cứu cho câu đặt lịch KHÔNG được nuốt mất
    câu hỏi thật về lịch."""
    assert predict_intent(text)["intent"] == "get_datetime"


def test_cau_dat_lich_phai_thuc_su_co_gio():
    """Cứu ở trên chỉ chạy khi câu có GIỜ CỤ THỂ, không chỉ có ngày."""
    r = predict_intent("đặt lịch hẹn khách 14 giờ ngày mai")
    assert r["intent"] == "set_reminder"
    assert r["time"]["type"] == "clock"
    assert r["time"]["hour"] == 14
    assert r["time"]["day_offset"] == 1


# ---------------------------------------------------------------------------
# 4. Nội dung sau khi bóc động từ vẫn phải ra lịch đúng
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected_task,hour", [
    ("đặt nhắc uống nước 10 giờ sáng", "uống nước", 10),
    ("tạo nhắc nhở gọi mẹ 8 giờ tối", "gọi mẹ", 20),
    ("nhắc việc nộp hồ sơ 5 giờ chiều", "nộp hồ sơ", 17),
    ("nhắc tôi nhớ gọi mẹ 5 phút nữa", "gọi mẹ", None),
])
def test_boc_dong_tu_xong_van_dat_dung_lich(text, expected_task, hour):
    r = predict_intent(text)
    assert r["intent"] == "set_reminder"
    if hour is not None:
        assert r["time"]["hour"] == hour
    else:
        assert r["time"]["type"] == "delay"


def test_ngay_ma_tu_cai_dong_tu_khong_anh_huong_lich():
    """"đặt lịch" chứa chữ "lịch" cùng họ với "ngày kia"; phải chứng minh ngày
    vẫn đúng sau khi động từ bị bóc."""
    info = parse_time_expression("đặt lịch hẹn khách 14 giờ ngày mai")
    target = datetime.date.today() + datetime.timedelta(days=info["day_offset"])
    assert target == datetime.date.today() + datetime.timedelta(days=1)
