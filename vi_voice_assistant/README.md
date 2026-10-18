# Trợ lý ảo tiếng Việt v7.10.3

Trợ lý ảo chạy bằng dòng lệnh, hiểu tiếng Việt **có dấu lẫn không dấu**, nhận diện
11 nhóm ý định và thực thi lệnh thật trên Windows (khuyến nghị Windows 10/11), macOS, Linux và WSL.

> **v7.10.3 (2026-10-18)** - công cụ hệ thống trả mã lỗi không còn báo
> thành công chỉ vì tạo được process. Chuỗi dự phòng có tổng timeout 15 giây;
> timeout/kết quả mơ hồ dừng chuỗi, không tự lặp hành động. Mở GUI vẫn bất đồng
> bộ. Confidence ngoài [0,1]/integer quá lớn/bool bị từ chối, không gây crash hay
> hiện 100%; tên ảnh có UUID và child output không lẫn stdout JSON.
> **1585 ca kiểm thử**, thêm 103 ca so với 7.10.2.
>
> **v7.10.2 (2026-10-18)** - callback timer kiểm tra thế hệ, không chỉ ID;
> callback cũ/đúp không chạm vào lịch được phục hồi. Khi tạo timer lỗi, lịch đã
> lưu/lịch lặp còn lại dưới trạng thái **tạm dừng**, có nhãn trong danh sách,
> có thể huỷ; khởi động lại để thử phục hồi, chưa có vòng retry tự động nền.
> Không mất bản ghi khi retry lỗi, không để lịch tạm dừng đã hết hạn tồn tại mãi.
> Chặn lỗi số nguyên lớn/tràn datetime; CI nhận PR nhắm vào mọi nhánh.
> **1482 ca kiểm thử**, thêm 55 ca so với 7.10.1.
>
> **v7.10.1 (2026-10-17)** - tiếp tục hardening: confidence 0/không hợp lệ
> luôn bị từ chối kể cả ngưỡng bằng 0; CSV đọc/ghi dùng khóa liên process có
> timeout, không trộn header/BOM/record. `log_feedback` trả bool sau flush/fsync,
> `teach` không báo ghi nhớ khi thất bại. Context lưu snapshot, dung lượng 0 tắt
> nhớ, không thay đại từ trong URL/path hoặc thay tiếp dữ liệu đã chèn.
> **1427 ca kiểm thử**, thêm 83 ca so với 7.10.0.
>
> **v7.10.0 (2026-10-17)** - sửa vòng đời timer (chia chặng khi nhắc xa,
> huỷ callback cũ, khôi phục idempotent và lịch lặp bỏ lỡ mốc); JSON CLI sạch
> trên stdout, mã thoát phản ánh lỗi và dry-run không chạy lệnh/timer; chặn
> phủ định hệ thống, giữ dấu câu truy vấn/URL và ngữ cảnh. Siết cấu hình,
> containment đường dẫn, số hữu hạn và giới hạn AST toán học; cache lite
> không cho giải tuần tự đối tượng tuỳ ý. Metadata/API/CLI dùng chung phiên bản.
> **1344 ca kiểm thử**, tăng 210, pytest và runner nhúng chạy đủ như nhau.
>
> **v7.8 (2026-09-27)** - **lớp bảo vệ không được làm hỏng thứ nó bảo vệ**:
> `normalize_text` xoá toán tử để câu dễ phân loại, rồi chính con số mất dấu trong
> lớp bảo vệ đó. `"12,75 + 1"` báo `target = "75 + 1"` (=76) nhưng `result = 13.75`;
> `"1.234,5 chia 3"` trả **78.17** thay vì 411.5 vì dấu chấm là dấu **phẩy nghìn**
> kiểu Việt Nam; `"2,5 nhân 4"` bị tách thành hai lệnh nên ra 20 thay vì 10. Nay
> `target` và `result` luôn khớp nhau, dấu chấm nhóm 3 số được đọc là nghìn
> (`1.5`/`12.75` vẫn là thập phân), và phẩy thập phân không bị cắt lệnh.
> `parse_math_expression` hiểu cả câu gõ **không dấu** (`"can bac hai cua 81"`).
> `confidence: NaN` không còn đi thẳng qua ngưỡng an toàn (vì `nan < x` luôn
> False, mà JSON mặc định chấp nhận `NaN`); `feedback.csv` mất dòng tiêu
> đề khiến `train_nlu.py` bỏ qua toàn bộ phần dạy còn lại - nay sửa cả đầu ghi lẫn đầu
> đọc (đọc được cả file không có header, và báo rõ thay vì im lặng);
> `data_path`/`voice_cache` không trèo ra ngoài thư mục dữ liệu. **1134 test**.
>
> **v7.7 (2026-09-20)** - **biên kiểu ở những hàm chưa bị audit**:
> `lite_model.predict("mở youtube")` lặp qua từng KÝ TỰ (model chấm chữ "ở", "y"
> như cả câu nói) - nay một chuỗi = MỘT câu, kiểu không lặp được báo `TypeError`
> nêu đúng tên tham số; `cancel_reminder(123)`, `teach("a", 123)`, `confirm_message({})`
> không còn `AttributeError`/`KeyError`; `log_feedback(..., confidence=None)` không
> làm hỏng `feedback.csv` (đầu vào của lần huấn luyện sau); `save_config` báo lý do
> không nối được JSON TRƯỚC khi chạm đĩa; `from_state` bỏ qua field sai kiểu thay
> vì làm sập lúc khởi động. **518 test**.
>
> **v7.6 (2026-09-20)** - **kho giọng tạo được, nhắc nhở chịu được thời điểm kiểu
> rác**: `python -m vi_voice_assistant.tts --cache` sinh file âm thanh +
> `index.csv` cho các câu lặp lại hằng ngày (máy không có engine ghi file thì báo
> rõ vì sao, không im lặng); `set_reminder` chấp nhận `"time": "3 phút nữa"`/`3`
> thay vì `AttributeError`; trả lời "5 phút nữa" sau câu hỏi "nhắc vào lúc nào?"
> giữ lại ĐƯỢC việc cần nhắc, chạy bằng pytest hoặc runner nhúng.
>
> **v7.5 (2026-09-20)** - **điểm vào chịu được dữ liệu thật**: `config.json` hỏng
> không còn giết mọi lệnh (dùng giá trị mặc định + in rõ lỗi, `--doctor` vẫn chạy);
> `tts.speak(123)`/`speak(None)` không crash và câu rỗng không in `"[TRỢ LÝ] None"`;
> `understand("")` không còn **bịa** một lệnh `open_website/unknown`; `--once ""`
> thoát ngay thay vì rơi vào REPL (treo script/CI); `sanitize_filename` chặn tên dành
> riêng của Windows (CON/AUX/COM1…) và giới hạn 255 byte. 392 test.
>
> **v7.4 (2026-09-20)** - **chất lượng nền**: `mypy` **60 lỗi -> 0** và CI có job
> `typecheck` giữ mức đó; `config.json` / `reminders.json` / `.history.json` ghi bằng
> MỘT hàm atomic duy nhất (`paths.atomic_write_json`: file tạm -> fsync -> replace);
> `vi-doctor` in được báo cáo đầy đủ cả khi một mục hỏng; `install.py` không còn khuyên
> người đang ở trong venv đi tạo venv; `voice_cache/` rời khỏi site-packages; và
> **Python 3.9 chạy được thật** (trước đây `import intent_model` nổ TypeError vì
> annotation PEP 604) - có máy quét AST khoá lại.
>
> **v7.3 (2026-09-20)** - **cài đặt & tiện nghi**: `pip install .` chạy được thật
> (`vi-assistant`, `vi-doctor`, `vi-train`, `vi-voice`), dữ liệu người dùng rời
> khỏi `site-packages` (mới `paths.py`), có `install.py` tự phát hiện môi trường
> và tự chữa lỗi pip (PEP 668), REPL có ↑/↓ + Tab + gợi ý khi gõ sai tên lệnh,
> và `run_tests.py` chạy trọn bộ test trên máy CHƯA cài pytest.
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

