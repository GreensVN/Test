"""
dataset.py
----------
TẬP DỮ LIỆU INTENT TIẾNG VIỆT v7.0

v7.0 nâng cấp:
- Thêm type hints đầy đủ, pathlib, logging
- Giữ nguyên 11 intent, ~1530 câu mẫu, logic sinh dữ liệu không đổi
- Tối ưu _generate, build_intent_data với typing

Hợp nhất 2 hướng cải tiến từ 2 bản trước:
  - "Bản nhiều tính năng": sinh dữ liệu bằng MẪU CÂU (template) x ĐỐI TƯỢNG
    (object) cho 11 nhóm ý định, cộng câu viết tay để tự nhiên hơn (~730 câu).
  - "Bản bảo mật/đa nền tảng": tự động sinh thêm bản KHÔNG DẤU cho mỗi câu
    (get_dataset_as_lists(augment_no_diacritics=True), mặc định BẬT) để mô
    hình TF-IDF tự nó cũng chịu được input không dấu

v5 -> v7.0: giữ nguyên logic, chỉ thêm typing và pathlib

Hợp nhất 2 hướng cải tiến từ 2 bản trước:
  - "Bản nhiều tính năng": sinh dữ liệu bằng MẪU CÂU (template) x ĐỐI TƯỢNG
    (object) cho 11 nhóm ý định, cộng câu viết tay để tự nhiên hơn (~730 câu).
  - "Bản bảo mật/đa nền tảng": tự động sinh thêm bản KHÔNG DẤU cho mỗi câu
    (get_dataset_as_lists(augment_no_diacritics=True), mặc định BẬT) để mô
    hình TF-IDF tự nó cũng chịu được input không dấu, không chỉ dựa vào tầng
    tiền xử lý smart_normalize() của nlu_advanced.py.

11 nhóm ý định (intent):
    1. open_website     : mở trang web
    2. open_app         : mở phần mềm trên máy
    3. open_file        : mở file / thư mục
    4. system_control   : điều khiển hệ thống (tắt máy, âm lượng...)
    5. search_web       : tìm kiếm thông tin trên mạng
    6. play_media       : phát nhạc / video
    7. set_reminder     : đặt nhắc nhở / báo thức / hẹn giờ
    8. get_weather      : hỏi thời tiết
    9. get_datetime     : hỏi giờ / ngày tháng
   10. calculate        : tính toán (cộng trừ nhân chia, căn bậc hai, phần trăm...)
   11. chitchat         : chào hỏi / tán gẫu / hỏi ngoài phạm vi điều khiển máy
                          tính (KHÔNG thực thi lệnh nào - chỉ trả lời hoặc báo
                          "chưa hiểu"). Đây cũng là nơi "hứng" các câu vốn nằm
                          ngoài phạm vi, đóng vai trò lưới an toàn giống nhãn
                          "unknown" của bản trước (xem HUONG_DAN_SU_DUNG.txt
                          mục "0-D" để biết lý do gộp 2 nhãn này làm một).

Chạy để xem thống kê:
    python dataset.py
v7.5 nâng cấp:
- `get_dataframe()` khi thiếu pandas nói rõ `pip install pandas` hoặc dùng
  `get_dataset_as_lists()` - trước đây chỉ `ModuleNotFoundError`, người đọc phải
  tự đoán bước tiếp theo.

"""


from __future__ import annotations

from pathlib import Path

from platform_utils import safe_print, setup_console
from text_utils import strip_diacritics

# ============================================================================
# 1. ĐỐI TƯỢNG (OBJECTS) - THÊM TỪ CỦA BẠN VÀO ĐÂY
# ============================================================================

