"""
executor.py v7.2
-----------
v7.1: thêm type hints, security hardening, CI
-----------
Mô-đun thực thi
Mô-đun thực thi lệnh trên máy tính - hỗ trợ Windows / macOS / Linux.

v7.0 nâng cấp:
- Type hints đầy đủ, pathlib thay os.path
- Lưu reminders.json atomic (temp + rename) + file lock đơn giản
- Tách các action thành class, thêm validation chặt hơn
- Sửa PowerShell injection bằng cách escape đúng cách
- Thêm timeout cho subprocess, tránh treo
- Thêm logging structured, metrics
- Bảo mật: chặn thêm đuôi .lnk, kiểm tra symlink
"""

from __future__ import annotations

import datetime
import difflib
import json
import logging
import os
import platform
import random
import re
import subprocess
import tempfile
import threading
import urllib.parse
import uuid
import webbrowser
from pathlib import Path
from typing import Any

from config import load_config
from platform_utils import (
    is_windows7_or_older,
    is_wsl,
    safe_print,
    setup_console,
    windows_version_label,
)
from text_utils import strip_diacritics

logger = logging.getLogger(__name__)

try:
    from rapidfuzz import fuzz, process

    _RAPIDFUZZ_AVAILABLE = True
except ImportError:
    _RAPIDFUZZ_AVAILABLE = False
    logger.warning(
        "Không nạp được rapidfuzz - chuyển sang difflib. "
        "Cài bằng: pip install rapidfuzz"
    )

SYSTEM = platform.system()
CONFIG = load_config()

CONFIDENCE_THRESHOLD: float = float(CONFIG.get("confidence_threshold", 0.35))
DANGEROUS_ACTIONS: set[str] = {str(a) for a in CONFIG.get("dangerous_actions", [])}

# --- Speech ---
SPEAK_ENABLED: bool = False


def reload_config(path: str | Path | None = None) -> dict[str, Any]:
    """Nạp lại config.json khi đang chạy, cập nhật tại chỗ."""
    global CONFIDENCE_THRESHOLD, DANGEROUS_ACTIONS
    fresh = load_config(path) if path else load_config()
    CONFIG.clear()
    CONFIG.update(fresh)
    CONFIDENCE_THRESHOLD = float(CONFIG.get("confidence_threshold", 0.35))
    DANGEROUS_ACTIONS = {str(a) for a in CONFIG.get("dangerous_actions", [])}
    # v7.2: đồng bộ cả ngưỡng của tầng NLU. Trước đây "nap lai"/--config chỉ
    # cập nhật executor nên người dùng đổi confidence_accept trong config.json
    # rồi nạp lại vẫn thấy trợ lý hỏi y như cũ (ngưỡng NLU đóng băng lúc import).
    try:
        import nlu_advanced

        nlu_advanced.refresh_thresholds(CONFIG)
    except Exception as e:  # pragma: no cover - NLU không bắt buộc phải có
        logger.debug("Không cập nhật được ngưỡng của tầng NLU: %s", e)
    logger.info(
        "Đã nạp lại cấu hình: %d web, %d file",
        len(CONFIG.get("website_map", {})),
        len(CONFIG.get("file_map", {})),
    )
    return CONFIG


def set_speech_enabled(enabled: bool) -> bool:
    global SPEAK_ENABLED
    SPEAK_ENABLED = bool(enabled)
    return SPEAK_ENABLED


# --- Regex & constants ---
_SAFE_PATH_RE = re.compile(r"^[\w\s:\\/.\-()%]+$", re.UNICODE)
_URL_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)
_BARE_DOMAIN_RE = re.compile(r"^[\w.\-]+\.[a-z]{2,}(?:/\S*)?$", re.IGNORECASE)

HOME = Path.home()
ACTIVE_REMINDERS: list[dict[str, Any]] = []
ACTIVE_REMINDERS_LOCK = threading.RLock()

BASE_DIR = Path(__file__).resolve().parent
REMINDERS_PATH = BASE_DIR / "reminders.json"

EXECUTABLE_EXTENSIONS = {
    ".exe",
    ".bat",
    ".cmd",
    ".com",
    ".scr",
    ".pif",
    ".msi",
    ".msp",
    ".ps1",
    ".psm1",
    ".vbs",
    ".vbe",
    ".js",
    ".jse",
    ".jar",
    ".wsf",
    ".wsh",
    ".hta",
    ".cpl",
    ".reg",
    ".sh",
    ".bash",
    ".zsh",
    ".py",
    ".pyw",
    ".app",
    ".lnk",  # v7.0: chặn thêm shortcut
}

