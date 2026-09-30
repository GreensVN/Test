"""
v7.9 (bổ sung 5) - Nhắc theo NGÀY TRONG TUẦN phải rơi đúng ngày, không phải hôm nay.

Bug gốc: "nhắc tôi họp 9 giờ sáng thứ hai" cho `day_offset = 0`, tức nhắc NGAY
HÔM NAY, dù câu nói rõ là thứ hai. Ngày đó chỉ còn nằm lại trong nội dung
nhắc dưới dạng chữ, nên trợ lý báo đúng giờ sai ngày, và người dùng tưởng mình
đã đặt nhầm. Cùng lớp lỗi với "sau 3 ngày" mà v7.8 đã sửa - khác ở chỗ dạng
này cần LỊCH THẬT chứ không chỉ đếm số.

Các test dùng `today` cố định (freeze) để kết quả không đổi theo ngày thật -
một bộ test lịch mà chạy đúng vào thứ Hai thì fail vào thứ Ba là bộ test vô
dụng. Phần "hôm nay" để mở, phần "ngày cụ thể" thì đóng.
"""

import datetime

import pytest
from executor import _reminder_confirmation
from intent_model import (
    _day_offset_for,
    _reminder_task,
    _weekday_day_offset,
    parse_time_expression,
)


def _days_from_now(days: int) -> datetime.date:
    return datetime.date.today() + datetime.timedelta(days=days)


# ---------------------------------------------------------------------------
# 1. Tên ngày trong tuần -> đúng ngày đích
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("weekday_name,target", [
    ("thứ hai", 0), ("thứ ba", 1), ("thứ tư", 2), ("thứ năm", 3),
    ("thứ sáu", 4), ("thứ bảy", 5), ("chủ nhật", 6),
])
def test_ten_ngay_trong_tuan_ra_dung_ngay(weekday_name, target):
    offset = _day_offset_for(weekday_name)
    landed = _days_from_now(offset)
    assert landed.weekday() == target
    assert 0 <= offset <= 7


@pytest.mark.parametrize("weekday_name,target", [
    ("thứ hai", 0), ("thứ ba", 1), ("thứ tư", 2), ("thứ năm", 3),
    ("thứ sáu", 4), ("thứ bảy", 5), ("chủ nhật", 6),
])
def test_ten_ngay_viet_tat_co_dau_va_khong_dau(weekday_name, target):
    """Người gõ tay trên điện thoại hay bỏ dấu; hai kiểu phải cho cùng kết quả."""
    import unicodedata

    plain = "".join(
        c for c in unicodedata.normalize("NFD", weekday_name)
        if unicodedata.category(c) != "Mn"
    )
    assert _day_offset_for(plain) == _day_offset_for(weekday_name)
    assert _days_from_now(_day_offset_for(plain)).weekday() == target


def test_ngay_dang_la_hom_nay_thi_khong_dich_ngay():
    """Nói "thứ tư" vào đúng thứ Tư là hôm nay, không phải tuần sau."""
    today = datetime.date.today()
    name = ["thứ hai", "thứ ba", "thứ tư", "thứ năm", "thứ sáu", "thứ bảy", "chủ nhật"]
    assert _day_offset_for(name[today.weekday()]) == 0


def test_ngay_nay_nhung_noi_toi_luon_la_tuan_sau():
    """"thứ tư tới" vào đúng thứ Tư = tuần sau, không phải hôm nay.

    Nếu đọc thành hôm nay thì "tới" mất hết nghĩa và người dùng bị nhắc sớm
    đúng lúc đang cố nói "TUẦN SAU".
    """
    today = datetime.date.today()
    name = ["thứ hai", "thứ ba", "thứ tư", "thứ năm", "thứ sáu", "thứ bảy", "chủ nhật"]
    same_day = name[today.weekday()]
    assert _day_offset_for(f"{same_day} tới") == 7
    assert _day_offset_for(f"{same_day} tuần sau") == 7
    # "nhắc tôi" chứa chữ "tôi" - không được nhầm với "tới" khi bỏ dấu.
    assert _day_offset_for(f"nhac toi hop 9 gio sang {same_day}") == 0


def test_cuoi_tuan_la_chu_nhat():
    """"cuối tuần" = Chủ nhật: đó là ngày luôn nghỉ, còn thứ Bảy vẫn có thể
    làm việc. Chọn thứ Bảy sẽ khiến người dùng phải đi làm vào cuối tuần."""
    assert _days_from_now(_day_offset_for("cuối tuần")).weekday() == 6
    assert _days_from_now(_day_offset_for("cuoi tuan")).weekday() == 6


def test_dau_tuan_la_thu_hai():
    assert _days_from_now(_day_offset_for("đầu tuần")).weekday() == 0


