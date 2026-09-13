import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataset import INTENT_DATA, get_dataset_as_lists


def test_all_11_intents_present():
    expected = {
        "open_website", "open_app", "open_file", "system_control",
        "search_web", "play_media", "set_reminder", "get_weather",
        "get_datetime", "calculate", "chitchat",
    }
    assert expected == set(INTENT_DATA.keys())


def test_all_intents_have_samples():
    for intent, sentences in INTENT_DATA.items():
        assert len(sentences) >= 10, f"Intent '{intent}' cần ít nhất 10 câu mẫu"


def test_chitchat_absorbs_out_of_scope_sentences():
    """chitchat đóng vai trò lưới an toàn cho câu ngoài phạm vi (thay cho
    nhãn 'unknown' riêng của bản trước - xem lời giải thích trong dataset.py
    và HUONG_DAN_SU_DUNG.txt)."""
    assert "chitchat" in INTENT_DATA
    assert "unknown" not in INTENT_DATA
    assert any("buồn" in s for s in INTENT_DATA["chitchat"])


def test_get_dataset_as_lists_same_length():
    texts, labels = get_dataset_as_lists()
    assert len(texts) == len(labels)
    assert len(texts) > 0


def test_augmentation_adds_no_diacritics_variants():
    texts_aug, _ = get_dataset_as_lists(augment_no_diacritics=True)
    texts_plain, _ = get_dataset_as_lists(augment_no_diacritics=False)
    assert len(texts_aug) > len(texts_plain)


def test_no_duplicate_text_label_pairs():
    texts, labels = get_dataset_as_lists()
    pairs = list(zip(texts, labels))
    assert len(pairs) == len(set(pairs))


def test_calculate_sentences_are_all_parseable():
    """v6.2: MỌI câu calculate trong dataset (kể cả số viết bằng chữ, vd
    "mười lăm cộng hai mươi bảy") đều phải tính ra kết quả. Bản v6.1 chỉ tính
    được số viết bằng chữ số; số bằng chữ được gắn nhãn đúng nhưng không tính
    được (giới hạn đã ghi nhận ở HUONG_DAN mục 0-D, nay đã khắc phục)."""
    from intent_model import parse_math_expression
    for s in INTENT_DATA["calculate"]:
        _expr, result = parse_math_expression(s)
        assert result is not None, f"Câu calculate không tính được: {s!r}"