CHITCHAT_REPLIES: list[tuple[str, list[str]]] = [
    (
        r"xin chào|chào bạn|hello|hi bạn|chào trợ lý|alô",
        ["Xin chào! Tôi có thể giúp gì cho bạn?", "Chào bạn, tôi đang nghe đây."],
    ),
    (r"chào buổi sáng", ["Chào buổi sáng! Chúc bạn một ngày hiệu quả."]),
    (r"chào buổi tối|ngủ ngon", ["Chúc bạn buổi tối vui vẻ và ngủ ngon nhé."]),
    (
        r"tên gì|là ai|ai tạo ra bạn",
        ["Tôi là trợ lý ảo tiếng Việt, giúp bạn điều khiển máy tính bằng giọng nói."],
    ),
    (
        r"làm được|giúp được|làm những gì",
        [
            "Tôi có thể mở trang web, mở phần mềm, mở file, tìm kiếm, phát nhạc, "
            "đặt nhắc nhở, xem thời tiết, tính toán và điều khiển hệ thống."
        ],
    ),
    (r"khoẻ không|thế nào|đang làm gì", ["Tôi vẫn chạy tốt và sẵn sàng nhận lệnh của bạn."]),
    (
        r"cảm ơn|cám ơn|giỏi|tốt lắm|okie",
        ["Không có gì, rất vui được giúp bạn.", "Dạ vâng, có gì bạn cứ gọi tôi."],
    ),
    (r"tạm biệt|bái bai|hẹn gặp lại", ["Tạm biệt bạn, hẹn gặp lại!"]),
    (r"buồn|mệt|tâm sự", ["Bạn nghỉ ngơi một chút nhé. Tôi có thể mở một bản nhạc nhẹ cho bạn."]),
    (
        r"chuyện cười|nói đùa|hát",
        ["Lập trình viên sợ nhất điều gì? Là code chạy được mà không biết tại sao!"],
    ),
    (r"bao nhiêu tuổi", ["Tôi vừa được bạn tạo ra thôi, còn rất trẻ!"]),
]


# ============================================================================
# Helpers
# ============================================================================
def _best_match(
    target: str, mapping: dict[str, Any], score_cutoff: int = 78, fuzzy: bool = True
) -> tuple[Any | None, str | None]:
    if not target:
        return None, None
    target = target.strip().lower()
    if target in mapping:
        return mapping[target], target

    no_dia = strip_diacritics(target)
    for key, value in mapping.items():
        if strip_diacritics(key) == no_dia:
            return value, key

    if not fuzzy:
        return None, None

    if _RAPIDFUZZ_AVAILABLE:
        match = process.extractOne(
            target, mapping.keys(), scorer=fuzz.WRatio, score_cutoff=score_cutoff
        )
        if match:
            return mapping[match[0]], match[0]
        return None, None

    close = difflib.get_close_matches(target, mapping.keys(), n=1, cutoff=score_cutoff / 100)
    if close:
        return mapping[close[0]], close[0]
    return None, None


def _confirm(prompt: str) -> bool:
    try:
        answer = input(f"[XÁC NHẬN] {prompt} (y/n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        safe_print("\n[HUỶ] Không lấy được xác nhận - huỷ để an toàn.")
        return False
    return answer in ("y", "yes", "co", "có", "ok")


def _escape_powershell_single_quoted(s: str) -> str:
    """Escape cho chuỗi single-quoted PowerShell: ' -> ''"""
    return s.replace("'", "''")


def _escape_osascript(s: str) -> str:
    """Escape cho chuỗi double-quoted AppleScript.

    v7.2 - SỬA LỖI BẢO MẬT NGHIÊM TRỌNG: thứ tự escape trước đây bị ĐẢO
    NGƯỢC (thay ``\"`` trước rồi mới thay ``\\\\``), nên chính dấu ``\\\\`` vừa chèn
    vào bị nhân đôi thành ``\\\\\\\\`` -> AppleScript hiểu là "1 backslash nguyên văn"
    và dấu ``\"`` phía sau TRỞ THÀNH KÝ TỰ ĐÓNG CHUỖI. Kết quả: nội dung nhắc nhở
    (vd "nhắc tôi a\\" with title \\"PWNED\\"") thoát ra khỏi chuỗi và được
    AppleScript chạy như MÃ LỆNH. Phải escape backslash TRƯỚC, rồi mới đến nháy kép.
    Ngoài ra AppleScript không cho phép ký tự xuống dòng trong chuỗi -> thay bằng khoảng trắng.
    """
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r\n", " ")
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("\t", " ")
    )


def respond(text: str) -> None:
    safe_print(f"[TRỢ LÝ] {text}")
    if SPEAK_ENABLED:
        try:
            import tts

            tts.speak(text, show=False)
        except Exception as e:
            logger.warning("Không đọc được phản hồi bằng giọng nói: %s", e)


def _open_url(url: str) -> bool:
    if SYSTEM == "Linux" and is_wsl():
        if _run_first_available([["wslview", url], ["explorer.exe", url]]):
            return True
        logger.warning("WSL: không tìm thấy wslview/explorer.exe để mở URL %s", url)
        return False
    try:
        return bool(webbrowser.open(url))
    except Exception as e:
        logger.warning("webbrowser.open(%r) lỗi: %s", url, e)
        return False