WEBSITES = [
    "google", "youtube", "facebook", "github", "gmail", "notion", "chatgpt",
    "tiki", "shopee", "lazada", "vnexpress", "zalo web", "stackoverflow",
    "google dịch", "tiktok", "instagram", "wikipedia", "linkedin",
    "kenh14", "báo mới", "coursera", "udemy", "drive", "twitter",
    "canva", "netflix", "outlook", "zoom", "microsoft teams", "reddit",
    "pinterest", "amazon", "aliexpress", "vietcombank", "momo", "grab",
]

APPS = [
    "chrome", "cốc cốc", "edge", "firefox", "notepad", "máy tính bỏ túi",
    "calculator", "paint", "cmd", "powershell", "word", "excel", "powerpoint",
    "vs code", "visual studio", "file explorer", "task manager", "zalo",
    "spotify", "telegram", "discord", "steam", "photoshop", "unikey",
    "onenote", "obs studio", "vlc", "winrar", "sublime text", "postman",
    "docker desktop", "teamviewer", "anydesk", "line", "viber", "whatsapp",
]

FILES = [
    "báo cáo", "báo cáo tài chính", "tài liệu word", "ảnh chụp màn hình",
    "excel doanh thu", "pdf hợp đồng", "thư mục tải xuống", "ghi chú",
    "danh sách sinh viên", "luận văn", "bài tập", "dữ liệu csv",
    "bảng lương", "kế hoạch tháng", "slide thuyết trình", "mã nguồn dự án",
    "hoá đơn", "hình ảnh du lịch", "video quay màn hình", "nhạc",
    "file cv xin việc", "hợp đồng lao động", "biên bản họp", "file thiết kế",
]

SEARCH_QUERIES = [
    "giá bitcoin hôm nay", "cách nấu phở bò", "tỷ giá đô la", "điểm chuẩn đại học",
    "cách học python", "tin tức bóng đá", "lịch chiếu phim", "giá vàng hôm nay",
    "quán ăn ngon gần đây", "cách làm cơm chiên", "machine learning là gì",
    "vé máy bay đi đà nẵng", "cách sửa lỗi win 11", "từ vựng tiếng anh",
    "lịch thi đấu world cup", "cách viết cv xin việc", "giá xăng hôm nay",
    "cách giảm cân hiệu quả", "review điện thoại mới", "lãi suất ngân hàng",
]

SONGS = [
    "nhạc không lời", "nhạc trữ tình", "nhạc làm việc tập trung", "nhạc chill",
    "bài hát lạc trôi", "nhạc bolero", "nhạc edm sôi động", "nhạc thiền",
    "nhạc trẻ xuân", "podcast tiếng việt", "nhạc rap việt", "nhạc piano nhẹ nhàng",
    "nhạc remix", "nhạc acoustic", "nhạc lofi", "audiobook tiếng việt",
]

CITIES = [
    "hà nội", "sài gòn", "đà nẵng", "hải phòng", "cần thơ", "huế",
    "nha trang", "đà lạt", "vũng tàu", "bình dương", "quy nhơn", "phú quốc",
]


# ============================================================================
# 1B. SỐ LIỆU TÍNH TOÁN (CALCULATE)
# ============================================================================

CALC_NUMBER_PAIRS = [
    (12, 8), (25, 37), (100, 4), (50, 3), (99, 1), (7, 6), (144, 12),
    (18, 9), (250, 5), (81, 9), (36, 6), (15, 27), (1000, 4), (17, 3),
    (64, 8), (45, 5), (23, 19), (500, 20), (72, 8), (9, 9),
]

CALC_OP_WORDS = ["cộng", "trừ", "nhân", "chia"]

CALC_TEMPLATES = [
    "{a} {op} {b} bằng bao nhiêu", "tính giúp tôi {a} {op} {b}",
    "{a} {op} {b} là mấy", "giúp tôi tính {a} {op} {b}",
    "tính hộ tôi {a} {op} {b}", "{a} {op} {b} ra kết quả bao nhiêu",
    "cho tôi biết {a} {op} {b} bằng mấy",
]

