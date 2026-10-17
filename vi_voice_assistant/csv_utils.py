"""
csv_utils.py
------------
Đọc/append CSV theo tên cột, chịu được file cũ không header; khóa OS cho I/O.

v7.10.1: append và reader phối hợp bằng khóa có timeout. Chỉ xác nhận ghi
thành công sau flush/fsync, không xem append là transaction chống mất điện.

v7.8 nâng cấp - lý do có file này
=================================
Cùng một kiểu lỗi từng xuất hiện ở HAI nơi, mỗi nơi một bản sao:

    for row in csv.DictReader(f):
        text = (row.get("text") or "").strip()

`csv.DictReader` coi DÒNG ĐẦU TIÊN là tên cột. File CSV do người dùng tự viết
tay - hoặc do chính `nlu_advanced.log_feedback` ghi vào một file RỖNG (mất điện
để lại file 0 byte) - thì dòng đầu là DÒNG DỮ LIỆU, không phải tên cột. Khi đó:

  1. dòng dữ liệu đầu tiên bị ăn mất thành tên cột,
  2. mọi dòng còn lại không còn khoá ``text``/``intent`` nên `.get()` trả None,
  3. vòng lặp nhảy qua toàn bộ file và in ra **"0 câu"** - đúng bằng câu "bạn
     chưa dạy gì", KHÔNG có bất kỳ cảnh báo nào.

Hậu quả thực tế: toàn bộ phần dữ liệu người dùng tự nhập biến mất khỏi vòng
huấn luyện, và họ không hề được báo. Sửa nguồn ghi chưa đủ - những file hỏng đó
đã nằm sẵn trên đĩa, nên phía ĐỌC cũng phải chịu được.

`read_keyed_csv()` chuẩn hoá việc đó ở MỘT chỗ, và - quan trọng hơn - báo cáo
khi file thiếu tiêu đề, để lần sau lỗi hiện ra thành một dòng cảnh báo thay vì
số 0 lặng lẽ.

Đặt ở module riêng (thay vì để trong `dataset.py` hoặc `train_nlu.py`) vì hai
module đó CÙNG cần, mà `train_nlu` lại `import dataset` - đặt helper vào một
trong hai sẽ tạo vòng import. File này chỉ phụ thuộc `platform_utils` (vốn
không import gì của dự án) nên không sinh vòng nào.

Ví dụ:

    read_keyed_csv("my_dataset.csv", ("text", "intent"), "my_dataset.csv")
    # -> [{"text": "mở notepad", "intent": "open_app"}, ...]
"""

from __future__ import annotations

import codecs
import csv
import errno
import io
import logging
import os
import time
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from typing import BinaryIO

from platform_utils import safe_print

__all__ = ["append_keyed_csv", "read_keyed_csv"]

logger = logging.getLogger(__name__)

# Cặp khoá mà MỌI file dữ liệu của dự án đều có. Chỉ cần cặp này để kết luận
# "dòng đầu là tên cột" - file thiếu cột phụ (ví dụ không có `verified`) vẫn
# đọc được theo header, phần thiếu để trống.
ESSENTIAL_KEYS = ("text", "intent")


def read_keyed_csv(path: str | Path, required: tuple[str, ...],
                   source: str | None = None):
    """Đọc `path` thành danh sách dict khoá theo tên cột trong `required`.

    `required` là THỨ TỰ CỘT khi file không có tiêu đề (thứ tự `log_feedback`
    ghi ra: time, text, intent, confidence, verified). Cột thiếu -> giá trị rỗng,
    dòng thiếu cột -> các khoá còn lại vẫn đọc được, không làm hỏng cả file.

    File rỗng -> `[]`. File thiếu tiêu đề -> vẫn đọc được theo vị trí cột, kèm
    một cảnh báo nói rõ file cần sửa (im lặng trả 0 là nguyên nhân khiến người
    dùng tưởng mình chưa nhập gì).
    """
    csv_path = Path(path)
    label = source or csv_path.name
    with csv_path.open(encoding="utf-8-sig", newline="") as f, _locked_csv(f.fileno(), shared=True):
        rows = [r for r in csv.reader(f) if any((c or "").strip() for c in r)]
    if not rows:
        return []

    header = [(c or "").strip().lower() for c in rows[0]]
    if all(key in header for key in ESSENTIAL_KEYS):
        pos = {name: i for i, name in enumerate(header)}
        return [
            {
                key: (row[pos[key]] if key in pos and pos[key] < len(row) else "")
                for key in required
            }
            for row in rows[1:]
        ]

    safe_print(f"    [!] {label} KHÔNG có dòng tiêu đề -> đọc theo thứ tự cột.")
    safe_print("        (nếu đây không phải ý bạn, hãy thêm dòng: "
               + ",".join(required) + " ở đầu file)")
    logger.warning("%s thiếu dòng tiêu đề: %s", label, csv_path)
    return [
        {key: (row[i] if i < len(row) else "") for i, key in enumerate(required)}
        for row in rows
    ]