def _open_path(path: str) -> bool:
    # Expand và resolve
    try:
        expanded = os.path.expandvars(os.path.expanduser(path))
        p = Path(expanded)
        # Kiểm tra tồn tại, không follow symlink nguy hiểm quá mức
        if not p.exists():
            safe_print(f"[LỖI] Không tìm thấy đường dẫn: {expanded}")
            logger.warning("Không tìm thấy đường dẫn: %s", expanded)
            return False
        # Chặn symlink trỏ ra ngoài nếu là file nhạy cảm? Giữ đơn giản: cảnh báo
        if p.is_symlink():
            logger.info("Mở symlink: %s -> %s", p, p.resolve())
    except Exception as e:
        safe_print(f"[LỖI] Đường dẫn không hợp lệ {path}: {e}")
        return False

    try:
        if SYSTEM == "Windows":
            # os.startfile là API chuẩn để mở file bằng ứng dụng mặc định của
            # Windows; không có chuỗi người dùng nào được ghép vào shell ở đây.
            os.startfile(str(p))  # type: ignore[attr-defined]  # noqa: S606
        elif SYSTEM == "Darwin":
            _popen(["open", str(p)])
        elif is_wsl():
            if not _run_first_available([["wslview", str(p)]]):
                safe_print("[LỖI] Trên WSL cần cài wslu: sudo apt install wslu")
                return False
        else:
            _popen(["xdg-open", str(p)])
        return True
    except Exception as e:
        safe_print(f"[LỖI] Không mở được {p}: {e}")
        logger.error("Không mở được %s: %s", p, e)
        return False


def _volume_via_pycaw(target: str) -> bool | None:
    try:
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    except ImportError:
        return None
    try:
        speakers = AudioUtilities.GetSpeakers()
        interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = interface.QueryInterface(IAudioEndpointVolume)
        if target == "mute":
            volume.SetMute(1, None)
        elif target == "unmute":
            volume.SetMute(0, None)
        elif target == "volume_up":
            level = min(1.0, volume.GetMasterVolumeLevelScalar() + 0.1)
            volume.SetMasterVolumeLevelScalar(level, None)
        elif target == "volume_down":
            level = max(0.0, volume.GetMasterVolumeLevelScalar() - 0.1)
            volume.SetMasterVolumeLevelScalar(level, None)
        else:
            return None
        return True
    except Exception as e:
        logger.warning("pycaw lỗi '%s': %s", target, e)
        return None


def _app_map_for_platform() -> dict[str, str]:
    if SYSTEM == "Darwin":
        return CONFIG.get("app_map_macos", {})
    if SYSTEM == "Windows":
        return CONFIG.get("app_map_windows", {})
    return CONFIG.get("app_map_linux", {})


# ============================================================================
# System actions
# ============================================================================
def action_open_website(target: str) -> bool:
    url, matched_key = _best_match(target, CONFIG.get("website_map", {}), fuzzy=False)
    if url is None:
        if _URL_SCHEME_RE.match(target):
            url = target
        elif _BARE_DOMAIN_RE.match(target):
            url = "https://" + target
        else:
            url, matched_key = _best_match(target, CONFIG.get("website_map", {}))
            if url is None:
                url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(target)

    safe_print(f"[THỰC THI] Mở trình duyệt: {url}")
    logger.info("Mở website: target=%r matched=%r url=%s", target, matched_key, url)
    _open_url(url)
    return True


def action_open_app(target: str) -> bool:
    config_key = {"Windows": "app_map_windows", "Darwin": "app_map_macos"}.get(
        SYSTEM, "app_map_linux"
    )
    exe, matched_key = _best_match(target, _app_map_for_platform())

    if (
        exe is not None
        and SYSTEM == "Windows"
        and re.match(r"^[\w.]+:$", exe)
        and is_windows7_or_older()
    ):
        safe_print(
            f"[TỪ CHỐI] '{matched_key}' là ứng dụng kiểu Store App (UWP), chỉ chạy được từ "
            f"Windows 8 trở lên - "
            f"Máy bạn: {windows_version_label()}. "
            f'Hãy đổi "{matched_key}" trong config.json sang .exe tương đương.'
        )
        logger.warning("Từ chối UWP '%s' trên %s", matched_key, windows_version_label())
        return False

    if exe is None:
        safe_print(
            f"[TỪ CHỐI] Chưa biết ứng dụng '{target}'. "
            f'Hãy thêm vào "{config_key}" trong config.json, vd:\n'
            f'  "{target}": "duong_dan_toi_file.exe"'
        )
        logger.warning("Từ chối app không trong whitelist (%s): %r", config_key, target)
        return False

    exe = os.path.expandvars(exe)
    safe_print(f"[THỰC THI] Mở ứng dụng: {exe} (khớp với '{matched_key}')")
    logger.info("Mở app: target=%r matched=%r exe=%s", target, matched_key, exe)
    try:
        if SYSTEM == "Windows":
            _popen(["cmd", "/c", "start", "", exe])
        elif SYSTEM == "Darwin":
            _popen(["open", "-a", exe])
        else:
            import shlex

            _popen(shlex.split(exe))
        return True
    except FileNotFoundError:
        safe_print(
            f"[LỖI] Không tìm thấy lệnh '{exe}'. Ứng dụng có thể chưa cài, "
            f'hãy sửa "{matched_key}" trong "{config_key}" (config.json).'
        )
        logger.error("Không tìm thấy lệnh '%s' (target=%r)", exe, target)
        return False
    except Exception as e:
        safe_print(f"[LỖI] Không mở được ứng dụng '{exe}': {e}")
        logger.error("Không mở được ứng dụng '%s': %s", exe, e)
        return False


