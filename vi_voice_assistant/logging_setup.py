"""
logging_setup.py
-----------------
Thiết lập logging tập trung.

v7.0 nâng cấp:
- Thêm JSON formatter tuỳ chọn
- Thêm context filter (thêm thread name)
- Hỗ trợ env LOG_LEVEL
- Rotating + backup tốt hơn

v7.2 nâng cấp & fix lỗi:
- SỬA RACE KHỞI TẠO: `_lock` trước đây chỉ là một biến bool, nên hai thread gọi
  setup_logging() đồng thời đều lọt qua và CÙNG thêm handler -> mỗi dòng log bị
  in 2 lần. Nay dùng threading.Lock + double-checked locking.
- SỬA JSON LỖI: `use_json=True` trước đây chỉ đổi CẤU TRÚC CHUỖI định dạng
  (ghép thủ công '{"msg":"%(message)s"}'), nên chỉ cần message chứa một dấu
  nháy kép (rất phổ biến - vd log dict/JSON của lệnh) là file log KHÔNG CÒN là
  JSON hợp lệ và mọi công cụ parse (jq, Loki...) fail. Nay có JsonFormatter
  chuẩn, escape đầy đủ, kèm exception.
- setup_logging() không còn làm sập chương trình nếu không tạo được thư mục log
  (đĩa đầy/thiếu quyền) - trước đây LOG_DIR.mkdir() nằm ngoài mọi try.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "assistant.log"

_configured = False
# Cờ "đã cấu hình" được bảo vệ bằng lock thật; bool trần không đủ để chống race.
_init_lock = threading.Lock()


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Thêm thông tin hữu ích nếu chưa có
        if not hasattr(record, "thread_name"):
            record.thread_name = record.threadName
        return True


class JsonFormatter(logging.Formatter):
    """Định dạng mỗi bản ghi thành MỘT dòng JSON hợp lệ (escape đúng chuẩn)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "thread": record.threadName,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(
    level: int = logging.INFO,
    console_level: int = logging.WARNING,
    log_file: Path | None = None,
    max_bytes: int = 2_000_000,
    backup_count: int = 5,
    use_json: bool = False,
) -> None:
    """Cấu hình root logger, an toàn khi gọi nhiều lần và an toàn đa luồng."""
    global _configured
    if _configured:
        return
    with _init_lock:
        if _configured:  # kiểm tra lại: thread khác có thể vừa setup xong
            return
        try:
            _configure_locked(level, console_level, log_file, max_bytes, backup_count, use_json)
        except Exception as e:  # pragma: no cover - chỉ khi hệ thống file có vấn đề
            # Logging là tính năng PHỤ: không được phép làm chết trợ lý chỉ vì
            # không ghi được file log (đĩa đầy, thiếu quyền, đường dẫn quá dài
            # trên Windows...). Chỉ in 1 dòng cảnh báo rồi chạy tiếp.
            print(f"[WARN] Không cấu hình được logging: {e}")


def _resolve_level(level: int) -> int:
    """Cho phép override mức log bằng biến môi trường LOG_LEVEL / VIVOICE_LOG_LEVEL."""
    env_level = os.environ.get("LOG_LEVEL") or os.environ.get("VIVOICE_LOG_LEVEL")
    if not env_level:
        return level
    resolved = getattr(logging, str(env_level).upper(), None)
    if isinstance(resolved, int):
        return resolved
    try:
        return int(env_level)
    except (TypeError, ValueError):
        return level


def _configure_locked(
    level: int,
    console_level: int,
    log_file,
    max_bytes: int,
    backup_count: int,
    use_json: bool,
) -> None:
    global _configured

    level = _resolve_level(level)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    target_log = Path(log_file) if log_file else LOG_FILE

    root = logging.getLogger()
    root.setLevel(level)
    # Xoá handler cũ nếu có (tránh duplicate khi reload)
    root.handlers.clear()

    ctx_filter = ContextFilter()
    if use_json:
        file_formatter: logging.Formatter = JsonFormatter()
        console_formatter: logging.Formatter = JsonFormatter()
    else:
        fmt_str = "%(asctime)s [%(levelname)s] %(name)s (%(thread_name)s): %(message)s"
        file_formatter = logging.Formatter(fmt_str, datefmt="%Y-%m-%d %H:%M:%S")
        console_formatter = logging.Formatter(fmt_str, datefmt="%Y-%m-%d %H:%M:%S")

    # File handler - rotating
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            str(target_log), maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(file_formatter)
        file_handler.addFilter(ctx_filter)
        root.addHandler(file_handler)
    except OSError as e:
        # Không tạo được file log -> vẫn chạy tiếp, chỉ log ra console
        print(f"[WARN] Không tạo được file log {target_log}: {e}")

    # Console handler - chỉ warning/error để không spam REPL
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(console_formatter)
    console_handler.addFilter(ctx_filter)
    root.addHandler(console_handler)

    _configured = True
    logging.getLogger(__name__).debug(
        "Logging configured: level=%s file=%s json=%s",
        logging.getLevelName(level),
        target_log,
        use_json,
    )


def get_logger(name: str) -> logging.Logger:
    """Lấy logger đã setup."""
    if not _configured:
        setup_logging()
    return logging.getLogger(name)
