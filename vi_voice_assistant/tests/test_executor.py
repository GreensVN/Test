import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import executor


def _raise_file_not_found(*args, **kwargs):
    raise FileNotFoundError()


# ----------------------------------------------------------------------------
# _best_match
# ----------------------------------------------------------------------------
def test_best_match_exact():
    value, key = executor._best_match("google", {"google": "https://google.com"})
    assert value == "https://google.com"
    assert key == "google"


def test_best_match_no_diacritics():
    mapping = {"google dich": "https://translate.google.com"}
    value, _ = executor._best_match("google dịch", mapping)
    assert value == "https://translate.google.com"


def test_best_match_fuzzy_typo():
    mapping = {"youtube": "https://youtube.com"}
    value, _ = executor._best_match("youtub", mapping)
    assert value == "https://youtube.com"


def test_best_match_rejects_unrelated():
    mapping = {"youtube": "https://youtube.com", "github": "https://github.com"}
    value, _ = executor._best_match("một chuỗi hoàn toàn không liên quan gì cả", mapping)
    assert value is None


def test_best_match_fuzzy_false_skips_fuzzy_matching():
    mapping = {"youtube": "https://youtube.com"}
    value, key = executor._best_match("youtub", mapping, fuzzy=False)
    assert value is None
    assert key is None


def test_best_match_falls_back_to_difflib_when_rapidfuzz_unavailable(monkeypatch):
    monkeypatch.setattr(executor, "_RAPIDFUZZ_AVAILABLE", False)
    mapping = {"youtube": "https://youtube.com"}
    value, key = executor._best_match("youtub", mapping)
    assert value == "https://youtube.com"
    assert key == "youtube"


def test_best_match_difflib_fallback_rejects_unrelated(monkeypatch):
    monkeypatch.setattr(executor, "_RAPIDFUZZ_AVAILABLE", False)
    mapping = {"youtube": "https://youtube.com", "github": "https://github.com"}
    value, _ = executor._best_match("một chuỗi hoàn toàn không liên quan gì cả", mapping)
    assert value is None


# ----------------------------------------------------------------------------
# open_website
# ----------------------------------------------------------------------------
def test_action_open_website_uses_mapped_url(monkeypatch):
    opened = {}
    monkeypatch.setattr(executor.webbrowser, "open", lambda url: opened.setdefault("url", url))
    assert executor.action_open_website("google") is True
    assert opened["url"] == "https://www.google.com"


def test_action_open_website_google_search_encodes_special_characters(monkeypatch):
    opened = {}
    monkeypatch.setattr(executor.webbrowser, "open", lambda url: opened.setdefault("url", url))
    ok = executor.action_open_website("ao khoac & giay adidas")
    assert ok is True
    assert "q=ao+khoac+%26+giay+adidas" in opened["url"]
    assert "&" not in opened["url"].split("q=", 1)[1]


def test_action_open_website_recognizes_domain_with_path(monkeypatch):
    opened = {}
    monkeypatch.setattr(executor.webbrowser, "open", lambda url: opened.setdefault("url", url))
    ok = executor.action_open_website("github.com/anthropics/claude")
    assert ok is True
    assert opened["url"] == "https://github.com/anthropics/claude"


def test_action_open_website_rejects_fake_http_prefix(monkeypatch):
    opened = {}
    monkeypatch.setattr(executor.webbrowser, "open", lambda url: opened.setdefault("url", url))
    ok = executor.action_open_website("httpxyz khong phai url that")
    assert ok is True
    assert opened["url"].startswith("https://www.google.com/search?q=")


def test_action_open_website_accepts_real_http_scheme(monkeypatch):
    opened = {}
    monkeypatch.setattr(executor.webbrowser, "open", lambda url: opened.setdefault("url", url))
    ok = executor.action_open_website("http://example.com")
    assert ok is True
    assert opened["url"] == "http://example.com"


# ----------------------------------------------------------------------------
# open_app (whitelist bảo mật + đa nền tảng)
# ----------------------------------------------------------------------------
def test_action_open_app_rejects_unwhitelisted_app(capsys):
    ok = executor.action_open_app("ung_dung_khong_ton_tai_xyz")
    assert ok is False
    captured = capsys.readouterr()
    assert "TỪ CHỐI" in captured.out


def test_app_map_for_platform_picks_correct_map(monkeypatch):
    monkeypatch.setattr(executor, "SYSTEM", "Windows")
    assert executor._app_map_for_platform() is executor.CONFIG["app_map_windows"]
    monkeypatch.setattr(executor, "SYSTEM", "Darwin")
    assert executor._app_map_for_platform() is executor.CONFIG["app_map_macos"]
    monkeypatch.setattr(executor, "SYSTEM", "Linux")
    assert executor._app_map_for_platform() is executor.CONFIG["app_map_linux"]


