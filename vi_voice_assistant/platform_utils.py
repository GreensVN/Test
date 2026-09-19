"""
platform_utils.py
------------------
Tiện ích phát hiện hệ điều hành + sửa lỗi console.

v7.0 nâng cấp:
- Dùng sys.getwindowsversion() thay cho platform.win32_ver() (deprecated từ 3.10)
- Thêm type hints, dataclass cho capability report
- Tối ưu _ResilientStream, thêm thread-safety
- Thêm hàm get_python_info, is_docker, is_ci
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

SYSTEM: str = platform.system()
_console_ready: bool = False
_console_lock = threading.Lock()


class _ResilientStream:
    """
    Bọc stdout/stderr để không bao giờ ném lỗi khi ghi.
    Xử lý WinError 31 tạm thời sau khi đổi code page.
    """

    def __init__(self, stream):
        self._stream = stream
        self._lock = threading.Lock()

    def write(self, s: str) -> int:
        if not isinstance(s, str):
            s = str(s)
        with self._lock:
            for attempt in range(3):
                try:
                    # Hop dong cua write() tra ve SO KY TU da ghi. `int(None)` ma
                    # ghi tran vao day se nang TypeError - ma do lai la loi cua
                    # stream ma ta dang boc (khi test thay sys.stdout bang mot doi
                    # tuong gia), nen lay len(s) lam gia tri quy uoc.
                    written = self._stream.write(s)
                    return len(s) if written is None else int(written)
                except (OSError, ValueError, UnicodeError):
                    if attempt < 2:
                        try:
                            import time

                            time.sleep(0.02)
                        except Exception as sleep_error:
                            # Không ngủ được thì bỏ qua, nhưng PHẢI ghi lại:
                            # đây là nhánh chỉ chạy khi console lỗi, im lặng là
                            # không bao giờ truy ra nguyên nhân in thiếu ký tự.
                            logger.debug("sleep retries thất bại: %s", sleep_error)
                        continue
                    # Fallback: ascii
                    try:
                        from text_utils import strip_diacritics

                        ascii_s = strip_diacritics(s).encode(
                            "ascii", errors="replace"
                        ).decode("ascii")
                        written = self._stream.write(ascii_s)
                        return (len(ascii_s) if written is None else int(written))
                    except Exception:
                        return len(s)
        return len(s)

    def flush(self) -> None:
        try:
            with self._lock:
                self._stream.flush()
        except (OSError, ValueError):
            pass

    def close(self) -> None:
        try:
            self._stream.close()
        except (OSError, ValueError):
            pass

    def isatty(self) -> bool:
        try:
            return bool(self._stream.isatty())
        except (OSError, ValueError):
            return False

    def __getattr__(self, name: str):
        return getattr(self._stream, name)


def setup_console() -> None:
    """
    Ép stdout/stderr sang UTF-8 với errors=replace và đổi code page Windows sang 65001.
    An toàn khi gọi nhiều lần. Có thể bỏ qua đổi code page bằng env VIVOICE_NO_UTF8_CONSOLE=1.
    """
    global _console_ready
    with _console_lock:
        if _console_ready:
            return
        _console_ready = True

    skip_cp_change = os.environ.get("VIVOICE_NO_UTF8_CONSOLE") == "1"
    force_cp_change = os.environ.get("VIVOICE_FORCE_UTF8_CONSOLE") == "1"
    unstable = skip_cp_change or (is_windows7_or_older() and not force_cp_change)

    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        try:
            if unstable:
                stream.reconfigure(errors="replace")
            else:
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
        setattr(sys, name, _ResilientStream(stream))

    if SYSTEM == "Windows" and not unstable:
        try:
            import ctypes
            import time

            # `ctypes.windll` chỉ tồn tại trên Windows: lấy qua getattr để đoạn
            # này không AttributeError nếu bị chép sang nền tảng khác, và để kiểm
            # được kiểu tĩnh thay vì mặc mypy báo "Module has no attribute".
            windll = getattr(ctypes, "windll", None)
            if windll is not None:
                windll.kernel32.SetConsoleOutputCP(65001)
                windll.kernel32.SetConsoleCP(65001)
                time.sleep(0.05)
        except Exception as cp_error:
            # Không đổi được code page -> tiếng Việt có thể hiển thị sai trên
            # console Windows cũ. stream đã được reconfigure(errors="replace")
            # nên chương trình vẫn chạy; ghi log để người dùng biết mà đối chiếu.
            logger.debug("Không đổi được code page sang UTF-8: %s", cp_error)


def safe_print(text: str = "", end: str = "\n") -> None:
    """
    In an toàn, chia theo dòng, fallback sang không dấu nếu lỗi.
    Thread-safe nhờ _ResilientStream.
    """
    if text is None:
        text = ""
    lines = str(text).split("\n")
    last = len(lines) - 1
    for i, line in enumerate(lines):
        line_end = end if i == last else "\n"
        try:
            print(line, end=line_end)
        except (PermissionError, OSError, UnicodeError):
            try:
                from text_utils import strip_diacritics

                print(
                    strip_diacritics(line).encode("ascii", errors="replace").decode("ascii"),
                    end=line_end,
                )
            except Exception:  # noqa: S110
                # Đây là tầng FALLBACK CUỐI của việc in ấn: nếu nó cũng hỏng thì
                # không còn cách nào khác ngoài im lặng (ném lỗi ở đây sẽ làm sập
                # chương trình chỉ vì in chữ không được). Không log vì logger có
                # thể chính là thứ đang hỏng (nó ghi ra cùng stream).
                pass


def _get_windows_build() -> int:
    """Lấy build number Windows, 0 nếu không xác định."""
    try:
        # Python 3.8+ có sys.getwindowsversion
        if hasattr(sys, "getwindowsversion"):
            return int(sys.getwindowsversion().build)
    except Exception as e:
        logger.debug("sys.getwindowsversion() lỗi: %s", e)
    try:
        raw = platform.win32_ver()[1]  # fallback, deprecated nhưng vẫn hoạt động
        parts = raw.split(".")
        if len(parts) >= 3:
            return int(parts[2])
    except Exception as e:
        logger.debug("platform.win32_ver() fallback lỗi: %s", e)
    return 0


def windows_version() -> tuple[int, int] | None:
    """
    Trả về (major, minor) kernel Windows, vd (6,1) cho Win7, (10,0) cho Win10/11.
    None nếu không phải Windows.
    """
    if SYSTEM != "Windows":
        return None
    try:
        if hasattr(sys, "getwindowsversion"):
            v = sys.getwindowsversion()
            return int(v.major), int(v.minor)
    except Exception as e:
        logger.debug("Không đọc được phiên bản Windows: %s", e)
    try:
        raw = platform.win32_ver()[1]
        parts = raw.split(".")
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError, AttributeError):
        return None


def is_windows7_or_older() -> bool:
    """True nếu Windows 7/Vista trở về trước (kernel <= 6.1)."""
    ver = windows_version()
    return ver is not None and ver <= (6, 1)


def windows_version_label() -> str:
    """Nhãn dễ đọc: 'Windows 7', 'Windows 10', 'Windows 11', ..."""
    ver = windows_version()
    if ver is None:
        return SYSTEM
    if ver == (10, 0):
        build = _get_windows_build()
        return "Windows 11" if build >= 22000 else "Windows 10"
    labels = {
        (6, 0): "Windows Vista",
        (6, 1): "Windows 7",
        (6, 2): "Windows 8",
        (6, 3): "Windows 8.1",
    }
    return labels.get(ver, f"Windows (kernel {ver[0]}.{ver[1]})")


# --- Môi trường nâng cao (v6.3+) ---

def _read_osrelease() -> str:
    try:
        return Path("/proc/sys/kernel/osrelease").read_text(
            encoding="utf-8", errors="ignore"
        )
    except OSError:
        return ""


def is_wsl() -> bool:
    """True nếu đang chạy trong WSL."""
    if SYSTEM != "Linux":
        return False
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    return "microsoft" in _read_osrelease().lower()


def is_docker() -> bool:
    """True nếu đang chạy trong Docker."""
    try:
        return Path("/.dockerenv").exists() or "docker" in _read_osrelease().lower()
    except Exception:
        return False


def is_ci() -> bool:
    """True nếu đang chạy trong CI (GitHub Actions, etc)."""
    ci_vars = ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL", "TF_BUILD")
    return any(os.environ.get(v) for v in ci_vars)


def linux_desktop() -> str:
    """Tên desktop Linux ('gnome', 'kde', ...) hoặc ''."""
    for var in ("XDG_CURRENT_DESKTOP", "DESKTOP_SESSION", "GDMSESSION"):
        value = os.environ.get(var, "")
        if value:
            return value.split(":")[-1].strip().lower()
    return ""


def has_command(name: str) -> bool:
    return shutil.which(name) is not None


def _module_available(module_name: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


@dataclass
class FeatureInfo:
    ok: bool
    via: str


@dataclass
class CapabilityReport:
    os: str
    os_label: str
    python: str
    is_wsl: bool
    is_docker: bool
    desktop: str
    features: dict[str, FeatureInfo] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "os": self.os,
            "os_label": self.os_label,
            "python": self.python,
            "is_wsl": self.is_wsl,
            "is_docker": self.is_docker,
            "desktop": self.desktop,
            "features": {k: {"ok": v.ok, "via": v.via} for k, v in self.features.items()},
        }


def capability_report() -> dict:
    """Báo cáo tính năng chạy được trên máy hiện tại."""
    features: dict[str, FeatureInfo] = {}

    def add(name: str, ok: bool, via: str):
        features[name] = FeatureInfo(ok=bool(ok), via=via)

    if SYSTEM == "Windows":
        add("open_website", True, "trình duyệt mặc định")
        add("open_app", True, "whitelist app_map_windows")
        add("open_file", True, "os.startfile")
        add("shutdown/restart/logout", True, "shutdown.exe")
        add("lock", True, "rundll32 LockWorkStation")
        add("sleep", True, "rundll32 powrprof")
        add(
            "volume",
            True,
            "pycaw (chính xác)"
            if _module_available("pycaw")
            else "phím ảo PowerShell (pip install pycaw comtypes để chính xác)",
        )
        add("screenshot", True, "PowerShell + System.Drawing")
        add(
            "tts",
            True,
            "Windows SAPI" + (" + pyttsx3" if _module_available("pyttsx3") else ""),
        )
    elif SYSTEM == "Darwin":
        add("open_website", True, "trình duyệt mặc định")
        add("open_app", True, "open -a (whitelist app_map_macos)")
        add("open_file", True, "open")
        add("shutdown/restart/logout/lock/sleep", True, "osascript / pmset")
        add("volume", True, "osascript output volume")
        add("screenshot", True, "screencapture")
        add(
            "tts",
            True,
            "macOS say" + (" + pyttsx3" if _module_available("pyttsx3") else ""),
        )
    elif is_wsl():
        add(
            "open_website",
            has_command("wslview") or has_command("explorer.exe"),
            "wslview/explorer.exe -> trình duyệt Windows host",
        )
        add("open_app", True, "lệnh trong app_map_linux (cần WSLg trên Win11)")
        add(
            "open_file",
            has_command("wslview"),
            "wslview (sudo apt install wslu)",
        )
        add("shutdown/restart/logout", has_command("shutdown.exe"), "shutdown.exe host")
        add("lock", has_command("rundll32.exe"), "rundll32 host")
        add("sleep", has_command("rundll32.exe"), "rundll32 powrprof host")
        add("volume", has_command("powershell.exe"), "phím ảo PowerShell host")
        add("screenshot", has_command("powershell.exe"), "PowerShell chụp màn hình host")
        add(
            "tts",
            has_command("powershell.exe")
            or _module_available("pyttsx3")
            or _module_available("gtts"),
            "SAPI host / pyttsx3 / gTTS",
        )
    else:  # Linux thật
        add("open_website", has_command("xdg-open"), "xdg-open")
        add("open_app", True, "lệnh trong app_map_linux")
        add("open_file", has_command("xdg-open"), "xdg-open")
        add(
            "shutdown/restart",
            has_command("systemctl") or has_command("shutdown"),
            "systemctl/shutdown",
        )
        add(
            "logout",
            has_command("loginctl") or has_command("gnome-session-quit"),
            "loginctl/gnome-session-quit",
        )
        add(
            "lock",
            any(
                has_command(c)
                for c in (
                    "loginctl",
                    "xdg-screensaver",
                    "gnome-screensaver-command",
                    "qdbus",
                    "dm-tool",
                )
            ),
            "loginctl / xdg-screensaver / gnome-screensaver / qdbus (KDE) / dm-tool",
        )
        add("sleep", has_command("systemctl"), "systemctl suspend")
        add(
            "volume",
            any(has_command(c) for c in ("wpctl", "pactl", "amixer")),
            "wpctl (PipeWire) / pactl (PulseAudio) / amixer (ALSA)",
        )
        add(
            "screenshot",
            any(
                has_command(c)
                for c in ("gnome-screenshot", "spectacle", "scrot", "grim", "import")
            ),
            "gnome-screenshot / spectacle (KDE) / scrot / grim (Wayland) / import",
        )
        add(
            "tts",
            _module_available("pyttsx3") or _module_available("gtts"),
            "pyttsx3 / gTTS",
        )

    add(
        "stt_mic_online",
        _module_available("speech_recognition"),
        "SpeechRecognition + Google STT (cần mạng)",
    )
    add(
        "stt_offline",
        _module_available("torch") and _module_available("transformers"),
        "PhoWhisper offline (transformers + torch)",
    )
    add("nlu_lite", True, "LiteIntentModel thuần Python (luôn chạy được)")
    add("nlu_tfidf", _module_available("sklearn"), "TF-IDF scikit-learn")
    add(
        "nlu_phobert",
        _module_available("torch") and _module_available("transformers"),
        "PhoBERT (cần train_phobert.py trước)",
    )

    report = CapabilityReport(
        os=SYSTEM,
        os_label=windows_version_label(),
        python=platform.python_version(),
        is_wsl=is_wsl(),
        is_docker=is_docker(),
        desktop=linux_desktop() if SYSTEM == "Linux" and not is_wsl() else "",
        features=features,
    )
    return report.to_dict()


def format_capability_report(report: dict) -> str:
    """Biến dict từ capability_report() thành văn bản dễ đọc."""
    lines = [
        "=" * 62,
        "BÁO CÁO KHẢ NĂNG CỦA MÁY (trợ lý ảo làm được gì trên máy này)",
        "=" * 62,
    ]
    os_line = report.get("os_label", report.get("os", "Unknown"))
    if report.get("is_wsl"):
        os_line += " - trong WSL trên Windows"
    elif report.get("desktop"):
        os_line += f" (desktop: {report['desktop']})"
    if report.get("is_docker"):
        os_line += " [Docker]"
    lines.append(f"Hệ điều hành : {os_line}")
    lines.append(f"Python       : {report.get('python', '?')}")
    lines.append("")
    lines.append("TÍNH NĂNG:")
    for name, info in report.get("features", {}).items():
        mark = "[OK]" if info.get("ok") else "[--]"
        lines.append(f"  {mark:<4} {name:<22} {info.get('via','')}")
    lines.append("")
    lines.append("Mục [--] là tính năng thiếu công cụ - xem HUONG_DAN_SU_DUNG.txt")
    return "\n".join(lines)


def get_python_info() -> dict:
    """Thông tin Python chi tiết để debug."""
    return {
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "executable": sys.executable,
        "path": sys.path[:3],
        "is_venv": sys.prefix != sys.base_prefix,
    }


if __name__ == "__main__":
    setup_console()
    safe_print(f"Hệ điều hành: {windows_version_label()}")
    safe_print(f"Windows 7 hoặc cũ hơn: {is_windows7_or_older()}")
    safe_print(f"WSL: {is_wsl()} | Docker: {is_docker()} | CI: {is_ci()}")
    safe_print("")
    safe_print(format_capability_report(capability_report()))
