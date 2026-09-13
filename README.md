# Trợ lý ảo tiếng Việt v7.2

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests 251 pass](https://img.shields.io/badge/tests-251%20pass-brightgreen.svg)](vi_voice_assistant/run_tests.py)
[![License MIT](https://img.shields.io/badge/license-MIT-green.svg)](vi_voice_assistant/GIAY_PHEP_MODEL.md)

Trợ lý ảo tiếng Việt chạy bằng dòng lệnh, hiểu tiếng Việt có dấu lẫn không dấu, 11 intent, đa nền tảng (Windows 7/10/11, macOS, Linux, WSL).

**v7.2** là bản trả nợ kỹ thuật: 15 lỗi thật đã sửa (trong đó có 1 lỗi chèn mã
AppleScript qua nội dung nhắc nhở), 347 cảnh báo lint -> 0, và các hàm "20-30
nhánh" được tách thành bảng tra - **hành vi giữ nguyên, có đối chứng tự động**
trên 188k câu. Xem [CHANGELOG](vi_voice_assistant/CHANGELOG.md).

## Cài đặt nhanh

```bash
git clone https://github.com/GreensVN/Test.git
cd Test

# Chạy ngay không cần cài gì
python vi_voice_assistant/main.py

# Hoặc cài đầy đủ
pip install -e .
pip install -e ".[full]"
vi-assistant
```

## Tính năng

### v7.2 - sửa lỗi & chất lượng code
- Không còn "thực thi bừa câu vô nghĩa": model lite có **bảo chứng từ điển**
  (`evidence_ratio`) - câu rác bị hạ confidence xuống ~0% và REPL hỏi lại
- Escape AppleScript/Powershell đúng thứ tự; lời nhắc lưu/xoá ra đĩa (atomic),
  `restore_reminders` bỏ mục quá hạn
- `config.json` sửa tay sai kiểu không còn làm sập chương trình lúc import;
  validation gọi tên ĐÚNG khoá bị thiếu/bị gõ sai
- Lệnh `nap lai` nạp lại cả ngưỡng tự tin của tầng NLU (trước đây chỉ executor)
- `run_tests.py` trả exit code thật; CI bỏ `pytest || run_tests.py` (nguồn
  "CI xanh giả"), thêm bước ruff + Python 3.13 + job "chỉ stdlib"
- 347 -> 0 cảnh báo ruff; các hàm C901 (REPL dispatcher, system control theo
  nền tảng, parse giờ/entity/số) tách thành bảng tra + handler

### v7.0 - nền tảng

- 11 ý định: web, app, file, system, search, media, reminder, weather, datetime, calculate, chitchat
- Không cần lib ngoài: LiteModel thuần Python ~97-98% chính xác
- Hiểu tiếng Việt tự nhiên: không dấu, teencode, sai chính tả nhẹ, nhiều lệnh 1 câu, nhớ ngữ cảnh
- An toàn: không shell injection, whitelist, regex đã fix, Path wrapper
- Nhắc nhở bền bỉ: atomic save, restore
- Giọng AI: VieNeu-TTS v3-Turbo (Apache 2.0) 10 giọng + clone tức thời

## Cấu trúc

```
vi_voice_assistant/
├── main.py              # CLI chính v7.2
├── executor.py          # Thực thi an toàn (fix major v7.0)
├── text_utils.py        # Xử lý text (fix major v7.0)
├── nlu_advanced.py      # Tầng NLU
├── intent_model.py      # Model TF-IDF + entity
├── lite_model.py        # Model thuần Python
├── tts.py / stt.py      # Giọng nói (nâng cấp v7.0)
├── platform_utils.py    # Utils đa nền tảng (mới v7.0)
├── logging_setup.py     # Logging (mới v7.0)
├── config.py            # Config loader (mới v7.0)
├── giong_noi_ai.py      # Giọng AI VieNeu
├── tests/               # 251 tests
├── run_tests.py         # Test runner không cần pytest
└── README.md / CHANGELOG.md / UPGRADE_REPORT_v7.md
```

## Kiểm thử

```bash
python vi_voice_assistant/run_tests.py
# Ket qua: 251 pass, 0 fail, 0 skip
```

## Tài liệu

- [README chi tiết](vi_voice_assistant/README.md)
- [CHANGELOG](vi_voice_assistant/CHANGELOG.md)
- [Báo cáo nâng cấp v7.0](vi_voice_assistant/UPGRADE_REPORT_v7.md)
- [Hướng dẫn sử dụng](vi_voice_assistant/HUONG_DAN_SU_DUNG.txt)
- [Giấy phép model](vi_voice_assistant/GIAY_PHEP_MODEL.md)

## Giấy phép

- Code: MIT
- VieNeu-TTS: Apache 2.0 (thương mại OK)
- Piper: CC BY 4.0 (thương mại OK, cần ghi công)

## Đóng góp

Xem issues và tạo PR từ nhánh `arena/*`.

## Lịch sử

- v7.2 (2026-09-13): 15 lỗi thật + 347 lint -> 0, 251 tests pass, refactor C901
- v7.1 (2026-09-13): Dọn cấu trúc dự án, đồng bộ docs/version, typing hiện đại
- v7.0 (2026-09-13): Fix regex, Path, Popen, 220 tests pass
- v6.4: VieNeu TTS
- v6.3: WSL support
- v6.2: Fix giờ, số bằng chữ
- v6.0: LiteModel, --once --json
