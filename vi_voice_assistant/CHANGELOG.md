# CHANGELOG

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
