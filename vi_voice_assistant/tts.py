"""
tts.py - Text-To-Speech, tự động chọn engine khả dụng

v7.0 nâng cấp:
- Type hints, pathlib, thread-safe engine cache
- Thêm timeout, cleanup tốt hơn cho file tạm
- Sửa lỗi race khi xoá file tạm đang phát
- Thêm logging debug chi tiết
v7.4 nâng cấp:
- Kho giọng `voice_cache/` đi theo paths.py (thư mục dữ liệu của người dùng)
  thay vì nằm cạnh mã nguồn: bản `pip install .` không còn bắt người dùng đặt
  mp3 vào site-packages. Thư mục cũ vẫn được đọc nên ai đã có cache không mất
  gì. `index.csv` chỉ nhận dòng mà file được trỏ tới thật sự tồn tại.
v7.6 nâng cấp:
- THÊM CHIỀU NGƯỢC cho kho giọng: `prewarm()` và lệnh `python tts.py --cache`.
  Từ ngày `train_tts.py cache` bị bỏ, `voice_cache/` chỉ có ĐỌC mà không có cách
  TẠO - tài liệu bảo người dùng tự đặt mp3 vào đó rồi thôi. Writers mới: gTTS
  (mp3, cần mạng) / espeak-ng (wav, offline) / pyttsx3 (wav) / piper (wav) /
  `say` trên macOS (aiff). Không thêm dependency: module vẫn import được bằng
  thuần stdlib, thiếu thư viện nào thì writer đó đơn giản là không có mặt.
- `available_writers()`: engine biết PHÁT khác engine biết GHI RA FILE, và
  `vi-doctor` phải nói đúng cái thứ hai khi hướng dẫn tạo cache.
- `_file_written()` từ chối file 44 byte: espeak/pyttsx3 tạo xong file chỉ có
  header thì phải tính là lỗi, nếu không cache "đủ" nhưng phát ra im lặng.

v7.5 nâng cấp:
- `speak()` kiểm tra nội dung TRƯỚC khi in echo và chịu được kiểu khác chuỗi:
  `speak(123)` từng AttributeError, `speak(None)`/`speak("")` in "[TRỢ LÝ] None"
  rồi mới chịu dừng. Nhánh "engine đã chốt vừa hỏng" tách thành
  `_retry_other_engines()` - hanh vi GIUYÊN, chỉ tách để `speak` dưới ngưỡng C901=10.

"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Callable

from paths import atomic_write_text, data_path
from platform_utils import is_wsl, safe_print, setup_console
from text_utils import sanitize_filename

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
                    key, fname = _cache_key(row[0]), row[1]
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
    # Kham biu cu di qua _cache_key - cung mot ham voi ben ghi (prewarm), neu
    # khong mot ben them buoc chuan hoa la cache lem thinh linh "miss".
    cache = _load_voice_cache()
    path = cache.get(_cache_key(text))
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


# ---------------------------------------------------------------------------
# VIẾT FILE - nhịp còn thiếu: "máy có kho giọng" -> "sao tôi tạo không được"
# ---------------------------------------------------------------------------

# Một file .wav 44 byte = đúng block header, không có mẫu âm thanh nào.
_WAV_HEADER_BYTES = 44


class TTSWriteError(RuntimeError):
    """Writer không tạo được file, KÈM LÝ DO đọc được.

    Vì sao không trả `False` đơn thuần: `prewarm` cần in ra "vì sao câu này hỏng"
    (chưa cài thư viện / cần mạng / file chỉ có header). Một giá trị nhị phân
    khiến CLI chỉ còn cách đoán, và đoán sai thì người dùng cài nhầm thứ.
    """

VoiceWriter = Callable[[str, Path], bool]
WriterCheck = Callable[[], bool]
# Một writer = (tên, đuôi file, hàm ghi, hàm kiểm tra "máy này chạy được không").
WriterSpec = tuple[str, str, VoiceWriter, WriterCheck]


def _file_written(path: Path, minimum: int = _WAV_HEADER_BYTES + 1) -> bool:
    """File có thật VÀ có nội dung (nhiều hơn khối header rỗng).

    Đây là chỗ espeak/pyttsx3 "nói dối" nhất: lệnh chạy xong, file được tạo,
    nhưng chỉ chứa 44 byte header. Tính là thành công thì kho giọng xem như đủ
    mà phát ra im lặng - khó chịu hơn nhiều so với báo lỗi ngay từ đầu.
    """
    try:
        return path.is_file() and path.stat().st_size >= minimum
    except OSError:
        return False


def _module_present(name: str) -> bool:
    """Thư viện có cài đặt không, MA KHÔNG chạy code của nó (`find_spec`)."""
    try:
        return find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _binary_present(*names: str) -> bool:
    return any(shutil.which(n) for n in names)


def _run_hidden(cmd: list[str], timeout: float = 60.0,
                stdin_bytes: bytes | None = None) -> bool:
    """Chạy một lệnh con, ẩn output; False nếu không chạy được hoặc lỗi.

    Ẩn stdout/stderr vì đây là công cụ dòng lệnh: thông báo của espeak/piper
    không giúp gì cho người dùng mà còn chen vào trước dòng kết quả thật.
    """
    try:
        subprocess.run(
            cmd,
            check=True,
            timeout=timeout,
            input=stdin_bytes,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return True


def _write_gtts(text: str, out: Path) -> bool:
    """gTTS - chất lượng tốt nhất nhưng CẦN MẠNG (mp3). Ném TTSWriteError nếu hỏng."""
    try:
        from gtts import gTTS  # import cục bộ: module vẫn chạy khi chưa cài
    except ImportError as e:
        raise TTSWriteError("chưa cài gTTS (pip install gTTS)") from e
    try:
        gTTS(text=text, lang="vi").save(str(out))
    except Exception as e:  # loi mang/HTTP - giu nguyen thong bao that de in ra
        raise TTSWriteError(f"gTTS cần mạng mà gọi không được ({type(e).__name__})") from e
    if not _file_written(out, minimum=1):
        raise TTSWriteError("gTTS trả về file rỗng")
    return True


def _write_espeak(text: str, out: Path) -> bool:
    """espeak-ng/espeak - offline, có sẵn trên nhiều bản Linux."""
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if exe is None:
        raise TTSWriteError("không có espeak-ng/espeak trên PATH (apt install espeak-ng)")
    if not _run_hidden([exe, "-v", "vi", "-s", "165", "-w", str(out), text], timeout=30.0):
        raise TTSWriteError(f"{Path(exe).name} chạy lỗi hoặc hết giờ (30s)")
    if not _file_written(out):
        raise TTSWriteError(f"{Path(exe).name} chỉ tạo được file rỗng (44 byte header)")
    return True


def _write_pyttsx3(text: str, out: Path) -> bool:
    """pyttsx3 - engine mặc định của dự án, biết lưu ra file."""
    try:
        import pyttsx3
    except ImportError as e:
        raise TTSWriteError("chưa cài pyttsx3 (pip install pyttsx3)") from e
    try:
        engine = pyttsx3.init()
        engine.setProperty("rate", 170)
        engine.save_to_file(text, str(out))
        engine.runAndWait()
    except Exception as e:
        raise TTSWriteError(f"pyttsx3 lỗi khi ghi file ({type(e).__name__}: {e})") from e
    if not _file_written(out):
        raise TTSWriteError("pyttsx3 không tạo được file âm thanh (backend espeak/SAPI?)")
    return True


def _write_piper(text: str, out: Path) -> bool:
    """piper - nhanh, offline, nhưng cần model đã tải (`giong_noi_ai.py tai`)."""
    if not _binary_present("piper"):
        raise TTSWriteError("không có piper trên PATH (model: python giong_noi_ai.py tai)")
    if not _run_hidden(["piper", "--output_file", str(out)], stdin_bytes=text.encode("utf-8")):
        raise TTSWriteError("piper chạy lỗi - thường là chưa tải model giọng tiếng Việt")
    if not _file_written(out):
        raise TTSWriteError("piper trả về file rỗng")
    return True


def _write_say(text: str, out: Path) -> bool:
    """`say` của macOS - chỉ khả dụng trên Darwin."""
    if SYSTEM != "Darwin":
        raise TTSWriteError("`say` chỉ có trên macOS")
    if not _binary_present("say"):
        raise TTSWriteError("không tìm thấy lệnh `say`")
    if not _run_hidden(["say", "-o", str(out), text], timeout=30.0):
        raise TTSWriteError("`say -o` chạy lỗi")
    if not _file_written(out, minimum=1):
        raise TTSWriteError("`say` không tạo ra file")
    return True


# Thứ tự ưu tiên: mp3 (dễ phát nhất, không cần aplay) -> wav offline -> còn lại.
# Mỗi phần tử: (tên, đuôi file, hàm ghi, hàm kiểm tra máy này chạy được hay không)
_WRITERS: tuple[WriterSpec, ...] = (
    ("gtts", ".mp3", _write_gtts, lambda: _module_present("gtts")),
    ("espeak", ".wav", _write_espeak, lambda: _binary_present("espeak-ng", "espeak")),
    ("pyttsx3", ".wav", _write_pyttsx3, lambda: _module_present("pyttsx3")),
    ("piper", ".wav", _write_piper, lambda: _binary_present("piper")),
    ("say", ".aiff", _write_say, lambda: SYSTEM == "Darwin" and _binary_present("say")),
)

_WRITER_NAMES: tuple[str, ...] = tuple(name for name, _ext, _fn, _can in _WRITERS)


def _writer_check(can: WriterCheck) -> bool:
    try:
        return bool(can())
    except Exception as e:  # pragma: no cover - shutil/find_spec không nên ném
        logger.debug("Kiểm tra writer thất bại: %s", e)
        return False


def writer_for(name: object) -> WriterSpec | None:
    """Tra về (tên, đuôi file, hàm ghi, hàm kiểm tra) của một writer; None nếu sai tên."""
    wanted = _speech_text(name).strip().lower()
    for entry in _WRITERS:
        if entry[0].lower() == wanted:
            return entry
    return None


def available_writers() -> list[str]:
    """Những engine có thể GHI RA FILE trên máy này (khác `available_engines()`).

    `available_engines()` trả về thứ biết PHÁT; ở đây cần thứ biết LƯU - hai danh
    sách không trùng nhau (SAPI và `afplay` phát được nhưng không tự ghi file).
    """
    return [name for name, _ext, _fn, can in _WRITERS if _writer_check(can)]


def _cache_key(text: object) -> str:
    """Khoá tra cứu cache - MỘT hàm cho cả ghi lẫn đọc, hai bên không được lệch.

    Ngoài strip+lower như bản cũ, v7.6 gộp mọi chuỗi khoảng trắng thành một dấu
    cách: `speak("Mở  YouTube")` (hai khoảng trắng do người dùng gõ hoặc do câu
    ghép) từng tìm hổng cache dù file đã có sẵn, rồi gọi engine lại từ đầu -
    đúng cái lỗi mà cache sinh ra để tránh.
    """
    return re.sub(r"\s+", " ", _speech_text(text)).strip().lower()


def _cache_name(key: str, ext: str) -> str:
    """Tên file cho một câu: phần đọc được + 8 ký tự băm để không đè nhau.

    `sanitize_filename` cắt ký tự cấm nhưng KHÔNG bảo đảm hai câu khác nhau cho ra
    hai tên khác nhau ("mo youtube" và "mo  youtube" cùng thành "mo_youtube");
    đuôi băm giải quyết đúng va chạm đó mà tên vẫn đọc được khi mở thư mục tay.
    """
    # `sanitize_filename` giu nguyen khoang trang (do la hop dong cua no, dung
    # cho ca ten tai lieu); o day ten file se duoc nguoi dung mo/quyen trong
    # shell nen gop khoang trang thanh `_`.
    slug = sanitize_filename(key).replace(" ", "_")[:48] or "cau_noi"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}{ext}"


def _read_cache_index(directory: Path) -> list[tuple[str, str]]:
    """Đọc `index.csv` của MỘT thư mục, giữ thứ tự và cả những dòng lạ."""
    index_path = directory / "index.csv"
    if not index_path.is_file():
        return []
    rows: list[tuple[str, str]] = []
    try:
        with index_path.open(newline="", encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) >= 2 and row[0].strip():
                    rows.append((row[0].strip(), row[1].strip()))
    except (OSError, csv.Error) as e:
        logger.debug("Không đọc được %s: %s", index_path, e)
    return rows


def _write_cache_index(directory: Path, rows: list[tuple[str, str]]) -> None:
    """Ghi lại `index.csv` kiểu atomic.

    Không được mở ``"w"`` trực tiếp: đây là file người dùng CŨNG sửa bằng tay,
    và một lần ghi hỏng giữa chừng xoá sạch cả kho mà không giải thích được vì sao.
    """
    lines = []
    for key, fname in rows:
        buf = io.StringIO(newline="")
        csv.writer(buf).writerow([key, fname])
        lines.append(buf.getvalue().rstrip("\r\n"))
    atomic_write_text(directory / "index.csv", "\n".join(lines) + "\n", prefix=".index_tmp_")


def _read_text_lines(path: Path) -> list[str]:
    """File văn bản -> mỗi dòng một câu (chịu được BOM UTF-8 và CRLF)."""
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise FileNotFoundError(f"không đọc được file danh sách câu: {path} ({e})") from e
    out = []
    for line in content.splitlines():
        clean = line.strip().lstrip("\ufeff").strip()
        if clean:
            out.append(clean)
    return out


def _cache_texts(texts: object) -> list[str]:
    """Chuẩn hoá đầu vào (một chuỗi / danh sách / Path file) -> các câu duy nhất.

    Chấp nhận cả ba vì người dùng sẽ đưa cả ba: một câu gõ trực tiếp, danh sách
    câu từ mã nguồn, và file văn bản mỗi dòng một câu (`--cache --file cau.txt`).
    """
    items: list[object]
    if isinstance(texts, (str, Path)):
        items = [texts]
    elif hasattr(texts, "__iter__"):
        items = list(texts)
    else:
        items = [texts]
    raw: list[object] = []
    for item in items:
        if isinstance(item, Path):
            raw.extend(_read_text_lines(item))
        elif isinstance(item, str) and "\n" in item:
            raw.extend(item.splitlines())
        else:
            raw.append(item)
    keys: list[str] = []
    seen: set[str] = set()
    for value in raw:
        key = _cache_key(value)
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def _prewarm_one(key: str, directory: Path, writers: list[WriterSpec],
                 force: bool,
                 cached: dict[str, str]) -> tuple[str, str | None, str | None, str]:
    """Tạo file cho MỘT câu. Trả về (tình trạng, tên file, writer đã dùng, lý do lỗi)."""
    if not force and key in cached:
        return "skip", cached[key], None, ""
    reasons: list[str] = []
    for name, ext, write, _can in writers:
        out = directory / _cache_name(key, ext)
        try:
            ok = write(key, out)
            # Kiểm tra LẠI ở đây dù writer cũng đã kiểm tra: "nói dối" là lỗi của
            # cả một họ engine (lệnh thành công, file 44 byte), và writer mới thêm
            # sau này chưa chắc nhớ. Một chỗ duy nhất chặn được cả hai.
            if ok and not _file_written(out, minimum=1 if ext != ".wav" else _WAV_HEADER_BYTES + 1):
                ok = False
                reasons.append(f"{name}: file sinh ra quá nhỏ, không có tiếng")
        except TTSWriteError as e:
            ok = False
            reasons.append(f"{name}: {e}")
        except Exception as e:  # writer cua ben thu ba nem kieu khong ai ngo -> van ghi log
            logger.debug("writer %s lỗi với %r: %s", name, key, e)
            ok = False
            reasons.append(f"{name}: lỗi bất ngờ ({type(e).__name__})")
        if ok:
            return "ok", out.name, name, ""
        try:
            if out.exists():
                out.unlink()
        except OSError:
            pass  # file tạm còn sót: thà để hơn là che mất kết quả
    return "fail", None, None, "; ".join(reasons)


def _pick_writers(engine: str | None, only_available: bool) -> list[WriterSpec]:
    """Chọn danh sách writer cho một lần prewarm.

    Tách khỏi `prewarm()` vì hàm đó đã chạm ngưỡng độ phức tạp C901=10, và vì
    đoạn "khoá engine / tự dò" là phần dễ đọc sai nhất trong cả luồng.
    """
    if engine:
        entry = writer_for(engine)
        if entry is None:
            raise ValueError(f"Không có writer {_speech_text(engine)!r}. "
                             f"Các writer: {', '.join(_WRITER_NAMES)}.")
        return [entry]
    picked = [w for w in _WRITERS if not only_available or _writer_check(w[3])]
    # Máy không có gì vẫn trả về danh sách đầy đủ: mỗi câu sẽ fail KÈM LÝ DO trong
    # detail, tử tế hơn là "0 mục" im lìm (người dùng phân biệt được "chưa cài gì"
    # và "không có câu nào").
    return picked or list(_WRITERS)


def prewarm(texts: object, *, out_dir: str | Path | None = None, engine: str | None = None,
            force: bool = False, dry_run: bool = False, only_available: bool = True) -> dict:
    """Sinh file âm thanh sẵn cho các câu hay dùng, ghi vào `voice_cache/`.

    Dùng khi nào: câu lệnh lặp lại mỗi ngày ("mở youtube", "tắt máy", "chúc ngủ
    ngon"). `speak()` gặp câu đã có trong cache thì phát thẳng, không gọi engine,
    không cần mạng - nhanh hơn và chạy được lúc offline.

    Args:
        texts: một câu, danh sách câu, hoặc Path tới file mỗi dòng một câu.
        out_dir: thư mục cache (mặc định `paths.data_path("voice_cache")`).
        engine: khoá writer ("gtts"/"espeak"/"pyttsx3"/"piper"/"say"); mặc định
            thử lần lượt và dùng cái đầu tiên ghi được.
        force: tạo lại cả câu đã có trong cache.
        dry_run: chỉ liệt kê việc sẽ làm, không ghi file nào.
        only_available: bỏ qua writer mà máy này không chạy được (mặc định True).

    Returns:
        dict tổng kết: ``dir / requested / written / skipped / failed / writers /
        detail``. Mỗi phần tử ``detail`` là ``{"text", "status", "file", "writer",
        "reason"}`` - ``status`` là ``ok`` / ``skip`` / ``fail`` / ``plan``, và
        ``reason`` chỉ có nội dung khi ``fail`` (lý do in ra cho người dùng).

    Không ném exception cho từng câu lỗi: lỗi nằm trong ``detail`` để người gọi in
    hết một lần. Riêng ``engine`` không tồn tại thì raise - đó là lỗi ở THAM SỐ
    chứ không phải ở dữ liệu, và im lặng trả về 0 mục sẽ bị đọc nhầm thành
    "chưa cài gì cả".
    """
    global _voice_cache_index
    directory = Path(str(out_dir)) if out_dir is not None else VOICE_CACHE_DIR
    keys = _cache_texts(texts)

    writers = _pick_writers(engine, only_available)

    summary: dict = {
        "dir": str(directory),
        "requested": len(keys),
        "written": 0,
        "skipped": 0,
        "failed": 0,
        "writers": [name for name, _e, _f, _c in writers],
        "detail": [],
    }
    if not keys:
        return summary

    cached = {_cache_key(k): f for k, f in _read_cache_index(directory)
              if f and (directory / f).is_file()}
    additions: list[tuple[str, str]] = []
    for key in keys:
        if dry_run:
            summary["detail"].append({"text": key, "status": "plan",
                                      "file": _cache_name(key, writers[0][1]), "reason": ""})
            summary["written"] += 1
            continue
        directory.mkdir(parents=True, exist_ok=True)
        status, fname, writer, reason = _prewarm_one(key, directory, writers, force, cached)
        summary["detail"].append({"text": key, "status": status, "file": fname,
                                  "writer": writer, "reason": reason})
        summary[{"ok": "written", "skip": "skipped", "fail": "failed"}[status]] += 1
        if status == "ok" and fname:
            additions.append((key, fname))

    if additions:
        rows = _read_cache_index(directory)
        by_key = {_cache_key(k): i for i, (k, _f) in enumerate(rows)}
        for key, fname in additions:
            if key in by_key:
                rows[by_key[key]] = (key, fname)
            else:
                rows.append((key, fname))
        _write_cache_index(directory, rows)
        _voice_cache_index = None  # ép đọc lại bảng tra ở lần nói kế tiếp
    return summary


def _speech_text(text: object) -> str:
    """Ép nội dung cần nói về chuỗi đã cắt khoảng trắng; "" = không có gì để nói.

    Tách thành hàm riêng vì `speak` đã ở ngưỡng độ phức tạp (C901=10) mà hai
    bước kiểm tra kiểu/khoảng trắng ở đây là việc của tầng gọi, không phải của
    việc phát âm thanh.
    """
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    return text.strip()


def speak(text: str, show: bool = True) -> None:
    """Đọc một câu. Im lặng tuyệt đối khi câu rỗng - không in "[TRỢ LÝ] None".

    v7.5: kiểm tra nội dung TRƯỚC khi in echo và chịu được giá trị không phải
    chuỗi (speak(123) trước đây AttributeError; None in ra "None" như thể trợ lý
    vừa nói chữ đó).
    """
    global _resolved_engine

    text = _speech_text(text)
    if not text:
        return

    if show:
        safe_print(f"[TRỢ LÝ] {text}")

    if not ENABLED:
        return

    if _speak_cache(text):
        return

    with _speak_lock:
        for fn in _engine_order():
            if _try_engine(fn, text):
                _resolved_engine = fn
                return

        if _retry_other_engines(text):
            return


def _retry_other_engines(text: str) -> bool:
    """Engine đã chốt hỏng giữa chừng -> thử lại các engine khác.

    Tách từ `speak` (v7.5) để `speak` ở dưới ngưỡng độ phức tạp C901=10; hành vi
    giữ nguyên từng dòng, kể cả thứ tự engine. Trả về True nếu một engine mới nói
    được, khi đó `_resolved_engine` đã trỏ sang engine mới.

    Chỉ thử lại khi ENGINE == "auto" - người dùng KHOÁ cứng một engine thì câu
    trả lời đúng là "engine đó hỏng", tự ý đổi sang engine khác chỉ làm họ hoang
    mang về chính cấu hình của mình.
    """
    global _resolved_engine
    if ENGINE != "auto" or _resolved_engine is None:
        return False
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
            return True
    _resolved_engine = None
    return False


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
    import argparse

    parser = argparse.ArgumentParser(
        prog="tts.py",
        description="Đọc to / tạo kho giọng đọc sẵn (voice_cache) cho Trợ lý ảo tiếng Việt",
    )
    parser.add_argument("--speak", metavar="CÂU", help="đọc một câu rồi thoát")
    parser.add_argument("--engines", action="store_true",
                        help="liệt kê engine phát được VÀ writer ghi được ra file")
    parser.add_argument("--list", action="store_true",
                        help="kho giọng hiện có (khoá -> file), kèm nơi lưu")
    parser.add_argument("--cache", action="store_true",
                        help="tạo file âm thanh cho các câu ở --text/--file (mới v7.6)")
    parser.add_argument("--text", action="append", default=[], metavar="CÂU",
                        help="câu cần đưa vào cache (lặp lại được nhiều lần)")
    parser.add_argument("--file", action="append", default=[], metavar="FILE",
                        help="file văn bản, MỖI DÒNG MỘT CÂU")
    parser.add_argument("--out", metavar="THƯ_MỤC",
                        help="thư mục cache (mặc định: thư mục dữ liệu của người dùng)")
    parser.add_argument("--engine", choices=list(_WRITER_NAMES), metavar="WRITER",
                        help="khoá writer, mặc định thử lần lượt")
    parser.add_argument("--force", action="store_true", help="tạo lại câu đã có trong cache")
    parser.add_argument("--dry-run", action="store_true", help="chỉ in kế hoạch, không ghi file")
    args = parser.parse_args()
    setup_console()

    if args.list:
        index = _load_voice_cache()
        safe_print(f"Kho giọng: {len(index)} mục (thư mục: {VOICE_CACHE_DIR})")
        for key in sorted(index)[:40]:
            safe_print(f"  {key!r} -> {index[key].name}")
        if len(index) > 40:
            safe_print(f"  ... còn lại {len(index) - 40} mục nữa")
        raise SystemExit(0)

    want_info = args.engines or not (args.speak or args.cache)
    if want_info:
        safe_print("Engine khả dụng trên máy này:")
        for e in available_engines():
            safe_print(f"  - {e}")
        writers = available_writers()
        safe_print(f"Writer ghi ra file (dùng cho --cache): {', '.join(writers) or 'KHÔNG CÓ'}")
        if not writers:
            safe_print("  -> cần một trong: pip install gTTS  |  apt install espeak-ng  |  "
                       "pip install pyttsx3")
        if not args.engines and not (args.speak or args.cache):
            speak("Xin chào, tôi là trợ lý ảo tiếng Việt của bạn")
        raise SystemExit(0)

    if args.speak:
        speak(args.speak)

    if args.cache:
        wanted: list[object] = list(args.text) + [Path(name) for name in args.file]
        if not wanted:
            safe_print('[LỖI] --cache cần ít nhất --text "câu nói" hoặc --file danh_sach.txt')
            raise SystemExit(2)
        try:
            result = prewarm(wanted, out_dir=args.out, engine=args.engine,
                             force=args.force, dry_run=args.dry_run)
        except (ValueError, FileNotFoundError) as e:
            safe_print(f"[LỖI] {e}")
            raise SystemExit(2) from e
        action = "Sẽ tạo" if args.dry_run else "Đã tạo"
        safe_print(f"[KHO GIỌNG] {action} {result['written']} mục, bỏ qua {result['skipped']} "
                   f"(đã có), lỗi {result['failed']} - thư mục: {result['dir']}")
        for item in result["detail"]:
            if item["status"] == "fail":
                safe_print(f"  [fail] {item['text']!r}\n         vì: {item['reason']}")
            elif item["status"] == "plan":
                safe_print(f"  [plan] {item['text']!r} -> {item.get('file')}")
        if result["requested"] and result["failed"] == result["requested"]:
            safe_print("  -> Không writer nào ghi được file. Thử --engine gtts (cần mạng), "
                       "hoặc cài espeak-ng / pyttsx3. Xem: --engines")
            raise SystemExit(1)
