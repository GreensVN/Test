"""Portable machine JSON, separate from human-readable configuration files."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, TextIO

__all__ = ["dumps_json", "error_text", "write_json_document"]

logger = logging.getLogger(__name__)


def error_text(error: object) -> str:
    """Error reporting must not fail because an exception has a broken __str__."""
    try:
        return str(error) or type(error).__name__
    except Exception:
        return type(error).__name__


def dumps_json(payload: Any, *, indent: int | None = 2) -> str:
    """Strict numbers and ASCII escapes keep Unicode portable on narrow streams.

    Values round-trip through Python's JSON decoder. Unicode code units are
    escaped, not normalized/repaired; stricter downstream Unicode validators
    may reject lone surrogates supplied by a provider. Local config/history
    files keep their existing readable UTF-8 encoding instead of this helper.
    """
    return json.dumps(payload, ensure_ascii=True, allow_nan=False, default=str, indent=indent)


def write_json_document(document: str, *, output: TextIO | None = None) -> bool:
    """Write and flush a prepared document, reporting ordinary I/O failures.

    A failed/partial physical write cannot be made atomic or repaired here.
    Callers must not dispatch new commands after False. Cancellation propagates.
    """
    try:
        stream = sys.stdout if output is None else output
        data = document + "\n"
        offset = 0
        while offset < len(data):
            chunk = data[offset:offset + 65536]
            written = stream.write(chunk)
            if (isinstance(written, bool) or not isinstance(written, int)
                    or not 0 < written <= len(chunk)):
                raise OSError("JSON output không xác nhận tiến độ ghi hợp lệ.")
            offset += written
        stream.flush()
    except Exception as error:
        try:
            logger.warning("Không ghi được JSON: %s", error_text(error))
        except Exception:
            return False  # Logging may be broken too; never recurse into it.
        return False
    return True
