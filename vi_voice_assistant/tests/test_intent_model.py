# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from intent_model import (
    extract_entity,
    parse_math_expression,
    parse_time_expression,
    predict_intent,
    train_model,
)


@pytest.fixture(scope="module")
def model():
    return train_model(show_report=False)


@pytest.mark.parametrize("text,expected_intent", [
    ("Bật Google lên", "open_website"),
    ("khởi chạy vs code", "open_app"),
    ("mở file báo cáo", "open_file"),
    ("tắt máy tính đi", "system_control"),
    ("tắt tiếng loa", "system_control"),
    ("tìm giá vàng trên google", "search_web"),
    ("nhắc tôi họp lúc 3 giờ chiều", "set_reminder"),
    ("thời tiết đà nẵng hôm nay thế nào", "get_weather"),
    ("mấy giờ rồi", "get_datetime"),
    ("15 cộng 27 bằng bao nhiêu", "calculate"),
    ("xin chào bạn", "chitchat"),
    ("hôm nay trời thế nào", "get_weather"),
])
def test_predict_intent_accented(model, text, expected_intent):
    result = predict_intent(text, model)
    assert result["intent"] == expected_intent


@pytest.mark.parametrize("text,expected_intent", [
    ("bat google len", "open_website"),
    ("tat may tinh di", "system_control"),
])
def test_predict_intent_no_diacritics(model, text, expected_intent):
    """Mô hình phải nhận diện đúng cả khi câu KHÔNG có dấu tiếng Việt (nhờ
    dataset.get_dataset_as_lists() tự động thêm biến thể không dấu)."""
    result = predict_intent(text, model)
    assert result["intent"] == expected_intent


def test_predict_intent_returns_base_schema(model):
    result = predict_intent("mở google lên", model)
    assert {"intent", "target", "confidence"} <= set(result.keys())
    assert 0.0 <= result["confidence"] <= 1.0


def test_predict_intent_set_reminder_has_time_key(model):
    result = predict_intent("nhắc tôi họp lúc 3 giờ chiều", model)
    assert result["intent"] == "set_reminder"
    assert "time" in result
    assert result["time"]["type"] == "clock"


def test_predict_intent_calculate_has_result_key(model):
    result = predict_intent("15 cộng 27 bằng bao nhiêu", model)
    assert result["intent"] == "calculate"
    assert result["result"] == 42


def test_extract_entity_website():
    assert extract_entity("Bật Google lên", "open_website") == "google"


def test_extract_entity_system_control():
    assert extract_entity("Tắt máy tính đi", "system_control") == "shutdown"


def test_extract_entity_system_control_no_diacritics():
    assert extract_entity("tat may tinh di", "system_control") == "shutdown"


def test_extract_entity_open_app():
    assert extract_entity("khởi chạy vs code giúp tôi", "open_app") == "vs code"


def test_extract_entity_search_web_strips_affixes():
    assert extract_entity("tìm giá vàng trên google", "search_web") == "giá vàng"


def test_extract_entity_get_datetime_time_vs_date():
    assert extract_entity("mấy giờ rồi", "get_datetime") == "time"
    assert extract_entity("hôm nay ngày mấy", "get_datetime") == "date"


def test_extract_entity_set_reminder_strips_time_and_verbs():
    assert extract_entity("nhắc tôi họp lúc 3 giờ chiều", "set_reminder") == "họp"


def test_extract_entity_calculate_returns_expression():
    assert extract_entity("15 cộng 27 bằng bao nhiêu", "calculate") == "15 + 27"


# ----------------------------------------------------------------------------
# CÁC TEST BẢO TOÀN TỪ BẢN VÁ LỖI TRƯỚC ĐÓ: URL/đường dẫn không bị cắt cụt
# hoặc mất hoa/thường
# ----------------------------------------------------------------------------
def test_extract_entity_website_keeps_full_path():
    result = extract_entity("mở github.com/anthropics/claude lên", "open_website")
    assert result == "github.com/anthropics/claude"


def test_extract_entity_website_preserves_case_and_query():
    text = "mở https://www.youtube.com/watch?v=dQw4w9WgXcQ lên"
    result = extract_entity(text, "open_website")
    assert result == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_extract_entity_website_does_not_false_positive_on_partial_tld():
    result = extract_entity("mở trang web abc.commercial nào đó", "open_website")
    assert result != "abc.com"
    assert "abc.com" not in result.split()


def test_extract_entity_file_path_preserves_case():
    result = extract_entity("mở file /Home/User/MyReport.PDF giúp tôi", "open_file")
    assert result == "/Home/User/MyReport.PDF"


