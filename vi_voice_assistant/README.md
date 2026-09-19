# Trợ lý ảo tiếng Việt v7.3

Trợ lý ảo chạy bằng dòng lệnh, hiểu tiếng Việt **có dấu lẫn không dấu**, nhận diện
11 nhóm ý định và thực thi lệnh thật trên Windows (kể cả Windows 7), macOS, Linux và WSL.

> **v7.3 (2026-09-20)** - **cài đặt & tiện nghi**: `pip install .` chạy được thật
> (`vi-assistant`, `vi-doctor`, `vi-train`, `vi-voice`), dữ liệu người dùng rời
> khỏi `site-packages` (mới `paths.py`), có `install.py` tự phát hiện môi trường
> và tự chữa lỗi pip (PEP 668), REPL có ↑/↓ + Tab + gợi ý khi gõ sai tên lệnh,
> và `run_tests.py` chạy trọn 330 test trên máy CHƯA cài pytest.
>
> **v7.2 (2026-09-13)** - bản **trả nợ kỹ thuật**: 15 lỗi thật đã sửa, 347 cảnh
> báo lint -> 0, 220 -> 251 test, và các hàm "20-30 nhánh" được tách thành bảng tra.
> Điểm đáng chú ý nhất:
> - **Bảo mật**: `executor._escape_osascript` escape sai thứ tự -> nội dung nhắc nhở
>   thoát khỏi chuỗi và chạy thành mã AppleScript. Đã sửa thứ tự escape (+ test).
> - **Đúng như quảng cáo**: `pip install .` không còn bắt cài scikit-learn/numpy;
>   `run_tests.py` trả exit code thật (trước đây luôn 0 -> "220 pass" có thể là ảo giác).
> - **Không làm gì sai khi không hiểu**: model lite có "bảo chứng từ điển", câu vô
>   nghĩa bị hạ confidence về ~0% -> trợ lý hỏi lại thay vì thực thi bừa.
> - **Bền dữ liệu**: `huy nhac`/lời nhắc mới được ghi xuống `reminders.json` ngay,
>   mục quá hạn không "nổ" dồn khi bật máy; `nap lai` nạp lại cả ngưỡng tự tin của NLU.
> - **Hành vi KHÔNG đổi**: đối chiếu tự động với bản v7.1 trên 188k câu
>   (số + giờ + thực thể) = 0 khác biệt.
>
> Chi tiết từng lỗi: **CHANGELOG.md**; báo cáo các bản trước: **UPGRADE_REPORT_v7.md**.

## Điểm nổi bật v7.2

- **11 ý định**: mở web, mở app, mở file, điều khiển hệ thống, tìm kiếm, phát nhạc/video, nhắc nhở, thời tiết, xem giờ/ngày, tính toán, chit-chat.
- **Không cần thư viện ngoài**: `lite_model.py` - Naive Bayes n-gram ký tự thuần Python, huấn luyện <1s, ~97-98% chính xác. Tự dùng scikit-learn hoặc PhoBERT nếu có.
- **Thông minh đời thường**: gõ không dấu, teencode, sai chính tả nhẹ, nhiều lệnh trong 1 câu, nhớ ngữ cảnh ("đóng nó lại"), học từ phản hồi, hiểu số viết bằng chữ.
- **An toàn**: 
  - Không chạy chuỗi người dùng qua shell
  - Whitelist app/web/file trong `config.json`
  - Xác nhận trước hành động nguy hiểm
  - Regex `_SAFE_PATH_RE` đã fix: `r"^[\w\s:\\/.\-()%]+$"` (- ở cuối hoặc escape)
  - `_INVALID_FILENAME_RE` fix: `r'[<>:"/\\|?*]'` + xử lý control chars riêng
  - `_popen()` wrapper tương thích mọi mock
  - `Path(HOME)` / `Path(REMINDERS_PATH)` wrapper cho cả `str` và `Path`
  - Escape nháy kép/backslash theo đúng thứ tự cho AppleScript *và* PowerShell
- **Nhắc nhở bền bỉ**: lưu `reminders.json` atomic (tempfile + replace), khôi phục khi mở lại, hiểu "3h30", "3 giờ rưỡi", "8 giờ kém 15", "11 giờ đêm".
- **Giọng AI**: VieNeu-TTS v3-Turbo (Apache 2.0) 10 giọng + nhân bản tức thời từ 3-5s audio, fallback Piper.

