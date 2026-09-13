# Trợ lý ảo tiếng Việt v7.0

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests 220 pass](https://img.shields.io/badge/tests-220%20pass-brightgreen.svg)](vi_voice_assistant/run_tests.py)
[![License MIT](https://img.shields.io/badge/license-MIT-green.svg)](vi_voice_assistant/GIAY_PHEP_MODEL.md)

Trợ lý ảo tiếng Việt chạy bằng dòng lệnh, hiểu tiếng Việt có dấu lẫn không dấu, 11 intent, đa nền tảng (Windows 7/10/11, macOS, Linux, WSL).

**v7.0** là bản nâng cấp toàn diện từ v6.4, fix tất cả lỗi regression sau khi merge 2 bản zip.

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

## Tính năng v7.0

- 11 ý định: web, app, file, system, search, media, reminder, weather, datetime, calculate, chitchat
- Không cần lib ngoài: LiteModel thuần Python ~97-98% chính xác
- Hiểu tiếng Việt tự nhiên: không dấu, teencode, sai chính tả nhẹ, nhiều lệnh 1 câu, nhớ ngữ cảnh
- An toàn: không shell injection, whitelist, regex đã fix, Path wrapper
- Nhắc nhở bền bỉ: atomic save, restore
- Giọng AI: VieNeu-TTS v3-Turbo (Apache 2.0) 10 giọng + clone tức thời

## Cấu trúc

```
vi_voice_assistant/
├── main.py              # CLI chính v7.0
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
├── tests/               # 220 tests
├── run_tests.py         # Test runner không cần pytest
└── README.md / CHANGELOG.md / UPGRADE_REPORT_v7.md
```

## Kiểm thử

```bash
python vi_voice_assistant/run_tests.py
# Ket qua: 220 pass, 0 fail, 0 skip
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

- v7.0 (2026-09-13): Fix regex, Path, Popen, 220 tests pass
- v6.4: VieNeu TTS
- v6.3: WSL support
- v6.2: Fix giờ, số bằng chữ
- v6.0: LiteModel, --once --json
