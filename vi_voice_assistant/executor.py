"""
executor.py v7.8
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
v7.7 nâng cấp:
- `cancel_reminder` ép kiểu keyword qua `as_text` (trước: `cancel_reminder(123)`
  nổ `AttributeError: 'int' object has no attribute 'strip'`).

v7.6 nâng cấp:
- `set_reminder` chịu được mọi kiểu `time` mà model/JSON gửi tới: trước đây
  `time: "3 phút"` (chuỗi, không phải dict) làm crash cả lệnh bằng
  ``AttributeError: 'str' object has no attribute 'get'``. Chuỗi/số được đưa qua
  `parse_time_expression`, và `minutes`/`hour`/`minute` kiểu rác không còn làm
  nổ `float()`/`int()` giữa chừng.
- Trợ lý KHÔNG QUÊN nội dung cần nhắc khi phải hỏi lại "nhắc vào lúc nào?": lời
  nhắc chờ được giữ 5 phút (`PENDING_REMINDER_TTL`), REPL nối câu trả lời thời
  điểm vào đúng việc đang hẹn thay vì đặt lại từ đầu với "báo thức".

v7.5 nâng cấp:
- `CONFIG, CONFIG_ERROR = load_config_safe()`: `config.json` hỏng không còn giết
  cả ứng dụng (trước đây `import executor` raise nên không chạy nổi lệnh nào, kể cả
  `--doctor`). Lỗi được ghi vào log và `main` in cảnh báo kèm đường dẫn cần sửa.

"""

from __future__ import annotations

import datetime
import difflib
import functools
import inspect
import json
import logging
import math
import os
import platform
import random
import re
import subprocess
import threading
import time
import urllib.parse
import uuid
import webbrowser
from pathlib import Path
from typing import Any, Callable

from config import load_config, load_config_safe
from paths import atomic_write_json, data_path
from platform_utils import (
    is_windows7_or_older,
    is_wsl,
    safe_print,
    setup_console,
    windows_version_label,
)
from text_utils import as_text, strip_diacritics

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

# v7.5: file config hong KHONG duoc giet ca ung dung. `load_config` o day chay
# luc import, nen truoc day mot dau phay thieu trong config.json -> RuntimeError
# tran ra truoc khi lenh nao kip chay (khi ca `vi-doctor`/`--help` cua module cung
# khong toi duoc). Gio dung ban mac dinh va ghi `CONFIG_ERROR` de `main` in canh
# bao - loi khong bi an, no chi khong con chan nguoi dung lam tiep.
CONFIG: dict[str, Any] = {}
CONFIG, CONFIG_ERROR = load_config_safe()
if CONFIG_ERROR:
    logger.warning("config.json không dùng được - chạy với giá trị mặc định: %s", CONFIG_ERROR)

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
# v7.3: --yes của CLI bật cờ này (xem set_auto_confirm). Mac dinh LUON hoi lai.
AUTO_CONFIRM = False
ACTIVE_REMINDERS_LOCK = threading.RLock()

BASE_DIR = Path(__file__).resolve().parent
REMINDERS_PATH = data_path("reminders.json")   # v7.3: xem paths.py

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


def set_auto_confirm(enabled: bool) -> bool:
    """Bật/tắt "không hỏi lại lệnh nguy hiểm" (cờ --yes của CLI). Trả về trạng thái mới.

    Tách thành hàm riêng (thay vì để main.py gán thẳng thuộc tính module) để
    caller khác - test, NLU, script - bật/tắt được và đọc lại được trạng thái.
    """
    global AUTO_CONFIRM
    AUTO_CONFIRM = bool(enabled)
    return AUTO_CONFIRM