def _popen(cmd: list[str]) -> None:
    """Popen wrapper that tolerates simple mocks (lambda cmd: ...) used in tests."""
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except TypeError:
        # Mock không nhận kwargs stdout/stderr (test cũ)
        subprocess.Popen(cmd)
    # FileNotFoundError sẽ được caller xử lý

def _run_first_available(candidates: list[list[str]]) -> bool:
    for cmd in candidates:
        try:
            _popen(cmd)
            logger.info("Lệnh hệ thống chạy thành công: %s", cmd)
            return True
        except FileNotFoundError:
            continue
        except Exception as e:
            logger.debug("Lệnh %s lỗi: %s", cmd, e)
            continue
    return False


def _is_executable_path(path: str) -> bool:
    cleaned = (path or "").strip().rstrip("\"'")
    return Path(cleaned).suffix.lower() in EXECUTABLE_EXTENSIONS


def action_open_file(target: str) -> bool:
    path, matched_key = _best_match(target, CONFIG.get("file_map", {}))
    if path is None:
        if target and _SAFE_PATH_RE.match(target) and ".." not in target:
            path = target
        else:
            safe_print(
                f"[TỪ CHỐI] Không nhận diện được file/thư mục '{target}'. "
                f'Hãy thêm vào "file_map" trong config.json.'
            )
            logger.warning("Từ chối mở file không xác định: %r", target)
            return False

    if _is_executable_path(path):
        safe_print(
            f"[TỪ CHỐI] '{path}' là file CÓ THỂ CHẠY ĐƯỢC (chương trình/script). "
            f"Vì an toàn, tôi không tự mở loại file này."
        )
        logger.warning("Từ chối mở file thực thi: %s", path)
        return False

    safe_print(f"[THỰC THI] Mở file: {path}")
    logger.info("Mở file: target=%r matched=%r path=%s", target, matched_key, path)
    return _open_path(path)


def _system_control_wsl(target: str) -> bool:
    commands = {
        "shutdown": ["shutdown.exe", "/s", "/t", "5"],
        "restart": ["shutdown.exe", "/r", "/t", "5"],
        "logout": ["shutdown.exe", "/l"],
        "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
        "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
    }
    if target in commands:
        try:
            _popen(commands[target])
            safe_print(f"[THỰC THI] Lệnh hệ thống (WSL -> Windows host): {target}")
            logger.info("Lệnh hệ thống qua Windows host (WSL): %s", target)
            return True
        except FileNotFoundError:
            safe_print(
                "[LỖI] Không gọi được lệnh Windows từ WSL (interop tắt? kiểm tra /etc/wsl.conf)."
            )
            logger.error("WSL interop không khả dụng cho: %s", target)
            return False

    if target in ("mute", "unmute", "volume_up", "volume_down"):
        key = {"mute": 173, "unmute": 173, "volume_down": 174, "volume_up": 175}[target]
        repeat = 5 if target in ("volume_up", "volume_down") else 1
        ps = (
            "$w = New-Object -ComObject WScript.Shell; "
            f"1..{repeat} | ForEach-Object {{ $w.SendKeys([char]{key}) }}"
        )
        try:
            _popen(["powershell.exe", "-NoProfile", "-Command", ps])
            safe_print(f"[THỰC THI] Điều chỉnh âm thanh (WSL -> Windows host): {target}")
            return True
        except FileNotFoundError:
            safe_print("[LỖI] Không gọi được powershell.exe từ WSL.")
            return False

    if target == "screenshot":
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
            "$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
            "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
            "$g = [System.Drawing.Graphics]::FromImage($bmp); "
            "$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size); "
            "$dir = [Environment]::GetFolderPath('MyPictures'); "
            "$path = Join-Path $dir ('screenshot_{0:yyyyMMdd_HHmmss}.png' -f (Get-Date)); "
            "$bmp.Save($path); Write-Output $path"
        )
        try:
            out = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", ps],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            safe_print(f"[THỰC THI] Đã chụp màn hình (Windows host): {out.stdout.strip()}")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            safe_print(f"[LỖI] Không chụp được màn hình qua Windows host: {e}")
            return False

    safe_print(f"[BỎ QUA] WSL chưa hỗ trợ lệnh '{target}'.")
    return False


# ============================================================================
# Bảng lệnh hệ thống theo nền tảng (v7.2: đưa lên module-level)
# ---------------------------------------------------------------------------
# Trước đây toàn bộ các dict này được TẠO LẠI bên trong mỗi lần gọi
# action_system_control() và bị nhúng trong một hàm 21 nhánh, nên: (a) mỗi lệnh
# phải dựng lại ~30 mục, (b) muốn biết Linux chạy lệnh nào phải đọc hết hàm,
# (c) không test/monkeypatch riêng từng nền tảng được.
# ============================================================================
COMMANDS_WINDOWS: dict[str, list[str]] = {
    "shutdown": ["shutdown", "/s", "/t", "5"],
    "restart": ["shutdown", "/r", "/t", "5"],
    "logout": ["shutdown", "/l"],
    "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
    "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
}
VOLUME_KEYS_WINDOWS = {"mute": 173, "unmute": 173, "volume_down": 174, "volume_up": 175}