def test_cuoi_thang_la_ngay_cuoi_cua_thang():
    """Ngày cuối tháng phải đúng với LỊCH THẬT, kể cả tháng 2 năm nhuận."""
    import calendar

    today = datetime.date.today()
    offset = _day_offset_for("cuối tháng")
    landed = today + datetime.timedelta(days=offset)
    last = calendar.monthrange(landed.year, landed.month)[1]
    assert landed.day == last
    # Nếu hôm nay đã là ngày cuối tháng thì offset 0 là đúng.
    assert offset == max(last - today.day, 0) if landed.month == today.month else True


def test_dau_thang_la_ngay_mot():
    landed = _days_from_now(_day_offset_for("đầu tháng"))
    assert landed.day == 1
    assert landed > datetime.date.today()


# ---------------------------------------------------------------------------
# 2. Ngày trong tuần phải THẮNG parser "sau N ngày/tuần" của v7.8
# ---------------------------------------------------------------------------
def test_so_thu_bi_dung_thanh_so_tuan():
    """"9 giờ sáng thứ 4 tuần sau" KHÔNG được đọc thành "4 tuần" (28 ngày).

    Con số 4 là của "thứ 4"; "tuần sau" chỉ là dấu hiệu khoảng cách chứ không
    có số đi kèm. Bug này đẩy lời nhắc tới 28 ngày sau.
    """
    info = parse_time_expression("nhắc tôi họp 9 giờ sáng thứ 4 tuần sau")
    assert info["type"] == "clock"
    assert info["minutes"] == 0
    landed = _days_from_now(info["day_offset"])
    assert landed.weekday() == 2                      # thứ tư
    assert 0 < info["day_offset"] <= 7


def test_khong_con_bien_so_ngay_thanh_so_tuan():
    """Bảo vệ chéo: đếm ngược VẪN phải chạy khi câu không có tên ngày."""
    assert parse_time_expression("nhắc tôi họp 3 ngày nữa")["minutes"] == 3 * 1440
    assert parse_time_expression("nhắc tôi họp sau 3 ngày")["minutes"] == 3 * 1440
    assert parse_time_expression("nhắc tôi họp 2 tuần nữa")["minutes"] == 2 * 10080
    assert parse_time_expression("nhắc tôi họp 5 phút nữa")["minutes"] == 5


# ---------------------------------------------------------------------------
# 3. Giờ đồng hồ vẫn đúng khi có ngày đi kèm
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,hour,minute", [
    ("nhắc tôi họp 9 giờ sáng thứ hai", 9, 0),
    ("nhắc tôi họp 14 giờ thứ ba", 14, 0),
    ("nhắc tôi họp 3 giờ chiều thứ tư", 15, 0),
    ("nhắc tôi họp 8 giờ tối thứ năm", 20, 0),
    ("nhắc tôi họp 7h30 sáng thứ sáu", 7, 30),
])
def test_gio_dong_ho_khong_doi_khi_them_ngay(text, hour, minute):
    info = parse_time_expression(text)
    assert info["type"] == "clock"
    assert (info["hour"], info["minute"]) == (hour, minute)


def test_buoi_khong_co_so_gio_va_ten_ngay():
    """"sáng thứ hai" không kèm số giờ vẫn hiểu được (7h như "sáng mai")."""
    info = parse_time_expression("nhắc tôi họp sáng thứ hai")
    assert info["type"] == "clock"
    assert info["hour"] == 7
    assert info["day_offset"] > 0


def test_ten_ngay_tran_khong_phan_noi_dung_thanh_nhac():
    """"ngày thứ hai nào đó" là câu nói về chuyện khác, KHÔNG phải đặt nhắc.

    Không có mốc giờ nào cả nên parser không được bịa ra một cái lịch.
    """
    assert parse_time_expression("ngày thứ hai nào đó")["type"] is None


# ---------------------------------------------------------------------------
# 4. Ngày đã rơi vào lịch thì KHÔNG lặp lại trong nội dung nhắc
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("nhắc tôi họp sáng mai", "họp"),
    ("nhắc tôi họp tối mai", "họp"),
    ("nhắc tôi họp chiều mai", "họp"),
    ("nhắc tôi họp sáng thứ hai", "họp"),
    ("nhắc tôi họp thứ hai buổi sáng", "họp"),
    ("nhắc tôi họp cuối tuần", "họp"),
    ("nhắc tôi họp cuối tháng", "họp"),
    ("nhắc tôi họp 8 giờ sáng mai", "họp"),
    ("nhắc tôi gặp bạn 3 giờ chiều thứ hai", "gặp bạn"),
])
def test_moc_gio_khong_con_lai_trong_noi_dung_nhac(text, expected):
    assert _reminder_task(text) == expected


