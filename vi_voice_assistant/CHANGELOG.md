# CHANGELOG

## v7.4 (2026-09-20) - Toàn vẹn dữ liệu & kiểu: mypy 60 lỗi -> 0, 367 test

### Vì sao bản này tồn tại
v7.3 làm cho dự án **cài được**. Bản này trả hai món nợ mà các bản trước để lại:
(1) `[tool.mypy]` có sẵn trong pyproject nhưng **chưa từng được chạy** - bật lên
thấy ngay 60 lỗi, trong đó có một lỗi làm `vi-doctor` sập; (2) file dữ liệu của
người dùng vẫn được ghi theo kiểu "mở ra là mất nội dung cũ". Xen giữa là một lỗi
làm **toàn bộ trợ lý chết trên Python 3.9** - bản mà README và CI đều nói hỗ trợ.

### Lỗi thật đã sửa
1. **`import intent_model` chết trên Python 3.9** [CRITICAL]
   `str | None` trong chữ ký hàm (PEP 604) cần Python 3.10, còn `intent_model.py`
   và `nlu_advanced.py` KHÔNG có `from __future__ import annotations`. Trên 3.9:
   `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'` ngay lúc
   import, tức mọi tính năng chết chứ không riêng gì máy học. CI có job 3.9 nhưng
   workflow chưa nằm trên nhánh mặc định nên chưa lần nào chạy; lỗi sống dai từ
   v7.1. Sửa: thêm future import (hành vi trên 3.10+ giữ nguyên) + máy quét AST
   trong `tests/test_v74_compat.py` khoá lại - quét cả `tests/` vì test cũng phải
   chạy trên 3.9 (chính file test mới này từng vi phạm đúng rule nó kiểm).
2. **`import train_phobert` tự chạy... vòng huấn luyện** [HIGH]
   `main()` nằm NGOÀI khối `if __name__ == "__main__":` (lệch đúng một cấp thụt
   lề), nên IDE/pytest/bộ kiểm tra import nào chạm vào là bị kéo qua toàn bộ
   pipeline; nặng hơn `parse_args()` đọc argv của chương trình gọi nên tiến trình
   nhận `SystemExit(2)` không lời giải thích. Nay `main(argv=None) -> int` và chỉ
   gọi trong khối guard - đúng khuôn `train_nlu`/`run_tests` đã sửa ở v7.3.
3. **`vi-doctor` chết trước khi in nổi một dòng trên Python >= 3.14**
   `platform.major` không tồn tại (phải là `sys.version_info.major`), và nó nằm ở
   nhánh chỉ chạy khi Python *mới hơn* bản đã kiểm tra - đúng chỗ không ai test.
   Quan trọng hơn: mỗi mục báo cáo giờ đi qua `_section_result()`, nên một mục
   hỏng (file model đọc không được, quyền thư mục...) thành dòng `[X]` chứ không
   kéo sập cả báo cáo, và CLI không bao giờ ném traceback cho người dùng.
4. **Báo cáo tự mâu thuẫn**: `print_report` in "Mọi thứ ổn - chạy: python main.py"
   mỗi lần không có lệnh gợi ý nào - kể cả khi còn mục `[X]` và exit code là 1.
5. **Dispatcher chọn cách gọi handler bằng bảng GHI TAY** (`_HANDLERS_WITH_DATA`):
   thêm handler 2 tham số mà quên ghi tên vào bảng thì gọi `handler(target)` ->
   TypeError. Nay suy ra từ `inspect.signature` (bọc `lru_cache`); tên cũ vẫn còn
   nhưng là giá trị TÍNH RA nên không lệch được nữa.
6. **`target` không phải chuỗi làm sập dispatcher**: `(2026 or "").strip()` ->
   AttributeError. Nay ép kiểu TRƯỚC khi strip; `intent` không phải chuỗi thì báo
   "không hiểu ý định" thay vì lỗi dict.
7. **Mục map lệch kiểu trong config.json lọt qua im lặng**:
   `CONFIG.get("app_map_linux", {})` trả nguyên giá trị, nên `"app_map_linux": null`
   hoặc nhầm sang chuỗi nổ ở `subprocess` - nơi người dùng chỉ thấy traceback. Nay
   `_as_map()` trả dict rỗng + ghi log, rơi vào nhánh "chưa cấu hình" đã có sẵn
   hướng dẫn sửa đúng tên key.
8. **`giong_nc`: file JSON đồng ý giấy phép hỏng làm sập CLI** - `json.load` trả gì
   trả; nay chỉ chấp nhận dict.
9. **`monkeypatch.setenv` của runner nhúng không hoàn tác được**: `os.environ` không
   phải dict, `undo()` gọi `delattr` rồi im lặng bỏ qua -> biến môi trường đặt ở
   test trước RÒ sang mọi test chạy sau (kết quả phụ thuộc thứ tự). Thêm `delenv`
   (pytest có, shim thiếu) và đánh dấu bản ghi kiểu "item" để undo dùng đúng phép.

12. **`voice_cache/` vẫn nằm trong site-packages** - chỗ cuối cùng chưa theo
    `paths.py` (bản v7.3 đã chuyển config/model/log/history nhưng quên kho giọng).
    Hệ quả: bản cài bằng pip bắt người dùng nhét mp3 vào thư mục thường CHỈ ĐỌC và
    bị xoá khi nâng cấp. Nay `VOICE_CACHE_DIR = data_path("voice_cache")`, và
    thư mục cũ cạnh mã nguồn vẫn được ĐỌC tiếp (ai đã có cache từ bản 6.x không
    mất gì). Cùng lúc, `_load_voice_cache()` chỉ nhận file thật sự tồn tại - trước
    đây một dòng lệch trong `index.csv` đưa Path ảo vào bảng tra, tts thử "phát"
    file không có.