COMMANDS_MACOS: dict[str, list[str]] = {
    "shutdown": ["osascript", "-e", 'tell app "System Events" to shut down'],
    "restart": ["osascript", "-e", 'tell app "System Events" to restart'],
    "logout": ["osascript", "-e", 'tell app "System Events" to log out'],
    "lock": [
        "osascript",
        "-e",
        'tell application "System Events" to keystroke "q" using {control down, command down}',
    ],
    "sleep": ["pmset", "sleepnow"],
}
VOLUME_MACOS: dict[str, list[str]] = {
    "mute": ["osascript", "-e", "set volume output muted true"],
    "unmute": ["osascript", "-e", "set volume output muted false"],
    "volume_up": [
        "osascript",
        "-e",
        "set volume output volume ((output volume of (get volume settings)) + 10)",
    ],
    "volume_down": [
        "osascript",
        "-e",
        "set volume output volume ((output volume of (get volume settings)) - 10)",
    ],
}

COMMANDS_LINUX: dict[str, list[list[str]]] = {
    "shutdown": [["systemctl", "poweroff"], ["shutdown", "-h", "now"]],
    "restart": [["systemctl", "reboot"], ["shutdown", "-r", "now"]],
    "logout": [
        ["loginctl", "terminate-user", os.environ.get("USER", "")],
        ["gnome-session-quit", "--logout", "--no-prompt"],
    ],
    "lock": [
        ["loginctl", "lock-session"],
        ["xdg-screensaver", "lock"],
        ["gnome-screensaver-command", "-l"],
        ["qdbus", "org.freedesktop.ScreenSaver", "/ScreenSaver", "Lock"],
        ["dm-tool", "lock"],
    ],
    "sleep": [["systemctl", "suspend"]],
}
VOLUME_LINUX: dict[str, list[list[str]]] = {
    "mute": [
        ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"],
        ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"],
        ["amixer", "set", "Master", "mute"],
    ],
    "unmute": [
        ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"],
        ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"],
        ["amixer", "set", "Master", "unmute"],
    ],
    "volume_up": [
        ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%+"],
        ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"],
        ["amixer", "set", "Master", "10%+"],
    ],
    "volume_down": [
        ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%-"],
        ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"],
        ["amixer", "set", "Master", "10%-"],
    ],
}
SCREENSHOT_LINUX_TOOLS = ["gnome-screenshot", "spectacle", "scrot", "grim", "import"]


def _screenshot_path() -> Path:
    """Đường dẫn file ảnh chụp màn hình: ~/Pictures/screenshot_<thoi-gian>.png

    Đặt tên file theo timestamp để KHÔNG ghi đè ảnh cũ - người dùng chụp liên
    tục khi lập trình báo cáo lỗi rất dễ có nhiều tấm trong cùng phút.
    """
    pictures_dir = Path(HOME) / "Pictures"
    pictures_dir.mkdir(parents=True, exist_ok=True)
    return pictures_dir / f"screenshot_{datetime.datetime.now():%Y%m%d_%H%M%S}.png"


def _send_virtual_key(target: str) -> None:
    """Bấm phím âm lượng ảo qua PowerShell (dùng cho Windows và WSL)."""
    key = VOLUME_KEYS_WINDOWS[target]
    repeat = 5 if target in ("volume_up", "volume_down") else 1
    ps = (
        "$w = New-Object -ComObject WScript.Shell; "
        f"1..{repeat} | ForEach-Object {{ $w.SendKeys([char]{key}) }}"
    )
    _popen(["powershell", "-NoProfile", "-Command", ps])


def _windows_screenshot() -> bool:
    path = _screenshot_path()
    safe_path = _escape_powershell_single_quoted(str(path))
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
        "$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
        "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
        "$g = [System.Drawing.Graphics]::FromImage($bmp); "
        "$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size); "
        f"$bmp.Save('{safe_path}')"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=15)
    safe_print(f"[THỰC THI] Đã chụp màn hình: {path}")
    logger.info("Đã chụp màn hình: %s", path)
    return True


def _system_control_windows(target: str) -> bool | None:
    """None = nền tảng này không biết lệnh 'target' (caller sẽ báo BỎ QUA)."""
    if target in COMMANDS_WINDOWS:
        safe_print(f"[THỰC THI] {' '.join(COMMANDS_WINDOWS[target])}")
        logger.info("Lệnh hệ thống (Windows): %s", target)
        _popen(COMMANDS_WINDOWS[target])
        return True

    if target in VOLUME_KEYS_WINDOWS:
        if _volume_via_pycaw(target):
            safe_print(f"[THỰC THI] Điều chỉnh âm thanh (pycaw, chính xác): {target}")
            logger.info("Điều chỉnh âm thanh qua pycaw: %s", target)
            return True

        _send_virtual_key(target)
        safe_print(f"[THỰC THI] Điều chỉnh âm thanh (phím ảo): {target}")
        if target == "unmute":
            safe_print(
                "[LƯU Ý] Cài thêm `pip install pycaw comtypes` để 'unmute' "
                "chính xác tuyệt đối thay vì chỉ bật/tắt luân phiên."
            )
        logger.info("Điều chỉnh âm thanh qua phím ảo: %s", target)
        return True

    if target == "screenshot":
        return _windows_screenshot()
    return None