def test_action_open_app_uses_macos_map_on_darwin(monkeypatch):
    monkeypatch.setattr(executor, "SYSTEM", "Darwin")
    calls = {}
    monkeypatch.setattr(executor.subprocess, "Popen", lambda cmd: calls.setdefault("cmd", cmd))
    ok = executor.action_open_app("chrome")
    assert ok is True
    assert calls["cmd"] == ["open", "-a", "Google Chrome"]


def test_action_open_app_uses_linux_map_and_splits_args(monkeypatch):
    monkeypatch.setattr(executor, "SYSTEM", "Linux")
    calls = {}
    monkeypatch.setattr(executor.subprocess, "Popen", lambda cmd: calls.setdefault("cmd", cmd))
    ok = executor.action_open_app("word")
    assert ok is True
    assert calls["cmd"] == ["libreoffice", "--writer"]


def test_action_open_app_reports_missing_linux_command(monkeypatch, capsys):
    monkeypatch.setattr(executor, "SYSTEM", "Linux")
    monkeypatch.setattr(executor.subprocess, "Popen", _raise_file_not_found)
    ok = executor.action_open_app("chrome")
    assert ok is False
    captured = capsys.readouterr()
    assert "Không tìm thấy lệnh" in captured.out


def test_action_open_app_rejects_uwp_app_on_windows7(monkeypatch, capsys):
    monkeypatch.setattr(executor, "SYSTEM", "Windows")
    monkeypatch.setitem(executor.CONFIG["app_map_windows"], "camera", "microsoft.windows.camera:")
    monkeypatch.setattr(executor, "is_windows7_or_older", lambda: True)
    monkeypatch.setattr(executor, "windows_version_label", lambda: "Windows 7")
    ok = executor.action_open_app("camera")
    assert ok is False
    captured = capsys.readouterr()
    assert "Store App" in captured.out
    assert "Windows 7" in captured.out


def test_action_open_app_allows_uwp_app_on_windows10(monkeypatch):
    monkeypatch.setitem(executor.CONFIG["app_map_windows"], "camera", "microsoft.windows.camera:")
    monkeypatch.setattr(executor, "is_windows7_or_older", lambda: False)
    monkeypatch.setattr(executor, "SYSTEM", "Windows")
    monkeypatch.setattr(executor.subprocess, "Popen", lambda *a, **k: None)
    ok = executor.action_open_app("camera")
    assert ok is True


# ----------------------------------------------------------------------------
# open_file
# ----------------------------------------------------------------------------
def test_action_open_file_rejects_unsafe_characters(capsys):
    ok = executor.action_open_file("file; rm -rf ~ #")
    assert ok is False


# ----------------------------------------------------------------------------
# system_control (đa nền tảng)
# ----------------------------------------------------------------------------
def test_volume_via_pycaw_returns_none_when_not_installed():
    assert executor._volume_via_pycaw("mute") is None


def test_action_system_control_macos_shutdown(monkeypatch):
    monkeypatch.setattr(executor, "SYSTEM", "Darwin")
    monkeypatch.setattr("builtins.input", lambda _: "y")
    calls = {}
    monkeypatch.setattr(executor.subprocess, "Popen", lambda cmd: calls.setdefault("cmd", cmd))
    ok = executor.action_system_control("shutdown")
    assert ok is True
    assert calls["cmd"][0] == "osascript"


def test_action_system_control_macos_volume_mute(monkeypatch):
    monkeypatch.setattr(executor, "SYSTEM", "Darwin")
    calls = {}
    monkeypatch.setattr(executor.subprocess, "Popen", lambda cmd: calls.setdefault("cmd", cmd))
    ok = executor.action_system_control("mute")
    assert ok is True
    assert "muted true" in calls["cmd"][-1]


def test_action_system_control_linux_uses_systemctl(monkeypatch):
    monkeypatch.setattr(executor, "SYSTEM", "Linux")
    # v6.3: ép KHÔNG phải WSL để test chạy đúng cả khi ai đó chạy test trên WSL
    monkeypatch.setattr(executor, "is_wsl", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _: "y")
    calls = []
    monkeypatch.setattr(executor.subprocess, "Popen", lambda cmd: calls.append(cmd))
    ok = executor.action_system_control("restart")
    assert ok is True
    assert calls[0] == ["systemctl", "reboot"]