### Toàn vẹn dữ liệu (thay đổi chính)
`paths.atomic_write_json()` - MỘT hàm duy nhất: file tạm cùng thư mục -> flush +
`fsync` -> `os.replace` -> `fsync` thư mục -> dọn file tạm khi lỗi. Ba nơi trước
đây tự viết ba biến thể, nay dùng chung:
- `config.save_config`: đã có fsync, giữ nguyên hành vi;
- `executor._save_reminders`: thiếu fsync và **thiếu tạo thư mục cha** - khi
  `REMINDERS_PATH` trỏ vào thư mục chưa tồn tại thì `mkstemp` raise và `except
  OSError` nuốt mất, nhắc nhở biến mất không một lời báo;
- `main.save_history_entry`: nặng nhất - `open("w")` cắt file ngay, tiến trình
  chết giữa chừng (Ctrl+C, hết đĩa, mất điện) để lại `.history.json` rỗng.
Chi phí đo được: **0,25 ms -> 1,39 ms mỗi lần lưu** (100 lần, trên tmpfs). History
chỉ ghi một lần mỗi lệnh nên không cảm nhận nổi; đổi lại là không mất dữ liệu.

### Kiểu được kiểm tra thật
- `[tool.mypy]` bật đủ độ: `check_untyped_defs`, `no_implicit_optional`,
  `warn_redundant_casts`, `warn_unused_ignores`, `files` gồm cả `install.py`.
  `python_version` phải đẩy lên 3.10 vì mypy không còn phân tích cho 3.9 - việc
  chạy *thật* trên 3.9 do job `test` (ma trận 3.9-3.13) và `test_v74_compat.py` lo.
- **60 lỗi -> 0** trên 37 file nguồn (kể cả test). `tests/` được nới lỏng có ghi
  rõ lý do trong pyproject: `lambda p: opened.append(p) or True` là phong cách test
  hợp lệ, siết ở đó chỉ sinh noise chứ không bắt thêm bug của người dùng.
- CI thêm job `typecheck` (mypy pinned) -> tổng cộng **7 job**.

### Cài đặt thông minh hơn
`install.py` từng khuyên người ĐANG ở trong venv... đi tạo venv, và thử `--user` /
`--break-system-packages` - hai cờ mà pip từ chối trong venv -> một lần lỗi vô ích
rồi vẫn tắc. Nay `in_virtualenv()` (VIRTUAL_ENV / CONDA_PREFIX / sys.prefix) quyết
định hướng: trong venv thì không đổi cờ, in hướng dẫn đúng (`python -m pip
--version`, venv nằm trên đĩa chỉ đọc thì tạo lại ở nơi khác). `retry_flags_for`
nhận `in_venv` như tham số THUẦN để test được mọi nhánh trên mọi máy.

### Runner nhúng: hai chỗ tự nói dối
10. **Chạy `run_tests.py` trên bản cài bằng pip in ra "0 pass, 0 fail" với exit 0** -
    wheel cố ý không kèm `tests/`, nên lệnh đó không kiểm tra gì mà vẫn xanh. Cùng
    họ với `|| echo passed` từng có trong CI. Nay: không thấy file test nào thì in
    rõ nguyên nhân + đường dẫn đã tìm, và trả **exit 1**.
11. **Không có cách nào test chính runner nhúng trên máy CÓ pytest** - mọi lệnh
    `run_tests.py` đều bị đẩy sang pytest thật, nên phần shim (fixture,
    parametrize, caplog, monkeypatch...) nằm ngoài vùng kiểm tra, hỏng cũng
    không ai biết. Thêm `VI_TESTS_FORCE_EMBEDDED=1` để cưỡng chế runner nhúng;
    job `embedded-runner` trong CI giờ cài pytest rồi *vẫn* chạy runner nhúng,
    nên phần đó được kiểm tra bất kể image của runner đổi ra sao.

### Test
`tests/test_v74_hardening.py` (29) + `tests/test_v74_compat.py` (8) -> **367 test**,
xanh trên cả ba cách chạy: pytest, `python vi_voice_assistant/run_tests.py` từ gốc,
và `python run_tests.py` từ trong package trên máy chưa cài pytest.

## v7.3 (2026-09-20) - Cài đặt & tiện nghi: `pip install .` chạy ĐƯỢC, 330 test

### Vì sao bản này tồn tại
v7.2 dọn code nhưng KHÔNG ai kiểm tra xem dự án **sau khi cài đặt** còn chạy
được không. Vừa kiểm tra là thấy nó chết ngay. Bản này nhắm đúng ba chỗ:
cài đặt, dùng hằng ngày, và tốc độ.

### Lỗi nghiêm trọng đã sửa (cài đặt / đóng gói)
1. **`pip install .` tạo ra gói DÙNG KHÔNG ĐƯỢC** [CRITICAL]
   - Triệu chứng: `vi-assistant` chết bằng
     `ModuleNotFoundError: No module named 'platform_utils'`.
   - Nguyên nhân: wheel chứa đủ file `.py` nhưng package không có `__init__.py`,
     mà toàn bộ mã nguồn dùng import PHẲNG (thiết kế "chạy thẳng từ thư mục").
   - Sửa: thêm `vi_voice_assistant/__init__.py` (nối thư mục gói vào `sys.path`
     MỘT LẦN, không sửa 20 file import) + `__main__.py` cho
     `python -m vi_voice_assistant`; khai báo tường minh `packages` +
     `package-data` trong pyproject.
2. **Dữ liệu người dùng bị ghi vào `site-packages`**
   - `config.json`/`reminders.json`/`feedback.csv`/`logs/`/model `.pkl` đều lấy
     `Path(__file__).parent` làm chỗ lưu -> máy cài system-wide (read-only) thì
     `PermissionError` giữa phiên, và MỌI dữ liệu bị xoá khi nâng cấp gói.
   - Sửa: module `paths.py` mới, quy tắc
     `$VI_ASSISTANT_HOME` → thư mục source (nếu ghi được) →
     `%LOCALAPPDATA%` / `~/Library/Application Support` / `$XDG_DATA_HOME`;
     thư mục không tạo được thì rơi về temp dir có PID (KHÔNG bao giờ crash).
