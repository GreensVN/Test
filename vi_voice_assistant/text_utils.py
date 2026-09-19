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
    "normalize_no_diacritics",
    "normalize_text",
    "sanitize_filename",
    "strip_diacritics",
    "truncate_text",
]


_TEXT_CACHE = 8192


def _as_text(text) -> str:
    """Mọi thứ không phải chuỗi đều được ép sang chuỗi TRƯỚC khi vào cache.

    lru_cache cần đối tượng hash được, và dự án không bao giờ được chết chỉ vì
    ai đó đưa vào một con số/khối dict từ config.
    """
    return text if isinstance(text, str) else ("" if text is None else str(text))


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


def sanitize_filename(name: str, replacement: str = "_") -> str:
    """Làm sạch tên file, bỏ ký tự không hợp lệ trên Windows/Linux."""
    if not name:
        return "untitled"
    # Bỏ ký tự không hợp lệ
    name = _INVALID_FILENAME_RE.sub(replacement, name)
    # Bỏ control chars
    name = "".join(ch if ord(ch) >= 32 else replacement for ch in name)
    name = name.strip().strip(".")
    return name or "untitled"


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