_FILE_LOCK_TIMEOUT = 5.0
_LOCK_RETRY_SECONDS = 0.01


def _file_lock_operation(fd: int, *, release: bool = False, shared: bool = False) -> None:
    """Khóa chính file CSV: mọi process/module alias dùng chung một khóa OS."""
    if os.name == "nt":
        msvcrt = import_module("msvcrt")
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK if release else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
        operation = fcntl.LOCK_UN if release else mode | fcntl.LOCK_NB
        fcntl.flock(fd, operation)


@contextmanager
def _locked_csv(fd: int, *, shared: bool = False) -> Iterator[None]:
    deadline = time.monotonic() + _FILE_LOCK_TIMEOUT
    while True:
        try:
            _file_lock_operation(fd, shared=shared)
            break
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            if time.monotonic() >= deadline:
                raise TimeoutError("File CSV đang bị khóa; chưa truy cập được dữ liệu.") from error
            time.sleep(_LOCK_RETRY_SECONDS)
    try:
        yield
    finally:
        _file_lock_operation(fd, release=True)


def _csv_bytes(row: Sequence[object]) -> bytes:
    buffer = io.StringIO(newline="")
    csv.writer(buffer).writerow(row)
    return buffer.getvalue().encode("utf-8")


def _csv_append_columns(stream: BinaryIO, columns: tuple[str, ...]) -> tuple[tuple[str, ...], bool]:
    stream.seek(0)
    rows = csv.reader((line.decode("utf-8-sig") for line in stream), strict=True)
    first = next((row for row in rows if any(cell.strip() for cell in row)), None)
    if first is None:
        return columns, True
    header = tuple(cell.strip().lower() for cell in first)
    if not all(key in header for key in ESSENTIAL_KEYS):
        # File cũ không header: giữ nguyên định dạng để read_keyed_csv còn đọc được.
        return columns, False
    if len(set(header)) != len(header) or not set(columns).issubset(header):
        raise ValueError("Dòng tiêu đề CSV thiếu/trùng cột bắt buộc; giữ nguyên file để sửa.")
    return header, False


def _csv_append_prefix(stream: BinaryIO, new_header: bool) -> bytes:
    size = stream.seek(0, os.SEEK_END)
    if size == 0:
        return codecs.BOM_UTF8
    if new_header and size == len(codecs.BOM_UTF8):
        stream.seek(0)
        if stream.read() == codecs.BOM_UTF8:
            return b""
    stream.seek(-1, os.SEEK_END)
    return b"" if stream.read(1) in (b"\n", b"\r") else b"\n"


def append_keyed_csv(path: str | Path, columns: tuple[str, ...], values: Sequence[object]) -> None:
    """Append một record dưới khóa liên process, rồi flush/fsync trước khi thành công.

    Không dùng exists/getsize trước open: hai writer đầu tiên sẽ cùng ghi header.
    UTF-8 được mã hóa trước khi mở file; BOM chỉ thêm một lần khi file thực sự
    rỗng, tránh codec utf-8-sig ghi BOM giữa các record. Khóa có timeout để luồng
    hội thoại không treo vô hạn. Khóa advisory chỉ bảo vệ các writer hợp tác,
    không biến append thành transaction chống mất điện hoặc sửa file bằng editor.
    """
    if not columns or len(set(columns)) != len(columns) or len(columns) != len(values):
        raise ValueError("CSV cần tên cột duy nhất và đủ số giá trị.")
    _csv_bytes(values)  # Unicode hỏng phải bị từ chối TRƯỚC khi chạm file cũ.
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    # Binary/unbuffered: không có encoder trạng thái riêng ở mỗi writer và
    # không để close() flush thêm dữ liệu sau khi khóa đã được trả.
    with open(csv_path, "a+b", buffering=0) as stream, _locked_csv(stream.fileno()):
        header, new_header = _csv_append_columns(stream, columns)
        fields = dict(zip(columns, values))
        payload = (_csv_append_prefix(stream, new_header)
                   + (_csv_bytes(columns) if new_header else b"")
                   + _csv_bytes([fields.get(key, "") for key in header]))
        position = 0
        while position < len(payload):
            written = stream.write(payload[position:])
            if not written:
                raise OSError(errno.EIO, "Không ghi đủ record CSV.")
            position += written
        stream.flush()
        os.fsync(stream.fileno())