## Cài đặt & chạy

```bash
# Chạy ngay, không cần cài gì thêm
python main.py

# Hoac dung bootstrap o thu muc goc (tu kiem tra may + tu chua loi pip)
python ../install.py            # cai goi co ban
python ../install.py --check    # chi chan doan

# Cai chuan Python -> co lenh toan cuc
pip install ..                  # vi-assistant "mở youtube"
pip install "..[full]"          # + scikit-learn, TTS/STT
python main.py --doctor         # may da du gi, thieu gi, lenh khac phuc la gi
```

# Cài đầy đủ (khuyến nghị)
pip install -r requirements.txt
# hoặc
pip install -e .

# Giọng AI
pip install vieneu
python giong_noi_ai.py tai
python giong_noi_ai.py thu "Xin chào Việt Nam"
```

## Cách dùng

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

## Cấu trúc

| File | Vai trò | Thay đổi ở v7.2 |
|---|---|---|
| `paths.py` | Thư mục dữ liệu người dùng | **Mới v7.3** - `pip install` không còn ghi vào site-packages |
| `diagnostic.py` | `--doctor` / `vi-doctor` | **Mới v7.3** - chẩn đoán cài đặt + in lệnh khắc phục |
| `__init__.py` / `__main__.py` | Nạp gói | **Mới v7.3** - làm `pip install .` và `python -m vi_voice_assistant` chạy được |
| `main.py` | Vòng lặp chính + CLI | v7.3: `main.py "câu lệnh"`, `--yes`, `--doctor`, ↑/↓ + Tab, gợi ý lệnh gõ sai. v7.2: tách REPL thành bảng lệnh `_CONTROL_COMMANDS`/`_CONTROL_PREFIXES` + `ReplState`/`ReplContext` (test được từng lệnh) |
| `nlu_advanced.py` | Tầng hiểu ý | `refresh_thresholds()`: `nap lai` đổi được ngưỡng; ngưỡng hỏng trong config không còn làm sập lúc import |
| `intent_model.py` | Pipeline TF-IDF + entity | `parse_time_expression`/`extract_entity`/`_parse_number_run` tách thành bảng quy tắc + handler (hành vi giữ nguyên) |
| `lite_model.py` | Classifier thuần Python | **`evidence_ratio()`** - câu không có từ đã biết bị hạ confidence; từ điển suy ra từ `_log_prob` nên file model cũ vẫn dùng được |
| `executor.py` | Thực thi an toàn | Bảng `COMMANDS_/VOLUME_` theo nền tảng + handler riêng; `None` = "nền tảng không làm được" -> `[BỎ QUA]`; sửa escape osascript; reminders ghi đĩa |
| `text_utils.py` | Xử lý text | Giữ nguyên |
| `dataset.py` | ~1.530 câu mẫu | `_generate()` không còn chia cho 0 khi một danh sách mẫu câu bị để trống |
| `config.json` / `config.py` | Whitelist + nạp cấu hình | `_validate_config()` hết là code chết: gọi tên khoá thiếu/khoá lạ, chặn map sai kiểu sớm |
| `stt.py` | Giọng nói vào | `_capture_audio`/`_recognize` tách rõ, bỏ hard-code 44 byte WAV header |
| `tts.py` | Giọng nói ra | `_engine_order()`/`_try_engine()`: engine sai tên có cảnh báo, engine chết tự chuyển |
| `platform_utils.py` | Utils đa nền tảng | `setup_console()` khôi phục encoding cũ |
| `logging_setup.py` | Logging | Lock thật (`threading`), hết race khi nhiều thread ghi log |
| `giong_noi_ai.py` | Giọng AI VieNeu | CLI chuyển sang bảng `_CLI_COMMANDS` |
| `pyproject.toml` | Metadata | `dependencies = []`, marker `python_version < "3.9"` đã bỏ, ignore ruff có chú thích |
| `run_tests.py` | Test runner | Uỷ quyền pytest + trả exit code thật |
| `tests/` | 330 test | + `test_v72_regressions.py` (31 test hồi quy, mỗi test gắn một lỗi) |

## Kiểm thử

```bash
python run_tests.py        # 330 pass, 0 fail - không cần cài gì
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
git log --oneline v6.4..v7.2
```

Tất cả lỗi regex và Path compatibility đã được fix, không còn regression.