## Điểm nổi bật

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

Các lệnh dưới đây chạy từ thư mục `vi_voice_assistant/` của bản checkout.
Nếu đã cài gói, thay `python main.py` bằng `vi-assistant` hoặc
`python -m vi_voice_assistant` từ thư mục bất kỳ.

```bash
# Chạy ngay, chỉ cần Python >= 3.9
python main.py

# Bootstrap ở thư mục gốc
python ../install.py
python ../install.py --check

# Cài chuẩn Python: core không cần thư viện ngoài
pip install ..
pip install "..[full]"          # + scikit-learn, TTS/STT (tuỳ chọn)
python main.py --doctor

# Giọng AI (tuỳ chọn, Python >= 3.10)
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
python main.py --engine auto                # Tự chọn TTS engine
python main.py --history                    # In lịch sử lệnh rồi thoát
python main.py --dry-run                    # chỉ phân tích
python main.py --sysinfo                    # thông tin hệ thống
```

Lệnh trong phiên: `mic`, `voice`, `test`, `nhac nho`, `huy nhac [từ khoá]`, `nap lai`, `day <câu> = <intent>`, `quen`, `help`, `thoat`.

Chi tiết: **HUONG_DAN_SU_DUNG.txt**, **CHANGELOG.md**

### JSON, mã thoát và an toàn

