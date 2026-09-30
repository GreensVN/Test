"""Test cho phần trích thực thể của bản v7.9 - chỗ để trống `unknown`.

Lỗi tìm được ở đây nặng hơn mọi lỗi "sai intent" khác, vì nó **tự tin**:
model đoán `open_app` với 0.97, rồi `extract_entity` trả về chuỗi `"unknown"`
- tức trình bày như thể người dùng đã gọi tên một ứng dụng tên "unknown". Trợ
lý đáp *"Chưa biết ứng dụng 'unknown'. Hãy thêm 'unknown' vào config.json"*:
không chỉ vô nghĩa mà còn dạy người dùng sửa sai file cấu hình.

Nguyên nhân: `STOP_WORDS_ALL` phải chứa "trình"/"duyệt" để câu dài bỏ đúng
("mở trình duyệt youtube" -> "youtube"), nhưng với câu NGẮN đúng bằng chỗ đó
thì bỏ hết rồi không còn gì để gọi tên, và `_entity_default` trả "unknown".

Cách sửa không phải bớt stop-word (sẽ hỏng câu dài), mà là **bỏ dần**: bỏ hết
mà rỗng thì bỏ tiếp động từ lệnh, giữ phần còn lại.

Phần thứ hai của file này là `system_control`, nơi chỗ để trống `"unknown"`
được in thẳng ra cho người dùng đọc.
"""
import sys
from pathlib import Path

import pytest

PKG_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = PKG_DIR.parent
sys.path.insert(0, str(PKG_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# 1. Câu ngắn không được rỗng chỉ vì bỏ hết stop-word.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("mở trình duyệt", "trình duyệt"),
    # Gọi thẳng `extract_entity` thì không qua `smart_normalize`, nên câu gõ
    # KHÔNG DẤU giữ nguyên không dấu - phục hồi dấu là việc của tầng trên,
    # và `test_khong_dau_duoc_khoi_phuc_dau` kiểm đúng chỗ đó.
    ("mo trinh duyet", "trinh duyet"),
    ("mở trình duyệt chrome", "chrome"),
    ("mở trình duyệt youtube", "youtube"),
    ("mở file báo cáo", "báo cáo"),
    ("mở ứng dụng", "ứng dụng"),
])
def test_cau_ngắn_khong_bi_boc_rong(text, expected):
    from intent_model import extract_entity

    assert extract_entity(text, "open_app") == expected


def test_boc_rong_hon_mot_tien_do_gi_duoc_dung():
    """Câu dài vẫn phải bỏ stop-word như cũ, không được biến thành
    "trình duyệt youtube" -> "trình duyệt youtube"."""
    from intent_model import extract_entity

    assert extract_entity("mở trình duyệt youtube", "open_website") == "youtube"
    assert extract_entity("mở google chrome đi", "open_app") == "google chrome"


def test_chua_gi_deu_la_chi_cho_trong():
    """Không có gì để gọi tên thì trả chỗ để trống - nhưng phải là CHỖ ĐỂ TRỐNG
    quen thuộc, để tầng dưới còn biết mà hỏi lại."""
    from intent_model import extract_entity

    assert extract_entity("mở", "open_app") == "unknown"


# ---------------------------------------------------------------------------
# 2. Chỗ để trống không được lọt ra miệng người dùng.
# ---------------------------------------------------------------------------
def test_lenh_he_thong_rong_hoi_lai_chu_khong_in_unknown(capsys):
    """"máy tính" là câu lệnh nửa vời. Bản cũ in "Không hỗ trợ lệnh hệ thống
    'unknown' trên Linux" - tự thừa nhận là không hiểu mà không giúp gì."""
    import executor

    assert executor.action_system_control("unknown") is False
    out = capsys.readouterr().out
    assert "unknown" not in out, "chỗ để trống bên trong lọt ra cho người dùng"
    assert "Bạn muốn làm gì" in out


def test_lenh_he_thong_rong_bang_chuoi_rong_cung_the(capsys):
    import executor

    assert executor.action_system_control("") is False
    assert "unknown" not in capsys.readouterr().out


def test_lenh_he_thong_that_van_chay_nhu_cu(capsys):
    """Chặn chỗ để trống KHÔNG được nuốt mất lệnh thật."""
    import executor

    called = []
    executor._SYSTEM_HANDLERS = {"Linux": lambda t: called.append(t) or True}
    try:
        assert executor.action_system_control("volume_up") is True
    finally:
        executor._SYSTEM_HANDLERS = {}
    assert called == ["volume_up"]
    assert "unknown" not in capsys.readouterr().out


def test_khong_dau_duoc_khoi_phuc_dau():
    """Qua tầng NLU thì câu gõ không dấu phải ra target CÓ DẤU, để người dùng
    đọc thấy "trình duyệt" chứ không phải "trinh duyet"."""
    from nlu_advanced import NLU

    assert NLU().understand("mo trinh duyet")[0]["target"] == "trình duyệt"


def test_tim_kiem_giu_nguyen_cau_hoi_san_co():
    """`action_search_web` đã xử lý chỗ để trống từ trước; giữ nguyên để các
    intent khác cùng cách."""
    import executor

    assert executor.action_search_web("unknown") is False


# ---------------------------------------------------------------------------
# 3. Cả đường tròn: câu nói -> target dùng được.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("mo trinh duyet", "trình duyệt"),
    ("mo chrome", "chrome"),
])
def test_tu_cau_noi_den_target_dung(text, expected):
    from nlu_advanced import NLU

    result = NLU().understand(text)[0]
    assert result["intent"] == "open_app"
    assert result["target"] == expected
    assert result["target"] != "unknown", "target rỗng thì lệnh không làm được gì"