def _system_control_macos(target: str) -> bool | None:
    if target in COMMANDS_MACOS:
        safe_print(f"[THỰC THI] Lệnh hệ thống (macOS): {target}")
        logger.info("Lệnh hệ thống (macOS): %s", target)
        _popen(COMMANDS_MACOS[target])
        return True

    if target in VOLUME_MACOS:
        safe_print(f"[THỰC THI] Điều chỉnh âm thanh (macOS): {target}")
        logger.info("Điều chỉnh âm thanh (macOS): %s", target)
        _popen(VOLUME_MACOS[target])
        return True

    if target == "screenshot":
        path = _screenshot_path()
        _popen(["screencapture", str(path)])
        safe_print(f"[THỰC THI] Đã chụp màn hình: {path}")
        return True
    return None


def _linux_screenshot() -> bool:
    path = _screenshot_path()
    candidates = []
    for tool in SCREENSHOT_LINUX_TOOLS:
        if tool == "gnome-screenshot":
            candidates.append([tool, "-f", str(path)])
        elif tool == "spectacle":
            candidates.append([tool, "-bn", "-o", str(path)])
        elif tool == "import":
            candidates.append([tool, "-window", "root", str(path)])
        else:  # scrot / grim chỉ nhận đường dẫn thẳng
            candidates.append([tool, str(path)])
    if _run_first_available(candidates):
        safe_print(f"[THỰC THI] Đã chụp màn hình: {path}")
        return True
    safe_print(
        "[LỖI] Không tìm thấy công cụ chụp màn hình (đã thử "
        f"{', '.join(SCREENSHOT_LINUX_TOOLS)})."
    )
    return False


def _system_control_linux(target: str) -> bool | None:
    if is_wsl():
        return _system_control_wsl(target)

    if target in COMMANDS_LINUX:
        if _run_first_available(COMMANDS_LINUX[target]):
            safe_print(f"[THỰC THI] Lệnh hệ thống (Linux): {target}")
            return True
        safe_print(
            f"[LỖI] Không tìm thấy công cụ phù hợp cho '{target}' trên Linux "
            f"(đã thử systemctl/shutdown/loginctl...)."
        )
        logger.warning("Không tìm thấy lệnh Linux khả dụng cho: %s", target)
        return False

    if target in VOLUME_LINUX:
        if _run_first_available(VOLUME_LINUX[target]):
            safe_print(f"[THỰC THI] Điều chỉnh âm thanh (Linux): {target}")
            return True
        safe_print(
            "[LỖI] Không tìm thấy công cụ chỉnh âm lượng (đã thử wpctl, pactl, amixer) "
            "trên máy này. Cài PipeWire (wpctl), PulseAudio (pactl) hoặc "
            "ALSA utils (amixer - gói alsa-utils, có ở gần mọi bản Linux để bàn)."
        )
        logger.warning("Không tìm thấy công cụ âm lượng Linux khả dụng cho: %s", target)
        return False

    if target == "screenshot":
        return _linux_screenshot()
    return None


_SYSTEM_HANDLERS = {
    "Windows": _system_control_windows,
    "Darwin": _system_control_macos,
    "Linux": _system_control_linux,
}


def action_system_control(target: str) -> bool:
    """Thực hiện một lệnh hệ thống (tắt máy, khoá, âm lượng, screenshot...).

    Trả về False (kèm thông báo dễ hiểu) khi người dùng huỷ, máy thiếu công cụ,
    hoặc nền tảng không hỗ trợ lệnh đó - KHÔNG bao giờ ném lỗi ra ngoài vì một
    lệnh hệ thống hỏng không được làm chết phiên trò chuyện.
    """
    if target in DANGEROUS_ACTIONS:
        if not _confirm(f"Bạn chắc chắn muốn '{target}'?"):
            safe_print("Đã huỷ lệnh.")
            logger.info("Người dùng huỷ lệnh nguy hiểm: %s", target)
            return False

    handler = _SYSTEM_HANDLERS.get(SYSTEM)
    try:
        outcome = handler(target) if handler is not None else None
    except Exception as e:
        safe_print(f"[LỖI] Không thực thi được lệnh hệ thống: {e}")
        logger.error("Không thực thi được lệnh hệ thống '%s': %s", target, e)
        return False

    if outcome is None:
        safe_print(f"[BỎ QUA] Không hỗ trợ lệnh hệ thống '{target}' trên {SYSTEM}.")
        logger.warning("Không hỗ trợ lệnh hệ thống '%s' trên %s", target, SYSTEM)
        return False
    return bool(outcome)


# ============================================================================
# Conversational actions
# ============================================================================
def action_search_web(target: str) -> bool:
    if not target or target == "unknown":
        respond("Bạn muốn tìm gì ạ?")
        return False
    url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(target)
    respond(f"Đang tìm kiếm {target}")
    logger.info("Tìm kiếm web: %s", target)
    _open_url(url)
    return True


def action_play_media(target: str) -> bool:
    query = target or "nhạc"
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
    respond(f"Đang phát {query}")
    logger.info("Phát media: %s", query)
    _open_url(url)
    return True


