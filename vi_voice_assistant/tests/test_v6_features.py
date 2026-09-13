# -*- coding: utf-8 -*-
"""
Test cho TOÀN BỘ tính năng mới của bản v6.

Nhóm kiểm tra:
  1. Lite model thuần Python (chạy được khi không có scikit-learn)
  2. Chặn "bom luỹ thừa" trong _safe_eval
  3. Toán tử "mũ" bằng lời nói
  4. Chặn mở file thực thi (.exe/.bat/...) trong action_open_file
  5. Nhắc nhở: lưu ra đĩa, khôi phục khi mở lại app, huỷ theo từ khoá
  6. Tách địa điểm thời tiết (kể cả câu gõ không dấu)
  7. Giữ nguyên URL (dấu ?, =, &, hoa/thường) xuyên qua tầng NLU
  8. Chế độ dòng lệnh --once / --json (main.run_once)
  9. describe_engine / reload_config / set_speech_enabled
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import executor
import main
import phobert_model
import tts
from intent_model import (
    _safe_eval,
    describe_engine,
    extract_entity,
    parse_math_expression,
)
from lite_model import load_lite_model, save_lite_model, train_lite_model
from nlu_advanced import NLU


# ----------------------------------------------------------------------------
# FIXTURES
# ----------------------------------------------------------------------------
@pytest.fixture(scope="module")
def lite_model():
    # Huấn luyện mới mỗi lần chạy test: nhanh (< 1 giây) và không phụ thuộc
    # file .pkl có sẵn trên máy.
    return train_lite_model(show_report=False)


@pytest.fixture(scope="module")
def nlu():
    return NLU()


# ----------------------------------------------------------------------------
# 1. LITE MODEL
# ----------------------------------------------------------------------------
def test_lite_model_predicts_common_commands(lite_model):
    # predict_one trả về tuple (nhãn, độ tự tin).
    assert lite_model.predict_one("Bật Google lên")[0] == "open_website"
    assert lite_model.predict_one("mo youtube nghe nhac di")[0] == "play_media"
    assert lite_model.predict_one("tat may tinh di")[0] == "system_control"


def test_lite_model_garbage_falls_back_to_chitchat(lite_model):
    assert lite_model.predict_one("asdkjh qwe zxc khong lien quan gi ca")[0] == "chitchat"


def test_lite_model_probabilities_sum_to_one(lite_model):
    probs = lite_model.predict_proba_dict("mở chrome lên")
    assert abs(sum(probs.values()) - 1.0) < 1e-6
    assert set(probs) == set(lite_model.classes_)


def test_lite_model_save_load_roundtrip(lite_model, tmp_path):
    path = str(tmp_path / "lite.pkl")
    save_lite_model(lite_model, path)
    assert os.path.exists(path)
    loaded = load_lite_model(path)
    for text in ("Bật Google lên", "tat may tinh di", "mấy giờ rồi"):
        assert loaded.predict_one(text) == lite_model.predict_one(text)


# ----------------------------------------------------------------------------
# 2 + 3. TÍNH TOÁN AN TOÀN
# ----------------------------------------------------------------------------
def test_safe_eval_allows_reasonable_power():
    assert _safe_eval("2**10") == 1024


def test_safe_eval_blocks_power_bomb():
    # 9**9**9 có ~369 TRIỆU chữ số - bản v5 sẽ treo cứng chương trình ở đây.
    with pytest.raises(ValueError):
        _safe_eval("9**9**9")
    with pytest.raises(ValueError):
        _safe_eval("99999999**99999")


def test_parse_math_supports_power_word():
    expr, result = parse_math_expression("2 mũ 10")
    assert result == 1024


# ----------------------------------------------------------------------------
# 4. CHẶN MỞ FILE THỰC THI
# ----------------------------------------------------------------------------
def test_open_file_refuses_executable(capsys):
    ok = executor.action_open_file("C:/Tools/setup.exe")
    assert ok is False
    captured = capsys.readouterr()
    assert "TỪ CHỐI" in captured.out


def test_open_file_refuses_batch_and_script(capsys):
    for bad in ("C:/tools/virus.bat", "C:/tools/crack.ps1", "/tmp/xóa_hết.sh"):
        assert executor.action_open_file(bad) is False
    captured = capsys.readouterr()
    assert captured.out.count("CÓ THỂ CHẠY ĐƯỢC") >= 3


def test_open_file_allows_normal_document(monkeypatch):
    opened = []
    monkeypatch.setattr(executor, "_open_path", lambda p: opened.append(p) or True)
    ok = executor.action_open_file("C:/Docs/bao_cao_thang_7.pdf")
    assert ok is True
    assert opened, "file tài liệu bình thường phải được mở"


def test_open_file_blocks_parent_traversal(capsys):
    assert executor.action_open_file("../../Windows/System32/drivers") is False


# ----------------------------------------------------------------------------
# 5. NHẮC NHỞ: LƯU / KHÔI PHỤC / HUỶ
# ----------------------------------------------------------------------------
def _future(minutes=60):
    return datetime.datetime.now() + datetime.timedelta(minutes=minutes)


def test_reminder_persists_to_disk(monkeypatch, tmp_path):
    monkeypatch.setattr(executor, "REMINDERS_PATH", str(tmp_path / "rem.json"))
    try:
        rid = executor._schedule_reminder("uống nước", _future())
        assert rid is not None
        with open(executor.REMINDERS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        assert any(item["task"] == "uống nước" for item in data)
    finally:
        executor.cancel_reminder()


def test_reminder_restore_after_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(executor, "REMINDERS_PATH", str(tmp_path / "rem.json"))
    try:
        executor._schedule_reminder("họp nhóm", _future(120))
        # Giả lập khởi động lại chương trình: danh sách trong RAM bị xoá sạch.
        for item in list(executor.ACTIVE_REMINDERS):
            item["timer"].cancel()
        executor.ACTIVE_REMINDERS.clear()
        restored = executor.restore_reminders()
        assert restored == 1
        assert executor.ACTIVE_REMINDERS[0]["task"] == "họp nhóm"
    finally:
        executor.cancel_reminder()


def test_reminder_restore_skips_expired(monkeypatch, tmp_path):
    path = tmp_path / "rem.json"
    past = (datetime.datetime.now() - datetime.timedelta(minutes=5)).isoformat()
    path.write_text(json.dumps([{"id": "x", "task": "quá hạn", "at": past}]),
                    encoding="utf-8")
    monkeypatch.setattr(executor, "REMINDERS_PATH", str(path))
    try:
        assert executor.restore_reminders() == 0
        assert not executor.ACTIVE_REMINDERS
    finally:
        executor.cancel_reminder()


def test_cancel_reminder_by_keyword(monkeypatch, tmp_path):
    monkeypatch.setattr(executor, "REMINDERS_PATH", str(tmp_path / "rem.json"))
    try:
        executor._schedule_reminder("uống nước", _future())
        executor._schedule_reminder("họp nhóm", _future())
        removed = executor.cancel_reminder("uống")
        assert len(removed) == 1
        assert removed[0]["task"] == "uống nước"
        assert len(executor.ACTIVE_REMINDERS) == 1
        # Huỷ không từ khoá = huỷ TẤT CẢ.
        assert len(executor.cancel_reminder()) == 1
        assert not executor.ACTIVE_REMINDERS
    finally:
        executor.cancel_reminder()


def test_fire_reminder_removes_itself_from_list(monkeypatch, tmp_path):
    monkeypatch.setattr(executor, "REMINDERS_PATH", str(tmp_path / "rem.json"))
    rid = executor._schedule_reminder("đứng dậy giãn cơ", _future())
    item = executor.ACTIVE_REMINDERS[-1]
    executor._fire_reminder("đứng dậy giãn cơ", rid)
    assert not executor.ACTIVE_REMINDERS
    item["timer"].cancel()  # dọn timer nền


# ----------------------------------------------------------------------------
# 6. TÁCH ĐỊA ĐIỂM THỜI TIẾT
# ----------------------------------------------------------------------------
def test_weather_location_without_diacritics():
    # Bản v5 không lọc nổi câu không dấu -> địa điểm = nguyên cả câu.
    assert extract_entity("thoi tiet da nang hom nay", "get_weather") == "da nang"


def test_weather_location_does_not_eat_da_nang():
    # "nắng" (thời tiết) và "Nẵng" (Đà Nẵng) bỏ dấu là MỘT - lọc kiểu cũ sẽ
    # xoá nhầm chính tên địa điểm.
    assert extract_entity("thời tiết Đà Nẵng hôm nay thế nào",
                          "get_weather") == "đà nẵng"


def test_weather_location_defaults_to_today():
    assert extract_entity("thời tiết thế nào", "get_weather") == "hôm nay"


# ----------------------------------------------------------------------------
# 7. GIỮ NGUYÊN URL QUA TẦNG NLU
# ----------------------------------------------------------------------------
def test_nlu_preserves_url_query_string(nlu):
    results = nlu.understand("mở youtube.com/watch?v=abc123")
    assert results
    # v6: dù model nhận intent nào, URL phải được giữ NGUYÊN VẸN ở target -
    # bản v5 băm "watch?v=abc123" thành "watch v abc123" làm hỏng liên kết.
    assert results[0]["intent"] in ("open_website", "play_media")
    assert "v=abc123" in results[0]["target"]


def test_nlu_preserves_url_case(nlu):
    results = nlu.understand("mở https://www.YouTube.com/watch?v=AbcXYZ")
    assert results
    assert "AbcXYZ" in results[0]["target"]


# ----------------------------------------------------------------------------
# 8. CHẾ ĐỘ DÒNG LỆNH --once / --json
# ----------------------------------------------------------------------------
def test_run_once_returns_zero_and_executes(nlu):
    assert main.run_once("mở google", nlu, dry_run=True) == 0


def test_run_once_json_output_is_parseable(nlu, capsys):
    code = main.run_once("mở google", nlu, dry_run=True, as_json=True)
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, list) and data
    assert data[0]["intent"] == "open_website"
    assert "confidence" in data[0] and "status" in data[0]


# ----------------------------------------------------------------------------
# 9. TIỆN ÍCH HỆ THỐNG MỚI
# ----------------------------------------------------------------------------
def test_describe_engine_names_lite_model(lite_model):
    assert "Lite" in describe_engine(lite_model)
    assert isinstance(describe_engine(), str) and describe_engine()


def test_reload_config_updates_in_place():
    before = executor.CONFIG
    cfg = executor.reload_config()
    assert cfg is before, "reload phải cập nhật TẠI CHỖ, không tạo dict mới"
    assert "website_map" in cfg
    assert "confidence_accept" in cfg  # khoá mới của v6


def test_set_speech_enabled_roundtrip():
    try:
        assert executor.set_speech_enabled(True) is True
        assert executor.SPEAK_ENABLED is True
        assert executor.set_speech_enabled(False) is False
        assert executor.SPEAK_ENABLED is False
    finally:
        executor.SPEAK_ENABLED = False


# ----------------------------------------------------------------------------
# 10. TTS: DỰ PHÒNG KHI ENGINE HỎNG GIỮA PHIÊN (v6.1)
# ----------------------------------------------------------------------------
def test_tts_falls_back_when_resolved_engine_breaks(monkeypatch):
    calls = []

    def bad_engine(text):
        calls.append(("bad", text))
        return False

    def good_engine(text):
        calls.append(("good", text))
        return True

    monkeypatch.setattr(tts, "_speak_cache", lambda t: False)
    monkeypatch.setattr(tts, "_speak_pyttsx3", bad_engine)
    monkeypatch.setattr(tts, "_speak_sapi", good_engine)
    monkeypatch.setattr(tts, "_speak_macos", lambda t: False)
    monkeypatch.setattr(tts, "_speak_gtts", lambda t: False)
    monkeypatch.setattr(tts, "_resolved_engine", bad_engine)
    monkeypatch.setattr(tts, "ENGINE", "auto")
    monkeypatch.setattr(tts, "ENABLED", True)

    tts.speak("xin chào", show=False)
    assert ("good", "xin chào") in calls
    assert tts._resolved_engine is good_engine


def test_tts_healthy_resolved_engine_is_not_retried(monkeypatch):
    calls = []

    def good_engine(text):
        calls.append(("good", text))
        return True

    def forbidden(text):
        raise AssertionError("engine đang khoẻ thì KHÔNG được thử engine khác")

    monkeypatch.setattr(tts, "_speak_cache", lambda t: False)
    monkeypatch.setattr(tts, "_speak_pyttsx3", forbidden)
    monkeypatch.setattr(tts, "_speak_sapi", forbidden)
    monkeypatch.setattr(tts, "_speak_macos", forbidden)
    monkeypatch.setattr(tts, "_speak_gtts", forbidden)
    monkeypatch.setattr(tts, "_resolved_engine", good_engine)
    monkeypatch.setattr(tts, "ENGINE", "auto")
    monkeypatch.setattr(tts, "ENABLED", True)

    tts.speak("chào buổi sáng", show=False)
    assert calls == [("good", "chào buổi sáng")]
    assert tts._resolved_engine is good_engine


def test_tts_all_engines_dead_clears_resolved(monkeypatch):
    monkeypatch.setattr(tts, "_speak_cache", lambda t: False)
    for name in ("_speak_pyttsx3", "_speak_sapi", "_speak_macos", "_speak_gtts"):
        monkeypatch.setattr(tts, name, lambda t: False)
    monkeypatch.setattr(tts, "_resolved_engine", tts._speak_pyttsx3)
    monkeypatch.setattr(tts, "ENGINE", "auto")
    monkeypatch.setattr(tts, "ENABLED", True)
    tts.speak("alo", show=False)
    assert tts._resolved_engine is None


# ----------------------------------------------------------------------------
# 11. PHOBERT: ĐƯỜNG DẪN MODEL TUYỆT ĐỐI (v6.1)
# ----------------------------------------------------------------------------
def test_phobert_model_dir_is_absolute():
    # Đường dẫn tuyệt đối -> chạy từ thư mục nào cũng tìm đúng model đã train.
    assert os.path.isabs(phobert_model.MODEL_DIR)


def test_phobert_is_trained_false_when_dir_missing(tmp_path):
    clf = phobert_model.PhoBertIntentClassifier(model_dir=str(tmp_path / "khong_co"))
    assert clf.is_trained() is False