CALC_SPECIAL = [
    "căn bậc hai của 81 là bao nhiêu", "căn bậc hai của 144 bằng mấy",
    "tính căn bậc hai của 25", "căn bậc hai của 49",
    "16 bình phương là bao nhiêu", "9 bình phương bằng mấy",
    "5 mũ 2 là bao nhiêu", "7 bình phương bằng bao nhiêu",
    "10 phần trăm của 500 là bao nhiêu", "20 phần trăm của 150 bằng mấy",
    "tính 15 phần trăm của 200", "50 phần trăm của 90 là bao nhiêu",
]


def _generate_calc() -> list[str]:
    """Sinh câu tính toán: ghép cặp số x phép toán x mẫu câu."""
    out = []
    for i, (a, b) in enumerate(CALC_NUMBER_PAIRS):
        op1 = CALC_OP_WORDS[i % len(CALC_OP_WORDS)]
        tpl1 = CALC_TEMPLATES[i % len(CALC_TEMPLATES)]
        out.append(tpl1.format(a=a, op=op1, b=b))

        op2 = CALC_OP_WORDS[(i + 1) % len(CALC_OP_WORDS)]
        tpl2 = CALC_TEMPLATES[(i + 3) % len(CALC_TEMPLATES)]
        out.append(tpl2.format(a=a, op=op2, b=b))
    out.extend(CALC_SPECIAL)
    return out


# ============================================================================
# 2. MẪU CÂU (TEMPLATES)
# ============================================================================

WEB_TEMPLATES = [
    "bật {} lên", "mở {} giúp tôi", "vào trang {} đi", "mở {} ra",
    "cho tôi vào {}", "truy cập {} nào", "mở trang web {}", "vào website {}",
    "mở {} lên xem", "lên {} đi", "mở giùm tôi trang {}", "cho tôi xem {}",
]

APP_TEMPLATES = [
    "mở {} ra", "khởi chạy {} giúp tôi", "bật {} lên", "mở ứng dụng {}",
    "chạy chương trình {}", "mở phần mềm {}", "khởi động {}", "cho tôi mở {}",
]

FILE_TEMPLATES = [
    "mở file {}", "cho tôi xem file {}", "mở tệp {} ra", "mở giúp tôi file {}",
    "xem lại file {}", "mở tài liệu {}", "mở tệp tin {} trong máy",
]

SEARCH_TEMPLATES = [
    "tìm kiếm {} trên google", "tra cứu {} giúp tôi", "tìm {} trên mạng",
    "search {} đi", "tìm thông tin về {}", "google {} giùm tôi",
    "cho tôi biết {}", "tìm giúp tôi {}",
]

MEDIA_TEMPLATES = [
    "phát {} đi", "mở {} nghe", "bật {} lên", "phát {} trên youtube",
    "cho tôi nghe {}", "mở video {}", "bật {} giúp tôi nghe",
]

WEATHER_TEMPLATES = [
    "thời tiết {} hôm nay thế nào", "{} có mưa không", "dự báo thời tiết {} ngày mai",
    "nhiệt độ ở {} bao nhiêu", "xem thời tiết {} giúp tôi", "trời ở {} thế nào",
]

# --- Nhắc nhở / báo thức ---
REMINDER_TASKS = [
    "họp nhóm", "uống nước", "nộp báo cáo", "gọi điện cho mẹ", "đi ăn trưa",
    "nghỉ giải lao", "đi tập gym", "học bài", "đón con", "gửi email cho sếp",
    "khám bệnh", "thanh toán hoá đơn", "tưới cây", "uống thuốc", "đi ngủ sớm",
]
REMINDER_TIMES = [
    "5 phút nữa", "10 phút nữa", "30 phút nữa", "1 tiếng nữa",
    "lúc 7 giờ sáng", "lúc 3 giờ chiều", "lúc 9 giờ tối", "lúc 12 giờ trưa",
]
REMINDER_TEMPLATES = [
    "nhắc tôi {task} {time}", "đặt nhắc nhở {task} {time}",
    "hẹn giờ {task} {time}", "tạo lời nhắc {task} {time}",
    "nhớ nhắc tôi {task} {time} nhé",
]
ALARM_TEMPLATES = [
    "đặt báo thức {time}", "báo thức {time} giúp tôi",
    "hẹn giờ {time}", "đặt đồng hồ đếm ngược {time}",
]

