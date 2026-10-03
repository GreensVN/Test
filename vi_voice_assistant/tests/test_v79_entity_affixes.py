"""
v7.9 (bổ sung 9) - Bóc động tỪ trong entity khi người gõ KHÔNG DẤU.

Bug gốc: `MEDIA_PREFIX` viết có dấu ("phát"), nên câu gõ không dấu ("phat
nhac") không bóc được gì cả - trợ lý đọc ra *"Đang phát phat nhac"*, tức đọc
nguyên cả câu lệnh cho người dùng. Trong khi "phát nhạc" (có dấu) thì chạy đúng:
cùng một câu, hai kết quả, chỉ khác dấu.

Đây là lần thứ N của lớp lỗi "mẫu viết không dấu/có dấu lệch chiều với câu
thật" - và lần này chiều NGƯỢC: mẫu CÓ dấu bị áp lên câu KHÔNG dấu.
"""

import pytest
from intent_model import predict_intent
from text_utils import strip_diacritics


# ---------------------------------------------------------------------------
# 1. Gõ không dấu vẫn phải bóc được động từ, giống hệt gõ có dấu
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("plain,accented", [
    ("phat nhac", "phát nhạc"),
    ("bat nhac", "bật nhạc"),
    ("cho toi nghe nhac", "cho tôi nghe nhạc"),
    ("nghe nhac", "nghe nhạc"),
])
def test_gio_khong_dau_va_co_dau_bo_cung_mot_du_oi(plain, accented):
    """Gõ không dấu phải bóc đúng bằng số từ như gõ có dấu.

    Đích vẫn giữ dấu THEO CÁCH ĐÃ GÕ: "phat nhac" -> "nhac", "phát nhạc" ->
    "nhạc". Đòi cả hai ra "nhạc" là sai - bộ bóc không thể BỎA dấu người dùng
    chưa từng gõ; bỏa dấu là bịa tin. Nó chỉ được KHÔNG tự thêm dấu.
    """
    from text_utils import strip_diacritics

    assert predict_intent(plain)["target"] == strip_diacritics(
        predict_intent(accented)["target"]
    )


def test_bo_dau_khong_duoc_lam_mat_dau_cua_cau_goc():
    """Kết quả phải là câu GỐC (có dấu), không phải bản bỏ dấu.

    Nếu trả bản bỏ dấu thì người đã gõ có dấu lại được đọc câu không dấu - lỗi
    mới, không kém lỗi cũ.
    """
    from intent_model import _sub_keep_accents

    assert _sub_keep_accents("phát nhạc", r"^(phát)\s+") == "nhạc"
    assert _sub_keep_accents("cho tôi nghe nhạc", r"^(cho tôi nghe)\s+") == "nhạc"


def test_strip_diacritics_giu_nguyen_do_dai():
    """Cả chuyện bóc mà giữ dấu dựa trên đúng điều này: tra ký tự 1-1."""
    for s in ["phát nhạc", "Đà Nẵng", "nghe nhạc trữ tình", "cần ơi"]:
        assert len(strip_diacritics(s)) == len(s), s


# ---------------------------------------------------------------------------
# 2. Động từ còn thiếu trong danh sách
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("chơi nhạc", "nhạc"),        # "chơi" là cách nói rất phổ biến
    ("choi nhac", "nhac"),   # giữ nguyên không dấu, xem test 1
    ("cho tôi tìm kiếm abc", "abc"),  # "cho tôi" đứng riêng
])
def test_dong_tu_moi_duoc_boc(text, expected):
    assert predict_intent(text)["target"] == expected


# ---------------------------------------------------------------------------
# 3. Chốt chặn: bỏ dấu làm hai cụm KHÁC NHAU trùng nhau
# ---------------------------------------------------------------------------
def test_bo_dau_co_tho_lam_hai_cum_trung_nhau():
    """Cơ sở để giải thích các giới hạn còn lại ở cuối file.

    "hộ tôi" -> "ho toi", mà "ho toi" nằm NGAY TRONG "cho toi" (vị trí 1). Nên
    bóc bằng cách khớp trên bản bỏ dấu sẽ ăn nhầm: "đọc báo cho tôi nghe" bị
    bóc mất đoạn "ho tôi" và thành *"đọc báo c nghe"* - mất cả chữ, không chỉ
    bóc hơi quá.
    """
    assert strip_diacritics("hộ tôi") == "ho toi"
    assert strip_diacritics("cho tôi") == "cho toi"
    assert strip_diacritics("cho tôi").find("ho toi") == 1


def test_khong_boc_nham_giua_cau():
    """Câu NÀO đúng thì phải bóc, kể cả khi có cụm dễ nhầm bên trong."""
    # "cho tôi" là đầu câu hợp lệ -> phải bóc
    from intent_model import _sub_keep_accents

    assert _sub_keep_accents("cho tôi tìm kiếm abc", r"^(cho tôi)\s+") == "tìm kiếm abc"
    # "cho tôi" đứng GIỮA không phải đầu câu -> không được đụng vào
    got = _sub_keep_accents("đọc báo cho tôi nghe", r"^(cho tôi)\s+")
    assert got == "đọc báo cho tôi nghe"


# ---------------------------------------------------------------------------
# 4. Còn lại, CHƯA sửa - ghi rõ để không tưởng đã xong
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,current", [
    # Cụm NỀN TẢNG nằm GIỮA câu. Mẫu hậu tố neo bằng `$` nên chỉ bóc được ở
    # đuôi; muốn bóc ở giữa thì phải so trên bản bỏ dấu, mà bỏ dấu thì
    # "hộ tôi" trùng "cho tôi" như test 3 chứng minh. Cần bóc theo RANH GIỚI
    # TỪ mới làm an toàn - việc đó lớn hơn phạm vi sửa lỗi ở đây.
    ("tìm trên google giá vàng", "trên google giá vàng"),
    ("tìm hộ tôi giá laptop", "hộ tôi giá laptop"),
])
def test_cum_nen_tang_o_giua_cau_hien_chua_boc(text, current):
    """Test khoá HÀNH VI HIỆN TẠI, không phải khoá hành vi đúng.

    Khi sửa được thì đổi `current` thành giá trị mong muốn - đừng xoá test này.
    """
    assert predict_intent(text)["target"] == current
