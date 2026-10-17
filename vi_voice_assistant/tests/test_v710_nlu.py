"""Câu gốc, ngữ cảnh và phủ định không được biến thành lệnh sai."""
import pytest
from intent_model import parse_repeat, predict_intent
from nlu_advanced import NLU, ContextMemory, split_commands


class FixedModel:
    def __init__(self, intent):
        self.intent = intent

    def predict(self, texts):
        return [self.intent]

    def predict_proba(self, texts):
        return [[1.0]]


@pytest.mark.parametrize("text", [
    "đừng tắt máy", "không khoá máy", "chớ restart", "ko tat may", "dung khoa may",
    "do not shutdown", "don't lock", "ĐỪNG tắt máy",
])
def test_negated_system_command_is_never_accepted(text):
    result = predict_intent(text, FixedModel("system_control"))
    assert result["confidence"] == 0.0
    assert NLU._judge(result) == "unknown"


@pytest.mark.parametrize("text", ["tắt máy", "khoá máy", "dừng nhạc", "chụp màn hình"])
def test_positive_system_commands_are_unchanged(text):
    assert predict_intent(text, FixedModel("system_control"))["confidence"] == 1.0


@pytest.mark.parametrize("text,parts", [
    ("2+3, mở chrome", ["2+3", "mở chrome"]),
    ("mở chrome,2+3", ["mở chrome", "2+3"]),
    ("2,5 nhân 4", ["2,5 nhân 4"]),
    ("MỞ CHROME RỒI MỞ GOOGLE", ["MỞ CHROME", "MỞ GOOGLE"]),
    ("MỞ CHROME VÀ MỞ GOOGLE", ["MỞ CHROME", "MỞ GOOGLE"]),
])
def test_split_respects_decimal_and_is_case_insensitive(text, parts):
    assert split_commands(text) == parts


@pytest.mark.parametrize("text", [
    "NHẮC TÔI ăn rồi uống thuốc lúc 8 giờ",
    "đặt nhắc ăn rồi uống thuốc lúc 8 giờ",
    "TÌM thông tin chrome rồi firefox",
    "đặt lịch ăn rồi uống thuốc lúc 8 giờ",
])
def test_reminder_and_search_content_is_not_executed_as_separate_commands(text):
    assert split_commands(text) == [text]


def test_context_substitutes_plural_pronoun_before_singular():
    context = ContextMemory()
    context.remember({"target": "google"})
    assert context.resolve("mở chúng nó") == "mở google"


@pytest.mark.parametrize("text", ["mở nó", "mo no", "mở trang đó"])
def test_context_keeps_original_url_case_and_query_symbols(text):
    nlu = NLU(model=FixedModel("open_website"))
    url = "https://example.com/VideoID?A=X&b=Y#part"
    nlu.context.remember({"intent": "open_website", "target": url})
    result = nlu.understand(text)[0]
    assert result["target"] == url
    assert result["raw"] == text


@pytest.mark.parametrize("text,intent,expected", [
    ("tìm C++ & C#", "search_web", "c++ & c#"),
    ("tìm chorme", "search_web", "chorme"),
    ("phát bài hát C++", "play_media", "bài hát c++"),
])
def test_query_is_data_not_typo_corrected_or_stripped(text, intent, expected):
    result = NLU(model=FixedModel(intent)).understand(text)[0]
    assert result["target"] == expected
    assert result["raw"] == text


def test_unknown_weekday_does_not_crash_repeat_parser():
    assert parse_repeat("nhắc tôi họp mỗi thứ 1") is None


@pytest.mark.parametrize("url", [
    "https://example.com/a;lock", "https://example.com/a,b?ID=AbC&X=Y",
    "www.example.com/a;lock", "example.com/a,b;c",
])
def test_delimiters_inside_literal_url_are_not_commands(url):
    assert split_commands(f"mở {url}") == [f"mở {url}"]
    assert split_commands(f"mở {url} rồi mở chrome") == [f"mở {url}", "mở chrome"]
    commands = NLU(model=FixedModel("system_control")).understand(f"mở {url}")
    assert len(commands) == 1
    assert commands[0]["intent"] == "open_website"
    assert commands[0]["target"] == url


def test_literal_placeholder_never_replaces_user_text_by_accident():
    text = "mở https://example.com/a,b rồi mở zzliteralz0zz"
    assert split_commands(text) == ["mở https://example.com/a,b", "mở zzliteralz0zz"]


@pytest.mark.parametrize("text,expected", [
    ("known", 0.9), ("foreign", 0.0), ("known foreign", 0.45), ("", 0.0),
])
def test_tfidf_confidence_requires_evidence_in_its_own_vocabulary(text, expected):
    class Vectorizer:
        def __init__(self):
            self.vocabulary_ = {"known": 0}

        @staticmethod
        def build_analyzer():
            return str.split

    model = FixedModel("open_website")
    model.predict_proba = lambda texts: [[0.9]]
    model.named_steps = {"tfidf": Vectorizer()}
    assert predict_intent(text, model)["confidence"] == expected


@pytest.mark.parametrize("text,intent,confidence", [
    ("v2.0", "chitchat", 0.0), ("version 1.2.3", "chitchat", 0.0),
    ("tính", "calculate", 1.0), ("15 + 27", "calculate", 1.0),
])
def test_version_number_is_not_calculation_but_explicit_math_still_is(text, intent, confidence):
    result = predict_intent(text, FixedModel("calculate"))
    assert result["intent"] == intent
    assert result["confidence"] == confidence


@pytest.mark.parametrize("text,intent,target", [
    ("google", "search_web", ""),
    ("mở youtube", "play_media", "youtube"),
    ("mở youtube.com", "open_website", "youtube.com"),
])
def test_canonical_media_and_bare_search_do_not_depend_on_classifier(text, intent, target):
    result = predict_intent(text, FixedModel("open_website"))
    assert result["intent"] == intent
    assert result["target"] == target


@pytest.mark.parametrize("text", [
    "tìm https://example.com/lock", "phát https://example.com/shutdown",
    "https://example.com/?action=restart",
])
def test_system_keyword_inside_url_never_authorizes_system_action(text):
    result = predict_intent(text, FixedModel("system_control"))
    assert result["confidence"] == 0.0
    assert NLU._judge(result) == "unknown"
