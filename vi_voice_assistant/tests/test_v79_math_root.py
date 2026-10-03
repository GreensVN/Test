"""
v7.9 (bổ sung 6) - Căn bậc N: bỏ dấu, `sqrt`, và lỗi đọc SAI SỐ.

Bug gốc: "căn 2 của 8" cho 1.4142, tức **đọc nhầm số bị căn**. Người Việt viết
tắt "căn 2" cho "căn bậc 2", nhưng bản cũ chỉ nhận "căn bậc 2" - thiếu chữ
"bậc" thì con số 2 bị nuốt làm số bị căn, ra căn bậc hai của 2.

Tệ hơn nhiều so với "chưa tính được": sai mà vẫn trông như một kết quả hợp
lệ, nên người dùng không có gì để nghi ngờ.
"""

import pytest
from intent_model import parse_math_expression, predict_intent
from text_utils import normalize_text


# ---------------------------------------------------------------------------
# 1. Dạng viết tắt "căn N của M" - đây là chỗ ra SỐ SAI trước khi sửa
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("căn 2 của 8", 2.8284271247),        # trước khi sửa: 1.4142 (căn của 2)
    ("căn bậc 2 của 8", 2.8284271247),    # trước khi sửa: 1.4142
    ("căn 3 của 27", 3.0),                # trước khi sửa: 1.7321 (căn của 3)
    ("căn bậc 3 của 27", 3.0),
    ("căn 4 của 16", 2.0),
    ("căn bậc 4 của 81", 3.0),
    ("căn 5 của 32", 2.0),
    ("căn bậc 2 của 0.25", 0.5),
    ("căn bậc 3 của 0.125", 0.5),
])
def test_dang_viet_tat_can_bac_n(text, expected):
    _, value = parse_math_expression(text)
    assert value is not None
    assert value == pytest.approx(expected)


def test_so_bi_can_phai_la_so_cuoi_cung():
    """"căn 2 của 8" = căn 8, KHÔNG phải căn 2."""
    expr, value = parse_math_expression("căn 2 của 8")
    assert "8" in expr
    assert "căn bậc hai của 8" == expr
    assert value != pytest.approx(2 ** 0.5)      # đừng ra 1.4142 nữa


# ---------------------------------------------------------------------------
# 2. Dấu "√" và chữ "sqrt" - trước đây mất sạch dấu hiệu
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("√16", 4.0),
    ("√ 144", 12.0),
    ("√0.25", 0.5),
    ("sqrt 144", 12.0),
    ("sqrt(144)", 12.0),
    ("sqrt 2", 1.4142135624),
    ("square root of 16", 4.0),
    ("root 3 of 27", 3.0),
])
def test_dau_can_viet_tat(text, expected):
    _, value = parse_math_expression(text)
    assert value == pytest.approx(expected)


def test_dau_can_khong_bi_chuan_hoa_xoa():
    """`_KEEP_RE` xoá sạch mọi thứ ngoài `\\w\\s./:\\-`; nếu lỡ quên `√` thì
    "√16" thành "16" và câu mất trọn dấu hiệu "đây là căn bậc hai"."""
    assert normalize_text("√16") == "√16"
    assert normalize_text("√ 144") == "√ 144"


def test_dau_can_viet_dinh_khong_bi_mat_khi_nlu_doc():
    """`predict_intent` dựng entity từ câu đã `normalize_text` - nếu dấu `√`
    bị xoá ở tầng đó thì parser toán không bao giờ nhìn thấy nó."""
    result = predict_intent("√16")
    assert result["intent"] == "calculate"
    assert "căn" in str(result["target"])


# ---------------------------------------------------------------------------
# 3. Số âm và nghiệm không tồn tại - phải trả None, KHÔNG bịa số
# ---------------------------------------------------------------------------
def test_can_bac_le_cua_so_am_co_nghiem_am():
    assert parse_math_expression("căn bậc 3 của -8")[1] == pytest.approx(-2.0)
    assert parse_math_expression("căn bậc 5 của -32")[1] == pytest.approx(-2.0)


def test_can_bac_chan_cua_so_am_khong_co_nghiem():
    _, value = parse_math_expression("căn bậc 2 của -4")
    assert value is None            # KHÔNG phải số bịa ra


def test_can_giua_khong_phai_so():
    """"căn lực" (căn lực vật lý) là từ khác, không phải căn bậc."""
    _, value = parse_math_expression("căn lực")
    assert value is None


# ---------------------------------------------------------------------------
# 4. Câu nhãn phải đúng số ĐÃ GÕ, không phải kết quả
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected_expr", [
    ("sqrt 144", "căn bậc hai của 144"),
    ("căn 4 của 16", "căn bậc 4 của 16"),
    ("căn bậc 3 của 27", "căn bậc 3 của 27"),
    ("căn bậc hai của 81", "căn bậc hai của 81"),
    ("căn 9", "căn bậc hai của 9"),
])
def test_cau_nhan_dung_so_da_go(text, expected_expr):
    expr, _ = parse_math_expression(text)
    assert expr == expected_expr


# ---------------------------------------------------------------------------
# 5. Định tuyến NLU - "square root" chứa chữ "root" dễ bị đoán nhầm
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "sqrt 144",
    "√16",
    "√ 144",
    "square root of 16",
    "root 3 of 27",
    "căn 2 của 8",
    "căn 4 của 16",
    "căn bậc 3 của 27",
    "căn bậc hai của 81",
])
def test_tat_ca_dang_can_bac_dieu_toi_calculate(text):
    assert predict_intent(text)["intent"] == "calculate"


def test_sqrt_khong_bi_doan_nham_lenh_gio():
    """Trước đây "square root of 16" bị model đoán là `get_datetime` - chữ
    "time" trong "root" đủ để model bịa ra ý nghĩa về giờ."""
    assert predict_intent("square root of 16")["intent"] != "get_datetime"
    assert predict_intent("root 3 of 27")["intent"] != "get_datetime"


# ---------------------------------------------------------------------------
# 6. Cách làm cũ vẫn phải chạy
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("căn bậc hai của 81", 9.0),
    ("căn bậc hai 25", 5.0),
    ("căn 144", 12.0),
    ("căn 9", 3.0),
    ("căn bậc 3 của 27", 3.0),
    # Lồng nhau: chỉ căn NGOÀI cùng được tính -> 16. Đây là hành vi có từ
    # trước v7.9 và giữ nguyên: "căn bậc hai của căn bậc hai của 256" = 16.
    ("căn bậc hai của căn bậc hai của 256", 16.0),
])
def test_cach_viet_cu_khong_dung(text, expected):
    _, value = parse_math_expression(text)
    assert value == pytest.approx(expected)


# ---------------------------------------------------------------------------
# 7. Toán khác KHÔNG bị `_KEEP_RE` mở rộng làm hỏng
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("15 + 27", 42.0),
    ("12% của 200", 24.0),
    ("2^10", 1024.0),
    ("100 chia 7 lấy dư", 2.0),
    ("5 mod 3", 2.0),
    ("log 100", 2.0),
])
def test_toan_khac_van_dung(text, expected):
    _, value = parse_math_expression(text)
    assert value == pytest.approx(expected)


@pytest.mark.parametrize("text,expected", [
    # `-` và `_` PHẢI được giữ: đường dẫn và tên biến là chuỗi hợp lệ.
    ("a-b_c", "a-b_c"),
    ("C:\\Users\\me", "c:\\users\\me"),
    ("./run.sh", "./run.sh"),
    ("12/25", "12/25"),
])
def test_chuan_hoa_van_giu_dau_quan_trong(text, expected):
    assert normalize_text(text) == expected
