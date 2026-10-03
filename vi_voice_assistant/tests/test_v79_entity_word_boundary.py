"""
v7.9 (bổ sung 9c) - HAI HÀNG RÀO cho nhánh bỏ dấu. Một bản sửa tự tạo ra lỗi.

Bổ sung 9b thêm nhánh khớp trên bản BỎ DẶU để "phat nhac" bóc được động từ.
Nhánh đó xoá mất đúng cái thông tin phân biệt các từ, và nó đã cắt nhầm ngay:

    "phát podcast về công nghệ"  ->  "podcast về công"

Vì "nghe" bỏ dấu ra "nghe", mà "nghe" nằm trong "nghệ" (ngh + ệ). Người dùng
không có tín hiệu nào để biết: câu vẫn ra, lệnh vẫn chạy, chỉ là dữ liệu bị
cắt cụt. Đây là bản sửa làm HỎNG thêm một lỗi, trong khi lý do ban đầu vẫn
đang đúng.

Bản này khoá lại HAI hàng rào, mỗi cái ứng với đúng một cách hỏng đã quan sát
được chứ không phải suy diễn.
"""

import pytest
from intent_model import _sub_keep_accents, extract_entity, predict_intent
from text_utils import strip_diacritics


def _target(text: str) -> str:
    intent = predict_intent(text)["intent"]
    return str(extract_entity(text, intent))


# ---------------------------------------------------------------------------
# 1. Hàng rào CHỐT DẤU: "nghệ" KHÔNG phải "nghe"
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("phát podcast về công nghệ", "podcast về công nghệ"),
    ("nghe nhạc về công nghệ", "nhạc về công nghệ"),
    ("cho tôi nghe nhạc về công nghệ", "nhạc về công nghệ"),
    ("nghe nhạc về chi tiết", "nhạc về chi tiết"),
])
def test_nghe_khong_duoc_an_vao_nghe(text, expected):
    """Người đã gõ dấu thì chữ đó KHÔNG phải mẫu không dấu.

    Nhánh bỏ dấu sinh ra để phục vụ người gõ KHÔNG dấu. Ai gõ "nghệ" đã chứng
    minh mình gõ được dấu, nên lúc đó "nghệ" không phải "nghe".
    """
    assert _target(text) == expected


def test_bo_dau_va_co_dau_la_hai_thu_khac_nhau_khong_phai_mot():
    """Bằng chứng nền cho hàng rào: bỏ dấu LÀM HAI TỪ KHÁC NHAU THÀNH MỘT."""
    assert strip_diacritics("nghệ") == "nghe" == strip_diacritics("nghe")
    # Chính vì vậy mà bản cũ cắt mất đuôi: hai từ này không còn phân biệt được.
    assert _sub_keep_affixes_nghe_matches("nghệ") is False
    assert _sub_keep_affixes_nghe_matches("nghe") is True


def _sub_keep_affixes_nghe_matches(text: str) -> bool:
    """`nghe` có bị bóc khỏi `text` không (mẫu hậu tố thật của MEDIA)."""
    from intent_model import MEDIA_SUFFIX

    return bool(_sub_keep_accents(text, MEDIA_SUFFIX) != text)


# ---------------------------------------------------------------------------
# 2. Hàng rào TRỌN TỪ: "ho toi" không được ăn vào "cho toi"
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "doc bao cho toi nghe",      # không dấu: nguy hiểm nhất, không chốt dấu cứu được
    "đọc báo cho tôi nghe",      # có dấu
    "tim ho toi gia laptop",     # "ho toi" đứng đầu câu, không phải đuôi
])
def test_ho_toi_khong_duoc_an_vao_cho_toi(text):
    """Bóc "ho toi" ra khỏi "cho toi" là MẤT CẢ CHỮ, không phải bóc hơi quá.

    Nếu không chặn, "doc bao cho toi nghe" thành *"doc bao c nghe"*. Chặn ở đây
    là chặn theo RANH GIỚI TỪ, không phụ thuộc có dấu hay không.
    """
    assert _sub_keep_accents(text, r"\s*hộ tôi\s*$") == text
    assert _sub_keep_accents(text, r"\s*ho toi\s*$") == text


def test_ho_toi_an_vao_cho_toi_khi_khong_co_ranh_gioi_tu():
    r"""Hàng rào trọn từ phải chịu được CẢ mẫu không neo, không chỉ mẫu có `$`.

    Đây là chỗ hàng rào thật sự gánh phần việc: "ho toi" bỏ dấu là "ho toi",
    nằm NGAY TRONG "cho toi". Bỏ hàng rào thì câu bị cắt thành
    *"doc bao c nghe"* - mất cả chữ, chứ không phải bóc hơi quá. Hàng rào chốt
    dấu KHÔNG cứu được câu này, vì câu này không dấu hoàn toàn.
    """
    assert _sub_keep_accents("cho toi nghe", r"\s*ho toi\s*") == "cho toi nghe"
    # mẫu neo vẫn phải bóc đúng khi khớp trọn từ thật sự
    assert _sub_keep_accents("xin ho toi", r"\s*ho toi\s*$") == "xin"


# ---------------------------------------------------------------------------
# 3. Hàng rào không được phá hỏng việc đã sửa ở 9b
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("phat nhac", "nhac"),
    ("bat nhac", "nhac"),
    ("cho toi nghe nhac", "nhac"),
    ("nghe nhac", "nhac"),
    ("choi nhac", "nhac"),
])
def test_bo_dau_van_boc_duoc_dong_tu(text, expected):
    """Không dấu thì VẪN phải bóc - hàng rào chặn nhầm, không phải chặn tất cả."""
    assert _target(text) == expected


def test_bao_cao_mat_dau_cua_mau_khong_duoc_lam_vo_hang_rau():
    r"""Mẫu hay kết thúc bằng `\s+`; nếu lấy nguyên khớp thì ký tự ngay sau
    luôn là chữ của từ kế tiếp và hàng rào trọn từ chặn nhầm chính cái bóc dấu
    mà ta muốn. Đã vỡ ra một lần: mọi thứ bị bỏ nguyên."""
    assert _sub_keep_accents("phát nhạc", r"^(phát)\s+") == "nhạc"
    assert _sub_keep_accents("phat nhac", r"^(phát)\s+") == "nhac"


# ---------------------------------------------------------------------------
# 4. GIỚI HẠN còn lại: không dấu thì thật sự không phân biệt được
# ---------------------------------------------------------------------------
def test_khong_dau_thi_nghe_va_nghe_khong_tach_duoc():
    """Người gõ KHÔNG dấu thì thông tin đó KHÔNG CÒN trong câu.

    Không thể sửa mà không BỎA. Ghi lại thay vì giả vờ đã xử lý xong.
    """
    assert _target("phat podcast về cong nghe") == "podcast về cong"
