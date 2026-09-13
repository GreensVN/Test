# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nlu_advanced
from nlu_advanced import ContextMemory, NLU, smart_normalize, split_commands


def test_smart_normalize_restores_diacritics():
    assert smart_normalize("mo chrome len") == "mở chrome lên"


def test_smart_normalize_expands_teencode():
    assert "google" in smart_normalize("bat gg giup toi")


def test_smart_normalize_fixes_light_typo():
    result = smart_normalize("mo chorme ra di")
    assert "chrome" in result


def test_split_commands_splits_on_roi():
    parts = split_commands("mở chrome rồi phát nhạc trữ tình")
    assert len(parts) == 2
    assert parts[0] == "mở chrome"
    assert "phát nhạc" in parts[1]


def test_split_commands_keeps_reminder_sentences_whole():
    """Câu nhắc nhở / tìm kiếm không được tách dù có từ nối bên trong, để
    không cắt nhầm nội dung công việc."""
    text = "nhắc tôi họp và gọi khách hàng lúc 3 giờ"
    assert split_commands(text) == [text]


def test_split_commands_returns_original_when_no_separator():
    text = "mở chrome"
    assert split_commands(text) == [text]


def test_context_memory_remembers_last_target():
    ctx = ContextMemory()
    ctx.remember({"intent": "open_website", "target": "google"})
    assert ctx.last_target == "google"


def test_context_memory_resolves_anaphora():
    ctx = ContextMemory()
    ctx.remember({"intent": "open_website", "target": "google"})
    assert ctx.resolve("đóng nó lại") == "đóng google lại"


def test_context_memory_ignores_sentinel_targets():
    ctx = ContextMemory()
    ctx.remember({"intent": "get_datetime", "target": "time"})
    assert ctx.last_target is None


def test_context_memory_clear_resets_history():
    ctx = ContextMemory()
    ctx.remember({"intent": "open_website", "target": "google"})
    ctx.clear()
    assert ctx.last_target is None


def test_dangerous_targets_loaded_from_config():
    assert "shutdown" in nlu_advanced.DANGEROUS_TARGETS
    assert "restart" in nlu_advanced.DANGEROUS_TARGETS


def test_nlu_judge_low_confidence_asks():
    result = {"confidence": 0.30, "target": "google"}
    assert NLU._judge(result) == "low_confidence"


def test_nlu_judge_very_low_confidence_is_unknown():
    result = {"confidence": 0.05, "target": "google"}
    assert NLU._judge(result) == "unknown"


def test_nlu_judge_dangerous_target_needs_confirm():
    # intent phải là system_control thì mới cần xác nhận (v6 làm chặt hơn v5
    # để tránh hỏi xác nhận nhầm lẫm với các intent khác có từ 'shutdown').
    result = {"intent": "system_control", "confidence": 0.95, "target": "shutdown"}
    assert NLU._judge(result) == "need_confirm"


def test_nlu_judge_high_confidence_is_ok():
    result = {"confidence": 0.9, "target": "google"}
    assert NLU._judge(result) == "ok"


def test_nlu_understand_multi_command():
    nlu = NLU()
    results = nlu.understand("mở chrome rồi phát nhạc trữ tình")
    assert len(results) == 2
    assert results[0]["intent"] == "open_app"


def test_nlu_confirm_message_mentions_target():
    nlu = NLU()
    msg = nlu.confirm_message({"intent": "open_app", "target": "chrome"})
    assert "chrome" in msg
