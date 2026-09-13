# -*- coding: utf-8 -*-
"""
logging_setup.py
-----------------
Thiết lập logging tập trung.

v7.0 nâng cấp:
- Thêm JSON formatter tuỳ chọn
- Thêm context filter (thêm thread name)
- Hỗ trợ env LOG_LEVEL
- Rotating + backup tốt hơn
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "assistant.log"

_configured = False
_lock = False


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Thêm thông tin hữu ích nếu chưa có
        if not hasattr(record, "thread_name"):
            record.thread_name = record.threadName
        return True


def setup_logging(
    level: int = logging.INFO,
    console_level: int = logging.WARNING,
    log_file: Optional[Path] = None,
    max_bytes: int = 2_000_000,
    backup_count: int = 5,
    use_json: bool = False,
) -> None:
    """Cấu hình root logger, an toàn khi gọi nhiều lần."""
    global _configured
    if _configured:
        return
    # Tránh race trong multi-thread init
    global _lock
    if _lock:
        return
    _lock = True

    try:
        # Cho phép override bằng env
        env_level = os.environ.get("LOG_LEVEL") or os.environ.get("VIVOICE_LOG_LEVEL")
        if env_level:
            try:
                level = getattr(logging, env_level.upper())
            except AttributeError:
                try:
                    level = int(env_level)
                except ValueError:
                    pass

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        target_log = Path(log_file) if log_file else LOG_FILE

        root = logging.getLogger()
        root.setLevel(level)
        # Xoá handler cũ nếu có (tránh duplicate khi reload)
        root.handlers.clear()

        fmt_str = "%(asctime)s [%(levelname)s] %(name)s (%(thread_name)s): %(message)s"
        if use_json:
            # Đơn giản: vẫn dùng text nhưng có thể mở rộng JSON sau
            fmt_str = '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'

        formatter = logging.Formatter(fmt_str, datefmt="%Y-%m-%d %H:%M:%S")
        ctx_filter = ContextFilter()

        # File handler - rotating
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                str(target_log), maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            file_handler.addFilter(ctx_filter)
            root.addHandler(file_handler)
        except OSError as e:
            # Không tạo được file log -> vẫn chạy tiếp, chỉ log ra console
            print(f"[WARN] Không tạo được file log {target_log}: {e}")

        # Console handler - chỉ warning/error để không spam REPL
        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_level)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(ctx_filter)
        root.addHandler(console_handler)

        _configured = True
        logging.getLogger(__name__).debug(
            "Logging configured: level=%s file=%s", logging.getLevelName(level), target_log
        )
    finally:
        _lock = False


def get_logger(name: str) -> logging.Logger:
    """Lấy logger đã setup."""
    if not _configured:
        setup_logging()
    return logging.getLogger(name)
