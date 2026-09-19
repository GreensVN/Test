# Trợ lý ảo tiếng Việt v7.4

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests 367 pass](https://img.shields.io/badge/tests-367%20pass-brightgreen.svg)](vi_voice_assistant/run_tests.py)
[![mypy 0 errors](https://img.shields.io/badge/mypy-0%20errors-informational.svg)](vi_voice_assistant)
[![ruff 0](https://img.shields.io/badge/ruff-0%20warnings-informational.svg)](pyproject.toml)
[![License MIT](https://img.shields.io/badge/license-MIT-green.svg)](vi_voice_assistant/GIAY_PHEP_MODEL.md)

Trợ lý ảo tiếng Việt chạy bằng dòng lệnh, hiểu tiếng Việt có dấu lẫn không dấu, 11 intent, đa nền tảng (Windows 7/10/11, macOS, Linux, WSL).

**v7.4** siết chất lượng nền: `mypy` từ 60 lỗi về **0** và có job CI giữ mức đó;
file dữ liệu (config/reminders/history) ghi bằng MỘT hàm atomic duy nhất có fsync;
`vi-doctor` không còn chết vì một mục hỏng; và **Python 3.9 chạy được thật** - trước
bản này `import intent_model` nổ TypeError trên 3.9 dù README ghi "3.9+".

**v7.3** tập trung vào CÀI ĐẶT và TIỆN NGHI: `pip install .` giờ chạy được thật
(có `vi-assistant`, `vi-doctor`), dữ liệu người dùng không còn nằm trong
`site-packages`, có `install.py` tự phát hiện môi trường + tự chữa lỗi pip
(PEP 668), REPL hỗ trợ phím ↑/↓ và Tab, và model nhẹ cache kết quả chuẩn hoá.
Chi tiết trong [CHANGELOG](vi_voice_assistant/CHANGELOG.md).

**v7.2** là bản trả nợ kỹ thuật: 15 lỗi thật đã sửa (trong đó có 1 lỗi chèn mã
AppleScript qua nội dung nhắc nhở), 347 cảnh báo lint -> 0, và các hàm "20-30
nhánh" được tách thành bảng tra - **hành vi giữ nguyên, có đối chứng tự động**
trên 188k câu. Xem [CHANGELOG](vi_voice_assistant/CHANGELOG.md).

## Cài đặt nhanh

```bash
git clone https://github.com/GreensVN/Test.git
cd Test

# C1. Chạy ngay, không cài gì (chỉ cần Python >= 3.9)
python vi_voice_assistant/main.py

# C2. Cài bằng script của dự án - tu phat hien may, tu xu ly loi pip (PEP 668)
python install.py                  # goi co ban: kiem tra + cai + chay test
python install.py --check          # chi chan doan, khong cai gi
python install.py --profile ml     # + scikit-learn (chinh xac hon lite)
python install.py --profile voice  # + doc/nhan giong noi
python install.py --offline        # may khong co mang
python install.py --dry-run        # chi in lenh se chay

# C3. Cach chuan cua Python
pip install .        # xong:  vi-assistant "mở youtube"
pip install ".[full]" && vi-doctor
python -m vi_voice_assistant        # cai roi van chay duoc bang -m
```

Ba lenh kiem tra nhanh sau khi cai:

```bash
python vi_voice_assistant/main.py --doctor   # may du gi, thieu gi, lenh khac phuc
python vi_voice_assistant/run_tests.py -q    # 367 test, khong can pytest
python vi_voice_assistant/main.py "mở youtube" --dry-run
```

## Tính năng

### v7.3 - cài đặt & tiện nghi
- `pip install .` chay duoc that (truoc day wheel thieu `__init__.py` nen
  `vi-assistant` chet bang `ModuleNotFoundError`)
- Du lieu (config, lời nhắc, log, model) ve `~/.local/share/vi_voice_assistant`
  hoac `%LOCALAPPDATA%...` - khong bi ghi vao / xoa khoi `site-packages`
- `install.py` tu chon lenh pip dung, tu thu `--user` khi bi PEP 668 chan
- `--yes` cho script/CI, ↑/↓ + Tab trong REPL, goi y khi goi sai ten lenh
- Cache `normalize_text`/`strip_diacritics`: 3.4us -> 0.32us; `predict_intent`
  172us -> 140us/moi cau

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
Test/
├── install.py             # Bootstrap cài đặt + tự kiểm tra (chỉ stdlib, mới v7.3)
├── pyproject.toml         # deps = []; [full] [ml] [tts] [stt] [dev] [all]
└── vi_voice_assistant/
    ├── __init__.py        # Nối import phẳng -> `pip install .` chạy được (mới v7.3)
    ├── __main__.py        # python -m vi_voice_assistant              (mới v7.3)
    ├── paths.py           # Thư mục dữ liệu người dùng, không còn site-packages (v7.3)
    ├── diagnostic.py      # --doctor / vi-doctor: chẩn đoán + lệnh khắc phục (v7.3)
    ├── main.py            # CLI chính + REPL (bảng lệnh điều khiển, ↑/↓, Tab, --yes)
    ├── nlu_advanced.py    # Tầng hiểu ý: không dấu, typo, ngữ cảnh, đa lệnh
    ├── intent_model.py    # Model TF-IDF + trích xuất thực thể/thời gian/toán
    ├── lite_model.py      # Model thuần Python (Naive Bayes) + "bảo chứng từ điển"
    ├── executor.py        # Thực thi lệnh theo nền tảng (bảng whitelist, escape)
    ├── text_utils.py      # normalize/strip dấu (cache LRU - v7.3)
    ├── dataset.py         # ~1.5k câu mẫu, tự sinh bản không dấu
    ├── config.py          # Nạp/kiểm tra/lưu config.json (atomic)
    ├── tts.py / stt.py    # Giọng nói ra / vào, engine dự phòng
    ├── giong_noi_ai.py    # Giọng AI VieNeu-TTS (Apache 2.0)
    ├── platform_utils.py  # capability report, safe_print, setup_console
    ├── logging_setup.py   # logs/ trong thư mục dữ liệu, lock thật
    ├── run_tests.py       # Test runner KHÔNG cần pytest (367 test)
    └── tests/             # 367 test (hồi quy v7.2 + v7.3 + v74 compat/hardening)
```

## Kiểm thử

```bash
# Ca hai cach deu chay duoc 367 test - may CHUA cai pytest van ok
python -m pytest vi_voice_assistant/tests -q
python vi_voice_assistant/run_tests.py
# Ket qua: 367 pass, 0 fail, 0 skip

# Kiem chat luong nen (CI that hai muc nay - xem job lint/typecheck):
python -m ruff check .                     # 0 canh bao
python -m mypy                             # 0 loi (doc [tool.mypy] trong pyproject.toml)
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

- v7.4 (2026-09-20): mypy 60->0 + job typecheck, ghi file atomic co fsync, sua loi sap tren Python 3.9, 367 tests
- v7.3 (2026-09-20): `pip install .` chay that, paths.py, install.py, vi-doctor, 330 tests
- v7.2 (2026-09-13): 15 lỗi thật + 347 lint -> 0, 251 tests pass, refactor C901
- v7.1 (2026-09-13): Dọn cấu trúc dự án, đồng bộ docs/version, typing hiện đại
- v7.0 (2026-09-13): Fix regex, Path, Popen, 220 tests pass
- v6.4: VieNeu TTS
- v6.3: WSL support
- v6.2: Fix giờ, số bằng chữ
- v6.0: LiteModel, --once --json