# --- Hỏi giờ / ngày ---
DATETIME_SENTENCES = [
    "mấy giờ rồi", "bây giờ là mấy giờ", "bây giờ mấy giờ rồi nhỉ",
    "cho tôi biết giờ hiện tại", "xem giờ giúp tôi", "giờ hiện tại là gì",
    "đồng hồ đang chỉ mấy giờ", "nói cho tôi biết mấy giờ",
    "hôm nay ngày bao nhiêu", "hôm nay ngày mấy", "hôm nay thứ mấy",
    "hôm nay ngày mấy tháng mấy", "ngày tháng hôm nay là gì",
    "hôm nay là ngày mấy của tháng", "cho tôi biết ngày hôm nay",
    "hôm nay là thứ mấy trong tuần", "năm nay là năm bao nhiêu",
    "ngày mai là thứ mấy", "còn bao nhiêu ngày nữa hết tháng",
    "xem lịch giúp tôi",
]

# --- Trò chuyện vặt / ngoài phạm vi điều khiển máy ---
CHITCHAT_SENTENCES = [
    "xin chào", "chào bạn", "hello bạn", "hi bạn", "chào buổi sáng",
    "chào buổi tối", "chào trợ lý", "alô nghe rõ không",
    "bạn tên gì", "bạn là ai vậy", "bạn làm được những gì",
    "bạn giúp được tôi việc gì", "bạn bao nhiêu tuổi", "ai tạo ra bạn",
    "bạn khoẻ không", "hôm nay bạn thế nào", "bạn đang làm gì đó",
    "cảm ơn nhé", "cảm ơn bạn nhiều", "cám ơn trợ lý", "giỏi lắm",
    "bạn giỏi quá", "tốt lắm", "okie hiểu rồi",
    "tạm biệt", "bái bai", "hẹn gặp lại", "chào tạm biệt nhé", "ngủ ngon",
    "kể chuyện cười đi", "nói chuyện với tôi đi", "hát một bài đi",
    "bạn có biết nói đùa không", "tôi buồn quá", "tôi mệt quá",
]


def _generate_reminders() -> list[str]:
    """Sinh câu nhắc nhở: ghép công việc x thời điểm x mẫu câu."""
    out = []
    for i, task in enumerate(REMINDER_TASKS):
        for k in range(3):
            tpl = REMINDER_TEMPLATES[(i + k) % len(REMINDER_TEMPLATES)]
            tim = REMINDER_TIMES[(i + k * 2) % len(REMINDER_TIMES)]
            out.append(tpl.format(task=task, time=tim))
    for i, tim in enumerate(REMINDER_TIMES):
        for k in range(2):
            out.append(ALARM_TEMPLATES[(i + k) % len(ALARM_TEMPLATES)].format(time=tim))
    return out


def _generate(templates: list[str], objects: list[str], per_object: int = 3) -> list[str]:
    """Ghép mẫu câu với đối tượng. Mỗi đối tượng dùng `per_object` mẫu khác nhau
    (xoay vòng theo chỉ số để kết quả luôn ổn định, không phụ thuộc random)."""
    out: list[str] = []
    n = len(templates)
    if n == 0 or not objects:
        # v7.2: người dùng tự sửa dataset.py mà xoá/rỗng một danh sách MẪU CÂU
        # (WEATHER_TEMPLATES = []) là `% n` ném ZeroDivisionError ngay lúc import
        # `dataset` -> cả trợ lý lẫn mọi test chết không rõ lý do. Trả về rỗng
        # là đủ; build_intent_data vẫn chạy và cảnh báo ở dưới sẽ nêu nhóm thiếu câu.
        return out
    for i, obj in enumerate(objects):
        for k in range(per_object):
            out.append(templates[(i + k * 3) % n].format(obj))
    return out