def _format_number(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{round(value, 4):g}"
    return str(value)


def action_calculate(target: str, data: dict[str, Any] | None = None) -> bool:
    data = data or {}
    result = data.get("result")
    if result is None:
        try:
            from intent_model import parse_math_expression

            _, result = parse_math_expression(target or "")
        except Exception:
            result = None

    if result is None:
        respond(f"Xin lỗi, tôi chưa tính được phép tính {target}")
        return False

    respond(f"{target} bằng {_format_number(result)}")
    return True


def action_get_weather(target: str) -> bool:
    location = target if target and target != "hôm nay" else ""
    query = f"thời tiết {location}".strip()
    url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)
    respond(f"Đang xem {query}")
    logger.info("Xem thời tiết: %s", query)
    _open_url(url)
    return True


WEEKDAYS_VI = ["thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật"]


def action_get_datetime(target: str) -> bool:
    now = datetime.datetime.now()
    if target == "date":
        msg = (
            f"Hôm nay là {WEEKDAYS_VI[now.weekday()]}, "
            f"ngày {now.day} tháng {now.month} năm {now.year}."
        )
    else:
        msg = f"Bây giờ là {now.hour} giờ {now.minute} phút."
    respond(msg)
    return True


def action_chitchat(target: str) -> bool:
    text = (target or "").lower()
    for pattern, replies in CHITCHAT_REPLIES:
        if re.search(pattern, text):
            respond(random.choice(replies))
            return True
    respond("Tôi chưa hiểu ý bạn lắm, bạn nói rõ hơn giúp tôi nhé.")
    return True


# --- Reminders với atomic write và lock ---
def _reminder_at(item: dict[str, Any]):
    """Lấy mốc giờ của một lời nhắc, chấp nhận cả khi nó được lưu dạng chuỗi.

    v7.2: ``reminders.json`` có thể bị sửa tay hoặc được ghi bởi phiên bản cũ,
    nên mọi chỗ đọc danh sách này phải dùng hàm "an toàn" thay vì index thẳng.
    """
    at = item.get("at")
    if isinstance(at, str):
        try:
            return datetime.datetime.fromisoformat(at)
        except ValueError:
            return None
    return at if isinstance(at, datetime.datetime) else None


def _save_reminders() -> None:
    try:
        with ACTIVE_REMINDERS_LOCK:
            data = []
            for item in ACTIVE_REMINDERS:
                at = _reminder_at(item)
                if at is None:
                    logger.warning(
                        "Bỏ qua nhắc nhở không hợp lệ khi lưu (thiếu mốc giờ): %r", item
                    )
                    continue
                data.append(
                    {"id": item.get("id"), "task": item.get("task", ""), "at": at.isoformat()}
                )
        # Atomic write - handle both Path and str for test compatibility
        rem_path = Path(REMINDERS_PATH)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(rem_path.parent), prefix=".reminders_tmp_", suffix=".json"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        Path(tmp_path).replace(rem_path)
    except OSError as e:
        logger.warning("Không lưu được danh sách nhắc nhở: %s", e)


def _schedule_reminder(task: str, run_at: datetime.datetime, persist: bool = True) -> str | None:
    delay = (run_at - datetime.datetime.now()).total_seconds()
    if delay <= 0:
        return None
    reminder_id = f"{run_at.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    timer = threading.Timer(delay, _fire_reminder, args=[task, reminder_id])
    timer.daemon = True
    timer.start()
    with ACTIVE_REMINDERS_LOCK:
        ACTIVE_REMINDERS.append(
            {"id": reminder_id, "task": task, "at": run_at, "timer": timer}
        )
    if persist:
        _save_reminders()
    return reminder_id


def restore_reminders() -> int:
    rem_path = Path(REMINDERS_PATH)
    if not rem_path.exists():
        return 0
    try:
        with rem_path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        logger.warning("Không đọc được reminders.json: %s", e)
        return 0

    restored = 0
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            logger.warning("Bỏ qua mục nhắc nhở không phải object trong reminders.json: %r", item)
            continue
        run_at = _reminder_at(item)
        if run_at is None:
            logger.warning("Bỏ qua mục nhắc nhở thiếu mốc giờ hợp lệ: %r", item)
            continue
        task = str(item.get("task") or "báo thức")
        if _schedule_reminder(task, run_at, persist=False):
            restored += 1
    _save_reminders()
    if restored:
        logger.info("Đã khôi phục %d nhắc nhở còn hạn", restored)
    return restored


def cancel_reminder(keyword: str | None = None) -> list[dict[str, Any]]:
    key = strip_diacritics((keyword or "").strip().lower())
    removed: list[dict[str, Any]] = []
    with ACTIVE_REMINDERS_LOCK:
        for item in list(ACTIVE_REMINDERS):
            # v7.2: dùng .get() - mục nhắc nhở có thể thiếu "task" (file
            # reminders.json bị sửa tay/ghi bởi bản cũ). Trước đây index thẳng
            # làm cancel_reminder ném KeyError và SẬP cả lệnh "huy nhac".
            task = str(item.get("task") or "")
            if key and key not in strip_diacritics(task.lower()) and key != item.get("id"):
                continue
            timer = item.get("timer")
            cancel = getattr(timer, "cancel", None)
            if callable(cancel):
                try:
                    cancel()
                except Exception as e:  # pragma: no cover - timer lạ không được làm hỏng lệnh huỷ
                    logger.warning("Không huỷ được timer của nhắc nhở %r: %s", item.get("id"), e)
            try:
                ACTIVE_REMINDERS.remove(item)
            except ValueError:  # pragma: no cover - đã bị gỡ ở nơi khác
                pass
            removed.append(item)
    if removed:
        _save_reminders()
    return removed


