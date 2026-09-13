# -*- coding: utf-8 -*-
"""
fetch_massive_vi.py
--------------------
TẢI DỮ LIỆU THẬT TIẾNG VIỆT TỪ BỘ MASSIVE (Amazon Science) VÀ CONVERT SANG
ĐỊNH DẠNG my_dataset.csv ĐỂ load_extra_csv() TRONG dataset.py TỰ NẠP.

MASSIVE là gì (tóm tắt, xem thêm https://github.com/alexa/massive):
    - Bộ dữ liệu > 1 triệu câu, 52 ngôn ngữ (có tiếng Việt), 60 intent.
    - Câu tiếng Việt do người bản ngữ dịch/viết tay (không phải máy sinh),
      mỗi câu được ít nhất 3 người khác chấm điểm lại (đúng ý định không,
      câu có tự nhiên không, chính tả đúng không...).
    - Giấy phép CC BY 4.0 - được dùng thương mại, chỉ cần ghi công Amazon
      Science khi công bố sản phẩm/dataset phái sinh.

Script này CHỈ lấy các intent của MASSIVE THỰC SỰ khớp với 11 nhóm ý định
của bạn (xem INTENT_MAP bên dưới) - phần "open_app/open_website/open_file/
calculate" KHÔNG có trong MASSIVE nên không đụng tới, dataset.py vẫn tự lo
phần đó như cũ.

CÁCH DÙNG:
    1) Đảm bảo đã cài:  pip install requests   (thường có sẵn vì SpeechRecognition cần nó)
    2) Chạy:            python fetch_massive_vi.py
       (sẽ tải ~350MB rồi tự xoá, chỉ giữ lại phần tiếng Việt đã lọc)
    3) File my_dataset.csv sẽ được tạo/ghi đè trong đúng thư mục này.
    4) Chạy lại:         python train_nlu.py
       (train_nlu.py đã tự động đọc my_dataset.csv sẵn - không cần sửa gì thêm)

Có thể chỉnh MAX_PER_INTENT bên dưới nếu muốn lấy nhiều/ít câu hơn.
"""

import csv
import json
import os
import sys
import tarfile
import tempfile

try:
    import requests
except ImportError:
    print("Chưa cài `requests`. Cài bằng:  pip install requests")
    sys.exit(1)

from platform_utils import setup_console, safe_print

setup_console()

MASSIVE_URL = "https://amazon-massive-nlu-dataset.s3.amazonaws.com/amazon-massive-dataset-1.0.tar.gz"
LOCALE = "vi-VN"
OUTPUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "my_dataset.csv")

# Số câu tối đa lấy cho MỖI intent của bạn (tránh 1 intent MASSIVE "cân" quá
# nhiều, làm lệch tỉ lệ so với các intent tự sinh open_app/open_website...).
MAX_PER_INTENT = 250

# ----------------------------------------------------------------------------
# BẢNG ÁNH XẠ: intent của MASSIVE (60 intent gốc) -> intent của BẠN (11 nhóm)
# Chỉ liệt kê các intent MASSIVE thực sự khớp nghĩa - xem lại HUONG_DAN nếu
# muốn thêm/bớt. Sửa trực tiếp dict này nếu bạn muốn map khác đi.
# ----------------------------------------------------------------------------
INTENT_MAP = {
    # --- thời tiết: khớp hoàn hảo ---
    "weather_query": "get_weather",

    # --- ngày giờ: khớp hoàn hảo ---
    "datetime_query": "get_datetime",

    # --- chào hỏi / tán gẫu ---
    "general_greet": "chitchat",
    "general_joke": "chitchat",
    "general_quirky": "chitchat",

    # --- phát nhạc / audio ---
    "play_music": "play_media",
    "play_radio": "play_media",
    "play_podcasts": "play_media",
    "play_podcast": "play_media",   # phòng khi số ít/số nhiều khác bản
    "play_audiobook": "play_media",

    # --- nhắc nhở / báo thức / lịch ---
    "alarm_set": "set_reminder",
    "alarm_query": "set_reminder",
    "calendar_set": "set_reminder",
    "calendar_query": "set_reminder",
}


def download_tar(url: str) -> str:
    safe_print(f"Đang tải MASSIVE dataset từ:\n  {url}")
    safe_print("(khoảng 300-400MB, tuỳ mạng có thể mất vài phút...)")
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".tar.gz")
    os.close(tmp_fd)
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        chunk_size = 1024 * 1024  # 1MB
        with open(tmp_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    print(f"\r  Da tai: {downloaded / 1e6:.1f}MB / {total / 1e6:.1f}MB ({pct:.0f}%)", end="")
        print()
    safe_print("Tải xong.")
    return tmp_path


def extract_locale_jsonl(tar_path: str, locale: str) -> list:
    safe_print(f"Đang giải nén phần dữ liệu '{locale}' từ file tar.gz...")
    with tarfile.open(tar_path, "r:gz") as tar:
        member = None
        for m in tar.getmembers():
            if m.name.endswith(f"{locale}.jsonl"):
                member = m
                break
        if member is None:
            safe_print(f"[LỖI] Không tìm thấy file {locale}.jsonl trong archive.")
            return []
        f = tar.extractfile(member)
        lines = f.read().decode("utf-8").splitlines()
    safe_print(f"Đã lấy {len(lines)} dòng dữ liệu thô cho locale {locale}.")
    return lines


def build_csv(lines: list) -> int:
    buckets = {intent: [] for intent in set(INTENT_MAP.values())}
    seen = set()

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue

        massive_intent = row.get("intent")
        utt = (row.get("utt") or "").strip()
        if not utt or massive_intent not in INTENT_MAP:
            continue

        target_intent = INTENT_MAP[massive_intent]
        key = (utt.lower(), target_intent)
        if key in seen:
            continue
        seen.add(key)
        buckets[target_intent].append(utt)

    total_written = 0
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["text", "intent"])
        for intent, sentences in buckets.items():
            sentences = sentences[:MAX_PER_INTENT]
            for s in sentences:
                writer.writerow([s, intent])
                total_written += 1
            safe_print(f"  {intent:<14}: lấy {len(sentences)} câu (còn dư "
                       f"{max(0, len(buckets[intent]) - MAX_PER_INTENT)} câu, "
                       f"tăng MAX_PER_INTENT nếu muốn lấy thêm)")

    return total_written


def main():
    tar_path = download_tar(MASSIVE_URL)
    try:
        lines = extract_locale_jsonl(tar_path, LOCALE)
    finally:
        try:
            os.remove(tar_path)
        except OSError:
            pass

    if not lines:
        safe_print("Không có dữ liệu để xử lý. Dừng.")
        return

    total = build_csv(lines)
    safe_print(f"\nĐã ghi {total} câu vào: {OUTPUT_CSV}")
    safe_print("Chạy tiếp:  python train_nlu.py   để huấn luyện lại với dữ liệu mới.")
    safe_print("\nLưu ý: MASSIVE dùng giấy phép CC BY 4.0 - nếu công bố sản phẩm,")
    safe_print("nhớ ghi công: FitzGerald et al., \"MASSIVE\", Amazon Science, 2022.")


if __name__ == "__main__":
    main()