# ============================================================================
# 3. CÁC CÂU VIẾT TAY (đa dạng, tự nhiên hơn - gộp từ cả 2 bản trước)
# ============================================================================

HANDWRITTEN = {
    "open_website": [
        "lên mạng kiểm tra gmail", "mở trình duyệt vào google",
        "cho tôi lướt facebook tí", "mở youtube lên xem phim",
        "vào trang chủ của github", "mở web đặt hàng shopee",
        "truy cập vào website chatgpt", "mở trang tin tức vnexpress",
        "vào google.com đi", "mở https://github.com",
        # v6: câu chứa URL cụ thể -> open_website (không phải play_media),
        # để model phân biệt "mở youtube nghe nhạc" với "mở youtube.com/watch..."
        "mở youtube.com/watch", "mở link youtube.com",
        "mở đường dẫn youtube.com/watch",
        "mở tab mới vào facebook", "vào messenger web",
        "mở trang web trường đại học", "cho tôi xem trang báo tuổi trẻ",
        "mở dịch google translate", "mở trang chủ notion",
    ],
    "open_app": [
        "mở cửa sổ dòng lệnh cmd", "bật máy tính bỏ túi lên tính toán",
        "mở vs code lên code", "khởi động visual studio code",
        "bật excel lên nhập số liệu", "mở powerpoint làm slide",
        "bật paint lên vẽ hình", "mở task manager xem ram",
        "chạy notepad giúp tôi", "mở trình quản lý file",
        "mở trình duyệt cốc cốc", "mở ứng dụng camera",
        "bật powershell lên", "mở outlook kiểm tra mail",
    ],
    "open_file": [
        "mở file báo cáo tháng này", "cho tôi xem lại luận văn",
        "mở thư mục tải xuống ra", "mở ảnh trong máy",
        "mở file d:\\work\\baocao.xlsx", "mở tệp ghi chú của tôi",
        "cho tôi mở bảng lương tháng 8", "mở file pdf hướng dẫn",
        "mở thư mục hình ảnh", "mở file trình chiếu",
        "cho tôi xem tài liệu hợp đồng", "mở file cv xin việc",
        "mở thư mục documents", "xem lại file backup",
    ],
    "system_control": [
        "tắt máy tính đi", "shutdown máy giúp tôi", "tắt nguồn máy tính",
        "tắt máy sau 5 phút", "cho máy tắt đi", "tắt máy giup tôi nhé",
        "khởi động lại máy", "restart máy tính giúp tôi", "reboot lại hệ thống",
        "khởi động lại windows", "bật lại máy từ đầu",
        "khoá màn hình lại", "khóa máy tính lại", "lock máy tính", "khoá máy đi",
        "cho máy ngủ đi", "chuyển sang chế độ sleep", "đưa máy về chế độ ngủ",
        "tắt âm thanh", "tắt tiếng loa đi", "mute âm thanh giúp tôi",
        "cho im lặng đi", "tắt tiếng ngay",
        "bật âm thanh lên", "mở tiếng lên giúp tôi", "bật lại tiếng",
        "tăng âm lượng", "tăng tiếng lên", "cho to hơn đi", "vặn to lên",
        "giảm âm lượng xuống", "giảm tiếng đi", "cho nhỏ hơn tí", "vặn nhỏ lại",
        "đăng xuất tài khoản", "thoát khỏi máy tính", "log out giúp tôi",
        "chụp màn hình lại", "chụp lại màn hình giúp tôi",
    ],
    "search_web": [
        "tìm giúp tôi cách làm bánh", "tra từ điển tiếng anh",
        "google xem hôm nay có gì hot", "tìm kiếm tin tức công nghệ",
        "cho tôi tìm tài liệu về python", "search hộ tôi giá laptop",
        "tìm giá vàng trên google", "giá vàng hôm nay bao nhiêu",
        "đọc báo cho tôi nghe",
    ],
    "play_media": [
        "phát nhạc đi", "mở nhạc lên nghe", "bật bài hát yêu thích",
        "cho tôi nghe nhạc trữ tình", "phát video hài trên youtube",
        "mở playlist nhạc làm việc",
    ],
    "set_reminder": [
        "nhắc tôi họp lúc 3 giờ chiều", "đặt báo thức lúc 6 giờ sáng",
        "hẹn giờ 10 phút nữa", "nhắc tôi uống nước sau 30 phút",
        "tạo nhắc nhở nộp báo cáo", "đặt hẹn giờ 5 phút",
        "nhắc tôi nghỉ giải lao sau 1 tiếng", "báo thức 7 giờ sáng mai",
        "đặt đồng hồ đếm ngược 15 phút", "nhắc tôi gọi điện cho mẹ",
        "hẹn giờ tắt máy sau 45 phút", "nhắc tôi đi ăn trưa lúc 12 giờ",
        # v6.2: giờ viết bằng CHỮ (đã hiểu được trong parse_time_expression)
        "nhắc tôi họp lúc bảy giờ sáng", "đặt báo thức sáu giờ sáng mai",
        "nhắc tôi uống thuốc lúc chín giờ tối",
        "hẹn giờ nghỉ giải lao sau mười lăm phút",
        "nhắc tôi dậy lúc năm giờ rưỡi sáng",
    ],
    "get_weather": [
        "thời tiết hôm nay thế nào", "hôm nay có mưa không",
        "ngày mai trời nắng hay mưa", "xem dự báo thời tiết đi",
        "trời hôm nay bao nhiêu độ", "có cần mang áo mưa không",
        "hôm nay trời thế nào", "dự báo thời tiết ngày mai thế nào",
    ],
    "get_datetime": [
        "mấy giờ rồi", "bây giờ là mấy giờ", "cho tôi biết giờ hiện tại",
        "hôm nay ngày bao nhiêu", "hôm nay thứ mấy", "hôm nay là ngày mấy",
        "xem giờ giúp tôi", "ngày tháng hôm nay là gì", "bây giờ mấy giờ rồi nhỉ",
        "hôm nay ngày mấy tháng mấy",
    ],
    "calculate": [
        "12 cộng 8 bằng bao nhiêu", "tính giúp tôi 45 trừ 12",
        "100 chia 5 là bao nhiêu", "9 nhân 9 bằng mấy",
        "tính hộ tôi 3 cộng 4 nhân 2", "33 trừ 8 ra bao nhiêu",
        "giúp tôi tính 200 chia 8", "tính giùm 7 nhân 6",
        "250 cộng 750 bằng bao nhiêu", "tính nhẩm giúp tôi 18 trừ 9",
        "một cộng một bằng mấy",
        # v6.2: số viết bằng CHỮ giờ cũng tính được (xem replace_number_words
        # trong intent_model.py) - thêm mẫu để mô hình quen cách nói này.
        "mười lăm cộng hai mươi bảy bằng mấy", "hai mươi nhân ba là bao nhiêu",
        "tính một trăm trừ hai mươi lăm", "năm mươi chia mười bằng mấy",
        "ba mũ hai bằng bao nhiêu", "hai phẩy năm nhân bốn là mấy",
        "một nghìn trừ một bằng mấy", "sáu nhân bảy bằng bao nhiêu",
        "căn bậc ba của hai mươi bảy", "100 chia cho 4 bằng mấy",
    ],
    "chitchat": [
        "xin chào", "chào bạn", "hello bạn", "chào buổi sáng",
        "bạn tên gì", "bạn là ai vậy", "bạn làm được gì",
        "bạn khoẻ không", "cảm ơn nhé", "cảm ơn bạn nhiều",
        "tạm biệt", "bái bai", "hẹn gặp lại", "kể chuyện cười đi",
        "bạn giỏi quá", "nói chuyện với tôi đi", "bạn bao nhiêu tuổi",
        "hôm nay bạn thế nào",
        # Gộp từ nhãn "unknown" của bản trước (những câu ngoài phạm vi vốn
        # không trùng với 10 intent hành động còn lại - xem lời giải thích ở
        # đầu file và trong HUONG_DAN_SU_DUNG.txt).
        "bạn có thể giúp gì cho tôi", "tôi đang buồn quá",
        "hôm nay ăn gì nhỉ", "kể chuyện cổ tích cho tôi nghe",
        "bạn có biết nấu ăn không", "tôi muốn tâm sự một chút",
        "bạn thích màu gì", "trời hôm nay đẹp quá",
        "1 với 1 là 2 đúng không",
    ],
}


