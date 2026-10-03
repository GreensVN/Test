"""Test cho logarit và phần dư trong toán học (bổ sung 4 của v7.9).

Hai hàm này thiếu khá lâu, và cái thiếu đó **im lặng**: người gõ đúng câu toán
rồi nhận về "chưa tính được phép tính" - y hệt lỗi `12% của 200` mà v7.8 đã sửa.

Ba điều dễ sai ở đây, mỗi cái đều ra CON SỐ SAI thay vì ra lỗi:

  1. **Mặc định của "log".** Trong toán Việt "log" không nói cơ số là cơ số
     **10**; phần lớn máy tính điện tử và mọi công cụ lập trình dùng "log" để
     chỉ ln. Theo quy ước kỹ thuật thì "log 100" ra 4.605 thay vì 2 - cộng
     thêm câu mô tả nghe rất hợp lý, nên người dùng rất dễ tin là mình sai.
     Đây là lý do chọn quy ước Việt: sai thì ÍT NHẤT cũng phải sai toán học.
  2. **`fixed_base` nuốt chữ số.** Cho phép mẫu số tùy ý không ràng buộc thì
     "log 100" bị tách thành cơ số "10" và số "0", ra 10⁰ = 1 thay vì
     log₁₀(100) = 2.
  3. **Thứ tự từ của phần dư.** Tiếng Anh "5 mod 3" là (số, từ, số), còn tiếng
     Việt "100 chia 7 lấy dư" đặt cụm "lấy dư" ở CUỐI. Chỉ nhận thứ tự thứ
     nhất thì câu tiếng Việt rơi xuống nhánh "chia" và ra 14.28 thay vì 2.

Ngoài ra, từ khoá toán **không thể nhầm** (log/ln/mod/lấy dư) được cứu khỏi
model sai kể cả khi model tự tin - khác với câu mơ hờ như "15 + 27" mà v7.8
cố ý để ngưỡng tự tin bảo vệ.
"""
import math
import sys
from pathlib import Path

import pytest

PKG_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = PKG_DIR.parent
sys.path.insert(0, str(PKG_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# 1. Logarit.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("log 100", 2.0),          # quy ước Việt: cơ số 10, KHÔNG phải e
    ("log 1000", 3.0),
    ("log 10", 1.0),
    ("log 1", 0.0),
    ("ln 100", math.log(100)),
    ("log2 1024", 10.0),
    ("log 8 cơ số 2", 3.0),
    ("log 8 base 2", 3.0),
    ("log 1,5", math.log(1.5, 10)),
    ("log 1.234,5", math.log(1234.5, 10)),   # dấu chấm là phẩy nghìn
    # gõ không dấu phải ra CÙNG kết quả (điều README quảng cáo)
    ("log 100", 2.0),
    ("log 8 co so 2", 3.0),
])
def test_logarit(text, expected):
    from intent_model import parse_math_expression

    _, value = parse_math_expression(text)
    assert value == pytest.approx(expected)


def test_log_mac_dinh_la_co_so_10_khong_phai_e():
    """Chốt chặn quan trọng nhất: theo quy ước kỹ thuật thì log(100) = 4.605.
    Sai ở đây cho ra con số hợp lý trông như đúng, khó phát hiện nhất trong
    toàn bộ nhóm lỗi này."""
    from intent_model import parse_math_expression

    _, value = parse_math_expression("log 100")
    assert value == pytest.approx(2.0)
    assert value != pytest.approx(math.log(100))


def test_log_khong_duoc_an_chu_so_dau_cua_so_can_lay():
    """Bản lỗi cho `fixed_base` là `\\d+` không ràng buộc: "log 100" bị tách
    thành cơ số "10" và số "0", ra 10^0 = 1 thay vì 2."""
    from intent_model import parse_math_expression

    for text, expected in [("log 100", 2.0), ("log 1000", 3.0),
                           ("log 10000", 4.0), ("log 100000", 5.0)]:
        _, value = parse_math_expression(text)
        assert value == pytest.approx(expected), f"{text!r} ra {value}"


def test_log_khong_xac_dinh_thi_tra_none_chu_khong_tra_nan():
    """log không xác định (số âm, 0, cơ số 1) phải trả None. Trả NaN thì JSON
    của Python mặc định chấp nhận NaN và đọc lại được - rất dễ bị tưởng là
    số thật khi xử lý kết quả."""
    from intent_model import parse_math_expression

    for text in ("log 0", "log -5", "log 8 cơ số 1", "log 8 cơ số 0"):
        _, value = parse_math_expression(text)
        assert value is None, f"{text!r} phải trả None, không phải {value!r}"
        assert not isinstance(value, float) or value == value  # không NaN


