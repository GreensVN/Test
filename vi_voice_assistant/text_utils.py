"""
text_utils.py
-------------
Các hàm xử lý văn bản tiếng Việt dùng chung.

v7.0 nâng cấp:
- Thêm type hints đầy đủ
- Tối ưu regex, cache compiled patterns
- Thêm hàm sanitize_filename, truncate
- Xử lý edge cases tốt hơn

v7.3 nâng cấp:
- CACHE hai hàm nóng nhất (normalize_text / strip_diacritics). Lý do thật:
  tầng NLU gọi lặp lại cùng một chuỗi RẤT nhiều lần cho một câu nói - tách từ,
  phân loại từng từ, so khớp mờ từng từ - nên bản không cache tốn ~3.4us/lần
  cho những lần lặp thừa. Cache chặn ở 8192 câu (LRU) nên bộ nhớ không tăng
  không giới hạn khi chạy cả ngày; kết quả đo được ở tests/test_v73_ux.py.
- Đầu vào KHÔNG phải chuỗi (số do config lỗi, None từ caller...) được ép sang
  str thay vì ném AttributeError: một trợ lý giọng nói không nên chết vì kiểu
  dữ liệu lạ ở tầng văn bản.
v7.5 nâng cấp:
- `_as_text` thành hàm CÔNG CỘNG `as_text` (export trong `__all__`): mọi điểm vào
  của dự án dùng chung một chính sách "không chết vì kiểu" thay vì mỗi module tự
  viết rồi quên.
- `sanitize_filename`: chặn tên dành riêng của Windows (CON/PRN/AUX/NUL/COM1-9/
  LPT1-9 - OS từ chối ở mọi vị trí, kể cả có phần mở rộng), cắt theo 255 byte của
  MỘT thành phần đường dẫn (tiếng Việt ~3 byte/ký tự, tên dài từng gây OSError 36),
  và nhận giá trị không phải chuỗi. Giữ tính chất idempotent.

"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Final

# Pre-compiled regex cho hiệu năng - để dấu - ở cuối để tránh range
_WS_RE: Final = re.compile(r"\s+")
_KEEP_RE: Final = re.compile(r"[^\w\s./:\\-]+", re.UNICODE)
_INVALID_FILENAME_RE: Final = re.compile(r'[<>:"/\\|?*]')

__all__ = [
    "as_text",
    "normalize_no_diacritics",
    "normalize_text",
    "sanitize_filename",
    "strip_diacritics",
    "truncate_text",
]


_TEXT_CACHE = 8192


def as_text(text: object) -> str:
    """Ép mọi giá trị về chuỗi; ``None`` -> ``""``.

    Lý do tồn tại (mới v7.5, trước là hàm riêng ``_as_text`` của tầng cache):
    mọi hàm xử lý văn bản trong dự án đều nhận `str` theo chữ ký, nhưng giá trị
    thật đến từ config/JSON/đối tượng trả về của bên thứ ba - và `re.search(123)`
    hay `(123).strip()` thì chết bằng traceback khó đọc thay vì trả kết quả.
    `lru_cache` còn cần thứ hash được, nên ép kiểu phải xảy ra TRƯỚC khi vào cache.

    Đây là hàm CÔNG CỘNG vì tầng NLU + tts cần dùng chung: cùng một chính sách
    "không chết vì kiểu" ở mọi điểm vào, thay vì mỗi module tự viết một kiểu.
    """
    return text if isinstance(text, str) else ("" if text is None else str(text))


_as_text = as_text  # ten cu, van duoc dung noi bo


def normalize_text(text: str | None) -> str:
    """Chuẩn hoá câu: NFC, lower, bỏ ký tự thừa, giữ ký tự đường dẫn."""
    return _normalize_cached(_as_text(text))


@lru_cache(maxsize=_TEXT_CACHE)
def _normalize_cached(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text.strip().lower())
    text = _KEEP_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def strip_diacritics(text: str | None) -> str:
    """
    Bỏ dấu tiếng Việt: 'bật google lên' -> 'bat google len'.
    Xử lý cả đ/Đ.
    """
    return _strip_diacritics_cached(_as_text(text))


@lru_cache(maxsize=_TEXT_CACHE)
def _strip_diacritics_cached(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D")
    return unicodedata.normalize("NFC", text)


def normalize_no_diacritics(text: str | None) -> str:
    """normalize_text() rồi bỏ dấu -> khoá so khớp 'khoan dung dấu'."""
    return strip_diacritics(normalize_text(text))


# Windows tu choi nhung ten nay o MOI vi tri, ke ca khi co phan mo rong: ghi file
# "CON.txt" khong tra ve loi "duoc" ma treo hoac loi kho hieu -> nguoi dung do loi
# cho phan mem. Ten den tu CHINH NOI DUNG nguoi dung (cau "luu ...", tieu de web).
_WINDOWS_RESERVED: Final = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)

_MAX_NAME_BYTES: Final = 255  # gioi han MOT thanh phan duong dan (ext4/APFS/NTFS)


def sanitize_filename(name: str, replacement: str = "_", *,
                      max_bytes: int = _MAX_NAME_BYTES) -> str:
    """Làm sạch tên file, bỏ ký tự không hợp lệ trên Windows/Linux.

    v7.5 sửa ba chỗ mà bản cũ bỏ qua - cả ba chỉ lộ ra khi tên file đến từ nội
    dung người dùng chứ không phải chuỗi cố định trong code:
      * **kiểu**: ``sanitize_filename(123)`` chết bằng ``TypeError`` trong
        ``re.sub``; giờ dùng ``as_text`` như mọi điểm vào khác của module này.
      * **tên dành riêng của Windows** (CON/PRN/AUX/NUL/COM1-9/LPT1-9): hợp lệ với
        POSIX nhưng bị Windows từ chối ở mọi vị trí, nên được chặn bằng cách thêm
        ``_`` - im lặng trả về một tên mà OS khác sẽ mở được.
      * **độ dài theo byte**: tiếng Việt ~3 byte/ký tự, một cái tên 90 ký tự đã
        vượt giới hạn 255 byte của một thành phần đường dẫn -> ``OSError
        [Errno 36]``. Cắt theo byte rồi giải mã, không cắt giữa ký tự.
    """
    text = as_text(name)
    if not text.strip():
        return "untitled"
    text = _INVALID_FILENAME_RE.sub(replacement, text)
    text = "".join(ch if ord(ch) >= 32 else replacement for ch in text)
    text = text.strip().strip(".")
    if not text:
        return "untitled"
    if text.split(".", 1)[0].lower() in _WINDOWS_RESERVED:
        text = "_" + text
    if max_bytes and max_bytes > 0:
        raw = text.encode("utf-8", errors="replace")
        if len(raw) > max_bytes:
            cut = raw[:max_bytes].decode("utf-8", errors="ignore").rstrip(". ")
            text = cut or "untitled"
    return text


def truncate_text(text: str, max_len: int = 100, suffix: str = "...") -> str:
    """Cắt ngắn văn bản, giữ từ nguyên vẹn nếu có thể."""
    if not text or len(text) <= max_len:
        return text or ""
    if max_len <= len(suffix):
        return text[:max_len]
    cut = text[: max_len - len(suffix)].rsplit(" ", 1)
    if len(cut) == 2 and len(cut[0]) >= max_len // 2:
        return cut[0] + suffix
    return text[: max_len - len(suffix)] + suffix