# ============================================================================
# 4. TỔNG HỢP DATASET GỐC (11 intent, dữ liệu có dấu)
# ============================================================================

def build_intent_data() -> dict[str, list[str]]:
    """Tạo dictionary: intent -> danh sách câu (đã khử trùng lặp)."""
    data = {
        "open_website": _generate(WEB_TEMPLATES, WEBSITES, 3),
        "open_app": _generate(APP_TEMPLATES, APPS, 3),
        "open_file": _generate(FILE_TEMPLATES, FILES, 3),
        "system_control": [],
        "search_web": _generate(SEARCH_TEMPLATES, SEARCH_QUERIES, 4),
        "play_media": _generate(MEDIA_TEMPLATES, SONGS, 4),
        "set_reminder": _generate_reminders(),
        "get_weather": _generate(WEATHER_TEMPLATES, CITIES, 3),
        "get_datetime": list(DATETIME_SENTENCES),
        "calculate": _generate_calc(),
        "chitchat": list(CHITCHAT_SENTENCES),
    }

    # Ghép thêm câu viết tay
    for intent, sentences in HANDWRITTEN.items():
        data.setdefault(intent, [])
        data[intent].extend(sentences)

    # Khử trùng lặp nhưng giữ nguyên thứ tự
    for intent in data:
        data[intent] = list(dict.fromkeys(s.strip().lower() for s in data[intent]))

    return data