def _confirm(prompt: str) -> bool:
    # --yes / AUTO_CONFIRM: cho pipeline tự động hoá. Vẫn in ra MỘT DÒNG để
    # trong log/terminal thấy rõ lệnh này đã KHÔNG được con người xác nhận.
    if AUTO_CONFIRM:
        safe_print(f"[TỰ XÁC NHẬN --yes] {prompt}")
        return True
    try:
        answer = input(f"[XÁC NHẬN] {prompt} (y/n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        # Xay ra khi chay trong CI/script (stdin dong/het) - truoc day chi in
        # "[HỦY] Không lấy được xác nhận" khiến người dùng tưởng mình bị từ chối.
        # Nay nêu nguyên nhân + đúng cách khắc phục (--yes).
        safe_print("\n[HUỶ] Không lấy được xác nhận (không có bàn phím tương tác) - huỷ để an toàn")
        safe_print("      (dùng --yes nếu bạn chắc chắn muốn chạy lệnh này)")
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


def _as_map(value: Any) -> dict[str, str]:
    """Một mục ``*_map`` trong config.json phải là dict.

    v7.4: trước đây hàm trả thẳng ``CONFIG.get(key, {})``, nên một file cấu hình
    bị lệch kiểu (viết ``"app_map_linux": null`` hoặc nhầm sang chuỗi) lọt qua
    im lặng rồi nổ ở chỗ không liên quan - người dùng chỉ thấy traceback khó hiểu.
    Nay coi mục lệch kiểu là TRỐNG để rơi vào nhánh "chưa cấu hình" vốn đã có sẵn
    hướng dẫn sửa đúng tên key.
    """
    if isinstance(value, dict):
        if all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            return value          # giu nguyen doi tuong: day la duong nong, goi lai moi lenh
        return {str(k): str(v) for k, v in value.items()}   # so/ten khong phai chuoi -> ep kieu
    if value is not None and value != "":
        logger.warning("Mục map trong config.json không phải dict (%s) - coi như trống",
                       type(value).__name__)
    return {}


def _app_map_for_platform() -> dict[str, str]:
    if SYSTEM == "Darwin":
        return _as_map(CONFIG.get("app_map_macos", {}))
    if SYSTEM == "Windows":
        return _as_map(CONFIG.get("app_map_windows", {}))
    return _as_map(CONFIG.get("app_map_linux", {}))


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


_SYSTEM_HANDLERS: dict[str, Callable[..., Any]] = {
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


# --- Nhịp lặp (v7.9) --------------------------------------------------------
# "mỗi ngày" là một thứ mà người dùng hỏi rất nhiều mà bản trước không có nơi
# để lưu: mỗi lần đến giờ thì nhắc xong là XOÁ, nên "uống thuốc mỗi ngày" chỉ
# nhắc đúng MỘT lần rồi im - im đúng kiểu lỗi, vì người dùng tin là đã hẹn cả
# tháng. Nay nhắc tự hẹn lại lần kế.
_REPEAT_KINDS = ("daily", "weekly", "monthly")
# threading.Timer trên Windows trần ở ~49.7 ngày; chia nhỏ để không phụ thuộc.
_MAX_TIMER_SECONDS = 24 * 3600.0
_WEEKDAY_NAMES = ("thứ hai", "thứ ba", "thứ tư", "thứ năm", "thứ sáu",
                  "thứ bảy", "chủ nhật")


def _coerce_repeat(repeat: object) -> dict[str, Any] | None:
    """Chấp nhận mọi kiểu `repeat` mà model/JSON gửi tới, trả về dict chuẩn.

    Không có `_coerce_repeat` thì `reminders.json` do người dùng sửa tay (hoặc
    bản cũ ghi ra) có thể mang bất kỳ thứ gì và `_fire_reminder` sẽ lỗi NGAY
    lúc bắn nhắc - tức đúng lúc người dùng cần nó nhất.
    """
    if not isinstance(repeat, dict):
        return None
    kind = repeat.get("kind")
    if kind not in _REPEAT_KINDS:
        return None
    clean: dict[str, Any] = {"kind": kind}
    if kind == "weekly":
        weekday = repeat.get("weekday")
        if isinstance(weekday, bool) or not isinstance(weekday, int):
            return clean  # lặp hằng tuần, chưa chốt thứ mấy
        if not 0 <= weekday <= 6:
            return clean
        clean["weekday"] = weekday
    return clean


def _next_occurrence(run_at: datetime.datetime,
                     repeat: dict[str, Any]) -> datetime.datetime | None:
    """Lần xuất hiện KẾ TIẾP sau `run_at`. None nếu không tính được.

    Luôn trả về mốc **sau** `run_at`. Nếu vì lý do gì đó trả về mốc đã qua,
    `_schedule_reminder` từ chối đặt (delay <= 0) và chuỗi lặp dừng lại - tức
    lỗi sẽ thày một nhắc bị bỏ, chứ không thành vòng lặp treo máy.
    """
    kind = repeat.get("kind")
    if kind == "daily":
        nxt = run_at + datetime.timedelta(days=1)
    elif kind == "weekly":
        weekday = repeat.get("weekday")
        if weekday is None:
            nxt = run_at + datetime.timedelta(days=7)
        else:
            # run_at.weekday() là 0=thứ hai; weekday của người dùng cùng hệ.
            ahead = (weekday - run_at.weekday()) % 7 or 7
            nxt = run_at + datetime.timedelta(days=ahead)
    elif kind == "monthly":
        year, month = run_at.year, run_at.month + 1
        if month > 12:
            year, month = year + 1, 1
        # Ngày 31 tháng 2 không tồn tại -> lùi về ngày cuối tháng đó thay vì nổ.
        day = min(run_at.day, _days_in_month(year, month))
        nxt = run_at.replace(year=year, month=month, day=day)
    else:
        return None
    return nxt if nxt > run_at else None


def _next_future_occurrence(run_at: datetime.datetime, repeat: dict[str, Any],
                            now: datetime.datetime) -> datetime.datetime | None:
    """Lần xuất hiện đầu tiên SAU `now`, cuộn từng bước.

    Vì sao phải cuộn vòng chứ không gọi `_next_occurrence` một lần: máy tắt 3
    ngày thì lịch "mỗi ngày" cần cuộn 3 bước mới tới tương lai. Cuộn đúng MỘT
    bước thì vẫn nằm trong quá khứ, `_schedule_reminder` từ chối, và cả chuỗi
    biến mất - đúng cái hỏng mà hàm này sinh ra để chặn.

    Có chặn trên để đồng hồ hỏng (lùi hàng năm) không quay vô hạn.
    """
    nxt = run_at
    for _ in range(400):
        step = _next_occurrence(nxt, repeat)
        if step is None:
            return None
        nxt = step
        if nxt > now:
            return nxt
    logger.warning("Không cuộn được tới lần lặp kế tiếp cho %r", repeat)
    return None


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (datetime.date(year, month + 1, 1)
            - datetime.date(year, month, 1)).days


def _repeat_label(repeat: dict[str, Any] | None) -> str:
    """Cách nói tiếng Việt của nhịp lặp, để câu xác nhận nói ra được."""
    if not repeat:
        return ""
    kind = repeat.get("kind")
    if kind == "daily":
        return "mỗi ngày"
    if kind == "monthly":
        return "mỗi tháng"
    weekday = repeat.get("weekday")
    if kind == "weekly" and isinstance(weekday, int) and not isinstance(weekday, bool):
        return f"mỗi {_WEEKDAY_NAMES[weekday]}"
    return "mỗi tuần"



def _save_reminders() -> None:
    try:
        with ACTIVE_REMINDERS_LOCK:
            data: list[dict[str, Any]] = []
            for item in ACTIVE_REMINDERS:
                at = _reminder_at(item)
                if at is None:
                    logger.warning(
                        "Bỏ qua nhắc nhở không hợp lệ khi lưu (thiếu mốc giờ): %r", item
                    )
                    continue
                entry = {"id": item.get("id"), "task": item.get("task", ""),
                         "at": at.isoformat()}
                repeat = _coerce_repeat(item.get("repeat"))
                if repeat:
                    entry["repeat"] = repeat
                data.append(entry)
        # Atomic write (paths.atomic_write_json) - chap nhận ca Path lan str de
        # test monkeypatch REMINDERS_PATH duoc de dang.
        atomic_write_json(REMINDERS_PATH, data, prefix=".reminders_tmp_")
    except OSError as e:
        logger.warning("Không lưu được danh sách nhắc nhở: %s", e)


def _arm_timer(task: str, delay: float, reminder_id: str,
               repeat: dict[str, Any] | None,
               continuation: bool = False) -> threading.Timer:
    """Bật một chặng đếm ngược.

    `continuation=True` là CHẶNG NỐI TIẾP của một lịch dài hơn trần Timer (lặp
    hằng tháng), KHÔNG phải lần nhắc thật: nó chỉ bật chặng kế tiếp, không báo,
    không hẹn lại. Không phân biệt thì mỗi chặng bắn một lần nhắc và hẹn thêm
    một lịch mới - nhắc hằng tháng thành nhắc vài lần mỗi tháng.
    """
    timer = threading.Timer(delay, _fire_reminder,
                            args=[task, reminder_id, repeat, continuation])
    timer.daemon = True
    timer.start()
    return timer


def _schedule_reminder(task: str, run_at: datetime.datetime, persist: bool = True,
                       repeat: object = None) -> str | None:
    clean_repeat = _coerce_repeat(repeat)
    delay = (run_at - datetime.datetime.now()).total_seconds()
    if delay <= 0:
        return None
    reminder_id = f"{run_at.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    # v7.8: ĐĂNG KÝ MỤC VÀO DANH SÁCH TRƯỚC KHI BẬT TIMER. Bản cũ `timer.start()`
    # đứng trước, nên với độ trễ rất ngắn (vài trăm phần nghìn giây, hợp lệ khi
    # `--json` gửi "0.001" phút) timer nổ trước lúc mục được thêm vào
    # ACTIVE_REMINDERS: `_fire_reminder` quét không thấy id của mình nên không
    # gỡ gì, rồi mục mới được thêm vào - một lời nhắc "ma" không bao giờ tắt,
    # cứ nằm trong `nhac nho` tới cuối phiên.
    entry: dict[str, Any] = {"id": reminder_id, "task": task, "at": run_at,
                             "timer": None}
    if clean_repeat:
        entry["repeat"] = clean_repeat
    with ACTIVE_REMINDERS_LOCK:
        ACTIVE_REMINDERS.append(entry)
    # Timer dài hơn trần của threading (Windows ~49.7 ngày) nổ OverflowError
    # lúc khởi tạo; cắt thành nhiều chặng ngắn (chặng sau nối tiếp ở
    # `_fire_reminder` nhờ `repeat`).
    while delay > _MAX_TIMER_SECONDS:
        _arm_timer(task, _MAX_TIMER_SECONDS, reminder_id, clean_repeat,
                   continuation=True)
        delay -= _MAX_TIMER_SECONDS
    entry["timer"] = _arm_timer(task, delay, reminder_id, clean_repeat)
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
        repeat = _coerce_repeat(item.get("repeat"))
        # v7.9: máy tắt rồi mở lại, mốc giờ lặp đã trôi qua trong lúc đó
        # (ngủ qua giờ uống thuốc chẳng hạn). Không cuộn tới lần kế thì lời nhắc
        # bị bỏ vĩnh viễn - và với "mỗi ngày" thì mất luôn cả chuỗi.
        if repeat and run_at <= datetime.datetime.now():
            rolled = _next_future_occurrence(run_at, repeat,
                                             datetime.datetime.now())
            if rolled is not None:
                run_at = rolled
        if _schedule_reminder(task, run_at, persist=False, repeat=repeat):
            restored += 1
    _save_reminders()
    if restored:
        logger.info("Đã khôi phục %d nhắc nhở còn hạn", restored)
    return restored


def cancel_reminder(keyword: object = None) -> list[dict[str, Any]]:
    # `as_text` (v7.5) chu khong phai `.strip()` tran: keyword den tu JSON nguoi
    # dung viet hoac tu script co the la so/None, va `(123 or "")` khong co
    # `.strip` -> sap ca lenh "huy nhac", tuc la mat luon cach huy mot lich sai.
    key = strip_diacritics(as_text(keyword).strip().lower())
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


def _fire_reminder(task: str, reminder_id: str | None = None,
                   repeat: object = None, continuation: bool = False) -> None:
    clean_repeat = _coerce_repeat(repeat)
    if continuation:
        # Chặng nối tiếp: chuyển sang chặng kế tiếp, KHÔNG nhắc và KHÔNG hẹn lại.
        _arm_timer(task, _MAX_TIMER_SECONDS, reminder_id or "", clean_repeat,
                   continuation=True)
        return
    fired_at: datetime.datetime | None = None
    if reminder_id is not None:
        with ACTIVE_REMINDERS_LOCK:
            for item in list(ACTIVE_REMINDERS):
                if item.get("id") == reminder_id:
                    fired_at = _reminder_at(item)
                    ACTIVE_REMINDERS.remove(item)
        # v7.9: nhắc có nhịp lặp tự hẹn lại lần kế thay vì biến mất. Làm
        # TRƯỚC khi respond/popup để người dùng đang bị vỗ vẫn một giây mà
        # `reminders.json` lỡ ghi hỏng không mất luôn lịch đã hẹn.
        #
        # `repeat` PHẢI truyền LẠI vào lịch mới. Bản đầu chỉ dùng nó để tính mốc
        # kế tiếp rồi bỏ, nên nhắc hằng ngày chỉ nhắc ĐÚNG HAI LẦN rồi hạ
        # xuống thành nhắc một lần - hỏng đúng kiểu khó phát hiện nhất, vì cả
        # tháng đầu vẫn chạy ngon.
        nxt = _next_occurrence(fired_at, clean_repeat) if (
            fired_at is not None and clean_repeat) else None
        if nxt is not None and _schedule_reminder(task, nxt,
                                                  repeat=clean_repeat) is None:
            nxt = None
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


# --- Thời điểm nhắc: chấp nhận dữ liệu THẬT, không phải dữ liệu lý tưởng ------

# Một lời nhắc đang chờ người dùng trả lời "lúc nào?". Giữ 5 phút là đủ cho một
# lượt gõ tiếp theo mà không để treo cả buổi: hết hạn thì câu nói kế tiếp được
# xử lý bình thường, không bị "nối" vào chuyện đã quên từ lâu.
PENDING_REMINDER_TTL = 300.0
_PENDING_LOCK = threading.Lock()
PENDING_REMINDER: dict[str, Any] | None = None


def _to_number(value: object, default: float, low: float, high: float) -> float:
    """Ép một giá trị bất kỳ về số trong đoạn cho phép; hỏng thì dùng `default`.

    `float(time_info["minutes"])` với `minutes` là "5 phút" hay None ném ValueError
    ra ngoài handler, và người dùng chỉ thấy "[LỖI] ...". Ở đây mọi kiểu rác đều
    có đường về mặc định hợp lệ - đúng tinh thần v7.5 (điểm vào công cộng chịu
    được dữ liệu thật).
    """
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):  # NaN / inf
        return default
    return max(low, min(high, number))


def _coerce_time_info(raw: object) -> dict[str, Any]:
    """Trả `time` về dict chuẩn; chuỗi/số thì đưa qua `parse_time_expression`.

    Định dạng chuẩn là ``{"type": "delay"|"clock", ...}`` do NLU sinh ra, nhưng
    `execute_command` cũng nhận JSON người dùng tự viết (`--json`), và ở đó
    ``"time": "3 phút nữa"`` là chuyện bình thường.
    """
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {"type": None}
    text = str(raw).strip()
    if not text:
        return {"type": None}
    try:
        from intent_model import parse_time_expression

        parsed = parse_time_expression(text)
    except Exception as e:  # module lite/model hỏng cũng phải còn đường đặt lịch
        logger.debug("parse_time_expression(%r) lỗi: %s", text, e)
        parsed = None
    if isinstance(parsed, dict) and parsed.get("type"):
        return parsed
    try:
        minutes = float(text.replace(",", "."))
    except ValueError:
        return {"type": None}
    # Con số trần: "3" -> 3 phút. Chọn đơn vị này vì nó là thứ người dùng gõ khi
    # nói vội, và `minutes` cũng là đơn vị nội bộ của `delay`.
    return {"type": "delay", "minutes": minutes}


def _reminder_when(time_info: dict[str, Any], now: datetime.datetime) -> datetime.datetime | None:
    """Tính thời điểm chạy từ `time_info`; None nếu chưa đủ thông tin để nhắc."""
    kind = time_info.get("type")
    if kind == "delay":
        minutes = _to_number(time_info.get("minutes"), 5.0, 0.0, 366 * 24 * 60)
        return now + datetime.timedelta(minutes=minutes)
    if kind == "clock":
        hour = int(_to_number(time_info.get("hour"), 7.0, 0.0, 23.0))
        minute = int(_to_number(time_info.get("minute"), 0.0, 0.0, 59.0))
        run_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        day_offset = int(_to_number(time_info.get("day_offset"), 0.0, 0.0, 3660.0))
        run_at += datetime.timedelta(days=day_offset)
        if run_at <= now:
            run_at += datetime.timedelta(days=1)
        return run_at
    return None


def _remember_pending_reminder(task: str, repeat: object = None) -> None:
    global PENDING_REMINDER
    with _PENDING_LOCK:
        PENDING_REMINDER = {"task": task, "until": time.monotonic() + PENDING_REMINDER_TTL}
        # v7.9: "mỗi ngày" mà không nói giờ thì hỏi lại giờ - nhưng phải GIỮ
        # nhịp lặp qua câu hỏi, nếu không "uống thuốc mỗi ngày" rồi trả lời
        # "8 giờ" sẽ ra một lời nhắc MỘT LẦN, đúng thứ người dùng đã tin là
        # hằng ngày.
        clean_repeat = _coerce_repeat(repeat)
        if clean_repeat:
            PENDING_REMINDER["repeat"] = clean_repeat


def _pop_pending_reminder_full() -> dict[str, Any] | None:
    """Lấy trạng thái chờ đầy đủ (kèm nhịp lặp) rồi xoá; None nếu hết hạn."""
    global PENDING_REMINDER
    with _PENDING_LOCK:
        pending = PENDING_REMINDER
        PENDING_REMINDER = None
    if not pending or pending.get("until", 0) < time.monotonic():
        return None
    return pending


def _pop_pending_reminder() -> str | None:
    """Lấy nội dung đang chờ (và xoá khỏi trạng thái); None nếu không có/hết hạn."""
    pending = _pop_pending_reminder_full()
    if not pending:
        return None
    task = pending.get("task")
    return str(task) if task else None


def clear_pending_reminder() -> None:
    """Quên lời nhắc đang chờ (REPL dùng khi người đổi chủ đề hoặc gõ 'quên')."""
    global PENDING_REMINDER
    with _PENDING_LOCK:
        PENDING_REMINDER = None


def pending_reminder() -> dict[str, Any] | None:
    """Bản sao trạng thái chờ, để REPL/test biết là còn câu hỏi đang treo."""
    with _PENDING_LOCK:
        return dict(PENDING_REMINDER) if PENDING_REMINDER else None


def try_complete_pending_reminder(text: object, dry_run: bool = False) -> bool | None:
    """Nối câu trả lời thời điểm vào lời nhắc đang chờ.

    Trả về None khi KHÔNG có gì đang chờ hoặc câu vừa nói không chứa thời điểm
    (khi đó câu nói được xử lý như bình thường); True/False là kết quả đặt lịch.
    """
    time_info = _coerce_time_info(text)
    if not time_info.get("type"):
        if pending_reminder():
            _pop_pending_reminder()  # nguoi dung noi chuyen khac: dung "no" vao do
        return None
    pending = _pop_pending_reminder_full()
    if not pending or not pending.get("task"):
        return None
    task = str(pending["task"])
    repeat = _coerce_repeat(pending.get("repeat"))
    now = datetime.datetime.now()
    run_at = _reminder_when(time_info, now)
    if run_at is None:
        respond("Bạn muốn tôi nhắc vào lúc nào ạ?")
        _remember_pending_reminder(task, repeat)
        return False
    delay = (run_at - now).total_seconds()
    if delay <= 0:
        respond("Thời điểm bạn đưa đã qua mất rồi.")
        return False
    if dry_run:
        safe_print(f"   [TEST] Sẽ nhắc {task!r} lúc {run_at:%H:%M} (chế độ test: không đặt lịch)")
        return True
    _schedule_reminder(task, run_at, repeat=repeat)
    logger.info("Đặt nhắc nhở (trả lời sau khi hỏi lại): %s lúc %s", task, run_at)
    respond(_reminder_confirmation(task, run_at, repeat))
    return True


def _reminder_confirmation(task: str, run_at: datetime.datetime,
                           repeat: dict[str, Any] | None) -> str:
    """Câu xác nhận đặt nhắc. Có nhịp lặp thì PHẢI nói ra, không nói thì
    người dùng tưởng mình đã hẹn cả tháng trong khi thực ra chỉ một lần."""
    base = f"Đã đặt nhắc nhở {task} vào lúc {run_at.hour} giờ {run_at.minute} phút."
    label = _repeat_label(repeat)
    return f"{base} Lặp lại {label}." if label else base


def action_set_reminder(target: str, data: dict[str, Any] | None = None) -> bool:
    data = data or {}
    time_info = _coerce_time_info(data.get("time"))
    repeat = _coerce_repeat(data.get("repeat"))
    task = target or "báo thức"
    now = datetime.datetime.now()

    run_at = _reminder_when(time_info, now)
    if run_at is None:
        # Chua co thoi diem thi giu lai noi dung: hoi "luc nao?" roi bon sau
        # "5 phut nua" la luong tu nhien cua cuoc tro chuyen. Nhịp lặp đi kèm
        # để câu trả lời sau vẫn lặp lại được.
        _remember_pending_reminder(task, repeat)
        respond("Bạn muốn tôi nhắc vào lúc nào ạ?")
        return False

    delay = (run_at - now).total_seconds()
    if delay <= 0:
        respond("Thời điểm bạn đưa đã qua mất rồi.")
        return False

    clear_pending_reminder()
    _schedule_reminder(task, run_at, repeat=repeat)
    logger.info("Đặt nhắc nhở: %s lúc %s (lặp %s)", task, run_at, repeat or "không")
    respond(_reminder_confirmation(task, run_at, repeat))
    return True


def action_unknown(_target: str) -> bool:
    safe_print(
        "Xin lỗi, tôi chỉ hỗ trợ mở web / ứng dụng / file, điều khiển hệ "
        "thống, tìm kiếm, phát nhạc, đặt nhắc nhở, xem thời tiết/giờ và "
        "tính toán. Bạn thử nói cụ thể hơn nhé."
    )
    return False


# --- Dispatcher ---
HANDLERS: dict[str, Callable[..., Any]] = {
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

@functools.lru_cache(maxsize=64)
def _handler_wants_data(handler) -> bool:
    """Handler có nhận tham số thứ hai (toàn bộ intent_json) hay không.

    v7.4: trước đây danh sách này GHI TAY (``{"set_reminder", "calculate"}``).
    Thêm một handler 2 tham số mà quên ghi tên vào danh sách thì dispatcher gọi
    ``handler(target)`` -> TypeError lúc chạy, chỉ lộ ra khi người dùng gọi đúng
    intent đó. Suy ra từ chữ ký thật của hàm thì không thể lệch được nữa.
    """
    try:
        params = list(inspect.signature(handler).parameters.values())
    except (TypeError, ValueError):        # builtin/C-implemented -> khong doc duoc chu ky
        return False
    if any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in params):
        return True
    positional = [q for q in params if q.kind in (
        inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)]
    return len(positional) >= 2


def _handlers_with_data(handlers: dict[str, Any]) -> frozenset[str]:
    return frozenset(name for name, fn in handlers.items() if _handler_wants_data(fn))


# Giu tên cũ cho tương thích (bây giờ là giá trị TÍNH RA, không phải bảng tay).
_HANDLERS_WITH_DATA = _handlers_with_data(HANDLERS)


def _read_confidence(raw: object) -> float:
    """Đọc `confidence` từ intent, trả số HỢP LỆ hoặc -1.0 (= không tin được).

    v7.8 - SỬA LỖ BỎ QUA NGƯỠNG AN TOÀN. `json.loads` MẶC ĐỊNH CHẤP NHẬN
    ``NaN``/``Infinity`` (đó là mở rộng của JSON, không phải JSON chuẩn), nên
    ``--json '{"intent":"system_control","target":"shutdown","confidence":NaN}'``
    cho ``confidence = nan``. Mọi phép so sánh với NaN đều cho False, nên
    ``nan < CONFIDENCE_THRESHOLD`` là False và lệnh ĐI THẲNG qua - đúng cái
    cổng mà con số này sinh ra để chặn. Lệnh nguy hiểm vẫn phải qua
    ``_confirm``, nhưng ngưỡng "độ tự tin" thì đã bị vô hiệu hoàn toàn.
    Giá trị không phải số, NaN, ±inf, hoặc ngoài [0,1] đều trả -1.0 để rơi
    vào nhánh "từ chối" - im lặng chạy là thứ tệ hơn nói thẳng là không tin.
    """
    if isinstance(raw, bool) or raw is None:
        return -1.0
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return -1.0
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        return -1.0
    return value


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

    raw_intent = intent_json.get("intent")
    # Key tra bang PHAI la chuoi: intent = 42 hay None thi phai bao "khong hieu
    # y dinh", khong phai TypeError luc tra dict.
    intent = raw_intent if isinstance(raw_intent, str) else ""
    raw_target = intent_json.get("target")
    # Ep kieu TRUOC khi strip: `target` co the la so (model goi len hoac intent
    # khac truyen vao), ma `(2026 or "").strip()` thi nang nhu chinh no.
    target = "" if raw_target is None else str(raw_target).strip()
    raw_confidence = intent_json.get("confidence", 1.0)
    confidence = _read_confidence(raw_confidence)

    handler = HANDLERS.get(intent)
    if handler is None:
        safe_print(f"[TỪ CHỐI] Không hiểu ý định: {raw_intent}")
        logger.warning("Không hiểu ý định: %s", raw_intent)
        return action_unknown(target)

    if confidence < CONFIDENCE_THRESHOLD:
        if confidence < 0:
            # Giá trị -1 = "độ tự tin không đọc được" (sai kiểu/NaN/vô hạn), khác
            # hẳn "thấp thật". In "-1.00" như thể là đo được sẽ khiến người dùng
            # đi tìm lỗi ở model, trong khi lỗi nằm ở dữ liệu đầu vào.
            safe_print(
                "[TỪ CHỐI] Trường 'confidence' không hợp lệ (cần là số trong [0,1]). "
                "Kiểm tra lại JSON đầu vào."
            )
            logger.warning("Từ chối: confidence không hợp lệ = %r", raw_confidence)
        else:
            safe_print(
                f"[TỪ CHỐI] Độ tự tin quá thấp ({confidence:.2f}). "
                f"Bạn nói rõ hơn giúp tôi nhé."
            )
            logger.info("Từ chối vì độ tự tin thấp: %.2f < %.2f", confidence, CONFIDENCE_THRESHOLD)
        return False

    if _handler_wants_data(handler):
        return bool(handler(target, intent_json))
    return bool(handler(target))


if __name__ == "__main__":
    setup_console()
    demo = {"intent": "open_website", "target": "google", "confidence": 0.95}
    safe_print(f"Demo: {demo}")
    execute_command(demo)