@pytest.mark.parametrize("text,expected", [
    # Lời nhắc LẶP LẠI: "thứ hai" là PHẦN ĐỊNH NGHĨA nhịp lặp, bóc đi thì mất.
    ("nhắc tôi họp mỗi thứ hai 9 giờ sáng", "họp"),
    ("nhắc tôi họp thứ hai hằng tuần", "họp"),
    ("nhắc tôi họp hàng tuần", "họp"),
    # TÊN RIÊNG: "Mai" là tên người, không phải "mai" = ngày mai.
    ("nhắc tôi gọi cho Mai 8 giờ", "gọi cho Mai"),
    # Từ này là nội dung việc, không phải mốc giờ.
    ("nhắc tôi hỏi thăm sức khỏe bà", "hỏi thăm sức khỏe bà"),
    ("nhắc tôi đi mua đồ trước khi về nhà", "đi mua đồ trước khi về nhà"),
    ("nhắc tôi nghỉ trưa", "nghỉ trưa"),
])
def test_noi_dung_nhac_giu_nguyen_phan_noi_dung_that(text, expected):
    assert _reminder_task(text) == expected


# ---------------------------------------------------------------------------
# 5. Hàm lịch gốc - dùng "today" cố định nên kết quả không đổi theo ngày thật
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("today,text,expected", [
    # 2026-09-30 là THỨ TƯ
    (datetime.date(2026, 9, 30), "thứ hai", 5),
    (datetime.date(2026, 9, 30), "thứ tư", 0),
    (datetime.date(2026, 9, 30), "thứ tư tới", 7),
    (datetime.date(2026, 9, 30), "chủ nhật", 4),
    (datetime.date(2026, 9, 30), "cuối tuần", 4),
    (datetime.date(2026, 9, 30), "cuối tháng", 0),          # 30/9 là cuối tháng
    (datetime.date(2026, 9, 30), "đầu tháng", 1),          # 1/10
    # 2026-10-01 là THỨ NĂM
    (datetime.date(2026, 10, 1), "thứ tư", 6),
    (datetime.date(2026, 10, 1), "thứ năm", 0),
    (datetime.date(2026, 10, 1), "cuối tháng", 30),        # 31/10
    (datetime.date(2026, 10, 1), "đầu tháng", 31),         # 1/11
    # 2026-02-28 - tháng 2 KHÔNG nhuận, ngày cuối là 28
    (datetime.date(2026, 2, 28), "cuối tháng", 0),
    # 2028-02-28 - tháng 2 NHUẬN, ngày cuối là 29
    (datetime.date(2028, 2, 28), "cuối tháng", 1),
])
def test_ham_lich_voi_ngay_co_dinh(today, text, expected):
    assert _weekday_day_offset(today, text) == expected


# ---------------------------------------------------------------------------
# 6. Câu xác nhận phải NÓ RA NGÀY
# ---------------------------------------------------------------------------
# Trước v7.9 câu xác nhận chỉ đọc "9 giờ 0 phút". Kể cả khi parser đã tra lịch
# đúng, người dùng vẫn không có cách nào biết mình đặt nhầm ngày hay không -
# phải mở danh sách nhắc ra kiểm lại. Câu xác nhận là chỗ rẻ nhất để nói ra.


def _conf(days: int, hour: int = 9, minute: int = 0) -> str:
    now = datetime.datetime(2026, 9, 30, 10, 0)          # thứ Tư
    run_at = (now + datetime.timedelta(days=days)).replace(
        hour=hour, minute=minute, second=0, microsecond=0)
    return str(_reminder_confirmation("họp", run_at, None, now))


def test_xac_nhan_khong_ngay_khi_nhac_ngay_hom_nay():
    assert "ngày mai" not in _conf(0)
    assert "thứ" not in _conf(0)
    assert "họp" in _conf(0)


def test_xac_nhan_no_ngay_mai():
    assert "ngày mai" in _conf(1)


@pytest.mark.parametrize("days,expected", [
    (5, "thứ hai tuần sau"),      # 5/10/2026 là thứ Hai
    (4, "chủ nhật tuần sau"),
    (6, "thứ ba tuần sau"),
])
def test_xac_nhan_no_ten_ngay_trong_tuan(days, expected):
    assert expected in _conf(days)


def test_xac_nhan_no_ngay_khi_qua_tuan():
    # 31/10: khác tháng, cùng năm.
    assert "ngày 31 tháng 10" in _conf(31)
    # sang năm sau.
    assert "năm" in _conf(400)


def test_xac_nhan_van_no_nhip_lap():
    now = datetime.datetime(2026, 9, 30, 10, 0)
    run_at = now.replace(hour=9, minute=0)
    text = _reminder_confirmation("họp", run_at, {"kind": "weekly", "weekday": 0}, now)
    assert "Lặp lại mỗi thứ hai" in text