def test_action_system_control_linux_falls_back_when_systemctl_missing(monkeypatch):
    monkeypatch.setattr(executor, "SYSTEM", "Linux")
    monkeypatch.setattr(executor, "is_wsl", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _: "y")
    calls = []

    def fake_popen(cmd):
        if cmd[0] == "systemctl":
            raise FileNotFoundError()
        calls.append(cmd)

    monkeypatch.setattr(executor.subprocess, "Popen", fake_popen)
    ok = executor.action_system_control("restart")
    assert ok is True
    assert calls == [["shutdown", "-r", "now"]]


def test_action_system_control_linux_volume_via_pactl(monkeypatch):
    """v6.3: wpctl (PipeWire) được thử TRƯỚC pactl - test này giả lập máy chỉ
    có pactl (không có wpctl) để bảo toàn đường dự phòng PulseAudio."""
    monkeypatch.setattr(executor, "SYSTEM", "Linux")
    monkeypatch.setattr(executor, "is_wsl", lambda: False)
    calls = []

    def fake_popen(cmd):
        if cmd[0] == "wpctl":
            raise FileNotFoundError("wpctl")
        calls.append(cmd)

    monkeypatch.setattr(executor.subprocess, "Popen", fake_popen)
    ok = executor.action_system_control("volume_up")
    assert ok is True
    assert calls[0][0] == "pactl"


def test_action_system_control_linux_reports_when_no_tool_available(monkeypatch, capsys):
    monkeypatch.setattr(executor, "SYSTEM", "Linux")
    monkeypatch.setattr(executor, "is_wsl", lambda: False)
    monkeypatch.setattr(executor.subprocess, "Popen", _raise_file_not_found)
    ok = executor.action_system_control("lock")
    assert ok is False
    captured = capsys.readouterr()
    assert "Không tìm thấy" in captured.out


# ----------------------------------------------------------------------------
# execute_command: ngưỡng tự tin, JSON string, giữ hoa/thường, lệnh nguy hiểm
# ----------------------------------------------------------------------------
def test_execute_command_rejects_low_confidence(capsys):
    result = {"intent": "system_control", "target": "shutdown", "confidence": 0.1}
    ok = executor.execute_command(result)
    assert ok is False
    captured = capsys.readouterr()
    assert "TỪ CHỐI" in captured.out


def test_execute_command_unknown_intent_label_falls_back_gracefully(capsys):
    """Nếu intent không nằm trong 11 nhãn đã huấn luyện (vd dữ liệu hỏng /
    tích hợp lỗi), execute_command() không được crash mà phải từ chối lịch
    sự qua action_unknown()."""
    result = {"intent": "some_unknown_label", "target": "", "confidence": 0.99}
    ok = executor.execute_command(result)
    assert ok is False
    captured = capsys.readouterr()
    assert "TỪ CHỐI" in captured.out


def test_execute_command_accepts_json_string(monkeypatch):
    monkeypatch.setattr(executor.webbrowser, "open", lambda url: True)
    ok = executor.execute_command(
        '{"intent": "open_website", "target": "google", "confidence": 0.9}'
    )
    assert ok is True