`--json` chỉ dùng với câu lệnh một lần hoặc `--doctor`. Stdout chứa đúng một
giá trị JSON; log và tiến trình khởi động ở stderr. Câu lệnh rỗng trả `[]`.
Mã thoát một lần: `0` đã xử lý; `1` lỗi khởi động/cấu hình/thực thi;
`2` chưa hiểu, cần xác nhận hoặc không phân tích được. Riêng dry-run trả `0`
nếu phân tích được (kể cả `status: "unknown"`); hãy đọc trường `status`.
`--yes` không bỏ ngưỡng tự tin.
`--once` được ưu tiên nếu đồng thời có đối số văn bản. Confidence bằng 0 luôn
bị từ chối, kể cả khi ngưỡng bằng 0.

`--dry-run` không thực thi, hỏi xác nhận, dạy model hay khôi phục timer; vẫn
có thể tạo cache, lịch sử và log. **Lời nhắc chỉ chạy khi tiến trình còn hoạt
động**, không phải lịch nền của hệ điều hành. Khi cài gói, dữ liệu nằm ở thư
mục người dùng; đặt `VI_ASSISTANT_HOME` để chọn thư mục riêng.

### Phản hồi và ngữ cảnh

`log_feedback(...)` trả `True` sau khi ghi và flush/fsync, `False` khi lỗi I/O,
encoding hoặc hết thời gian chờ khóa. `teach(...)` chỉ báo ghi nhớ khi lưu thành
công và nhãn đã được kiểm tra. Chỉ `True` hoặc integer `1` là phản hồi xác nhận;
chuỗi `"false"`/`"0"`/`"1"` không được coi là nhãn đã xác nhận.

Các reader/writer dùng `csv_utils` phối hợp bằng khóa OS (timeout 5 giây).
Khóa không bảo vệ thao tác editor/ghi ngoài helper và append không phải
transaction chống mất điện. `reminders.json`/history vẫn chưa có khóa liên
process; tránh nhiều phiên dùng chung thư mục dữ liệu để ghi các file này.

`ContextMemory(0)` tắt nhớ; dung lượng âm/sai kiểu bị từ chối rõ ràng. Các kết
quả được deepcopy để caller sửa dict không đổi lại lịch sử đã ghi nhận.

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
| `tests/` | 1585 ca kiểm thử | Thêm 2 file `test_v7103_*.py` cho mã thoát công cụ và biên confidence; giữ các test trước, cập nhật mock đúng API chờ process |

## Kiểm thử

```bash
python run_tests.py -q     # 1585 pass, 0 fail - không cần cài gì
# Ép runner nhúng ngay cả khi đã cài pytest:
# Linux/macOS: VI_TESTS_FORCE_EMBEDDED=1 python run_tests.py -q
# PowerShell: $env:VI_TESTS_FORCE_EMBEDDED="1"; python run_tests.py -q
python -m pytest tests/ -q # 1585 passed
# Từ thư mục GỐC repo, sau khi cài ".[dev]":
python -m ruff check .
python -m mypy
```

## Tương thích

- Python 3.9+; khuyến nghị Python 3.12/3.13, Windows 10/11, macOS, Linux hoặc WSL
- Không cam kết Python 3.8/Windows 7; metadata gói yêu cầu Python >= 3.9
- Đã kiểm chứng Linux/Python 3.11 trong sandbox; CI cấu hình Python 3.9–3.13 đa hệ điều hành. Micro/âm thanh/model giọng và thao tác OS thật cần kiểm trên máy đích
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

Xem CHANGELOG.md để biết phạm vi sửa lỗi và các giới hạn đã biết; bộ test không thay thế kiểm thử thiết bị thật.