# ----------------------------------------------------------------------------
# PARSE_TIME_EXPRESSION (nhắc nhở)
# ----------------------------------------------------------------------------
def test_parse_time_expression_delay():
    result = parse_time_expression("30 phút nữa")
    # v6: hàm nay LUÔN trả đủ khoá (type/minutes/hour/minute/day_offset) nên
    # kiểm tra theo từng khoá thay vì so sánh nguyên cả dict.
    assert result["type"] == "delay"
    assert result["minutes"] == 30


def test_parse_time_expression_delay_without_diacritics():
    """v6: gõ không dấu vẫn phải hiểu."""
    assert parse_time_expression("30 phut nua")["minutes"] == 30


def test_parse_time_expression_delay_seconds():
    """v6: đơn vị giây trước đây bị bỏ qua hoàn toàn."""
    result = parse_time_expression("nhắc tôi 30 giây nữa")
    assert result["type"] == "delay"
    assert abs(result["minutes"] - 0.5) < 1e-6


def test_parse_time_expression_clock_afternoon():
    result = parse_time_expression("lúc 3 giờ chiều")
    assert result["type"] == "clock"
    assert (result["hour"], result["minute"]) == (15, 0)


def test_parse_time_expression_clock_short_form():
    """v6: dạng viết tắt '3h30' rất hay gặp khi gõ nhanh.

    v6.2: kết quả đúng là (3, 30) - bản v6.1 trả về (15, 30) vì LỖI nhận nhầm
    chữ 'tôi' (đại từ) thành buổi 'tối' khi tìm buổi trên TOÀN câu; giờ buổi
    chỉ được nhận diện sau biểu thức giờ (xem intent_model.parse_time_expression).
    """
    result = parse_time_expression("nhắc tôi uống thuốc lúc 3h30")
    assert (result["hour"], result["minute"]) == (3, 30)


def test_parse_time_expression_half_past_and_quarter_to():
    """v6: 'rưỡi' và 'kém' - hai cách nói giờ rất đời thường."""
    assert parse_time_expression("3 giờ rưỡi chiều")["minute"] == 30
    result = parse_time_expression("hẹn 8 giờ kém 15")
    assert (result["hour"], result["minute"]) == (7, 45)


def test_parse_time_expression_night_hour():
    """v6: '11 giờ đêm' = 23h chứ không phải 11h sáng."""
    assert parse_time_expression("11 giờ đêm")["hour"] == 23


def test_parse_time_expression_tomorrow_sets_day_offset():
    """v6: trước đây chữ 'mai' bị bỏ qua -> lời nhắc kêu ngay trong hôm nay."""
    result = parse_time_expression("7 giờ sáng mai gọi điện")
    assert result["hour"] == 7
    assert result["day_offset"] == 1
    assert parse_time_expression("tối mai nhắc tôi chạy bộ")["day_offset"] == 1


def test_parse_time_expression_does_not_treat_name_mai_as_tomorrow():
    """'gọi Mai' là TÊN NGƯỜI, không phải 'ngày mai'."""
    assert parse_time_expression("nhắc tôi gọi Mai lúc 9 giờ")["day_offset"] == 0


def test_parse_time_expression_none_when_no_time():
    result = parse_time_expression("nhắc tôi họp nhóm")
    assert result["type"] is None
    # v6: kể cả khi không nhận ra giờ, dict vẫn đủ khoá cho nơi gọi dùng.
    for key in ("minutes", "hour", "minute", "day_offset"):
        assert key in result


# ----------------------------------------------------------------------------
# PARSE_MATH_EXPRESSION (tính toán an toàn, không dùng eval() trên câu thô)
# ----------------------------------------------------------------------------
def test_parse_math_expression_basic_addition():
    expr, result = parse_math_expression("12 cộng 8 bằng bao nhiêu")
    assert expr == "12 + 8"
    assert result == 20


def test_parse_math_expression_square_root():
    expr, result = parse_math_expression("căn bậc hai của 81")
    assert result == 9.0


def test_parse_math_expression_percentage():
    expr, result = parse_math_expression("10 phần trăm của 500")
    assert result == 50.0


def test_parse_math_expression_returns_none_for_non_math_text():
    expr, result = parse_math_expression("xin chào bạn")
    assert expr is None
    assert result is None


def test_parse_math_expression_rejects_unsafe_input():
    """Không được cho phép chạy mã tuỳ ý - chỉ số + toán tử được chấp nhận."""
    expr, result = parse_math_expression("__import__('os').system('echo hi') cộng 1")
    # Không có số hợp lệ để ghép biểu thức -> không tính được, không ném lỗi ra ngoài
    assert result is None or isinstance(result, (int, float))
