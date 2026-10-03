"""
csv_utils.py
------------
Đọc file CSV theo TÊN CỘT, nhưng chịu được cả file KHÔNG có dòng tiêu đề.

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

import csv
import logging
from pathlib import Path

from platform_utils import safe_print

__all__ = ["read_keyed_csv"]

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
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
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