3. **File riêng tư của người build bị phát tán trong wheel**
   - `include-package-data = true` khiến setuptools vơ cả file đang có trên đĩa
     (`.history.json` - tức NHỮNG CÂU ĐÃ NÓI với trợ lý) vào wheel.
   - Sửa: `include-package-data = false` + `package-data` liệt kê đích danh
     6 file cần thiết; thêm bước CI kiểm wheel không có file runtime/tests.
4. **`config.json` không đi theo wheel** -> bản đã cài chạy với cấu hình mặc định
   trong code, mất whitelist. Nay `paths.migrate_from_package_dir()` chép một lần
   (không bao giờ ghi đè) dữ liệu từ gói sang thư mục người dùng.
5. **`python run_tests.py -q` chết trên máy chưa cài pytest**: runner tự định nghĩa
   argparse nhưng không có cờ `-q` -> `unrecognized arguments`, trong khi CI
   `no-deps` và `install.py` chính xác là gọi như vậy. Nay nhận `-q` thật và bỏ
   qua cờ lạ (`parse_known_args`).
6. **Runner nhúng thiếu 4 khả năng của pytest** - mỗi cái đều biến test HỢP LỆ
   thành lỗi trên máy chưa cài pytest:
   - fixture-nhà-fixture (`def fx(tmp_path, monkeypatch)`) -> TypeError;
   - fixture `yield` -> test nhận generator, teardown không chạy;
   - thiếu `caplog` -> missing argument;
   - `monkeypatch.setattr(..., raising=False)` -> TypeError;
   - `parametrize` một tham số là LIST bị bung thành TỪNG KÝ TỰ
     (`main.py: error: unrecognized arguments: - h i s t o r y`).
   Thêm: `__spec__` cho module giả (nếu không, `import pytest` chết bằng
   `pytest.__spec__ is None`), và `_detect_real_pytest()` để shim không tự nhận
   mình là pytest thật ở lần import thứ hai.
7. **`import run_tests` giữa một phiên pytest che mất pytest thật** (gán
   `sys.modules["pytest"]` vô điều kiện) -> fixture/mark của các file chạy sau
   hỏng khó hiểu. Nay chỉ lắp shim khi KHÔNG có pytest thật.
8. **Test của v7.3 tụt ở chế độ nhúng** (chỉ copy thư mục con rồi chạy,
   không cài gì): hai test import theo tên package nên cần thư mục gốc trên đường
   dẫn import. File test tự thêm gốc vào `sys.path`; bây giờ bộ test xanh ở cả ba cách
   chạy: `pytest`, `python vi_voice_assistant/run_tests.py` từ gốc, và
   `python run_tests.py` từ bên trong package không cần `PYTHONPATH`.

### Tiện lợi (CLI)
- **Nói thẳng ra lệnh, không cần cờ**: `vi-assistant "mở youtube"` (thay vì
  bắt nhớ `--once`); `--once` vẫn giữ nguyên.
- **`--yes` / `-y`**: bỏ bước xác nhận cho script/CI; `_confirm()` khi không có
  bàn phím tương tác nay nói rõ NGUYÊN NHÂN + chỉ cách khắc phục, thay vì "[HỦY]"
  lạnh lùng.
- **`--doctor` (và `vi-doctor`)**: chẩn đoán cài đặt trong một lần chạy -
  Python, nền tảng, đang chạy source hay pip, thư mục dữ liệu có ghi được không,
  config hợp lệ + đếm whitelist THẬT theo nền tảng, model đã cache/fingerprint còn
  hợp không, từng thư viện tuỳ chọn, engine TTS, giọng AI - và in ĐÚNG lệnh cần gõ
  (đã khử trùng lặp). Có `--json` cho công cụ.
- **Phím ↑/↓ gọi lại lệnh cũ + Tab hoàn thành tên lệnh** trong REPL (dùng
  `readline` nếu có, nhập history từ `.history.json` sẵn có; không có readline
  thì REPL y hệt trước - nâng cấp tuỳ chọn, không phải yêu cầu mới).
- **Gợi ý khi gõ sai lệnh**: `he thogng` -> "Có phải bạn muốn gõ  he thong ?".
  Bảng gợi ý lấy trực tiếp từ table đăng ký lệnh, nên thêm lệnh mới tự được gợi ý.
  An toàn: KHÔNG BAO GIỜ gợi ý lệnh thoát (`hát` không còn bị xui "thoát"), và
  chỉ áp cho câu <= 2 từ.
- Console scripts mới: `vi-doctor`, `vi-train`, `vi-voice`; `train_nlu`/`run_tests`
  có `main()` trả mã exit thật + `--lite` (huấn luyện model không cần sklearn).
- `install.py` ở thư mục gốc: cài đặt một lệnh, chỉ dùng stdlib -
  `--check`, `--profile core|ml|voice|full|all|dev`, `--offline`, `--dry-run`,
  `--index-url`; tự xử lý PEP 668 theo trình tự an toàn
  (`--user` trước, `--break-system-packages` chỉ khi hết cách) và nhắc tạo venv
  bằng đúng cú pháp của nền tảng đang chạy.

### Hiệu năng
- `text_utils.normalize_text()` / `strip_diacritics()` có cache LRU 8192 câu:
  tầng NLU gọi lại cùng một chuỗi hàng chục lần cho MỘT câu nói.
  Đo: 3.4µs -> **0.32µs** mỗi lần lặp lại; `predict_intent` 172µs -> **140µs**/câu.
- Đầu vào không phải chuỗi được ép sang `str` thay vì `AttributeError`.
- Startup đã nhanh sẵn (83ms toàn bộ tiến trình, model lite cache 5ms) nên KHÔNG
  "tối ưu" thêm bằng cách hy sinh độ đọc được của code; con số đo được ghi trong
  test để không ai phải đoán lại.

### Kiểm chứng
- 251 -> **330 test**; `pytest` và `python run_tests.py` (môi trường KHÔNG có
  pytest) đều **330 pass / 0 fail** - xác nhận bằng venv sạch không cài pytest.
