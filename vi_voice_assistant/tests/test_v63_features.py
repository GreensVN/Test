"""
Test cho các nâng cấp HỖ TRỢ HỆ ĐIỀU HÀNH của bản v6.3:

  1. Phát hiện WSL (is_wsl) - trước đây WSL bị nhận nhầm là Linux thuần nên
     tắt máy/âm lượng/mở web... âm thầm thất bại (không có systemctl/pactl/
     xdg-open thật); v6.3 chuyển tiếp sang Windows host qua interop.
  2. Phân biệt Windows 10 / Windows 11 (trước đây gộp chung "Windows 10/11").
  3. Nhận diện desktop Linux (linux_desktop) + dò lệnh có sẵn (has_command).
  4. Báo cáo khả năng của máy (capability_report / format_capability_report)
     - dùng bởi cờ --sysinfo và lệnh "he thong".
  5. Linux: chuỗi dự phòng mới (wpctl cho PipeWire, qdbus cho KDE, thêm
     spectacle/grim/import cho chụp màn hình).
  6. WSL: chuyển tiếp lệnh hệ thống / mở URL / TTS sang Windows host.
  7. Cờ --sysinfo của main.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import executor
import main
import platform_utils
import tts


# ----------------------------------------------------------------------------
# 1. PHÁT HIỆN WSL
# ----------------------------------------------------------------------------
def test_is_wsl_false_on_windows(monkeypatch):
    monkeypatch.setattr(platform_utils, "SYSTEM", "Windows")
    assert platform_utils.is_wsl() is False


def test_is_wsl_detects_env_marker(monkeypatch):
    monkeypatch.setattr(platform_utils, "SYSTEM", "Linux")
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    assert platform_utils.is_wsl() is True


def test_is_wsl_detects_microsoft_kernel(monkeypatch):
    monkeypatch.setattr(platform_utils, "SYSTEM", "Linux")
    monkeypatch.setenv("WSL_DISTRO_NAME", "")
    monkeypatch.setenv("WSL_INTEROP", "")
    monkeypatch.setattr(platform_utils, "_read_osrelease",
                        lambda: "5.15.90.1-microsoft-standard-WSL2")
    assert platform_utils.is_wsl() is True


def test_is_wsl_false_on_plain_linux(monkeypatch):
    monkeypatch.setattr(platform_utils, "SYSTEM", "Linux")
    monkeypatch.setenv("WSL_DISTRO_NAME", "")
    monkeypatch.setenv("WSL_INTEROP", "")
    monkeypatch.setattr(platform_utils, "_read_osrelease",
                        lambda: "6.5.0-15-generic")
    assert platform_utils.is_wsl() is False


# ----------------------------------------------------------------------------
# 2. PHÂN BIỆT WINDOWS 10 / 11
# ----------------------------------------------------------------------------
def test_windows_11_label(monkeypatch):
    monkeypatch.setattr(platform_utils, "SYSTEM", "Windows")
    monkeypatch.setattr(platform_utils.platform, "win32_ver",
                        lambda: ("11", "10.0.22631", "", ""))
    assert platform_utils.windows_version_label() == "Windows 11"


def test_windows_10_label(monkeypatch):
    monkeypatch.setattr(platform_utils, "SYSTEM", "Windows")
    monkeypatch.setattr(platform_utils.platform, "win32_ver",
                        lambda: ("10", "10.0.19045", "", ""))
    assert platform_utils.windows_version_label() == "Windows 10"


# ----------------------------------------------------------------------------
# 3. DESKTOP LINUX + DÒ LỆNH
# ----------------------------------------------------------------------------
def test_linux_desktop_from_env(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "ubuntu:GNOME")
    assert platform_utils.linux_desktop() == "gnome"
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    assert platform_utils.linux_desktop() == "kde"


def test_has_command():
    assert platform_utils.has_command(sys.executable) or platform_utils.has_command("python3")
    assert platform_utils.has_command("lenh_khong_ton_tai_xyz_123") is False


# ----------------------------------------------------------------------------
# 4. BÁO CÁO KHẢ NĂNG CỦA MÁY
# ----------------------------------------------------------------------------
def test_capability_report_structure():
    report = platform_utils.capability_report()
    assert report["os"] in ("Windows", "Darwin", "Linux")
    assert report["python"]
    assert report.get("features")
    for info in report["features"].values():
        assert set(info) == {"ok", "via"}
        assert isinstance(info["ok"], bool)
        assert info["via"]
    # Model nhẹ thuần Python luôn chạy được trên mọi hệ điều hành
    assert report["features"]["nlu_lite"]["ok"] is True


def test_format_capability_report_content():
    text = platform_utils.format_capability_report(platform_utils.capability_report())
    assert "Hệ điều hành" in text
    assert "TÍNH NĂNG" in text
    assert "nlu_lite" in text


# ----------------------------------------------------------------------------
# 5. LINUX: CHUỖI DỰ PHÒNG MỚI
# ----------------------------------------------------------------------------
def test_linux_volume_tries_wpctl_first(monkeypatch):
    calls = []
    monkeypatch.setattr(executor, "SYSTEM", "Linux")
    monkeypatch.setattr(executor, "is_wsl", lambda: False)

    def fake_popen(cmd, *a, **k):
        calls.append(cmd)
        if cmd[0] == "wpctl":
            raise FileNotFoundError("wpctl")  # giả lập máy chưa có PipeWire

    monkeypatch.setattr(executor.subprocess, "Popen", fake_popen)
    assert executor.action_system_control("volume_up") is True
    assert calls[0][0] == "wpctl"
    assert calls[1][0] == "pactl"


def test_linux_lock_includes_qdbus(monkeypatch):
    calls = []
    monkeypatch.setattr(executor, "SYSTEM", "Linux")
    monkeypatch.setattr(executor, "is_wsl", lambda: False)

    def fake_popen(cmd, *a, **k):
        calls.append(cmd)
        raise FileNotFoundError(cmd[0])  # giả lập máy không có lệnh nào

    monkeypatch.setattr(executor.subprocess, "Popen", fake_popen)
    assert executor.action_system_control("lock") is False
    tools = [c[0] for c in calls]
    assert tools[0] == "loginctl"
    assert "qdbus" in tools


def test_linux_screenshot_fallback_chain(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(executor, "SYSTEM", "Linux")
    monkeypatch.setattr(executor, "is_wsl", lambda: False)
    monkeypatch.setattr(executor, "HOME", str(tmp_path))

    def fake_popen(cmd, *a, **k):
        calls.append(cmd)
        if cmd[0] != "grim":
            raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(executor.subprocess, "Popen", fake_popen)
    assert executor.action_system_control("screenshot") is True
    tools = [c[0] for c in calls]
    assert tools == ["gnome-screenshot", "spectacle", "scrot", "grim"]


# ----------------------------------------------------------------------------
# 6. WSL: CHUYỂN TIẾP SANG WINDOWS HOST
# ----------------------------------------------------------------------------
def test_wsl_lock_routes_to_windows_host(monkeypatch):
    calls = []
    monkeypatch.setattr(executor, "SYSTEM", "Linux")
    monkeypatch.setattr(executor, "is_wsl", lambda: True)
    monkeypatch.setattr(executor.subprocess, "Popen",
                        lambda cmd, *a, **k: calls.append(cmd))
    assert executor.action_system_control("lock") is True
    assert calls and calls[0][0] == "rundll32.exe"


def test_wsl_shutdown_uses_windows_exe(monkeypatch):
    calls = []
    monkeypatch.setattr(executor, "SYSTEM", "Linux")
    monkeypatch.setattr(executor, "is_wsl", lambda: True)
    monkeypatch.setattr(executor, "DANGEROUS_ACTIONS", set())  # bỏ hỏi xác nhận trong test
    monkeypatch.setattr(executor.subprocess, "Popen",
                        lambda cmd, *a, **k: calls.append(cmd))
    assert executor.action_system_control("shutdown") is True
    assert calls[0][0] == "shutdown.exe"
    assert "/s" in calls[0]


def test_open_url_uses_wslview_on_wsl(monkeypatch):
    calls = []
    monkeypatch.setattr(executor, "SYSTEM", "Linux")
    monkeypatch.setattr(executor, "is_wsl", lambda: True)
    monkeypatch.setattr(executor.subprocess, "Popen",
                        lambda cmd, *a, **k: calls.append(cmd))
    monkeypatch.setattr(executor.webbrowser, "open", lambda url: False)
    assert executor._open_url("https://example.com") is True
    assert calls[0][0] == "wslview"


def test_open_url_falls_back_to_webbrowser(monkeypatch):
    opened = []
    monkeypatch.setattr(executor, "SYSTEM", "Linux")
    monkeypatch.setattr(executor, "is_wsl", lambda: False)
    monkeypatch.setattr(executor.webbrowser, "open",
                        lambda url: opened.append(url) or True)
    assert executor._open_url("https://example.com") is True
    assert opened == ["https://example.com"]


# ----------------------------------------------------------------------------
# 6B. TTS QUA WSL
# ----------------------------------------------------------------------------
def test_tts_sapi_available_via_wsl(monkeypatch):
    calls = []
    monkeypatch.setattr(tts, "SYSTEM", "Linux")
    monkeypatch.setattr(tts, "is_wsl", lambda: True)
    monkeypatch.setattr(tts.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    assert tts._speak_sapi("xin chào") is True
    assert calls[0][0] == "powershell.exe"


def test_tts_sapi_not_used_on_plain_linux(monkeypatch):
    monkeypatch.setattr(tts, "SYSTEM", "Linux")
    monkeypatch.setattr(tts, "is_wsl", lambda: False)
    assert tts._speak_sapi("xin chào") is False


# ----------------------------------------------------------------------------
# 7. CỜ --sysinfo
# ----------------------------------------------------------------------------
def test_sysinfo_flag_exits_zero_and_prints_report(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py", "--sysinfo"])
    assert main.main() == 0
    captured = capsys.readouterr()
    assert "Hệ điều hành" in captured.out
    assert "TÍNH NĂNG" in captured.out