def test_hien_thi_co_so_e_thay_vi_so_thap_phan():
    """Câu này được ĐỌC THÀNH TIẾNG: "log cơ số 2.71828 của 100" nghe như
    người dùng nhập sai."""
    from intent_model import parse_math_expression

    expr, _ = parse_math_expression("ln 100")
    assert "cơ số e" in expr
    assert "2.71" not in expr


# ---------------------------------------------------------------------------
# 2. Phần dư (modulo) - cả hai thứ tự từ.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("5 mod 3", 2.0),
    ("100 mod 7", 2.0),
    ("5 chia lấy dư 3", 2.0),
    ("số dư của 17 và 5", 2.0),
    ("phần dư của 100 và 7", 2.0),
    # Thứ tự tiếng Việt: cụm "lấy dư" ở CUỐI, không nằm giữa hai số
    ("100 chia 7 lấy dư", 2.0),
    ("17 chia 5 lấy dư", 2.0),
    ("100 chialaydu 7", 2.0),
])
def test_phan_du(text, expected):
    from intent_model import parse_math_expression

    _, value = parse_math_expression(text)
    assert value == pytest.approx(expected)


def test_phan_du_khong_duoc_roi_thanh_phep_chia():
    """Bản cũ không có thứ tự "100 chia 7 lấy dư" nên câu rơi xuống nhánh
    "chia" và ra 14.28 thay vì 2 - SAI mà vẫn trông như phép chia bình thường."""
    from intent_model import parse_math_expression

    expr, value = parse_math_expression("100 chia 7 lấy dư")
    assert value == pytest.approx(2.0)
    assert "14.28" not in expr


def test_chia_luu_du_khong_bi_doc_thanh_chia_thuong():
    """Bảo vệ ngược lại: "5 chia 3" vẫn là phép chia, không phải phần dư."""
    from intent_model import parse_math_expression

    _, value = parse_math_expression("5 chia 3")
    assert value == pytest.approx(5 / 3)


def test_phan_du_khong_the_chia_cho_khong():
    from intent_model import parse_math_expression

    assert parse_math_expression("5 mod 0") == (None, None)
    assert parse_math_expression("phần dư của 5 và 0") == (None, None)


# ---------------------------------------------------------------------------
# 3. Từ khoá toán không thể nhầm thì cứu được, kể cả khi model tự tin.
# ---------------------------------------------------------------------------
def test_log_va_mod_duoc_cuu_khi_model_tu_tin():
    """Model đoán `system_control` cho "log 8 co so 2" là sai hiển nhiên: không
    có cách đọc nào khác ngoài toán. Không cứu thì người dùng gõ đúng mà trợ
    lý điều khiển máy tính."""
    import intent_model as im

    class ConfidentWrong:
        def predict(self, x):
            return ["system_control"]

        def predict_proba(self, x):
            return [[0.99, 0.01]]

    for text in ("log 8 cơ số 2", "log2 1024", "5 mod 3", "100 chia 7 lấy dư"):
        assert im.predict_intent(text, ConfidentWrong())["intent"] == "calculate"


def test_cau_toan_mo_hoi_van_duoc_bao_ve_nguong_tin_cay():
    """v7.8 chốt: "15 + 27" model chắc thì để model quyết, vì có thể là số
    phiên bản. Mở rộng cứu cho từ khoá rõ ràng KHÔNG được làm mất ngưỡng này."""
    import intent_model as im

    class Stub:
        def predict(self, x):
            return ["play_media"]

        def predict_proba(self, x):
            return [[0.9, 0.1]]

    saved = im._MATH_INTENT_MIN_CONFIDENCE
    im._MATH_INTENT_MIN_CONFIDENCE = 0.5
    try:
        assert im.predict_intent("15 + 27", Stub())["intent"] == "play_media"
    finally:
        im._MATH_INTENT_MIN_CONFIDENCE = saved


# ---------------------------------------------------------------------------
# 4. Cả đường tròn và chốt chặn an toàn.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("log 100", 2.0),
    ("log2 1024", 10.0),
    ("5 mod 3", 2.0),
    ("100 chia 7 lấy dư", 2.0),
])
def test_tu_cau_noi_den_ket_qua(text, expected):
    from nlu_advanced import NLU

    result = NLU().understand(text)[0]
    assert result["intent"] == "calculate"
    assert result["result"] == pytest.approx(expected)


@pytest.mark.parametrize("text", [
    "xem log hệ thống",      # "log" trong câu thường, không phải toán
    "mở file log.txt",
    "tắt máy tính",
    "mở chrome",
    "het",
    "",
])
def test_cau_thuong_khong_bi_tinh_nham(text):
    from intent_model import parse_math_expression

    assert parse_math_expression(text) == (None, None)