- `ruff check .` = 0 (thêm `install.py`, `paths.py`, `diagnostic.py` vào vùng lint).
- Cài thật + chạy thật: `pip install .` trong venv → `vi-assistant --version`,
  `vi-doctor`, `python -m vi_voice_assistant --once ...` từ `cwd` khác;
  chmod read-only thư mục cài đặt vẫn chạy, dữ liệu rơi vào `~/.local/share/...`.
- Wheel mới: 34 file, `__init__.py`/`__main__.py`/`config.json`/`diagnostic.py`
  có mặt; `.history.json`, `*.pkl`, `tests/`, `__pycache__` không có.


## v7.2 (2026-09-13) - Trả nợ kỹ thuật: 347 cảnh báo lint -> 0, 15 lỗi thật đã sửa

### Tổng quan
- Mục tiêu bản này KHÔNG phải tính năng mới: dọn toàn bộ nợ kỹ thuật tích tụ qua
  các bản merge (lint, hàm 20-30 nhánh, code chết, tài liệu nói khác code).
- 347 cảnh báo ruff -> **0**; số test 220 -> **251**; hành vi giữ nguyên có kiểm chứng.

### Lỗi thật đã sửa (mỗi lỗi có test hồi quy trong `tests/test_v72_regressions.py`)
1. **run_tests.py luôn thoát 0** dù có test fail - runner tự viết nuốt mã lỗi, nên
   "220 pass" trên CI có thể là ảo giác. Nay uỷ quyền cho pytest khi có sẵn và trả exit code thật.
2. **train_nlu.py import scikit-learn cứng** - máy chưa cài thư viện ML không chạy
   được dù README quảng cáo "chạy ngay không cần cài gì" -> sklearn/joblib thành tuỳ
   chọn, gọi `_require_sklearn()` ngay trước khi cần.