# Dataset gốc (có dấu, đã khử trùng lặp) - dùng bởi nlu_advanced.py để dựng
# từ điển phục hồi dấu (ACCENT_MAP) và bởi train_phobert.py / train_nlu.py.
INTENT_DATA = build_intent_data()

# Danh sách intent không cần thực thi hành động trên máy (chỉ trả lời/đọc kết quả)
PASSIVE_INTENTS = {"chitchat", "get_datetime", "calculate", "get_weather"}


# ============================================================================
# 5. HÀM TIỆN ÍCH
# ============================================================================

def get_dataset_as_lists(augment_no_diacritics: bool = True) -> tuple[list[str], list[str]]:
    """
    Trả về 2 list song song: (texts, labels).

    augment_no_diacritics: nếu True (mặc định), với mỗi câu có dấu sẽ thêm
        1 câu tương ứng KHÔNG DẤU vào tập huấn luyện, giúp mô hình TF-IDF tự
        nó cũng nhận diện tốt khi người dùng gõ tắt hoặc STT trả về văn bản
        không dấu - bổ sung cho tầng tiền xử lý smart_normalize() của
        nlu_advanced.py (hữu ích khi bạn gọi predict_intent() trực tiếp,
        không qua NLU()). Câu trùng lặp sẽ tự bị bỏ qua.
    """
    texts, labels = [], []
    seen = set()
    for intent, sentences in INTENT_DATA.items():
        for s in sentences:
            variants = [s]
            if augment_no_diacritics:
                no_dia = strip_diacritics(s)
                if no_dia != s:
                    variants.append(no_dia)
            for v in variants:
                key = (v, intent)
                if key in seen:
                    continue
                seen.add(key)
                texts.append(v)
                labels.append(intent)
    return texts, labels


