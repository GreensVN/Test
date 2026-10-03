"""
v7.9 (bổ sung 9d) - Câu CHỈ có động từ thì phải HỎI, không được đoán.

`SEARCH_PREFIX` bắt buộc phải có khoảng trắng phía sau (`\\s+`), nên câu chỉ
toàn động từ thì nhánh dài không khớp được, regex rơi xuống nhánh ngắn và để
lại MẢNH VỠ:

    "tìm kiếm" -> "kiếm"      (KIẾM - con dao)
    "tra cứu"  -> "cứu"       (CỨU - cứu người)
    "tìm"      -> "tìm"

Rồi `_entity_search_web` có `or ctx.raw` để "đỡ rỗng", nên máy mở thật Google
tìm chính mẫu tự khiến. Người dùng chỉ nói *"tìm kiếm"* - một lệnh rất tự
nhiên - và nhận về một cửa sổ trình duyệt với từ khoá là con dao.
"""

import pytest
from intent_model import extract_entity, predict_intent


def _target(text: str) -> str:
    return str(extract_entity(text, predict_intent(text)["intent"]))


# ---------------------------------------------------------------------------
# 1. Câu chỉ toàn động từ -> rỗng, để executor HỎI
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "tìm kiếm",          # KHÔNG được thành "kiếm"
    "tra cứu",           # KHÔNG được thành "cứu"
    "tìm",
    "search",
    "google",
    "cho tôi tìm kiếm",
    "tim kiem",          # không dấu
    "tra cuu",           # không dấu
])
def test_cau_chi_co_dong_tu_thi_hhoi(text):
    assert _target(text) == ""


def test_dong_tu_len_dai_duoc_uu_tien_hon_dong_tu_ngan():
    """Regex phải ăn theo nghĩa DÀI, không theo nghĩa NGẮN.

    "tra cuu" mà rơi xuống nhánh `tra` thì để lại "cuu". Nhánh `tra cứu` ăn
    trọn câu thì không còn gì để hỏi.
    """
    assert "cuu" not in _target("tra cuu")
    assert "cuu" not in _target("tìm kiếm")


# ---------------------------------------------------------------------------
# 2. Hỏi thì tốn một lượt, đoán thì mở nhầm cửa sổ
# ---------------------------------------------------------------------------
def test_action_search_web_hoi_khi_target_rong():
    """Đích của hành vi này là câu hỏi, nên phải kiểm chứng cả tầng executor."""
    from executor import action_search_web

    said: list[str] = []
    import executor

    original = executor.respond
    executor.respond = said.append
    try:
        opened: list[str] = []
        executor._open_url = opened.append
        assert action_search_web("") is False
    finally:
        executor.respond = original
    assert said == ["Bạn muốn tìm gì ạ?"]
    assert not opened, "rỗng thì KHÔNG được mở trình duyệt"


# ---------------------------------------------------------------------------
# 3. Không được phá hỏng việc bóc câu CÓ nội dung
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("tìm giá vàng", "giá vàng"),
    ("tìm kiếm giá vàng", "giá vàng"),
    ("cho tôi tìm kiếm abc", "abc"),
    ("tìm giá vàng trên google", "giá vàng"),
    ("tra cứu thông tin về bệnh viêm gan", "bệnh viêm gan"),
    ("cho tôi tìm kiếm abc", "abc"),
])
def test_cau_co_noi_dung_van_boc_dung(text, expected):
    assert _target(text) == expected