3. **executor._escape_osascript escape SAI THỨ TỰ** - thay `\"` trước rồi `\`, nên
   backslash vừa chèn bị nhân đôi và nháy kép thoát ra ngoài chuỗi => nội dung nhắc
   nhở do người dùng gõ chạy thành MÃ AppleScript. Đổi thứ tự escape (lỗi bảo mật).
4. **`huy nhac` chỉ xoá trong RAM** - lời nhắc đã huỷ "hồi sinh" ở lần bật máy sau,
   và lời nhắc đang chờ biến mất khi tắt máy. `cancel_reminder` + `_save_reminders`
   Nay ghi đĩa atomic; `restore_reminders` bỏ mục quá hạn (không "nổ" dồn khi mở máy).
5. **ngưỡng tự tin đọc NGOÀI try/except lúc import** (`nlu_advanced`) - một giá trị
   sửa tay sai trong config.json ném ValueError/TypeError ngay `import nlu_advanced`
   và làm chết cả main.py, kể cả phần không liên quan tới ML. Nay: cảnh báo + mặc định an toàn.
6. **lệnh `nap lai` không đổi được ngưỡng** - tầng NLU đóng băng từ lúc import, executor
   mới được nạp lại -> người dùng sửa `confidence_accept` rồi nạp lại vẫn thấy hành vi cũ.
   Thêm `refresh_thresholds()` đồng bộ cả hai phía.
7. **tts: engine chết bị nuốt im lặng / tên engine sai bị hiểu là auto** - `--engine pipper`
   chạy "bình thường" nên không ai biết mình viết sai. Nay ghi log cảnh báo kèm danh sách
   hợp lệ, và chốt lại engine sống được (`_resolved_engine`) khi engine đang dùng hỏng giữa chừng.
8. **stt hard-code 44 byte header WAV** - chỉ đúng với PCM canonical; nếu `wave` ghi
   chunk mở rộng thì dữ liệu âm thanh lệch -> nhận diện sai im lặng. Nay đọc độ dài
   header thật; thiếu sounddevice cũng báo rõ thay vì giả vờ "không nghe thấy gì".
9. **config._validate_config là CODE CHẾT** - hàm tính `missing` rồi `pass`, docstring
   vẫn ghi "raise nếu sai nghiêm trọng". Nay: gọi tên từng khoá thiếu/khoá LẠ (gõ sai
   chính tả), raise sớm khi `website_map`/`app_map_*` sai kiểu (tránh AttributeError
   giữa lệnh), và bỏ mô tả "cache TTL" chưa từng tồn tại.
10. **logging_setup dùng lock giả** (không phải `threading.Lock` thật) -> race khi nhiều
    thread cùng ghi log (bộ đếm lời nhắc + REPL + TTS đều đa luồng).
11. **lite_model / hash md5** - `hashlib.md5(..., usedforsecurity=False)` để chạy được
    trên Python dựng theo FIPS (md5 chỉ dùng làm fingerprint, không dùng bảo mật).
12. **dataset._generate chia cho 0** - người dùng tự sửa `dataset.py` mà để trống một
    danh sách MẪU CÂU thì `% n` (n=0) ném ZeroDivisionError NGAY lúc import `dataset`,
    giết luôn cả trợ lý lẫn toàn bộ test với traceback không liên quan gì tới config.
13. **platform_utils.setup_console không khôi phục encoding cũ** - trạng thái console bị
    đổi vĩnh viễn cho tiến trình con; Nay có cờ revert.
14. **main.py thiếu `--engine nc`** - module `giong_nc.py` đã có sẵn engine "nc" nhưng
    CLI không cho chọn.
15. **CÂU VÔ NGHĨA VẪN ĐƯỢC THỰC THI** - "asdfgh jklzxbv" được model lite chấm tự tin
    0.50, CAO HƠN ngưỡng `CONFIDENCE_ACCEPT` (0.45), nên trợ lý lẽ ra đã gọi hàm thật
    theo một câu hoàn toàn vô nghĩa. Nguyên nhân: softmax với temperature 0.08 khuếch
    đại khoảng cách log-prob, "không có bằng chứng" vẫn thành "tương đối chắc chắn".
    Nay mỗi câu dự đoán phải qua **bảo chứng từ điển** `evidence_ratio()` (tỷ lệ feature
    nằm trong từ điển huấn luyện, char-ngram chỉ tính 25%): câu rác -> 0%, REPL hỏi lại;
    câu tiếng Việt thật -> không đổi. Không cần file model mới (từ điển suy ra từ
    `_log_prob`), và `predict_proba_dict()` vẫn trả phân phối softmax nguyên bản.

### Kiến trúc / chất lượng code
- **347 -> 0 cảnh báo ruff** (E, F, W, C90, I, N, UP, S, B, A, C4, TCH, TID, Q, RUF);
  mỗi dòng `ignore` trong `pyproject.toml` có chú thích lý do + `per-file-ignores`.
- **Tách các hàm quá phức tạp** (C901 > 10) thành bảng tra + hàm một nhiệm vụ, xoá dần
  các chuỗi if/elif theo nền tảng/theo lệnh:
  - `main.main()`: REPL dispatcher -> `_CONTROL_COMMANDS` (từ khoá -> handler) +
    `_CONTROL_PREFIXES` (lệnh có tham số) + `ReplState`/`ReplContext` test được từng lệnh.
  - `executor.action_system_control()`: bảng `COMMANDS_WINDOWS/MACOS/LINUX`,
    `VOLUME_*`, handler riêng theo nền tảng; `None` = "nền tảng này không làm được"
    -> in `[BỎ QUA]` thay vì nói dối "đã thực thi".
  - `intent_model`: `parse_time_expression` (28 nhánh) thành 4 máy phân tích + bảng
    quy tắc đổi giờ theo buổi; `extract_entity` (20 nhánh) thành `_ENTITY_HANDLERS`;
    `_parse_number_run` (25 nhánh) thành bảng quy tắc `_NUMBER_RUN_RULES`.
  - `tts.speak`, `stt.listen_once`, `config._validate_config`, `train_nlu.train`,
    `giong_noi_ai.main` cũng được tách tương tự.
- **Kiểm chứng tương đương hành vi** bằng đối chiếu tự động với bản v7.1 (module cũ nạp
  song song): 70.668 cụm từ-số x 3 hàm, 96.737 câu thời gian, 1.618 câu x 13 intent
  trích xuất thực thể => **0 khác biệt**. Các hàm refactor không đổi hành vi, chỉ đổi cấu trúc.

### Đóng gói & CI
- `dependencies = []`: `pip install .` không còn bắt cài scikit-learn/numpy (chuyển vào
  `[full]`/`[ml]`) - khớp với cam kết "chạy ngay không cần cài gì"; bỏ 2 marker
  `python_version < "3.9"` mâu thuẫn với `requires-python >= 3.9`.
- CI: bỏ bước `pytest ... || python run_tests.py` (dấu `||` biến CI ĐỎ thành XANH);
  mỗi bộ test một bước riêng; thêm bước **ruff**; thêm **Python 3.13** (pyproject đã
  quảng cáo nhưng chưa từng được kiểm tra); thêm job "không cài tuỳ chọn" để giữ hợp
  đồng "chỉ cần stdlib".

### Tests
- 220 -> **251 test**; file mới `tests/test_v72_regressions.py` (31 test) - mỗi test
  gắn với một lỗi ở trên, có chú thích mô tả triệu chứng trước khi sửa.


## v7.0 (2026-09-13) - Nâng cấp toàn diện & fix regression sau merge

### Tổng quan
- Merge 2 bản zip v6.4 (`vi_voice_assistant_v6_4_vieneu.zip` + `out_vi_voice_assistant_v6_4_fixed.zip`) thành một dự án duy nhất
- Fix tất cả lỗi regression, đạt 220/220 tests pass
- Nâng cấp kiến trúc: pyproject.toml, requirements.txt, logging_setup.py, platform_utils.py, config.py

### Fix lỗi nghiêm trọng (regression sau merge)

#### 1. Regex `bad character range \-( at position 11` [CRITICAL]
- **executor.py:92** `_SAFE_PATH_RE = r"^[\w\s:\\/.\\-()%]+$"` → FAIL
  - Fix: `r"^[\w\s:\\/.\-()%]+$"` (escape `-` đúng cách) ✅
- **text_utils.py** `_KEEP_RE = r"[^\w\s\.\-/:\\]"` → FAIL tương tự
  - Fix: `r"[^\w\s./:\\-]+"` (đưa `-` ra cuối) ✅
- **_INVALID_FILENAME_RE** `r'[<>:"/\\|?*\x00-\x1f]'` raw string chứa \x00 không hoạt động
  - Fix: `r'[<>:"/\\|?*]'` + xử lý `ord(c) < 32` riêng ✅

#### 2. Tương thích HOME/REMINDERS_PATH khi monkeypatch bằng str
- `HOME / "Pictures"` fail khi `HOME = str(tmp_path)` trong tests
  - Fix: `Path(HOME) / "Pictures"` + `Path(pictures_dir).mkdir()` ✅
- `REMINDERS_PATH.exists()/.parent` fail khi `REMINDERS_PATH = str(...)`
  - Fix: `rem_path = Path(REMINDERS_PATH)` wrapper trong `_save_reminders()` và `restore_reminders()` ✅
  - Atomic write: `tempfile.mkstemp(dir=str(rem_path.parent))` + `replace()` ✅

#### 3. Mock Popen không tương thích với DEVNULL
- `subprocess.Popen(cmd, stdout=DEVNULL)` fail với `lambda cmd: ...` trong tests (không nhận kwargs)
  - Fix: thêm `_popen(cmd)` wrapper thử DEVNULL, fallback không kwargs ✅
  - Thay tất cả Popen bằng _popen ✅
- Message UWP thiếu "Store App" → test fail
  - Fix: `"ứng dụng kiểu Store App (UWP)"` ✅

### Nâng cấp v7.0 (đã có sẵn trước fix)

- **tts.py**: RLock, timeout, voice_cache index, fallback engines, health check
- **stt.py**: STT class, RMS fallback struct, thread-safe
- **main.py**: --debug/--no-banner/--config/--engine/--history, signal handling, .history.json, 7.0 banner
- **platform_utils.py**: safe_print, setup_console, is_wsl, capability_report (mới)
- **logging_setup.py**: logging có cấu hình (mới)
- **config.py**: loader config với validation (mới)
- **pyproject.toml**: metadata chuẩn PEP 621 (mới)
- **requirements.txt**: deps với markers python_version (mới)
- **giong_noi_ai.py**: tự tạo thư mục cha cho out_path, check rỗng (fix nhỏ v7.0)
- **giong_nc.py**: tương tự

### Kết quả
- Trước fix: 119 pass / 3 fail + 2 load error
- Sau fix regex + Path: 212 pass / 8 fail
- Sau fix _popen + message: **220 pass / 0 fail** ✅

## Chưa gắn số phiên bản (2026-08-08)

### cai_dat_win10.bat - tự động nhận diện Windows
- Script cài đặt Windows không còn "đoán mò" là Windows 10/11 nữa: giờ tự đọc
  `CurrentBuildNumber` từ registry để phân biệt Windows 7 / 8 / 8.1 / 10 / 11
  (và nhận diện kiến trúc CPU 32-bit / 64-bit / ARM64), rồi chọn đúng nhánh
  cài đặt tương ứng.
- **Nhánh Windows 7**: tự dò tìm Python 3.8.x (bắt buộc trên Win7) qua `py`
  launcher rồi tới `python` trong PATH; báo lỗi kèm link tải rõ ràng nếu
  không thấy đúng bản; kiểm tra sẵn Visual C++ Redistributable 2015-2022
  (x64) trong registry; **không** đổi code page console sang UTF-8 (đồng bộ
  với quyết định trong `platform_utils.setup_console()` - tránh lỗi treo
  console đã ghi nhận trên một số máy Windows 7).
- **Nhánh Windows 8/8.1/10/11**: tự dò Python mới nhất đang có (ưu tiên
  3.13 -> 3.9 qua `py` launcher), cho phép UTF-8 console.
- Cả hai nhánh dùng chung `requirements.txt` - file này đã tự chọn đúng
  phiên bản `scikit-learn`/`joblib` theo `python_version` bằng environment
  marker, nên script chỉ cần gọi đúng 1 lệnh `pip install` duy nhất.
- Tên file giữ nguyên `cai_dat_win10.bat` để không phá vỡ các hướng dẫn cũ
  (vd `FIX_LOI_CYTHON_WIN10.txt`), dù nay đã hỗ trợ mọi bản Windows của dự án.

### cai_dat_giong_ai.bat + giong_noi_ai.py - đồng bộ với engine VieNeu (v6.4)
- **Lỗi nghiêm trọng đã sửa**: `cai_dat_giong_ai.bat` vẫn còn nguyên logic v6.3
  (chỉ cài Piper), trong khi `giong_noi_ai.py` từ v6.4 đã đổi engine mặc định
  sang VieNeu-TTS. Kết quả trước khi sửa: cài xong, bước "tải giọng"/"đọc thử"
  ở cuối script đều âm thầm thất bại vì gói `vieneu` chưa từng được cài.
- Viết lại `cai_dat_giong_ai.bat` (7 bước): kiểm tra phiên bản Python (VieNeu
  cần 3.10+), cài `vieneu` làm engine chính, hỏi tuỳ chọn (`choice`) cài thêm
  `torch`+`torchaudio` cho nhân bản giọng, vẫn giữ cài Piper làm dự phòng như
  cũ (không cần Python 3.10+, nhẹ hơn, dùng khi máy yếu hoặc Python quá cũ).
- **Phát hiện qua đọc source gói `vieneu` (PyPI, bản 3.2.4)**: 10 giọng dựng
  sẵn chạy thuần ONNX/CPU thật (torch-free), nhưng NHÂN BẢN GIỌNG
  (`ref_audio=...`) luôn cần `torchaudio` được cài thêm - `speaker/audio_utils.py`
  import torch/torchaudio ở cấp module cho bước trích đặc trưng giọng nói, dù
  vẫn chạy trên CPU (không cần GPU/CUDA thật). Docstring và `huong_dan_train()`
  trong `giong_noi_ai.py` từng nói "chạy ngay, không cần gì thêm" - đã sửa lại
  cho chính xác.
- `giong_noi_ai.py`: thêm `is_clone_available()` (kiểm tra riêng điều kiện cho
  nhân bản giọng, tách khỏi `is_available()` vốn chỉ xác nhận gói `vieneu`);
  `synth_to_file()` giờ báo lỗi rõ ràng + hướng dẫn cài đặt ngay khi thiếu
  torch/torchaudio thay vì để lỗi ImportError khó hiểu; `kiem_tra()` báo thêm
  trạng thái sẵn sàng nhân bản giọng.
- `requirements-giong-noi.txt`: gắn `python_version >= "3.10"` cho dòng
  `vieneu` (trước đó thiếu - sẽ khiến `pip install -r ...` báo lỗi cứng trên
  Python cũ hơn); thêm 2 dòng chú thích cho `torch`/`torchaudio` (tuỳ chọn).

## v6.3 (2026-08-07)

### Nâng cấp hỗ trợ hệ điều hành (trọng tâm bản này)
- **WSL (Windows Subsystem for Linux) được hỗ trợ thật sự**: trước đây WSL bị
  nhận nhầm là "Linux" thuần nên tắt máy / khởi động lại / khoá màn hình / âm
  lượng / chụp màn hình / mở web / mở file đều âm thầm thất bại (WSL không có
  systemctl/pactl/xdg-open thật). Nay platform_utils.is_wsl() tự phát hiện WSL
  và chuyển tiếp sang Windows host qua cơ chế interop:
  - Lệnh hệ thống -> shutdown.exe / rundll32.exe của Windows
  - Âm lượng -> phím ảo qua powershell.exe
  - Chụp màn hình -> PowerShell + System.Drawing (lưu vào Pictures của Windows)
  - Mở web / mở file -> wslview (sudo apt install wslu) hoặc explorer.exe
  - Đọc giọng nói -> SAPI của Windows host (tts.py)
  - Nếu interop bị tắt, báo lỗi rõ kèm gợi ý kiểm tra /etc/wsl.conf.
- **Phân biệt Windows 10 / Windows 11** (trước đây gộp chung "Windows 10/11";
  Windows 11 = kernel 10.0 build >= 22000).
- **Linux hiện đại hơn**: âm lượng thử wpctl (PipeWire) trước pactl/amixer;
  khoá màn hình thêm qdbus (KDE Plasma); chụp màn hình thêm spectacle (KDE),
  grim (Wayland/Sway) và import (ImageMagick); nhận diện môi trường desktop
  qua linux_desktop() (hiển thị trong báo cáo --sysinfo).
- **Báo cáo khả năng của máy (mới)**: `python main.py --sysinfo` hoặc gõ
  `he thong` trong phiên -> in ra tính năng nào sẽ chạy được trên máy hiện
  tại và thiếu công cụ gì (xem platform_utils.capability_report()).

### Kiểm thử
- Thêm 20 test mới (tổng 220, từ 200 ở v6.2): phát hiện/chuyển tiếp WSL, nhãn
  Windows 11, desktop Linux, chuỗi dự phòng wpctl/qdbus/screenshot, mở URL
  trên WSL, TTS SAPI qua WSL, cờ --sysinfo.
- Các test Linux cũ ép is_wsl() = False để chạy đúng cả khi ai đó chạy bộ
  test trên WSL; test pactl cập nhật theo thứ tự dự phòng mới (wpctl trước).

## v6.2 (2026-08-07)

### Sửa lỗi nghiêm trọng (phát hiện nhờ rà soát vòng 4)
- **intent_model.py - parse_time_expression()**: chữ "tôi" (đại từ) từng bị
  nhận nhầm thành buổi "tối" vì buổi được tìm trên TOÀN câu -> "nhắc tôi họp
  lúc 9 giờ" bị hẹn thành 21h thay vì 9h. Giờ buổi chỉ nhận diện trong phần
  SAU biểu thức giờ (hoặc cụm "tối nay/mai" đứng trước giờ), kèm đối chiếu
  văn bản có dấu để tách "tôi"/"tối".
- **"12 giờ đêm" = 0h** (trước đây 12h trưa), **"1 giờ đêm" = 1h** (trước đây
  13h); hiểu thêm buổi "khuya".
- **Tên riêng "Sáu" không còn bị nhầm thành từ nối "sau"**: dấu hiệu đếm
  ngược giờ kiểm tra trên văn bản CÓ DẤU khi có thể -> "nhắc tôi gọi cho Sáu
  lúc 7 giờ" hẹn đúng 7h (trước đây thành "7 tiếng nữa").
- **nlu_advanced.py - phục hồi dấu**: không còn đổi nhầm một dạng không dấu
  vốn LÀ từ thật trong dataset (vd "hai mươi" từng thành "hải mươi" theo "hải
  phòng").

### Tính năng mới
- **Số viết bằng chữ** trong tính toán và nhắc nhở (hàm mới
  replace_number_words() trong intent_model.py): "mười lăm cộng hai mươi bảy"
  = 42, "hai phẩy năm nhân bốn" = 10, "nhắc tôi họp lúc bảy giờ sáng" = 7:00.
  Hỗ trợ mươi/trăm/nghìn/triệu/tỷ, "lẻ/linh", "phẩy" (thập phân), cả khi gõ
  không dấu. An toàn: "tâm sự" không bị đổi thành "8 sự", "căn bậc hai"
  không thành "căn bậc 2", "phần trăm" không thành "phần 100".
- **Tách nhiều lệnh khi gõ không dấu** ("mo chrome roi phat nhac" -> 2 lệnh);
  "và/va" + động từ không dấu cũng tách được ("mo chrome va tat may").
- **Toán tử nhiều từ**: "chia cho", "nhân với", "cộng với", "trừ đi"; thêm
  căn bậc ba ("căn bậc ba của 27" = 3) và lập phương ("5 lập phương" = 125).
- **Nhắc nhở hiểu thêm**: "nửa tiếng nữa" (30 phút), "1 tiếng rưỡi nữa" (90
  phút), "đặt hẹn giờ 5 phút" (đếm ngược không cần chữ "nữa/sau"), giờ viết
  bằng chữ; bóc nội dung sạch cả đuôi "kém 15" (trước đây còn sót).
- **Lệnh "day" kiểm định tên intent** trước khi ghi feedback.csv (chặn gõ
  nhầm tạo lớp 1-mẫu làm nhiễu lần huấn luyện sau).
- Nhận diện thêm tên miền .ai/.app/.xyz/.me/.tv/.info/.gov/.edu/.shop/...
  ("mở claude.ai") và đường dẫn Windows dùng dấu / ("C:/Users/...").

### Sửa lẻ & hạ tầng
- ID nhắc nhở dùng hậu tố ngẫu nhiên (trước đây 2 lời nhắc đặt trong cùng 1
  giây có thể trùng ID -> gỡ/huỷ nhầm).
- Sửa URL Notion mặc định bị hỏng trong config.py/config.json.
- Sửa toàn bộ ký tự tiếng Việt bị hỏng mã hoá còn sót lại trong tài liệu và
  comment (HUONG_DAN_SU_DUNG.txt, executor.py, intent_model.py,
  train_phobert.py).
- Test không còn ghi vào reminders.json thật của dự án.

### Kiểm thử
- Thêm 29 test mới (tổng 200, từ 170 ở v6.1): lỗi giờ, số bằng chữ, toán tử
  mở rộng, tách lệnh không dấu, kiểm định intent, URL/đường dẫn mới...
- Cập nhật 2 test mã hoá nhầm giới hạn cũ: "3h30" giờ đúng là (3, 30) thay vì
  (15, 30) (v6.1 kỳ vọng theo đúng lỗi "tôi"/"tối"); test "không tính được"
  đổi từ "một cộng một" (nay đã tính được = 2) sang "căn bậc hai của -5".
- Dataset: 779 câu có dấu (từ ~760), 1.558 câu kèm biến thể không dấu.

## v6.1 (2026-08-07)

### Sửa lỗi (phát hiện nhờ rà soát vòng 3)
- **tts.py**: engine giọng nói đã chọn (vd pyttsx3) mà hỏng giữa phiên thì tự động
  thử các engine còn lại (SAPI / macOS say / gTTS) thay vì im lặng bỏ cuộc như v6.0;
  nếu tất cả đều hỏng thì xoá lựa chọn đã cache để lần sau dò lại từ đầu.
- **phobert_model.py**: `MODEL_DIR` chuyển thành đường dẫn TUYỆT ĐỐI neo theo thư mục
  mã nguồn - trước đây là đường dẫn tương đối nên chạy từ thư mục khác (Task
  Scheduler, shortcut, gọi `--once` từ script khác) sẽ không nhận ra model PhoBERT
  đã huấn luyện.

### Kiểm thử
- Thêm 5 test mới (tổng 170): dự phòng engine TTS khi hỏng, không thử lại khi engine
  khoẻ, xoá cache khi mọi engine đều hỏng, `MODEL_DIR` tuyệt đối, `is_trained()` với
  thư mục không tồn tại.

## v6.0 (2026-08-07)

### Sửa lỗi nghiêm trọng
- **Không còn sập khi thiếu scikit-learn/joblib**: toàn bộ import sklearn được bọc
  `try/except`; khi thiếu thư viện, chương trình tự chuyển sang `lite_model.py`
  (trước đây crash ngay lúc khởi động — lỗi nặng nhất trên máy Windows 7/không mạng).
- **URL không còn bị băm nát**: `predict_intent()` nhận thêm `raw_text` (câu gốc) để
  trích xuất thực thể, và `extract_entity()` giờ **luôn** trả URL nguyên vẹn (giữ
  `? = & #`, hoa/thường) bất kể model nhận intent nào. Trước đây
  "mở youtube.com/watch?v=abc123" bị biến thành "youtube.com/watch v abc123".
- **Chặn "bom luỹ thừa"**: `_safe_eval` giới hạn số mũ (|số mũ| ≤ 64, |cơ số| ≤ 10⁶);
  trước đây "9 mũ 9 mũ 9" treo cứng chương trình.
- **"mở file" từ chối file thực thi** (`.exe .bat .ps1 .sh .py .app`… 26 đuôi) và
  chặn đường dẫn chứa `..`. Trước đây "mở file setup.exe" tương đương chạy mã tuỳ ý.
- **Nhắc nhở không còn mất khi thoát app**: tự lưu/khôi phục qua `reminders.json`;
  nhắc nhở đã kêu tự gỡ khỏi danh sách (trước đây nằm mãi trong RAM).
- **"11 giờ đêm" = 23:00** (trước đây hiểu nhầm 11:00 sáng); nhớ được chữ "mai"
  ("7 giờ sáng mai" hẹn sang ngày hôm sau, không kêu ngay hôm nay).
- **Tách địa điểm thời tiết viết lại**: câu không dấu hoạt động đúng
  ("thoi tiet da nang hom nay" → "da nang"); không còn xoá nhầm chữ "Nẵng" trong
  "Đà Nẵng" (do "nắng" và "Nẵng" bỏ dấu là một).
- **2 ngưỡng độ tự tin `confidence_accept` / `confidence_ask` chuyển vào config.json**
  — trước đây viết cứng trong mã nguồn, sửa config không có tác dụng.

### Tính năng mới
- **`lite_model.py`**: Naive Bayes n-gram ký tự (3–4) thuần Python, huấn luyện
  < 1 giây, ~97,7% độ chính xác hold-out, tự kiểm tra fingerprint dataset và tự
  huấn luyện lại khi dữ liệu đổi. `python main.py --version` cho biết đang dùng
  PhoBERT / TF-IDF / LiteModel.
- **Chế độ dòng lệnh**: `--once "câu lệnh"` (chạy 1 lệnh rồi thoát), `--json`
  (xuất JSON cho script), `--version`; chương trình giờ trả mã thoát chuẩn cho shell
  (0 = OK, 1 = lệnh lỗi, 2 = không hiểu).
- **Lệnh phiên mới**: `huy nhac [từ khoá]` (huỷ nhắc nhở), `nap lai` (nạp lại
  config.json không cần khởi động lại).
- **Hiểu giờ giấc phong phú**: `3h30`, `3 giờ rưỡi`, `8 giờ kém 15`, `30 giây nữa`,
  `sáng/trưa/chiều/tối mai`, và toàn bộ dạng trên khi gõ không dấu.
- **Toán tử luỹ thừa bằng lời**: "2 mũ 10" → 1024.
- **`reload_config()` / `set_speech_enabled()`** trong `executor.py` thay cho việc
  gán biến toàn cục trực tiếp từ module khác.

### Hạ tầng & kiểm thử
- **`run_tests.py`**: chạy toàn bộ test **không cần cài pytest** (shim đủ dùng cho
  `fixture`, `parametrize`, `monkeypatch`, `capsys`, `tmp_path`, `raises`, `skipif`);
  nếu máy có pytest thật sẽ tự chuyển sang pytest.
- **165 test** (từ 73 ở bản v5), trong đó ~40 test mới cho các tính năng/sửa lỗi v6.
- `requirements.txt`: scikit-learn/joblib chuyển thành **tuỳ chọn (khuyến nghị)**.
- Thêm `README.md`, `.gitignore`, `conftest.py`, `pytest.ini`.

### Thay đổi hành vi cần lưu ý
- `parse_time_expression()` luôn trả dict đủ khoá
  `{type, minutes, hour, minute, day_offset}` (trước đây chỉ trả khoá tuỳ loại).
- `NLU._judge()` chỉ yêu cầu xác nhận khi intent là `system_control` (tránh hỏi
  xác nhận nhầm các intent khác có chứa từ như "shutdown").
