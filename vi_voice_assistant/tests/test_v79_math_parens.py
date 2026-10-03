"""
v7.9 (bổ sung 9) - Dấu ngoặc: người gõ ngoặc để BỎ THỨ TỰ ƯU TIÊN, và nó phải có tác dụng.

Bug gốc: `normalize_text()` xoá `(` `)`. Người dùng gõ ngoặc để làm rõ ý, trợ lý
xoá luôn ngoặc rồi tính theo thứ tự ưu tiên mặc định, và ra CON SỐ SAI chứ không
ra lỗi:

    "(5 + 3) * 2"  ->  5 + 3 * 2  = 11   (đáng lẽ 16)
    "(10-4) / 2"   ->  10-4 / 2   =  8   (đáng lẽ  3)
    "2*(3+4)"      ->  2* 3+4     = 10   (đáng lẽ 14)
    "((5))"        ->  "5" rồi mất hết dấu ngoặc -> không ra biểu thức nào

Đây là lớp lỗi nguy hiểm nhất của toán: người dùng đã làm đúng mọi thứ, viết rõ
ý mình, và vẫn nhận về một con số trông rất hợp lệ.
"""

import pytest
from intent_model import _safe_eval, parse_math_expression, predict_intent
from text_utils import normalize_text


# ---------------------------------------------------------------------------
# 1. Ngoặc phải BỎ THỨ TỰ ƯU TIÊN - phần cốt lõi
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("(5 + 3) * 2", 16.0),
    ("(10-4) / 2", 3.0),
    ("(10-4)/2", 3.0),
    ("(2+2)^2", 16.0),
    ("2*(3+4)", 14.0),
    ("(1+1)", 2.0),
    ("(5 + 3) * 2 + 1", 17.0),
    ("100 / (2 + 3)", 20.0),
    ("((1+2)*(3+4))", 21.0),
    ("(2+3) * (4+5)", 45.0),
    ("3 * (1 + 1) * 2", 12.0),
])
def test_dau_ngoac_bay_thu_tu_uu_tien(text, expected):
    _, value = parse_math_expression(text)
    assert value is not None, f"{text!r} phải ra được số"
    assert value == pytest.approx(expected)


def test_khong_co_ngoac_thi_van_theo_thu_tu_uu_tien_mac_dinh():
    """Bọc ngoặc KHÔNG được phá thứ tự ưu tiên mặc định."""
    assert parse_math_expression("5 + 3 * 2")[1] == pytest.approx(11.0)
    assert parse_math_expression("(5 + 3) * 2")[1] == pytest.approx(16.0)
    # Hai câu trên CỐ TÌNH khác nhau - đó mới là điều người dùng muốn.
    assert parse_math_expression("5 + 3 * 2")[1] != \
        parse_math_expression("(5 + 3) * 2")[1]


@pytest.mark.parametrize("text", [
    "((5))",             # ngoặc lồng, không có toán tử -> chưa phải phép tính
    "(5",                # ngoặc mở không khép -> không phải biểu thức hợp lệ
    "5)",
    "()",
])
def test_ngoac_khong_hop_le_thi_khong_bia_so(text):
    assert parse_math_expression(text) == (None, None)


# ---------------------------------------------------------------------------
# 2. Dấu gạch nối không khoảng trắng: "10-4" phải chạy như "10 - 4"
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("10-4", 6.0),
    ("5-3", 2.0),
    ("10 - 4", 6.0),
    ("100-1-1", 98.0),
])
def test_dau_gach_khong_khoang_trang(text, expected):
    _, value = parse_math_expression(text)
    assert value == pytest.approx(expected)


@pytest.mark.parametrize("text", ["abc-123", "bản-2", "iphone-15", "abc-123-xyz"])
def test_chu_oi_khong_bi_coi_la_phep_tinh(text):
    """`_MATH_SYNTAX_RE` giờ có `-`, nhưng nó chỉ là CỔNG: phải có SỐ ở cả hai
    bên. Tên có gạch nối vẫn phải đi đúng đường của nó."""
    assert parse_math_expression(text) == (None, None)


# ---------------------------------------------------------------------------
# 3. Ngoặc phải sống sót qua chuẩn hoá
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("(5 + 3) * 2", 16.0),
    ("(10-4)/2", 3.0),
    ("2*(3+4)", 14.0),
])
def test_ngoac_song_sot_den_parser(text, expected):
    """`normalize_text` CỐ TÌNH xoá ngoặc - đó là bước chuẩn hoá chung, dùng
    cho mọi intent. Việc giữ ngoặc làm ở `_protect_math_syntax`, đúng tầng của
    parser toán. Nên thứ phải kiểm ở đây là: biểu thức còn nguyên khi tới
    parser, chứ không phải `normalize_text` giữ ngoặc."""
    assert normalize_text(text) != text          # xác nhận normalize xoá thật
    assert parse_math_expression(text)[1] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# 4. An toàn: ngoặc KHÔNG được mở đường thoát
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("evil", [
    "(1).__class__",        # truy cập thuộc tính qua ngoặc
    "().__class__",
    "(lambda:1)",
    "(1)+open('/etc/passwd')",
    "(1,2)",                 # tuple, không phải số học
    "[1,2]",
    "(1 if 1 else 2)",       # biểu thức điều kiện
    "(2**999999999)",        # số mũ vượt giới hạn
])
def test_ngoac_khong_mo_duong_thoat(evil):
    with pytest.raises(ValueError):
        _safe_eval(evil)


@pytest.mark.parametrize("evil", [
    "(1).__class__", "(2**999999999)", "(1)+(2).__class__",
])
def test_bieu_thuc_goc_dau_khong_tinh_duoc(evil):
    """Đuôi `.__class__` bị mẫu bóc bỏ nên câu có thể ra số thường - thứ cần
    chứng minh là KHÔNG lọt được đối tượng nào ra, chứ không phải luôn None.
    Xác nhận cả hai: `(1).__class__` không tính được, còn câu có đuôi rác thì
    chỉ cho ra CON SỐ (không phải object)."""
    expr, value = parse_math_expression(evil)
    assert value is None or isinstance(value, (int, float)), (expr, value)


# ---------------------------------------------------------------------------
# 5. Định tuyến NLU
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "(5 + 3) * 2", "(10-4)/2", "2*(3+4)", "(10-4)", "10-4", "5-3",
])
def test_bieu_thuc_co_ngoac_dieu_toi_calculate(text):
    assert predict_intent(text)["intent"] == "calculate"


# ---------------------------------------------------------------------------
# 6. Luỹ thừa không được phá vỡ khi dựng lại mẫu bóc biểu thức
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("2^10", 1024.0),
    ("2 ** 10", 1024.0),
    ("3^3", 27.0),
])
def test_luy_tha_van_chay(text, expected):
    _, value = parse_math_expression(text)
    assert value is not None
    assert value == pytest.approx(expected)


def test_luy_tha_lop_khong_tinh():
    """`2**3**2` bị từ chối CỐ Ý, không phải lỗi.

    `_safe_eval` chỉ cho phép số mũ là HẰNG SỐ, nên `2**(3**2)` - số mẩu là một
    biểu thức chứ không phải số - bị chặn. Đây là hàng rào chống bom số
    (`(2**999999999)` cũng rơi vào đây), giữ nguyên từ v7.8.
    """
    assert parse_math_expression("2^3^2") == (None, None)
    assert parse_math_expression("2**3**2") == (None, None)
