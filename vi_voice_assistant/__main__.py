"""Cho phép ``python -m vi_voice_assistant [cờ...]`` (v7.3).

Trước đây chỉ chạy được ``python vi_voice_assistant/main.py``; lệnh ``-m`` chết
vì ``import main`` không có trong path. Import ở đây lấy THẲNG module ``main``
(tên phẳng) - ``__init__.py`` đã lo phần đường dẫn.
"""
import sys

from main import main as _main


def _run() -> int:
    return _main() or 0


if __name__ == "__main__":
    sys.exit(_run())
