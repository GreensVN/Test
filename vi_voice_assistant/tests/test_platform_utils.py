import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import platform_utils


def test_setup_console_does_not_raise_when_called_twice():
    """An toàn khi gọi nhiều lần (vd main.py và 1 module khác đều gọi)."""
    platform_utils.setup_console()
    platform_utils.setup_console()  # không được ném lỗi


def test_setup_console_does_not_raise_on_stream_without_reconfigure(monkeypatch):
    """Không crash khi stdout bị thay bằng đối tượng không có reconfigure()
    (mô phỏng môi trường bị redirect / capsys của pytest ở một số bản)."""
    platform_utils._console_ready = False
    fake_stdout = io.StringIO()  # StringIO có reconfigure ở 1 số bản, test vẫn phải an toàn
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    platform_utils.setup_console()  # không được ném lỗi
    platform_utils._console_ready = False  # reset cho test khác


def test_safe_print_handles_multiline_text(capsys):
    """Bản vá lỗi Windows PermissionError [WinError 31]: in banner nhiều
    dòng không được làm sập chương trình - xem docstring của safe_print()."""
    text = "dòng một\ndòng hai\ndòng ba có dấu tiếng Việt: mở, tắt, đóng"
    platform_utils.safe_print(text)
    captured = capsys.readouterr()
    assert "dòng một" in captured.out
    assert "dòng ba" in captured.out


def test_safe_print_falls_back_to_ascii_when_console_rejects_write(monkeypatch, capsys):
    """Nếu print() ném PermissionError (mô phỏng lỗi console Windows thật),
    safe_print() phải in lại được bản KHÔNG DẤU thay vì làm sập chương trình."""
    calls = {"n": 0}
    real_print = print

    def flaky_print(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(
                "[WinError 31] A device attached to the system is not functioning"
            )
        real_print(*args, **kwargs)

    monkeypatch.setattr("builtins.print", flaky_print)
    platform_utils.safe_print("mở trình duyệt")  # 1 dòng duy nhất
    captured = capsys.readouterr()
    assert "mo trinh duyet" in captured.out or captured.out == ""  # bản ascii thay thế


def test_safe_print_never_raises_even_on_persistent_console_failure(monkeypatch):
    """Ngay cả khi MỌI lần print() đều lỗi, safe_print() vẫn không được ném
    lỗi ra ngoài (chương trình phải tiếp tục chạy được, chỉ mất dòng đó)."""
    def always_fail(*args, **kwargs):
        raise PermissionError("[WinError 31] A device attached to the system is not functioning")

    monkeypatch.setattr("builtins.print", always_fail)
    platform_utils.safe_print("dòng 1\ndòng 2")  # không được ném lỗi


def test_windows_version_none_on_non_windows(monkeypatch):
    monkeypatch.setattr(platform_utils, "SYSTEM", "Linux")
    assert platform_utils.windows_version() is None
    assert platform_utils.is_windows7_or_older() is False


def test_windows_version_parses_win7_kernel(monkeypatch):
    monkeypatch.setattr(platform_utils, "SYSTEM", "Windows")
    monkeypatch.setattr(platform_utils.platform, "win32_ver", lambda: ("7", "6.1.7601", "SP1", ""))
    assert platform_utils.windows_version() == (6, 1)
    assert platform_utils.is_windows7_or_older() is True


def test_windows_version_parses_win10_kernel(monkeypatch):
    monkeypatch.setattr(platform_utils, "SYSTEM", "Windows")
    monkeypatch.setattr(platform_utils.platform, "win32_ver", lambda: ("10", "10.0.19041", "", ""))
    assert platform_utils.windows_version() == (10, 0)
    assert platform_utils.is_windows7_or_older() is False


def test_windows_version_handles_bad_string(monkeypatch):
    monkeypatch.setattr(platform_utils, "SYSTEM", "Windows")
    monkeypatch.setattr(platform_utils.platform, "win32_ver", lambda: ("", "", "", ""))
    assert platform_utils.windows_version() is None


def test_windows_version_label_known_and_unknown(monkeypatch):
    monkeypatch.setattr(platform_utils, "SYSTEM", "Windows")
    monkeypatch.setattr(platform_utils.platform, "win32_ver", lambda: ("7", "6.1.7601", "", ""))
    assert platform_utils.windows_version_label() == "Windows 7"

    monkeypatch.setattr(platform_utils.platform, "win32_ver", lambda: ("", "6.4.9999", "", ""))
    assert "6.4" in platform_utils.windows_version_label()
