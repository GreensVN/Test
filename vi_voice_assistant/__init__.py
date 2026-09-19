"""
Trợ lý ảo tiếng Việt - gói Python (v7.3)
-----------------------------------------

Toàn bộ mã nguồn trong thư mục này từ trước tới nay dùng LỆNH IMPORT PHẲNG
(``from platform_utils import ...``, ``import executor``...) vì dự án được thiết
kế để ChẠy TRựC TIẾP tỪ thƯ mỤc: ``python vi_voice_assistant/main.py``, và bộ
test cũng ``sys.path.insert`` rồi ``import executor``.

Hệ quả khi ``pip install .`` (v7.2 trở về trước): wheel chứa đủ file .py nhưng
KHÔNG THỂ DÙNG - chạy ``vi-assistant`` chết ngay với

    ModuleNotFoundError: No module named 'platform_utils'

``__main__.py``/``__init__.py`` này sửa đúng chỗ đó mà KHÔNG đụng 20 file import:
thêm thư mục gói vào ``sys.path`` một lần lúc nạp gói, nên tên phẳng nào cũng
giải được như khi chạy từ source.

    python -m vi_voice_assistant              # REPL
    python -m vi_voice_assistant --once "mở youtube"
    vi-assistant --doctor                     # console script
"""

from __future__ import annotations

import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
if _HERE not in _sys.path:
    # Chen vao cuoi (khong phai dau) de khong "che" tam mot ten module nao cua
    # ung dung; moi module trong goi deu dung ten phang nen chi can thu muc nay
    # CO MAT trong path.
    _sys.path.append(_HERE)

__version__ = "7.3"
__all__ = ["__version__", "main"]


def main() -> int:
    """Điểm vào console script (``vi-assistant``).

    Import TRỄ bên trong hàm: ``import vi_voice_assistant`` (chỉ để lấy
    ``__version__``, ví dụ tools đọc metadata) không được phép kéo theo cả
    NLU + executor rồi mất ~80ms.
    """
    import main as _main

    return _main.main() or 0


def doctor() -> int:
    """Điểm vào ``vi-doctor`` - chẩn đoán cài đặt/môi trường."""
    import diagnostic

    return diagnostic.main()
