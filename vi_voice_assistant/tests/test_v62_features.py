"""
Test cho các nâng cấp / sửa lỗi của bản v6.2.

Nhóm kiểm tra:
  1. Sửa lỗi phân tích giờ: "tôi" không còn bị nhận nhầm thành "tối",
     "12 giờ đêm" = 0h, "1 giờ đêm" = 1h, tên "Sáu" không bị nhầm thành "sau"
  2. Số viết bằng CHỮ trong tính toán và nhắc nhở
  3. Toán tử nhiều từ, căn bậc ba, lập phương, "phần trăm" không bị đổi thành số
  4. Tách nhiều lệnh khi gõ KHÔNG DẤU
  5. Kiểm định tên intent khi dạy (teach)
  6. URL/đường dẫn: TLD mở rộng (.ai...), đường dẫn Windows dùng dấu /
  7. Bóc nội dung nhắc nhở với giờ viết bằng chữ / không dấu / đuôi "kém"
  8. Config mặc định: URL hợp lệ (bản v6.1 xuất xưởng với URL notion bị hỏng)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import nlu_advanced
import pytest
from intent_model import (
    extract_entity,
    parse_math_expression,
    parse_time_expression,
    replace_number_words,
)
from nlu_advanced import NLU, split_commands


@pytest.fixture(scope="module")
def nlu():
    return NLU()


# ----------------------------------------------------------------------------
# 1. SỬA LỖI PHÂN TÍCH GIỜ
# ----------------------------------------------------------------------------
def test_pronoun_toi_is_not_evening_marker():
    """Lỗi nghiêm trọng của v6.1: 'tôi' trong 'nhắc tôi...' bị nhận nhầm thành
    buổi 'tối' -> giờ sáng bị đẩy sang buổi tối (21h thay vì 9h)."""
    assert parse_time_expression("nhắc tôi họp lúc 9 giờ")["hour"] == 9
    assert parse_time_expression("nhắc tôi dậy lúc 6 giờ")["hour"] == 6
    assert parse_time_expression("nhắc tôi gọi Mai lúc 9 giờ")["hour"] == 9


def test_evening_marker_still_works():
    """Buổi tối THẬT vẫn phải được nhận diện (sau giờ, hoặc 'tối nay' trước giờ)."""
    assert parse_time_expression("nhắc tôi họp lúc 9 giờ tối")["hour"] == 21
    assert parse_time_expression("tối nay lúc 9 giờ nhắc tôi")["hour"] == 21


def test_midnight_and_early_morning_night():
    """'12 giờ đêm' = 0h nửa đêm (không phải 12h trưa); '1 giờ đêm' = 1h sáng
    (không phải 13h). Bảo toàn: '11 giờ đêm' = 23h."""
    assert parse_time_expression("nhắc tôi lúc 12 giờ đêm")["hour"] == 0
    assert parse_time_expression("nhắc tôi lúc 1 giờ đêm")["hour"] == 1
    assert parse_time_expression("11 giờ đêm")["hour"] == 23


def test_name_sau_is_not_delay_marker():
    """'Sáu' là TÊN NGƯỜI, không phải 'sau' (after) - chỉ phân biệt được nhờ
    kiểm tra dấu hiệu đếm ngược trên văn bản CÓ DẤU."""
    result = parse_time_expression("nhắc tôi gọi cho Sáu lúc 7 giờ")
    assert result["type"] == "clock"
    assert result["hour"] == 7


def test_delay_marker_still_works_with_diacritics():
    result = parse_time_expression("sau 2 giờ nhắc tôi")
    assert result["type"] == "delay"
    assert result["minutes"] == 120


def test_bare_minutes_means_countdown():
    """'đặt hẹn giờ 5 phút' = đếm ngược 5 phút (v6.2) - trước đây không nhận
    ra mốc thời gian nào vì thiếu chữ 'nữa/sau'."""
    result = parse_time_expression("đặt hẹn giờ 5 phút")
    assert result["type"] == "delay"
    assert result["minutes"] == 5


def test_half_hour_and_hour_and_a_half():
    assert parse_time_expression("nửa tiếng nữa")["minutes"] == 30
    assert parse_time_expression("1 tiếng rưỡi nữa")["minutes"] == 90


def test_morning_tomorrow_not_hijacked_by_toi():
    """'sáng mai nhắc tôi dậy' = 7h sáng mai (v6.1 nhầm thành 19h vì 'tôi')."""
    result = parse_time_expression("sáng mai nhắc tôi dậy")
    assert result["hour"] == 7
    assert result["day_offset"] == 1


# ----------------------------------------------------------------------------
# 2. SỐ VIẾT BẰNG CHỮ
# ----------------------------------------------------------------------------
def test_replace_number_words_basic():
    assert replace_number_words("mười lăm") == "15"
    assert replace_number_words("hai mươi mốt") == "21"
    assert replace_number_words("một trăm lẻ năm") == "105"
    assert replace_number_words("hai trăm nghìn") == "200000"
    assert replace_number_words("một triệu hai trăm nghìn") == "1200000"
    assert replace_number_words("hai phẩy năm") == "2.5"


def test_replace_number_words_keeps_non_numbers():
    """Không được đổi các từ đồng âm không phải số khi chúng CÓ DẤU."""
    assert replace_number_words("tâm sự") == "tâm sự"
    assert replace_number_words("căn bậc hai của 81") == "căn bậc hai của 81"
    assert replace_number_words("phần trăm") == "phần trăm"


def test_word_numbers_in_math():
    assert parse_math_expression("mười lăm cộng hai mươi bảy")[1] == 42
    assert parse_math_expression("hai mươi nhân ba")[1] == 60
    assert parse_math_expression("một cộng một bằng mấy")[1] == 2
    assert parse_math_expression("hai phẩy năm nhân bốn")[1] == 10.0


def test_word_numbers_in_clock_time():
    assert parse_time_expression("nhắc tôi họp lúc bảy giờ sáng")["hour"] == 7
    result = parse_time_expression("đặt báo thức sáu giờ sáng mai")
    assert result["hour"] == 6
    assert result["day_offset"] == 1


def test_word_numbers_in_delay():
    result = parse_time_expression("hẹn giờ nghỉ giải lao sau mười lăm phút")
    assert result["type"] == "delay"
    assert result["minutes"] == 15


# ----------------------------------------------------------------------------
# 3. TOÁN TỬ MỞ RỘNG
# ----------------------------------------------------------------------------
def test_multiword_operators():
    assert parse_math_expression("100 chia cho 4")[1] == 25
    assert parse_math_expression("5 nhân với 6")[1] == 30
    assert parse_math_expression("7 cộng với 8")[1] == 15
    assert parse_math_expression("10 trừ đi 3")[1] == 7


def test_cube_root_and_cube():
    assert abs(parse_math_expression("căn bậc ba của 27")[1] - 3.0) < 1e-9
    assert parse_math_expression("5 lập phương")[1] == 125


def test_percentage_not_broken_by_tram():
    """Hồi quy đã vá: 'trăm' trong 'phần trăm' từng bị đổi thành số 100 khiến
    câu phần trăm không tính được."""
    assert parse_math_expression("10 phần trăm của 500")[1] == 50.0
    assert parse_math_expression("hai mươi phần trăm của một trăm năm mươi")[1] == 30.0


# ----------------------------------------------------------------------------
# 4. TÁCH NHIỀU LỆNH KHÔNG DẤU
# ----------------------------------------------------------------------------
def test_split_commands_unaccented_roi():
    """Giới hạn mục 0-D của v6.1 (đã khắc phục): câu nhiều lệnh không dấu
    không bị tách vì 'roi' chưa được nhận ra là 'rồi'."""
    parts = split_commands("mo chrome roi phat nhac")
    assert len(parts) == 2
    assert parts[0] == "mo chrome"
    assert "phat nhac" in parts[1]


def test_split_commands_unaccented_va_with_verb():
    parts = split_commands("mo chrome va tat may")
    assert len(parts) == 2
    assert parts[1] == "tat may"


def test_split_commands_guard_unaccented_reminder():
    """Câu nhắc nhở không dấu vẫn được giữ nguyên (không cắt nhầm nội dung)."""
    text = "nhac toi hop va goi khach hang luc 3 gio"
    assert split_commands(text) == [text]


def test_split_commands_music_tru_tinh_not_guarded():
    """'trữ tình' không được kích guard (tránh chặn nhầm tách lệnh phát nhạc)."""
    parts = split_commands("mo chrome roi phat nhac tru tinh")
    assert len(parts) == 2


def test_nlu_understand_multi_command_unaccented(nlu):
    results = nlu.understand("mo chrome roi phat nhac tru tinh")
    assert len(results) == 2
    assert results[0]["intent"] == "open_app"
    assert results[1]["intent"] == "play_media"


# ----------------------------------------------------------------------------
# 5. KIỂM ĐỊNH INTENT KHI DẠY
# ----------------------------------------------------------------------------
def test_teach_rejects_unknown_intent(nlu, monkeypatch, tmp_path):
    """Gõ nhầm tên intent không được ghi vào feedback.csv (làm nhiễu lần
    huấn luyện sau)."""
    monkeypatch.setattr(nlu_advanced, "FEEDBACK_PATH", str(tmp_path / "fb.csv"))
    msg = nlu.teach("mở chrome", "open_ap")   # gõ nhầm
    assert "không hợp lệ" in msg
    assert not (tmp_path / "fb.csv").exists()


def test_teach_accepts_valid_intent(nlu, monkeypatch, tmp_path):
    monkeypatch.setattr(nlu_advanced, "FEEDBACK_PATH", str(tmp_path / "fb.csv"))
    msg = nlu.teach("mở chrome", "open_app")
    assert "Đã ghi nhớ" in msg
    assert (tmp_path / "fb.csv").exists()


# ----------------------------------------------------------------------------
# 6. URL / ĐƯỜNG DẪN
# ----------------------------------------------------------------------------
def test_url_new_tlds_recognized():
    """v6.1 chỉ nhận com/vn/net/org/io/dev - 'mở claude.ai' rơi xuống nhánh
    tìm kiếm Google thay vì mở thẳng trang."""
    assert extract_entity("mở claude.ai lên", "open_website") == "claude.ai"
    assert extract_entity("mở trang abc.xyz", "open_website") == "abc.xyz"


def test_windows_path_forward_slashes():
    result = extract_entity("mở file C:/Users/me/bao_cao.pdf", "open_file")
    assert result == "C:/Users/me/bao_cao.pdf"


def test_default_config_urls_are_valid():
    """v6.1 xuất xưởng với URL 'notion' bị hỏng trong config mặc định."""
    for cfg in (config.DEFAULT_CONFIG, config.load_config()):
        url = cfg["website_map"]["notion"]
        assert url.startswith("https://") and url.endswith(".so")
        assert "{" not in url and "}" not in url


# ----------------------------------------------------------------------------
# 7. BÓC NỘI DUNG NHẮC NHỞ
# ----------------------------------------------------------------------------
def test_reminder_task_strips_word_number_time():
    assert extract_entity("nhắc tôi uống thuốc lúc bảy giờ tối", "set_reminder") == "uống thuốc"


def test_reminder_task_strips_unaccented_prefix_and_time():
    assert extract_entity("nhac toi hop luc 9 gio", "set_reminder") == "hop"


def test_reminder_task_strips_kem_tail():
    """v6.1 để sót 'kém 15' trong nội dung nhắc nhở."""
    assert extract_entity("hẹn 8 giờ kém 15", "set_reminder") == "hẹn"


def test_reminder_task_strips_two_word_tail():
    """'6 giờ sáng mai' phải bị bóc trọn (cả 'sáng' lẫn 'mai')."""
    assert extract_entity("đặt báo thức 6 giờ sáng mai", "set_reminder") == "báo thức"