def get_dataframe(augment_no_diacritics: bool = True):
    """Trả về dữ liệu dạng Pandas DataFrame (cột: text, intent)."""
    try:
        import pandas as pd  # import cục bộ: file vẫn import được khi chưa có pandas
    except ImportError as e:
        # Loi phai noi duoc cach khac phuc, khong phai "No module named 'pandas'"
        # roi de nguoi dung tu doan (day la cho duoc goi truc tiep tu REPL/README).
        raise RuntimeError(
            "get_dataframe() cần pandas. Cài bằng: pip install pandas "
            "(hoặc dùng get_dataset_as_lists() - không cần thư viện ngoài)."
        ) from e
    texts, labels = get_dataset_as_lists(augment_no_diacritics=augment_no_diacritics)
    return pd.DataFrame({"text": texts, "intent": labels})


def export_csv(
    path: str | Path = "dataset_intent.csv", augment_no_diacritics: bool = False
) -> Path:
    """Xuất dataset ra file CSV để bạn dễ xem / chỉnh sửa bằng Excel. v7.0: dùng pathlib."""
    import csv

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    texts, labels = get_dataset_as_lists(augment_no_diacritics=augment_no_diacritics)
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["text", "intent"])
        writer.writerows(zip(texts, labels))
    safe_print(f"Đã xuất {len(texts)} câu ra: {out_path}")
    return out_path


def load_extra_csv(path: str | Path = "my_dataset.csv") -> int:
    """
    Nạp thêm dữ liệu riêng của bạn từ file CSV (2 cột: text,intent)
    và ghép vào INTENT_DATA. Gọi trước khi huấn luyện nếu cần.
    v7.0: dùng pathlib, type hints.
    """
    import csv

    csv_path = Path(path)
    if not csv_path.exists():
        return 0
    count = 0
    try:
        with csv_path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                text = (row.get("text") or "").strip().lower()
                intent = (row.get("intent") or "").strip()
                if text and intent:
                    INTENT_DATA.setdefault(intent, [])
                    if text not in INTENT_DATA[intent]:
                        INTENT_DATA[intent].append(text)
                        count += 1
    except UnicodeDecodeError as e:
        # Rủi ro THẬT khi tự sửa/tạo file bằng tay: Notepad trên Windows 7
        # mặc định lưu kiểu ANSI chứ không phải UTF-8 - đọc bằng utf-8-sig
        # sẽ lỗi. Báo rõ nguyên nhân + cách khắc phục thay vì crash mập mờ.
        safe_print(f"[LỖI] File '{csv_path}' không phải mã UTF-8: {e}")
        safe_print("   -> Mở lại file đó, chọn 'Save As', đổi Encoding thành UTF-8, rồi thử lại.")
        return 0
    except OSError as e:
        safe_print(f"[LỖI] Không đọc được file '{csv_path}': {e}")
        return 0
    safe_print(f"Đã nạp thêm {count} câu từ {csv_path}")
    return count


if __name__ == "__main__":
    setup_console()
    texts, labels = get_dataset_as_lists()
    texts_plain, _ = get_dataset_as_lists(augment_no_diacritics=False)
    safe_print(f"TỔNG SỐ CÂU MẪU (có dấu)       : {len(texts_plain)}")
    safe_print(f"TỔNG SỐ CÂU MẪU (kèm không dấu): {len(texts)}")
    safe_print(f"SỐ NHÓM Ý ĐỊNH: {len(INTENT_DATA)}\n")
    for intent, sentences in INTENT_DATA.items():
        example = sentences[0] if sentences else "(CHƯA CÓ CÂU NÀO - cần bổ sung!)"
        safe_print(f"  - {intent:<16}: {len(sentences):>3} câu   | ví dụ: {example}")
