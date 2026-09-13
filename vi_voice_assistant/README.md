# Trợ lý ảo tiếng Việt v7.1

Trợ lý ảo chạy bằng dòng lệnh, hiểu tiếng Việt **có dấu lẫn không dấu**, nhận diện
11 nhóm ý định và thực thi lệnh thật trên Windows (kể cả Windows 7), macOS, Linux và WSL.

> **v7.1 (2026-09-13)**: Nâng cấp toàn diện từ v6.4, fix tất cả lỗi regression sau merge 2 bản zip.
> - Fix lỗi regex `bad character range \-( at position 11` trong `executor.py` và `text_utils.py`
> - Fix tương thích `HOME`/`REMINDERS_PATH` khi bị monkeypatch bằng `str` trong tests
> - Thêm wrapper `_popen()` để tương thích mock `Popen(lambda cmd: ...)` trong tests
> - Nâng cấp `tts.py` (RLock, timeout, voice cache), `stt.py` (STT class, RMS fallback), `main.py` (--debug/--no-banner/--config/--engine/--history)
> - Thêm `pyproject.toml`, `requirements.txt`, `logging_setup.py`, `platform_utils.py`
> - 220 tests pass 100%
> - Xem chi tiết trong **CHANGELOG.md** và **UPGRADE_REPORT_v7.md**

## Điểm nổi bật v7.1

- **11 ý định**: mở web, mở app, mở file, điều khiển hệ thống, tìm kiếm, phát nhạc/video, nhắc nhở, thời tiết, xem giờ/ngày, tính toán, chit-chat.
- **Không cần thư viện ngoài**: `lite_model.py` - Naive Bayes n-gram ký tự thuần Python, huấn luyện <1s, ~97-98% chính xác. Tự dùng scikit-learn hoặc PhoBERT nếu có.
- **Thông minh đời thường**: gõ không dấu, teencode, sai chính tả nhẹ, nhiều lệnh trong 1 câu, nhớ ngữ cảnh ("đóng nó lại"), học từ phản hồi, hiểu số viết bằng chữ.
- **An toàn v7.1**: 
  - Không chạy chuỗi người dùng qua shell
  - Whitelist app/web/file trong `config.json`
  - Xác nhận trước hành động nguy hiểm
  - Regex `_SAFE_PATH_RE` đã fix: `r"^[\w\s:\\/.\-()%]+$"` (- ở cuối hoặc escape)
  - `_INVALID_FILENAME_RE` fix: `r'[<>:"/\\|?*]'` + xử lý control chars riêng
  - `_popen()` wrapper tương thích mọi mock
  - `Path(HOME)` / `Path(REMINDERS_PATH)` wrapper cho cả `str` và `Path`
- **Nhắc nhở bền bỉ**: lưu `reminders.json` atomic (tempfile + replace), khôi phục khi mở lại, hiểu "3h30", "3 giờ rưỡi", "8 giờ kém 15", "11 giờ đêm".
- **Giọng AI**: VieNeu-TTS v3-Turbo (Apache 2.0) 10 giọng + nhân bản tức thời từ 3-5s audio, fallback Piper.

## Cài đặt & chạy

```bash
# Chạy ngay, không cần cài gì thêm
python main.py

# Cài đầy đủ (khuyến nghị)
pip install -r requirements.txt
# hoặc
pip install -e .

# Giọng AI
pip install vieneu
python giong_noi_ai.py tai
python giong_noi_ai.py thu "Xin chào Việt Nam"
```

## Cách dùng v7.1

```bash
python main.py                              # hỏi-đáp
python main.py --once "mở youtube"          # 1 lệnh rồi thoát
python main.py --once "mấy giờ" --json      # JSON output
python main.py --version                    # phiên bản + model
python main.py --debug                      # log chi tiết
python main.py --no-banner                  # không banner
python main.py --config my_config.json      # config riêng
python main.py --engine edge                # TTS engine
python main.py --history .history.json      # lịch sử riêng
python main.py --dry-run                    # chỉ phân tích
python main.py --sysinfo                    # thông tin hệ thống
```

Lệnh trong phiên: `mic`, `voice`, `test`, `nhac nho`, `huy nhac [từ khoá]`, `nap lai`, `day <câu> = <intent>`, `quen`, `help`, `thoat`.

Chi tiết: **HUONG_DAN_SU_DUNG.txt**, **CHANGELOG.md**

## Cấu trúc v7.1

| File | Vai trò | v7.1 |
|---|---|---|
| `main.py` | Vòng lặp chính + CLI | + --debug/--no-banner/--config/--engine/--history, signal handling |
| `nlu_advanced.py` | Tầng hiểu ý | Giữ nguyên + type hints |
| `intent_model.py` | Pipeline TF-IDF + entity | Giữ nguyên + type hints |
| `lite_model.py` | Classifier thuần Python | Nâng cấp, không cần sklearn |
| `executor.py` | Thực thi an toàn | **Fix major**: regex, Path wrapper, _popen |
| `text_utils.py` | Xử lý text | **Fix major**: _KEEP_RE, _INVALID_FILENAME_RE |
| `dataset.py` | ~1.530 câu mẫu | Giữ nguyên |
| `config.json` | Whitelist | Giữ nguyên |
| `stt.py` | Giọng nói vào | Nâng cấp: STT class, RMS fallback |
| `tts.py` | Giọng nói ra | Nâng cấp: RLock, timeout, cache |
| `platform_utils.py` | Utils đa nền tảng | Mới v7.1 |
| `logging_setup.py` | Logging | Mới v7.1 |
| `config.py` | Config loader | Mới v7.1 |
| `pyproject.toml` | Metadata | Mới v7.1 |
| `requirements.txt` | Deps | Mới v7.1 |
| `run_tests.py` | Test runner | 220 tests, không cần pytest |
| `tests/` | Unit tests | 220 tests |

## Kiểm thử

```bash
python run_tests.py        # 220 pass, 0 fail - không cần cài gì
pytest tests/ -v           # nếu đã cài pytest
python -m unittest discover
```

## Tương thích

- Python 3.8+ (Windows 7: Python 3.8.x), Windows 8/10/11, macOS, Linux, WSL
- `python main.py --sysinfo` để kiểm tra

## Giấy phép

- Code chính: MIT (xem `GIAY_PHEP_MODEL.md`)
- VieNeu-TTS v3-Turbo: Apache 2.0 (thương mại OK)
- Piper vais1000: CC BY 4.0 (thương mại OK, cần ghi công)

## Nâng cấp từ v6.4

Xem **UPGRADE_REPORT_v7.md** để biết chi tiết các lỗi đã fix và breaking changes.

```bash
git log --oneline v6.4..v7.1
```

Tất cả lỗi regex và Path compatibility đã được fix, không còn regression.