def _fire_reminder(task: str, reminder_id: str | None = None) -> None:
    if reminder_id is not None:
        with ACTIVE_REMINDERS_LOCK:
            for item in list(ACTIVE_REMINDERS):
                if item.get("id") == reminder_id:
                    ACTIVE_REMINDERS.remove(item)
        _save_reminders()
    respond(f"Đến giờ rồi. Nhắc bạn: {task}")
    try:
        if SYSTEM == "Windows":
            safe = _escape_powershell_single_quoted(task)
            ps = (
                "Add-Type -AssemblyName PresentationFramework; "
                f"[System.Windows.MessageBox]::Show('{safe}','Nhắc nhở')"
            )
            _popen(["powershell", "-NoProfile", "-Command", ps])
        elif SYSTEM == "Darwin":
            safe = _escape_osascript(task)
            _popen(["osascript", "-e", f'display notification "{safe}" with title "Nhắc nhở"'])
        else:
            _run_first_available([["notify-send", "Nhắc nhở", task]])
    except Exception as e:
        logger.warning("Không hiện được popup nhắc nhở: %s", e)


def action_set_reminder(target: str, data: dict[str, Any] | None = None) -> bool:
    time_info = (data or {}).get("time") or {"type": None}
    task = target or "báo thức"
    now = datetime.datetime.now()

    if time_info.get("type") == "delay":
        minutes = float(time_info.get("minutes", 5))
        run_at = now + datetime.timedelta(minutes=minutes)
    elif time_info.get("type") == "clock":
        hour = max(0, min(23, int(time_info.get("hour", 7))))
        minute = max(0, min(59, int(time_info.get("minute", 0))))
        run_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        run_at += datetime.timedelta(days=max(0, int(time_info.get("day_offset") or 0)))
        if run_at <= now:
            run_at += datetime.timedelta(days=1)
    else:
        respond("Bạn muốn tôi nhắc vào lúc nào ạ?")
        return False

    delay = (run_at - now).total_seconds()
    if delay <= 0:
        respond("Thời điểm bạn đưa đã qua mất rồi.")
        return False

    _schedule_reminder(task, run_at)
    logger.info("Đặt nhắc nhở: %s lúc %s", task, run_at)
    respond(f"Đã đặt nhắc nhở {task} vào lúc {run_at.hour} giờ {run_at.minute} phút.")
    return True


def action_unknown(_target: str) -> bool:
    safe_print(
        "Xin lỗi, tôi chỉ hỗ trợ mở web / ứng dụng / file, điều khiển hệ "
        "thống, tìm kiếm, phát nhạc, đặt nhắc nhở, xem thời tiết/giờ và "
        "tính toán. Bạn thử nói cụ thể hơn nhé."
    )
    return False


# --- Dispatcher ---
HANDLERS = {
    "open_website": action_open_website,
    "open_app": action_open_app,
    "open_file": action_open_file,
    "system_control": action_system_control,
    "search_web": action_search_web,
    "play_media": action_play_media,
    "set_reminder": action_set_reminder,
    "get_weather": action_get_weather,
    "get_datetime": action_get_datetime,
    "calculate": action_calculate,
    "chitchat": action_chitchat,
}

_HANDLERS_WITH_DATA = {"set_reminder", "calculate"}


def execute_command(intent_json: dict[str, Any] | str) -> bool:
    if isinstance(intent_json, str):
        try:
            intent_json = json.loads(intent_json)
        except json.JSONDecodeError:
            safe_print("[LỖI] Đầu vào không phải JSON hợp lệ.")
            return False

    if not isinstance(intent_json, dict):
        safe_print("[LỖI] Đầu vào phải là dict hoặc JSON string.")
        return False

    intent = intent_json.get("intent")
    target = (intent_json.get("target") or "").strip()
    try:
        confidence = float(intent_json.get("confidence", 1.0))
    except (TypeError, ValueError):
        confidence = 0.0

    handler = HANDLERS.get(intent)
    if handler is None:
        safe_print(f"[TỪ CHỐI] Không hiểu ý định: {intent}")
        logger.warning("Không hiểu ý định: %s", intent)
        return action_unknown(target)

    if confidence < CONFIDENCE_THRESHOLD:
        safe_print(f"[TỪ CHỐI] Độ tự tin quá thấp ({confidence:.2f}). Bạn nói rõ hơn giúp tôi nhé.")
        logger.info("Từ chối vì độ tự tin thấp: %.2f < %.2f", confidence, CONFIDENCE_THRESHOLD)
        return False

    if intent in _HANDLERS_WITH_DATA:
        return handler(target, intent_json)
    return handler(target)


if __name__ == "__main__":
    setup_console()
    demo = {"intent": "open_website", "target": "google", "confidence": 0.95}
    safe_print(f"Demo: {demo}")
    execute_command(demo)