def test_dangerous_action_requires_confirmation(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    result = {"intent": "system_control", "target": "shutdown", "confidence": 0.9}
    ok = executor.execute_command(result)
    assert ok is False


def test_execute_command_preserves_case_for_website_target(monkeypatch):
    opened = {}
    monkeypatch.setattr(executor.webbrowser, "open", lambda url: opened.setdefault("url", url))
    result = {
        "intent": "open_website",
        "target": "https://youtube.com/watch?v=dQw4w9WgXcQ",
        "confidence": 0.9,
    }
    ok = executor.execute_command(result)
    assert ok is True
    assert opened["url"] == "https://youtube.com/watch?v=dQw4w9WgXcQ"


def test_execute_command_preserves_case_for_file_target(monkeypatch):
    called = {}

    def fake_open_path(p):
        called["path"] = p
        return True

    monkeypatch.setattr(executor, "_open_path", fake_open_path)
    result = {"intent": "open_file", "target": "/Home/User/MyReport.PDF", "confidence": 0.9}
    ok = executor.execute_command(result)
    assert ok is True
    assert called["path"] == "/Home/User/MyReport.PDF"


# ----------------------------------------------------------------------------
# CÁC TEST MỚI: 7 intent "phản hồi hội thoại" thêm từ bản nhiều tính năng
# ----------------------------------------------------------------------------
def test_action_search_web_opens_google(monkeypatch):
    opened = {}
    monkeypatch.setattr(executor.webbrowser, "open", lambda url: opened.setdefault("url", url))
    ok = executor.action_search_web("giá vàng hôm nay")
    assert ok is True
    assert "google.com/search?q=" in opened["url"]


def test_action_search_web_asks_when_empty():
    ok = executor.action_search_web("")
    assert ok is False


def test_action_play_media_opens_youtube_search(monkeypatch):
    opened = {}
    monkeypatch.setattr(executor.webbrowser, "open", lambda url: opened.setdefault("url", url))
    ok = executor.action_play_media("nhạc trữ tình")
    assert ok is True
    assert "youtube.com/results?search_query=" in opened["url"]


def test_action_get_weather_opens_search(monkeypatch):
    opened = {}
    monkeypatch.setattr(executor.webbrowser, "open", lambda url: opened.setdefault("url", url))
    ok = executor.action_get_weather("đà nẵng")
    assert ok is True
    assert (
        "thời tiết" in opened["url"]
        or "th%E1%BB%9Di" in opened["url"]
        or "google.com/search" in opened["url"]
    )


def test_action_get_datetime_time(capsys):
    ok = executor.action_get_datetime("time")
    assert ok is True
    captured = capsys.readouterr()
    assert "Bây giờ là" in captured.out


def test_action_get_datetime_date(capsys):
    ok = executor.action_get_datetime("date")
    assert ok is True
    captured = capsys.readouterr()
    assert "Hôm nay là" in captured.out


def test_action_calculate_uses_precomputed_result(capsys):
    ok = executor.action_calculate("15 + 27", {"result": 42})
    assert ok is True
    captured = capsys.readouterr()
    assert "42" in captured.out


def test_action_calculate_recomputes_when_missing(capsys):
    ok = executor.action_calculate("12 cộng 8 bằng bao nhiêu", {})
    assert ok is True
    captured = capsys.readouterr()
    assert "20" in captured.out


def test_action_calculate_graceful_when_uncomputable(capsys):
    # v6.2: "một cộng một" giờ TÍNH ĐƯỢC (=2) nhờ hỗ trợ số viết bằng chữ,
    # nên đổi sang trường hợp thật sự không tính được: căn bậc hai của số âm.
    ok = executor.action_calculate("căn bậc hai của -5", {"result": None})
    assert ok is False
    captured = capsys.readouterr()
    assert "chưa tính được" in captured.out


def test_action_chitchat_matches_greeting(capsys):
    ok = executor.action_chitchat("xin chào")
    assert ok is True
    captured = capsys.readouterr()
    assert "[TRỢ LÝ]" in captured.out


def test_action_chitchat_falls_back_when_unmatched(capsys):
    ok = executor.action_chitchat("một câu hoàn toàn ngẫu nhiên không khớp mẫu nào")
    assert ok is True
    captured = capsys.readouterr()
    assert "chưa hiểu" in captured.out


def test_action_set_reminder_delay_schedules_timer(monkeypatch, tmp_path):
    # v6.2: trỏ REMINDERS_PATH sang thư mục tạm - trước đây test này ghi thẳng
    # vào reminders.json THẬT của dự án, làm bẩn thư mục mã nguồn.
    monkeypatch.setattr(executor, "REMINDERS_PATH", str(tmp_path / "rem.json"))
    before = len(executor.ACTIVE_REMINDERS)
    ok = executor.action_set_reminder("uống nước", {"time": {"type": "delay", "minutes": 5}})
    assert ok is True
    assert len(executor.ACTIVE_REMINDERS) == before + 1
    reminder = executor.ACTIVE_REMINDERS[-1]
    assert reminder["task"] == "uống nước"
    reminder["timer"].cancel()  # dọn dẹp, không đợi thật
    executor.ACTIVE_REMINDERS.remove(reminder)


def test_action_set_reminder_asks_when_no_time():
    ok = executor.action_set_reminder("họp nhóm", {"time": {"type": None}})
    assert ok is False


def test_execute_command_routes_calculate_intent_with_data(monkeypatch, capsys):
    result = {"intent": "calculate", "target": "15 + 27", "confidence": 0.9, "result": 42}
    ok = executor.execute_command(result)
    assert ok is True
    captured = capsys.readouterr()
    assert "42" in captured.out


def test_execute_command_confidence_threshold_applies_to_chitchat():
    """Ngưỡng độ tự tin áp dụng ĐỀU cho cả 11 intent, kể cả chitchat (không
    còn ngoại lệ nào giống nhãn 'unknown' cũ)."""
    result = {"intent": "chitchat", "target": "xin chào", "confidence": 0.01}
    ok = executor.execute_command(result)
    assert ok is False


def test_respond_prints_assistant_prefix(capsys):
    executor.respond("Đang mở Chrome")
    captured = capsys.readouterr()
    assert "[TRỢ LÝ] Đang mở Chrome" in captured.out


def test_speak_disabled_by_default():
    """SPEAK_ENABLED phải mặc định False để không phát âm thanh ngoài ý muốn
    trong môi trường test/script tự động."""
    assert executor.SPEAK_ENABLED is False
