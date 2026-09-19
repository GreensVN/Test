"""
tts.py - Text-To-Speech, tự động chọn engine khả dụng

v7.0 nâng cấp:
- Type hints, pathlib, thread-safe engine cache
- Thêm timeout, cleanup tốt hơn cho file tạm
- Sửa lỗi race khi xoá file tạm đang phát
- Thêm logging debug chi tiết
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from paths import data_path
from platform_utils import is_wsl, safe_print, setup_console

SYSTEM = platform.system()

ENABLED: bool = True
ENGINE: str = "auto"

_engine_cache: Any | None = None
_resolved_engine: Callable[[str], bool] | None = None
_engine_lock = threading.RLock()
_speak_lock = threading.Lock()

# v7.4: kho giọng chuyển sang THƯ MỤC DỮ LIỆU (paths.py) - trước đây nó nằm cạnh
# file mã nguồn, nghĩa là bản `pip install .` bắt người dùng bỏ mp3 vào
# site-packages (nơi thường chỉ đọc và bị xoá khi nâng cấp). Thư mục cũ vẫn được
# ĐỌC tiếp để ai đã có sẵn voice_cache/ từ bản 6.x không mất gì.
VOICE_CACHE_DIR = data_path("voice_cache")
VOICE_CACHE_DIR_LEGACY = Path(__file__).resolve().parent / "voice_cache"


def _cache_dirs() -> list[Path]:
    """Nơi có thể chứa voice_cache, theo thứ tự ưu tiên (user dir trước)."""
    out = []
    for d in (VOICE_CACHE_DIR, VOICE_CACHE_DIR_LEGACY):
        d = Path(str(d))
        if d.is_dir() and d not in out:
            out.append(d)
    return out
_voice_cache_index: dict[str, Path] | None = None

logger = logging.getLogger(__name__)


def _load_voice_cache() -> dict[str, Path]:
    """index.csv trong mỗi thư mục cache -> {key_noi_dung: file mp3}.

    Đọc ở Cả HAI nơi (thư mục người dùng trước), file nào cầm trước thì thắng -
    không còn cách nào “đổ” một file .csv sang Path: đường dẫn được kiểm tra
    tồn tại trước khi đưa vào bảng tra.
    """
    global _voice_cache_index
    if _voice_cache_index is not None:
        return _voice_cache_index

    import csv

    _voice_cache_index = {}
    for directory in _cache_dirs():
        index_path = directory / "index.csv"
        if not index_path.is_file():
            continue
        try:
            with index_path.open(newline="", encoding="utf-8") as f:
                for row in csv.reader(f):
                    if len(row) < 2:
                        continue
                    key, fname = row[0], row[1]
                    full = directory / fname
                    if full.is_file():
                        _voice_cache_index.setdefault(key, full)
        except OSError as e:
            logger.debug("Không đọc được voice_cache index: %s", e)
    return _voice_cache_index


def _play_audio(path: str | Path) -> bool:
    p = Path(path)
    if not p.exists():
        return False

    # Ưu tiên playsound vì nó block tới khi phát xong
    try:
        from playsound import playsound

        playsound(str(p))
        return True
    except ImportError:
        pass
    except Exception as e:
        logger.debug("playsound lỗi, thử fallback: %s", e)

    try:
        if SYSTEM == "Windows":
            # os.startfile la API chuan de mo file bang ung dung mac dinh cua
            # Windows - khong co chuoi nguoi dung nao duoc ghep vao shell.
            os.startfile(str(p))  # type: ignore[attr-defined]  # noqa: S606
        elif SYSTEM == "Darwin":
            subprocess.run(["afplay", str(p)], check=True, timeout=30)
        else:
            # Thử nhiều player
            for player in (["mpg123", "-q", str(p)], ["mpg321", "-q", str(p)], ["aplay", str(p)]):
                try:
                    subprocess.run(player, check=True, timeout=30)
                    return True
                except (FileNotFoundError, subprocess.CalledProcessError):
                    continue
            return False
        return True
    except Exception as e:
        logger.debug("Phát audio fallback lỗi: %s", e)
        return False


def _speak_cache(text: str) -> bool:
    cache = _load_voice_cache()
    path = cache.get(text.strip().lower())
    return _play_audio(path) if path else False


def _speak_piper(text: str) -> bool:
    """Dùng VieNeu-TTS (giữ tên hàm cũ để tương thích)."""
    try:
        import giong_noi_ai
    except Exception as e:
        logger.debug("Không import được giong_noi_ai: %s", e)
        return False
    try:
        if not giong_noi_ai.is_available():
            return False
        return bool(giong_noi_ai.speak(text))
    except Exception as e:
        logger.debug("giong_noi_ai.speak lỗi: %s", e)
        return False


def _speak_nc(text: str) -> bool:
    try:
        import giong_nc
    except Exception:
        return False
    try:
        if not giong_nc.is_available():
            return False
        return bool(giong_nc.speak(text))
    except Exception:
        return False


def _speak_pyttsx3(text: str) -> bool:
    global _engine_cache
    with _engine_lock:
        try:
            import pyttsx3

            if _engine_cache is None:
                _engine_cache = pyttsx3.init()
                _engine_cache.setProperty("rate", 170)
                _engine_cache.setProperty("volume", 1.0)
                try:
                    for voice in _engine_cache.getProperty("voices"):
                        info = f"{voice.id} {getattr(voice, 'name', '')}".lower()
                        if "vietnam" in info or "vi-vn" in info:
                            _engine_cache.setProperty("voice", voice.id)
                            break
                except Exception as voice_error:
                    logger.debug("Không chọn được giọng tiếng Việt: %s", voice_error)
            _engine_cache.say(text)
            _engine_cache.runAndWait()
            return True
        except Exception as e:
            logger.debug("pyttsx3 lỗi: %s", e)
            _engine_cache = None
            return False


def _speak_sapi(text: str) -> bool:
    if SYSTEM == "Windows":
        exe = "powershell"
    elif SYSTEM == "Linux" and is_wsl():
        exe = "powershell.exe"
    else:
        return False
    try:
        safe = text.replace("'", "''")
        ps = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.Speak('{safe}')"
        )
        subprocess.run(
            [exe, "-NoProfile", "-Command", ps],
            check=True,
            capture_output=True,
            timeout=20,
        )
        return True
    except Exception as e:
        logger.debug("SAPI lỗi: %s", e)
        return False


def _speak_macos(text: str) -> bool:
    if SYSTEM != "Darwin":
        return False
    try:
        subprocess.run(["say", text], check=True, timeout=20)
        return True
    except Exception as e:
        logger.debug("macOS say lỗi: %s", e)
        return False


def _speak_gtts(text: str) -> bool:
    try:
        from gtts import gTTS

        tmp_path = Path(tempfile.gettempdir()) / f"tro_ly_tts_{uuid.uuid4().hex}.mp3"
        gTTS(text=text, lang="vi").save(str(tmp_path))
        ok = _play_audio(tmp_path)
        try:
            # Đợi 1 chút trước khi xoá nếu dùng os.startfile (không block)
            if SYSTEM == "Windows":
                import time

                time.sleep(0.5)
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return ok
    except Exception as e:
        logger.debug("gTTS lỗi: %s", e)
        return False


def _engine_order() -> list:
    """Danh sách hàm engine sẽ thử, theo biến ENGINE hiện tại.

    Các engine được LẤY THEO TÊN trong module-global lúc gọi (không dựng một
    tuple cố định ở đầu file) - nhờ vậy test có thể monkeypatch từng engine,
    và người dùng chèn thêm engine mới mà không phải sửa speak().
    """
    explicit = {
        "piper": [_speak_piper],
        "nc": [_speak_nc],
        "pyttsx3": [_speak_pyttsx3],
        "sapi": [_speak_sapi],
        "gtts": [_speak_gtts],
        "print": [],  # chỉ in chữ, không đọc
    }
    if ENGINE in explicit:
        return explicit[ENGINE]

    if ENGINE != "auto":
        # v7.2: tên engine sai trước đây bị hiểu nhầm là "auto" HOÀN TOÀN ÂM
        # THẦM - người dùng gõ --engine pipper vẫn thấy trợ lý chạy bình
        # thường nên không bao giờ biết mình viết sai. Ghi log kèm danh sách
        # hợp lệ để dễ chẩn đoán.
        logger.warning(
            "ENGINE=%r không hợp lệ -> dùng 'auto'. Hợp lệ: %s",
            ENGINE,
            ", ".join(sorted([*explicit, "auto"])),
        )

    if _resolved_engine is not None:
        return [_resolved_engine]
    return [_speak_piper, _speak_pyttsx3, _speak_sapi, _speak_macos, _speak_gtts]


def _try_engine(fn, text: str) -> bool:
    """Gọi một engine, coi mọi lỗi = 'engine này không đọc được' (không ném tiếp).

    TTS là tính năng PHỤ: lỗi pyttsx3/Windows SAPI không được phép làm chết lệnh
    mà người dùng vừa ra.
    """
    try:
        return bool(fn(text))
    except Exception as e:
        logger.debug("Engine %s lỗi: %s", getattr(fn, "__name__", str(fn)), e)
        return False


def speak(text: str, show: bool = True) -> None:
    global _resolved_engine

    if show:
        safe_print(f"[TRỢ LÝ] {text}")

    if not ENABLED or not text or not text.strip():
        return

    if _speak_cache(text):
        return

    with _speak_lock:
        for fn in _engine_order():
            if _try_engine(fn, text):
                _resolved_engine = fn
                return

        # Engine đã "chốt" (lưu từ lần trước) vừa hỏng giữa chừng - vd micro bị
        # rút, dịch vụ SAPI bị tắt. Thử lại các engine khác TRƯỚC KHI bỏ trống.
        if ENGINE == "auto" and _resolved_engine is not None:
            broken = _resolved_engine
            for fn in (
                _speak_piper,
                _speak_pyttsx3,
                _speak_sapi,
                _speak_macos,
                _speak_gtts,
            ):
                if fn is broken:
                    continue
                if _try_engine(fn, text):
                    _resolved_engine = fn
                    return
            _resolved_engine = None


def set_enabled(value: bool) -> None:
    global ENABLED
    ENABLED = bool(value)


def available_engines() -> list[str]:
    found: list[str] = []
    try:
        import giong_noi_ai

        if giong_noi_ai.is_available():
            found.append("giọng AI VieNeu-TTS v3-Turbo (offline, Apache 2.0)")
    except Exception:
        logger.debug("Không nạp được giong_noi_ai khi liệt kê engine", exc_info=True)

    try:
        import pyttsx3  # noqa: F401

        found.append("pyttsx3 (offline)")
    except ImportError:
        pass

    if SYSTEM == "Windows":
        found.append("Windows SAPI (có sẵn)")
    elif SYSTEM == "Linux" and is_wsl():
        found.append("Windows SAPI của host (qua WSL interop)")

    if SYSTEM == "Darwin":
        found.append("macOS say (có sẵn)")

    try:
        import gtts  # noqa: F401

        found.append("gTTS (cần internet)")
    except ImportError:
        pass

    cache = _load_voice_cache()
    if cache:
        found.insert(0, f"kho giọng sẵn ({len(cache)} câu)")

    return found or ["không có engine nào - sẽ chỉ in chữ"]


def is_available() -> bool:
    if _load_voice_cache():
        return True
    try:
        import pyttsx3  # noqa: F401

        return True
    except ImportError:
        pass
    if SYSTEM in ("Windows", "Darwin"):
        return True
    if SYSTEM == "Linux" and is_wsl():
        return True
    try:
        import gtts  # noqa: F401

        return True
    except ImportError:
        pass
    # Kiểm tra cả VieNeu
    try:
        import giong_noi_ai

        if giong_noi_ai.is_available():
            return True
    except Exception as e:
        logger.debug("Không kiểm tra được VieNeu: %s", e)
    return False


if __name__ == "__main__":
    setup_console()
    safe_print("Engine khả dụng trên máy này:")
    for e in available_engines():
        safe_print(f"  - {e}")
    safe_print("")
    speak("Xin chào, tôi là trợ lý ảo tiếng Việt của bạn")
