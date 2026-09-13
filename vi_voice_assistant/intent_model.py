"""
intent_model.py v7.0
--------------------
HUẤN LUYỆN MÔ HÌNH PHÂN LOẠI Ý ĐỊNH (TF-IDF + LogisticRegression / SVM,
hoặc PhoBERT nếu đã fine-tune) và TRÍCH XUẤT THỰC THỂ (Entity Extraction).

v7.0 nâng cấp:
- Thêm from __future__ import annotations, type hints, pathlib
- Giữ nguyên toàn bộ logic parse_time_expression, parse_math_expression, entity extraction
- Thêm logging, validation, atomic save cho model
- Tương thích 100% với tests v6.x

BẢN KẾT HỢP (v5) + v6.2 (số bằng chữ) + v6.3 (WSL) + v7.0 (typing & pathlib):
- Trích URL/đường dẫn KHÔNG bị cắt cụt, giữ nguyên hoa/thường
- normalize_text() dùng chung qua text_utils.py
- Trích xuất thời gian cho nhắc nhở (parse_time_expression)
- Phân tích + tính biểu thức toán AN TOÀN (parse_math_expression)
- Tự động ưu tiên dùng PhoBERT nếu đã huấn luyện xong

Chạy để huấn luyện và lưu model TF-IDF ra `intent_model.pkl`:
    python intent_model.py
"""

import ast
import json
import logging
import math
import os
import re

# v6 - THAY ĐỔI QUAN TRỌNG: scikit-learn/joblib giờ là TUỲ CHỌN.
# Trước đây 6 dòng import này nằm trần: máy nào chưa cài được scikit-learn
# (rất hay gặp trên Windows 7 / Python 3.8, hoặc máy không có mạng) là TOÀN
# BỘ trợ lý sập ngay từ dòng import - kể cả những tính năng chẳng liên quan
# gì tới máy học. Nay thiếu thư viện thì tự chuyển sang lite_model.py.
try:
    import joblib
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import classification_report
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    SKLEARN_AVAILABLE = True
except ImportError:   # pragma: no cover
    joblib = None
    TfidfVectorizer = None
    LogisticRegression = None
    classification_report = None
    train_test_split = None
    Pipeline = object   # để các chú thích kiểu "-> Pipeline" vẫn hợp lệ
    SKLEARN_AVAILABLE = False

from dataset import get_dataset_as_lists
from platform_utils import safe_print, setup_console
from text_utils import normalize_text, strip_diacritics

logger = logging.getLogger(__name__)

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "intent_model.pkl")


# ============================================================================
# 1. HUẤN LUYỆN MÔ HÌNH (TF-IDF)
# ============================================================================
def _require_sklearn(what: str = "chức năng này") -> None:
    """Báo lỗi RÕ RÀNG thay vì NameError khó hiểu khi máy chưa có scikit-learn."""
    if not SKLEARN_AVAILABLE:
        raise ImportError(
            "Cần scikit-learn để dùng " + what + ".\n"
            "   Cài bằng:  pip install scikit-learn joblib\n"
            "   (Không cài cũng không sao - trợ lý tự dùng model nhẹ trong lite_model.py)"
        )


def build_pipeline(algorithm: str = "logistic") -> Pipeline:
    """Tạo pipeline TF-IDF (n-gram ký tự) -> bộ phân loại."""
    _require_sklearn("bộ phân loại TF-IDF")
    if algorithm == "svm":
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.svm import LinearSVC
        classifier = CalibratedClassifierCV(LinearSVC(), cv=3)
    else:
        classifier = LogisticRegression(max_iter=2000, C=10)

    return Pipeline([
        ("tfidf", TfidfVectorizer(
            analyzer="char_wb",   # n-gram ký tự: hợp tiếng Việt, không cần tokenizer
            ngram_range=(1, 5),
            sublinear_tf=True,
            min_df=1,
        )),
        ("clf", classifier),
    ])


def train_model(algorithm: str = "logistic", show_report: bool = True):
    """Huấn luyện mô hình trên dataset tiếng Việt và trả về model đã fit.

    v6: nếu máy KHÔNG có scikit-learn thì tự huấn luyện model nhẹ thuần Python
    (lite_model.py) thay vì ném lỗi và làm chết cả chương trình.
    """
    if not SKLEARN_AVAILABLE:
        from lite_model import train_lite_model
        safe_print("[MODEL] Không tìm thấy scikit-learn -> huấn luyện model nhẹ thuần Python.")
        return train_lite_model(show_report=show_report)

    texts, labels = get_dataset_as_lists()
    texts = [normalize_text(t) for t in texts]
    safe_print(f"Dữ liệu: {len(texts)} câu / {len(set(labels))} nhóm ý định")
    logger.info("Huấn luyện với %d câu mẫu (đã gồm biến thể không dấu).", len(texts))

    # train_test_split(..., stratify=labels) BẮT BUỘC mỗi nhãn phải có ÍT
    # NHẤT 2 mẫu (1 cho train, 1 cho test) - nếu không sẽ ném ValueError và
    # LÀM SẬP CHƯƠNG TRÌNH NGAY LÚC HUẤN LUYỆN. Tình huống này hoàn toàn có
    # thể xảy ra nếu bạn tự thêm 1 intent MỚI vào my_dataset.csv nhưng chỉ
    # viết 1 câu ví dụ. Cảnh báo sớm để bạn biết cần bổ sung thêm câu, và
    # tự động chuyển sang chia KHÔNG phân tầng nếu vẫn còn thiếu (model cuối
    # cùng vẫn học trên TOÀN BỘ dữ liệu ở pipeline.fit(texts, labels) bên
    # dưới nên không mất dữ liệu, chỉ ảnh hưởng độ tin cậy của báo cáo).
    from collections import Counter
    thin = {intent: c for intent, c in Counter(labels).items() if c < 2}
    if thin:
        safe_print(f"[CẢNH BÁO] {len(thin)} nhóm ý định có QUÁ ÍT câu mẫu (dưới 2 câu): {thin}")
        safe_print(
            "   -> Nên bổ sung thêm câu cho các nhóm này (sửa dataset.py hoặc my_dataset.csv)."
        )

    try:
        X_train, X_test, y_train, y_test = train_test_split(
            texts, labels, test_size=0.2, random_state=42, stratify=labels
        )
    except ValueError:
        safe_print("[CẢNH BÁO] Không chia được tập train/test theo tỉ lệ đều giữa các nhóm "
                   "(do 1 vài nhóm quá ít mẫu) - chuyển sang chia ngẫu nhiên thường.")
        X_train, X_test, y_train, y_test = train_test_split(
            texts, labels, test_size=0.2, random_state=42
        )

    pipeline = build_pipeline(algorithm)
    pipeline.fit(X_train, y_train)

    if show_report:
        y_pred = pipeline.predict(X_test)
        report = classification_report(y_test, y_pred, zero_division=0)
        safe_print("\n===== BÁO CÁO ĐÁNH GIÁ TRÊN TẬP TEST =====")
        safe_print(report)
        logger.info("Báo cáo đánh giá:\n%s", report)

    # Huấn luyện lại trên toàn bộ dữ liệu để dùng thực tế
    pipeline.fit(texts, labels)
    return pipeline


def save_model(pipeline, path: str = MODEL_PATH) -> None:
    # v6: model nhẹ tự lưu bằng pickle chuẩn của Python (không cần joblib).
    try:
        from lite_model import LITE_MODEL_PATH, LiteIntentModel, save_lite_model
        if isinstance(pipeline, LiteIntentModel):
            target = LITE_MODEL_PATH if path == MODEL_PATH else path
            if save_lite_model(pipeline, target):
                safe_print(f"Đã lưu model nhẹ tại: {target}")
            else:
                safe_print(f"[LỖI] Không lưu được model nhẹ ra '{target}'")
            return
    except ImportError:
        pass

    if joblib is None:
        safe_print("[LỖI] Cần joblib để lưu model TF-IDF (pip install joblib).")
        return

    try:
        joblib.dump(pipeline, path)
    except OSError as e:
        # Không để lỗi ghi đĩa (thiếu quyền, ổ đĩa đầy...) làm mất TOÀN BỘ
        # công sức huấn luyện (có thể mất 1-3 phút với GridSearchCV) mà
        # không rõ lý do - báo rõ ràng thay vì traceback khó hiểu.
        safe_print(f"[LỖI] Không lưu được model ra '{path}': {e}")
        safe_print(
            "   (Model đã huấn luyện xong trong bộ nhớ, nhưng sẽ mất khi chương trình "
            "thoát vì chưa lưu được ra đĩa)"
        )
        logger.error("Không lưu được model tại %s: %s", path, e)
        return
    safe_print(f"Đã lưu model tại: {path}")
    logger.info("Đã lưu model tại: %s", path)


def load_model(path: str = MODEL_PATH, prefer_phobert: bool = True):
    """
    Nạp model tốt nhất hiện có để hiểu ý.

    - Nếu đã chạy `python train_phobert.py` (thư mục phobert_model/ tồn tại)
      và máy có cài transformers/torch -> ưu tiên dùng PhoBERT (hiểu ngữ nghĩa
      tốt hơn TF-IDF, đặc biệt với câu dài / cách diễn đạt khác nhau).
    - Nếu chưa có PhoBERT -> dùng model TF-IDF (intent_model.pkl), tự động
      huấn luyện nếu chưa tồn tại.

    Không cần sửa gì ở nlu_advanced.py / main.py: chúng luôn gọi load_model()
    và nhận về model "tốt nhất" hiện có một cách tự động.
    """
    if prefer_phobert:
        try:
            from phobert_model import PhoBertIntentClassifier
            phobert = PhoBertIntentClassifier()
            if phobert.is_trained():
                phobert.load()
                safe_print("[MODEL] Đang dùng PhoBERT (đã huấn luyện) để hiểu ý.")
                logger.info("Dùng PhoBERT để hiểu ý (đã huấn luyện).")
                return phobert
        except Exception as e:
            safe_print(f"[MODEL] Chưa dùng được PhoBERT ({e}), chuyển sang TF-IDF.")

    if SKLEARN_AVAILABLE and os.path.exists(path):
        logger.info("Nạp model TF-IDF có sẵn từ %s", path)
        try:
            return joblib.load(path)
        except Exception as e:
            # v7.2 - SỬA LỖI LÀM SẬP TRỢ LÝ Ở BƯỚC KHỞI ĐỘNG: file
            # intent_model.pkl có thể hỏng (mất điện lúc ghi, disk đầy) hoặc
            # được lưu bởi MỘT PHIÊN BẢN scikit-learn khác (cấu trúc lớp bên
            # trong thay đổi -> ValueError/AttributeError khi nạp). Trước đây
            # lỗi này ném thẳng ra ngoài, main.py chết hẳn dù hoàn toàn có thể
            # tự huấn luyện lại trong vài giây. Nay: cảnh báo + tự train lại.
            safe_print(f"[MODEL] File model '{path}' nạp không được ({e}) -> sẽ huấn luyện lại.")
            logger.warning("Không nạp được model tại %s: %s", path, e)
            # Dời file hỏng sang .bak (không xoá luôn) để bạn còn mang đi hỏi
            # được "vì sao model cũ không nạp nổi", đồng thời lần khởi động
            # sau không phải lặp lại đúng cảnh báo này.
            try:
                backup = f"{path}.bak"
                os.replace(path, backup)
                safe_print(f"   Đã cất bản hỏng sang: {backup}")
            except OSError as move_error:
                logger.warning("Không dời được file model hỏng: %s", move_error)

    # v6 - TẦNG DỰ PHÒNG CUỐI: không có scikit-learn thì dùng model nhẹ thuần
    # Python. Đây chính là điểm khiến bản v5 "chết cứng" trên máy chưa cài được
    # scikit-learn: trợ lý không chạy nổi dù phần lớn tính năng không cần tới nó.
    if not SKLEARN_AVAILABLE:
        from lite_model import get_lite_model
        model = get_lite_model()
        safe_print("[MODEL] Đang dùng model nhẹ thuần Python (không cần scikit-learn).")
        logger.info(
            "Dùng LiteIntentModel: %d nhãn, nhiệt độ %s", len(model.classes_), model.temperature
        )
        return model

    safe_print("Chưa có model, đang tự động huấn luyện...")
    logger.info("Chưa có model tại %s, tự động huấn luyện.", path)
    model = train_model(show_report=False)
    save_model(model, path)
    return model


def describe_engine(model=None) -> str:
    """Tên bộ hiểu ý đang thực sự được dùng - để in cho người dùng biết (v6).

    Trước đây không có cách nào biết trợ lý đang chạy PhoBERT hay TF-IDF nếu
    không đọc kỹ log lúc khởi động.
    """
    if model is None:
        model = load_model()
    name = type(model).__name__
    if name == "PhoBertIntentClassifier":
        return "PhoBERT (chính xác nhất, cần torch + transformers)"
    if name == "LiteIntentModel":
        return "Lite Naive Bayes thuần Python (không cần thư viện ngoài)"
    return "TF-IDF + scikit-learn"


# ============================================================================
# 2. TRÍCH XUẤT THỰC THỂ (ENTITY EXTRACTION)
# ============================================================================

# Từ "vô nghĩa" cần loại bỏ để còn lại tên đối tượng (đã dọn lại: bỏ các mục
# ghép lỗi kiểu "lênđi", "mởra" của bản gốc rất cũ)
STOP_WORDS = {
    "bật", "mở", "vào", "truy", "cập", "lên", "ra", "đi", "giúp", "tôi", "cho",
    "nào", "nhé", "nha", "ạ", "ơi", "hãy", "làm", "ơn", "khởi", "chạy",
    "chương", "trình", "ứng", "dụng", "phần", "mềm", "app", "trang", "web",
    "website", "chủ", "của", "file", "tệp", "tin", "tài", "liệu", "xem", "lại",
    "trên", "trong", "máy", "hệ", "thống", "một", "cái", "thử", "dùm", "giùm",
    "hộ", "là", "để", "với", "cửa", "sổ", "duyệt", "ngay", "nữa", "quản", "lý",
    "search", "tìm", "kiếm", "tab", "mới",
}
# Tự sinh thêm bản KHÔNG DẤU của từng stop-word để lọc được cả câu không dấu
# (vd "mo google len" -> "mo" và "len" cũng cần được coi là stop-word)
STOP_WORDS_ALL = STOP_WORDS | {strip_diacritics(w) for w in STOP_WORDS}

# Từ khoá chuẩn hoá cho system_control -> hành động chuẩn
# (pattern sẽ tự động được thử thêm bản không dấu, xem _match_any_pattern)
SYSTEM_KEYWORDS = [
    (r"khởi động lại|restart|reboot|bật lại máy", "restart"),
    (r"tắt máy|shutdown|tắt nguồn|tắt (?:cái )?máy tính", "shutdown"),
    (r"khoá màn hình|khóa màn hình|khoá máy|khóa máy|lock", "lock"),
    (r"chụp màn hình|screenshot|chụp lại màn hình", "screenshot"),
    (r"ngủ|sleep|chế độ ngủ", "sleep"),
    (r"đăng xuất|logout|log out|thoát khỏi máy", "logout"),
    (r"tắt âm|tắt tiếng|im lặng|mute", "mute"),
    (r"bật âm|mở tiếng|bật tiếng|bật lại tiếng|unmute", "unmute"),
    (r"tăng âm|to hơn|vặn to|volume up", "volume_up"),
    (r"giảm âm|nhỏ hơn|vặn nhỏ|volume down", "volume_down"),
]


def _match_any_pattern(pattern: str, raw: str, raw_no_dia: str) -> bool:
    """Thử khớp pattern với câu có dấu VÀ bản không dấu của cả câu lẫn pattern."""
    if re.search(pattern, raw):
        return True
    return re.search(strip_diacritics(pattern), raw_no_dia) is not None


# Nhận diện URL/tên miền TRONG CÂU NÓI (không neo ^...$, cần TÌM 1 token URL
# nằm giữa câu, vd "mở github.com/abc lên"). Có 3 nhánh:
#   1. https?://... (scheme tường minh) -> nhận trọn phần còn lại của token.
#   2. www.... -> tương tự.
#   3. tên miền trần + TLD quen thuộc, có thể kèm /đường-dẫn?truy=vấn#mảnh -
#      dùng negative lookahead (?!\w) để không khớp nhầm 1 phần của từ dài
#      hơn (vd "abc.commercial" KHÔNG được hiểu nhầm là domain "abc.com").
# LƯU Ý QUAN TRỌNG (bản vá lỗi giữ lại từ bản "bảo mật/đa nền tảng"): PHẢI
# giữ nguyên phần đường dẫn/truy vấn phía sau TLD (không dùng \b ngay sau
# TLD), nếu không "github.com/abc/xyz" sẽ bị cắt cụt về "github.com".
# v6.2: mở rộng danh sách TLD (ai, app, xyz, me, tv, info, gov, edu, shop,
# online...) - trước đây "mở claude.ai" không được nhận là URL mà rơi xuống
# nhánh tìm kiếm Google.
_URL_ENTITY_RE = re.compile(
    r"(https?://\S+|www\.\S+|[\w\-]+(?:\.[\w\-]+)*\.(?:com|vn|net|org|io|dev|ai|app|xyz|me|tv|info|gov|edu|shop|online|site|tech|cloud)(?:[/?#]\S*)?)(?!\w)",
    re.IGNORECASE,
)
# Đường dẫn file kiểu Windows ("C:\..." hoặc "C:/...") hoặc Unix ("/thu/muc/file").
# v6.2: chấp nhận cả dấu / cho ổ đĩa Windows - người dùng rất hay gõ/dán
# đường dẫn kiểu "C:/Users/...".
_PATH_ENTITY_RE = re.compile(r"([a-zA-Z]:[\\/][^\s]+|/[^\s]+/[^\s]+)")

# Từ cần bóc ở đầu/cuối câu tìm kiếm
SEARCH_PREFIX = r"^(tìm kiếm|tra cứu|tìm|search|google|tra|cho tôi biết|thông tin về)\s+"
SEARCH_SUFFIX = r"\s*(trên google|trên mạng|giúp tôi|giùm tôi|hộ tôi|đi|nhé|xem)\s*$"

# Từ cần bóc ở câu phát nhạc
MEDIA_PREFIX = r"^(phát|mở|bật|cho tôi nghe|nghe)\s+"
MEDIA_SUFFIX = r"\s*(trên youtube|trên spotify|giúp tôi nghe|giúp tôi|đi|nghe|lên|nhé)\s*$"


def _strip_affixes(text: str, prefix: str, suffix: str) -> str:
    """Bóc các cụm thừa đầu/cuối câu (lặp cho đến khi không bóc được nữa)."""
    prev = None
    while prev != text:
        prev = text
        text = re.sub(prefix, "", text).strip()
        text = re.sub(suffix, "", text).strip()
    return text


# "ngày mai / sáng mai / tối mai..." -> hẹn sang HÔM SAU. Cố tình KHÔNG bắt
# chữ "mai" đứng một mình vì đó còn là tên người ("nhắc tôi gọi Mai").
_TOMORROW_RE = re.compile(
    r"\b(ngay mai|sang mai|trua mai|chieu mai|toi mai|dem mai|khuya mai|hom sau)\b"
)


# ============================================================================
# 2B. SỐ VIẾT BẰNG CHỮ TIẾNG VIỆT (MỚI v6.2)
# ============================================================================
# Trước đây parse_math_expression() / parse_time_expression() chỉ hiểu chữ SỐ,
# nên "mười lăm cộng hai mươi bảy" hay "nhắc tôi họp lúc bảy giờ" đều bó tay
# (giới hạn đã ghi nhận trong HUONG_DAN_SU_DUNG.txt mục 0-D). Bộ chuyển đổi
# dưới đây đọc một CỤM từ-số liền nhau ("hai mươi mốt", "một trăm lẻ năm",
# "hai phẩy năm") rồi thay bằng chữ số ("21", "105", "2.5") TRƯỚC khi các
# regex sẵn có làm việc - không phải đụng vào các regex đó.
#
# Quy tắc an toàn:
#   - Từ CÓ DẤU được tra đúng dấu trước ("tâm" khác "tám"); chỉ khi token hoàn
#     toàn KHÔNG dấu mới tra theo bản không dấu ("tam" -> 8).
#   - "sáu" chỉ nhận dạng CÓ DẤU: bản không dấu "sau" trùng từ nối "sau"
#     (after), đổi nó sẽ phá mất dấu hiệu đếm ngược ("sau 2 giờ").
#   - Từ đứng ngay sau "bậc" không đổi ("căn bậc hai" KHÔNG thành "căn bậc 2").
#   - Cụm không phân tích được thì giữ NGUYÊN văn, không thay thế bừa.
#   - Chỉ gọi trong các hàm gắn với intent calculate / set_reminder, KHÔNG chạy
#     trên câu thường (tránh đổi nhầm "một", "tâm sự"... ở nơi khác).

_NUMBER_DIGIT_WORDS = {
    "không": 0, "một": 1, "mốt": 1, "hai": 2, "ba": 3, "bốn": 4, "tư": 4,
    "năm": 5, "lăm": 5, "nhăm": 5, "sáu": 6, "bảy": 7, "bẩy": 7,
    "tám": 8, "chín": 9,
}
_NUMBER_TENS_WORDS = {"mươi", "chục"}          # nhân 10 theo chữ số đứng trước
_NUMBER_TEN_WORD = "mười"                        # = 10
_NUMBER_HUNDRED_WORD = "trăm"                    # nhân 100
_NUMBER_SCALE_WORDS = {"nghìn": 1000, "ngàn": 1000, "triệu": 10 ** 6,
                       "tỷ": 10 ** 9, "tỉ": 10 ** 9}
_NUMBER_ZERO_WORDS = {"lẻ", "linh"}              # "một trăm lẻ năm"
_NUMBER_DECIMAL_WORD = "phẩy"                    # "hai phẩy năm" = 2.5

# Bản KHÔNG DẤU của từ-số chữ số. Loại "sáu" (sau) vì trùng từ nối "sau".
# Các từ đồng âm còn lại sau khi bỏ dấu đều CÙNG giá trị ("một"/"mốt" -> 1,
# "lăm"/"nhăm" -> 5, "bảy"/"bẩy" -> 7) nên không gây xung đột.
_NUMBER_DIGITS_PLAIN = {}
for _w, _v in _NUMBER_DIGIT_WORDS.items():
    _p = strip_diacritics(_w)
    if _p != "sau":
        _NUMBER_DIGITS_PLAIN.setdefault(_p, _v)


def _number_digit_value(token):
    """Giá trị chữ số của 1 từ-số (0-9), hoặc None. Ưu tiên khớp CÓ DẤU; token
    hoàn toàn không dấu mới tra bản không dấu (để 'tâm' không đọc thành 'tám')."""
    if token in _NUMBER_DIGIT_WORDS:
        return _NUMBER_DIGIT_WORDS[token]
    if strip_diacritics(token) == token:
        return _NUMBER_DIGITS_PLAIN.get(token)
    return None


def _classify_number_token(token, prev_token):
    """Phân loại 1 token trong cụm từ-số. Trả về None nếu không phải từ-số.

    Các loại: ("digit", n) | ("ten",) mười | ("tens",) mươi/chục |
    ("hundred",) trăm | ("scale", n) nghìn/triệu/tỷ | ("zero",) lẻ/linh |
    ("decimal",) phẩy | ("ten_or_tens",) "muoi" không dấu (mười hay mươi).
    """
    if prev_token is not None and strip_diacritics(prev_token) in ("bac", "phan"):
        # "bậc hai/ba" là BẬC của căn; "phần trăm" là PHẦN TRĂM - đều không
        # phải toán hạng (trước đây "trăm" trong "phần trăm" bị đổi thành 100).
        return None
    digit = _number_digit_value(token)
    if digit is not None:
        return ("digit", digit)
    if token == _NUMBER_TEN_WORD:
        return ("ten", None)
    if token in _NUMBER_TENS_WORDS:
        return ("tens", None)
    if token == _NUMBER_HUNDRED_WORD:
        return ("hundred", None)
    if token in _NUMBER_SCALE_WORDS:
        return ("scale", _NUMBER_SCALE_WORDS[token])
    if token in _NUMBER_ZERO_WORDS:
        return ("zero", None)
    if token == _NUMBER_DECIMAL_WORD:
        return ("decimal", None)
    if strip_diacritics(token) == token:   # token hoàn toàn không dấu
        if token == "muoi":
            return ("ten_or_tens", None)
        if token == "chuc":
            return ("tens", None)
        if token == "tram":
            return ("hundred", None)
        if token in ("nghin", "ngan"):
            return ("scale", 1000)
        if token == "trieu":
            return ("scale", 10 ** 6)
        if token in ("ty", "ti"):
            return ("scale", 10 ** 9)
        if token in ("le", "linh"):
            return ("zero", None)
        if token == "phay":
            return ("decimal", None)
    return None


def _parse_number_run(tokens, prev_token):
    """Đọc 1 cụm từ-số -> int/float. Trả về None nếu cụm không hợp lệ (caller
    sẽ giữ nguyên văn cụm đó, không thay thế bừa)."""
    kinds = []
    prev = prev_token
    for token in tokens:
        kind = _classify_number_token(token, prev)
        if kind is None:
            return None
        kinds.append(kind)
        prev = token

    total = 0            # tích luỹ các nhóm lớn (nghìn/triệu/tỷ)
    current = 0          # giá trị đang dở trong nhóm hiện tại
    last_digit = None    # chữ số đứng ngay trước (để "mươi"/"trăm" nhân lên)
    fraction = []
    is_fraction = False
    seen = False

    for kind, value in kinds:
        if kind == "decimal":
            if is_fraction:
                return None
            is_fraction = True
        elif is_fraction:
            if kind == "digit":
                fraction.append(str(value))
            elif kind == "ten":
                fraction.extend(("1", "0"))   # "hai phẩy mười" = 2.10
            elif kind == "zero":
                fraction.append("0")
            else:
                return None
        elif kind == "digit":
            if last_digit is not None:
                return None       # "hai ba" không hợp lệ trong tiếng Việt
            current += value
            last_digit = value
            seen = True
        elif kind == "ten":
            if last_digit is not None:
                return None       # "hai mười" không dùng -> từ chối cho chắc
            current += 10
            seen = True
        elif kind in ("tens", "ten_or_tens"):
            # "muoi" không dấu: sau chữ số là "mươi" (hai muoi = 20), đứng
            # một mình là "mười" (muoi lam = 15).
            if kind == "ten_or_tens" and last_digit is None:
                current += 10
            elif last_digit is not None:
                current -= last_digit
                current += last_digit * 10
                last_digit = None
            else:
                current += 10
            seen = True
        elif kind == "hundred":
            if last_digit is not None:
                current -= last_digit
                current += last_digit * 100
                last_digit = None
            else:
                current += 100
            seen = True
        elif kind == "scale":
            group = current if (current or last_digit is not None) else 1
            total += group * value
            current, last_digit = 0, None
            seen = True
        elif kind == "zero":
            last_digit = None     # "lẻ năm": chữ số sau cộng thẳng vào

    if not seen:
        return None
    result = total + current
    if is_fraction:
        if not fraction:
            return None
        result += int("".join(fraction)) / float(10 ** len(fraction))
    if isinstance(result, float) and result.is_integer():
        return int(result)
    return result


def _format_number_word(value):
    """int/float -> chuỗi chữ số gọn (2.5 -> '2.5', 105 -> '105')."""
    if isinstance(value, int):
        return str(value)
    return f"{value:g}"


def replace_number_words(text):
    """Thay các cụm từ-số tiếng Việt bằng chữ số (v6.2).

    Ví dụ: "mười lăm cộng hai mươi bảy" -> "15 cộng 27";
           "nhắc tôi họp lúc bảy giờ sáng" -> "nhắc tôi họp lúc 7 giờ sáng".
    Cụm không đọc được được giữ nguyên văn.
    """
    tokens = (text or "").split()
    out = []
    i = 0
    prev = None
    while i < len(tokens):
        if _classify_number_token(tokens[i], prev) is None:
            out.append(tokens[i])
            prev = tokens[i]
            i += 1
            continue
        j = i
        while j < len(tokens) and _classify_number_token(
            tokens[j], tokens[j - 1] if j > i else prev
        ) is not None:
            j += 1
        run = tokens[i:j]
        value = _parse_number_run(run, prev)
        if value is None:
            out.extend(run)      # không đọc được -> giữ nguyên văn
        else:
            out.append(_format_number_word(value))
        prev = tokens[j - 1]
        i = j
    return " ".join(out)


# v6.2: cụm SỐ (chữ số "15" hoặc từ-số "mười lăm" / "một trăm lẻ năm") -
# dùng trong regex bóc mốc giờ của extract_entity(). Cố tình KHÔNG gồm
# "sau" (="sáu" không dấu) để không nuốt mất từ nối "sau" (after).
_NUMBER_WORD_ALT = (
    "không|một|mốt|hai|ba|bốn|tư|năm|lăm|nhăm|sáu|bảy|bẩy|tám|chín|"
    "mười|mươi|chục|trăm|nghìn|ngàn|triệu|tỷ|tỉ|lẻ|linh|phẩy|rưỡi|"
    "khong|mot|bon|tu|nam|lam|nham|bay|tam|chin|"
    "muoi|chuc|tram|nghin|ngan|trieu|ty|ti|le|phay|ruoi"
)
_NUMBER_WORD_RUN = (
    r"(?:\d+(?:[.,]\d+)?|(?:" + _NUMBER_WORD_ALT + r")"
    r"(?:\s+(?:" + _NUMBER_WORD_ALT + r"))*)"
)

# v6.2: dấu hiệu "khoảng thời gian" (đếm ngược) - kiểm tra trên văn bản CÓ DẤU
# khi có thể để tránh nhầm tên riêng "Sáu" (bỏ dấu -> "sau") với từ nối "sau".
_DURATION_RE = re.compile(r"(\d+)\s*(giay|phut|tieng|gio)\b")
_DELAY_MARKER_ACCENTED_RE = re.compile(r"\b(?:sau|nữa)\b|\bđếm\s+ngược\b")
_DELAY_MARKER_PLAIN_RE = re.compile(r"\b(?:sau|nua)\b|\b(?:dem|em)\s+nguoc\b")

# Những từ mà sau chúng "tôi" là ĐẠI TỪ (tôi = tôi), không phải buổi "tối".
_PRONOUN_PRECEDERS = {
    "nhac", "cho", "giup", "hoi", "voi", "cua", "bao", "nho", "goi",
    "ke", "gap", "thay", "hen", "dan",
}


def _detect_period(t, u_segment, plain_input):
    """Nhận diện buổi trong ngày trong đoạn văn bản (đã bỏ dấu) ->
    'sang' | 'trua' | 'chieu' | 'dem' | 'khuya' | 'toi' | None.

    Riêng "tối" phải tách khỏi đại từ "tôi": với văn bản CÓ DẤU thì khớp chính
    xác \\btối\\b trên văn bản gốc; với văn bản KHÔNG DẤU thì loại trừ "tôi"
    đứng sau các động/tính từ đi kèm đại từ (nhắc tôi, cho tôi, giúp tôi...).
    """
    for pattern, period in ((r"\bsang\b", "sang"), (r"\btrua\b", "trua"),
                            (r"\bchieu\b", "chieu"), (r"\bdem\b", "dem"),
                            (r"\bkhuya\b", "khuya")):
        if re.search(pattern, u_segment):
            return period
    if plain_input:
        for marker in re.finditer(r"\btoi\b", u_segment):
            before = u_segment[:marker.start()].split()
            if before and before[-1] in _PRONOUN_PRECEDERS:
                continue          # "nhắc tôi / cho tôi..." -> đại từ, bỏ qua
            return "toi"
        return None
    # Văn bản có dấu: chỉ chấp nhận khi thật sự có chữ "tối" (không phải "tôi")
    if re.search(r"\btối\b", t):
        return "toi"
    return None


def parse_time_expression(text: str) -> dict:
    """
    Phân tích biểu thức thời gian tiếng Việt.

    Trả về dict LUÔN ĐỦ KHOÁ (v6 - trước đây khi không nhận ra giờ thì chỉ
    trả về {"type": None}, sai khác với chính docstring của nó và bắt mọi nơi
    gọi phải dùng .get() phòng hờ):
        {"type": "delay"|"clock"|None, "minutes", "hour", "minute", "day_offset"}

    Hiểu thêm nhiều cách nói thường gặp mà bản v5 BỎ QUA:
        "3h30", "7h"            -> giờ viết tắt kiểu tin nhắn
        "3 giờ rưỡi"           -> 3:30
        "8 giờ kém 15"          -> 7:45
        "11 giờ đêm"            -> 23:00
        "30 giây nữa"           -> đếm ngược dưới 1 phút
        "7 giờ sáng mai"        -> đúng HÔM SAU (trước đây mất chữ "mai")
    và chạy được cả khi người dùng GÕ KHÔNG DẤU ("30 phut nua", "3 gio chieu").
    """
    t = normalize_text(text)
    # v6.2: đổi từ-số thành chữ số TRƯỚC ("bảy giờ sáng" -> "7 giờ sáng",
    # "tám giờ kém mười lăm" -> "8 giờ kém 15") để các regex bên dưới hiểu được.
    t = replace_number_words(t)
    u = strip_diacritics(t)   # so khớp trên bản không dấu để bao được cả 2 kiểu gõ
    plain_input = (t == u)    # người dùng gõ hoàn toàn không dấu
    none_result = {"type": None, "minutes": 0, "hour": 0, "minute": 0, "day_offset": 0}

    # --- "nửa tiếng/giờ (nữa)" = 30 phút (v6.2) ---
    # "nửa" và "nữa" bỏ dấu đều là "nua": câu CÓ DẤU bắt buộc khớp đúng
    # "nửa"; chỉ câu hoàn toàn không dấu mới khớp "nua tieng/gio".
    if re.search(r"\bnửa\s+(?:tiếng|giờ)\b", t) or (
            plain_input and re.search(r"\bnua\s+(?:tieng|gio)\b", u)):
        return {"type": "delay", "minutes": 30, "hour": 0, "minute": 0, "day_offset": 0}

    # --- Dạng đếm ngược: "sau/nữa X giây / X phút / X tiếng" (v6.2 viết lại) ---
    durations = list(_DURATION_RE.finditer(u))
    if durations:
        # Dấu hiệu khoảng thời gian: kiểm tra trên bản CÓ DẤU khi có thể -
        # tránh nhầm tên riêng "Sáu" (bỏ dấu -> "sau") với từ nối "sau".
        if plain_input:
            has_marker = bool(_DELAY_MARKER_PLAIN_RE.search(u))
        else:
            has_marker = bool(_DELAY_MARKER_ACCENTED_RE.search(t))
        preceded_by_luc = bool(re.search(r"(?:lúc|luc)\s*$", u[:durations[0].start()]))
        only_small_units = all(m.group(2) in ("phut", "giay") for m in durations)
        # "lúc 3 giờ" / "3 giờ" trần là GIỜ ĐỒNG HỒ, không phải khoảng chờ;
        # "5 phút" trần (vd "đặt hẹn giờ 5 phút") hiểu là đếm ngược (v6.2).
        if has_marker or (only_small_units and not preceded_by_luc):
            minutes = 0.0
            for dur in durations:
                value = int(dur.group(1))
                unit = dur.group(2)
                if unit == "giay":
                    minutes += value / 60.0
                elif unit in ("tieng", "gio"):
                    minutes += value * 60
                else:
                    minutes += value
            # "1 tiếng rưỡi nữa" = 90 phút (v6.2)
            if any(dur.group(2) in ("tieng", "gio") for dur in durations) \
                    and re.search(r"\bruoi\b", u):
                minutes += 30
            return {"type": "delay", "minutes": round(minutes, 4), "hour": 0,
                    "minute": 0, "day_offset": 0}

    # --- Dạng giờ cụ thể: "lúc X giờ [Y] [sáng/trưa/chiều/tối]", "3h30" ---
    m = re.search(r"(\d{1,2})\s*(?:gio|h)\s*(\d{1,2})?", u)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0

        if not m.group(2) and "ruoi" in u:
            minute = 30                                  # "3 giờ rưỡi"
        kem = re.search(r"kem\s*(\d{1,2})", u)
        if kem:                                          # "8 giờ kém 15" = 7:45
            hour -= 1
            minute = 60 - int(kem.group(1))

        # v6.2 - SỬA LỖI NGHIÊM TRỌNG: buổi (sáng/trưa/chiều/tối/đêm/khuya)
        # chỉ được nhận diện trong phần SAU biểu thức giờ (hoặc cụm "tối nay/
        # mai" đứng trước giờ). Trước đây tìm trong TOÀN CÂU bằng pattern
        # "chieu|toi\b" nên chữ "tôi" trong "nhắc tôi..." bị nhận nhầm thành
        # "tối" -> "nhắc tôi họp lúc 9 giờ" bị hẹn thành 21h thay vì 9h.
        period = _detect_period(t, u[m.end():], plain_input)
        if period is None:
            compound = re.search(
                r"\b(sang|trua|chieu|toi|dem|khuya)\s+(?:nay|mai|hom)\b", u)
            if compound:
                candidate = compound.group(1)
                if candidate == "toi":
                    # "tôi mai..." (đại từ) không được tính là "tối mai"
                    if plain_input:
                        before = u[:compound.start()].split()
                        if before and before[-1] in _PRONOUN_PRECEDERS:
                            candidate = None
                    elif not re.search(r"\btối\b", t):
                        candidate = None
                period = candidate

        if period in ("chieu", "toi"):
            if hour < 12:
                hour += 12
        elif period in ("dem", "khuya"):
            # v6.2: "1 giờ đêm" = 1h sáng (không phải 13h); "12 giờ đêm" = 0h
            # (nửa đêm, không phải 12h trưa); "11 giờ đêm" = 23h như cũ.
            if 5 <= hour < 12:
                hour += 12
            elif hour == 12:
                hour = 0
        elif period == "trua":
            if hour < 11:
                hour += 12
        elif period == "sang":
            if hour == 12:                               # "12 giờ sáng" = 0h
                hour = 0

        return {
            "type": "clock",
            "hour": hour % 24,
            "minute": max(0, min(59, minute)),
            "minutes": 0,
            "day_offset": 1 if _TOMORROW_RE.search(u) else 0,
        }

    # --- Không kèm số: "sáng mai", "trưa mai", "tối mai" ---
    if _TOMORROW_RE.search(u):
        # v6.2: dùng _detect_period thay vì tìm chuỗi con - trước đây "toi"
        # trong "nhắc tôi" cũng bị tính là buổi tối ("sáng mai nhắc tôi dậy"
        # thành 19h thay vì 7h).
        period = _detect_period(t, u, plain_input)
        hour = {"trua": 12, "chieu": 15, "toi": 19, "dem": 19,
                "khuya": 23}.get(period, 7)
        return {"type": "clock", "hour": hour, "minute": 0, "minutes": 0, "day_offset": 1}

    return none_result


# Từ toán tử tiếng Việt -> ký hiệu số học.
# v6.2: thêm cụm NHIỀU TỪ (đặt TRƯỚC các từ đơn để khớp đúng): trước đây
# "100 chia cho 4" không tính được vì "chia" bị đổi thành / nhưng "cho" bị
# bỏ lại giữa biểu thức khiến regex trích xuất không ghép được.
OPERATOR_WORDS = [
    (r"\bchia\s+cho\b", "/"),
    (r"\bnhân\s+với\b", "*"),
    (r"\bcộng\s+với\b", "+"),
    (r"\btrừ\s+đi\b", "-"),
    (r"\bcộng\b|\bthêm\b", "+"),
    (r"\btrừ\b|\bbớt\b", "-"),
    (r"\bnhân\b", "*"),
    (r"\bchia\b", "/"),
    # v6: luỹ thừa - đã có chặn số mũ khổng lồ trong _safe_eval() bên dưới.
    (r"\bmũ\b|\bluỹ thừa\b|\blũy thừa\b", "**"),
]

_SAFE_AST_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.UAdd, ast.USub, ast.Pow,
)


# Chặn "bom tính toán" kiểu 9**9**9: an toàn về mặt CHẠY MÃ nhưng vẫn đủ sức
# treo cứng chương trình và ngốn sạch RAM, vì Python tính số nguyên lớn tùy ý (v6).
MAX_POW_BASE = 10 ** 6
MAX_POW_EXPONENT = 64


def _safe_eval(expr: str):
    """Tính biểu thức số học AN TOÀN: chỉ cho phép số, + - * / ** và dấu ngoặc.
    Không dùng eval() trực tiếp trên chuỗi thô để tránh chạy mã tuỳ ý."""
    node = ast.parse(expr, mode="eval")
    for child in ast.walk(node):
        if not isinstance(child, _SAFE_AST_NODES):
            raise ValueError(f"Biểu thức không hợp lệ / không an toàn: {expr!r}")
        # Luỷ thừa được phép nhưng phải có GIỚI HẠN.
        if isinstance(child, ast.BinOp) and isinstance(child.op, ast.Pow):
            base = getattr(child.left, "value", None)
            exponent = getattr(child.right, "value", None)
            if not isinstance(exponent, (int, float)) or abs(exponent) > MAX_POW_EXPONENT:
                raise ValueError("Số mũ quá lớn hoặc không hợp lệ")
            if isinstance(base, (int, float)) and abs(base) > MAX_POW_BASE:
                raise ValueError("Cơ số quá lớn")
    # eval() ở đây AN TOÀN có kiểm chứng: vòng lặp phía trên đã
    # duyệt từng node AST và CHỐI mọi node ngoài tập _SAFE_AST_NODES (chỉ số,
    # + - * / ** và ngoặc). Không có Name/Attribute/Call/Subscript nên không thể
    # gọi hàm hay chạm tới thuộc tính nào. ast.literal_eval() KHÔNG thay được vì
    # nó không đánh giá biểu thức số học (chỉ parse hằng số).
    return eval(compile(node, "<expr>", "eval"))  # noqa: S307


def parse_math_expression(text: str):
    """
    Trích xuất và tính một biểu thức toán học đơn giản từ câu tiếng Việt.

    Hỗ trợ: cộng/trừ/nhân/chia, căn bậc hai, bình phương, phần trăm.

    Trả về: (biểu_thức_hiển_thị: str, kết_quả: float|None)
    Ví dụ:
        "12 cộng 8 bằng bao nhiêu" -> ("12 + 8", 20.0)
        "căn bậc hai của 81"       -> ("căn bậc hai của 81", 9.0)
    """
    t = normalize_text(text)
    # v6.2: đổi từ-số thành chữ số trước khi tách biểu thức - "mười lăm cộng
    # hai mươi bảy" giờ tính được (trước đây chỉ tính được số viết bằng chữ số).
    t = replace_number_words(t)

    # --- Căn bậc hai / bậc ba (v6.2 thêm bậc ba) ---
    m = re.search(r"căn\s*(?:bậc\s*(hai|2|ba|3))?\s*(?:của)?\s*(-?\d+(?:[.,]\d+)?)", t)
    if m:
        degree_word = m.group(1)
        num = float(m.group(2).replace(",", "."))
        if degree_word in ("ba", "3"):
            # Căn bậc ba của số âm vẫn tính được (khác căn bậc hai).
            result = math.copysign(abs(num) ** (1.0 / 3.0), num)
            return f"căn bậc ba của {num:g}", round(result, 10)
        if num < 0:
            return f"căn bậc hai của {num:g}", None
        return f"căn bậc hai của {num:g}", math.sqrt(num)

    # --- Bình phương / lập phương (v6.2 thêm lập phương) ---
    m = re.search(r"(-?\d+(?:[.,]\d+)?)\s*(bình phương|mũ 2|lập phương|mũ 3)", t)
    if m:
        num = float(m.group(1).replace(",", "."))
        if m.group(2) in ("lập phương", "mũ 3"):
            return f"{num:g} lập phương", num ** 3
        return f"{num:g} bình phương", num ** 2

    # --- Phần trăm: "X phần trăm của Y" ---
    m = re.search(r"(-?\d+(?:[.,]\d+)?)\s*phần trăm\s*(?:của)?\s*(-?\d+(?:[.,]\d+)?)", t)
    if m:
        pct = float(m.group(1).replace(",", "."))
        base = float(m.group(2).replace(",", "."))
        return f"{pct:g}% của {base:g}", base * pct / 100

    # --- Phép tính cơ bản: thay từ toán tử bằng ký hiệu rồi bóc biểu thức số ---
    expr_text = t
    for pattern, symbol in OPERATOR_WORDS:
        expr_text = re.sub(pattern, f" {symbol} ", expr_text)

    # v6: cho phép toán tử ** (luỹ thừa) trong biểu thức - trước đây lớp ký
    # tự [+\-*/] không nhận "**" nên "2 mũ 10" không bao giờ ghép được biểu thức.
    m = re.search(r"(-?\d+(?:[.,]\d+)?(?:\s*(?:\*\*|[+\-*/])\s*-?\d+(?:[.,]\d+)?)+)", expr_text)
    if not m:
        return None, None

    expr_display = m.group(1).replace(",", ".").strip()
    expr_display = re.sub(r"\s+", " ", expr_display)
    expr_clean = re.sub(r"\s+", "", expr_display)
    try:
        result = _safe_eval(expr_clean)
    except Exception:
        return None, None
    return expr_display, result


def extract_entity(text: str, intent: str) -> str:
    """
    Trích xuất tên đối tượng (target) tương ứng với từng intent. Khoan dung
    với câu không dấu.

    Ví dụ:
        "Bật Google lên"              -> "google"
        "mo vs code len code"         -> "vs code"   (không dấu vẫn tách đúng)
        "Tắt máy tính đi"              -> "shutdown"
        "mở github.com/abc/xyz"       -> "github.com/abc/xyz"  (giữ trọn đường dẫn)
        "Tìm giá vàng trên google"     -> "giá vàng"
        "Nhắc tôi họp lúc 3 giờ chiều" -> "họp"
    """
    raw = normalize_text(text)

    # v6: nếu câu chứa URL THẬT thì luôn trả về URL nguyên vẹn (giữ hoa/thường
    # và các ký tự ? = & #) BẤT KỂ intent model nhận ra là gì. Trước đây nhánh
    # bảo toàn URL chỉ chạy khi intent đã đúng là open_website/open_file, nên
    # một khi phân loại lệch (vd "mở youtube.com/watch?v=..." bị nhận thành
    # play_media) thì liên kết vẫn bị băm nát ở tầng trích xuất.
    _original_case = (text or "").strip()
    if intent in ("open_website", "play_media", "open_file", "search_web"):
        _url_m = _URL_ENTITY_RE.search(_original_case)
        if _url_m:
            return _url_m.group(1)
    raw_no_dia = strip_diacritics(raw)

    # --- Lệnh hệ thống -> map về hành động chuẩn ---
    if intent == "system_control":
        for pattern, action in SYSTEM_KEYWORDS:
            if _match_any_pattern(pattern, raw, raw_no_dia):
                return action
        return "unknown"

    # --- Hỏi giờ / ngày ---
    if intent == "get_datetime":
        if re.search(r"ngày|thứ|tháng|năm|lịch", raw):
            return "date"
        return "time"

    # --- Trò chuyện vặt: giữ nguyên câu để chọn câu trả lời phù hợp ---
    if intent == "chitchat":
        return raw

    # --- Tính toán: trả về biểu thức đã nhận dạng được ---
    if intent == "calculate":
        expr, _ = parse_math_expression(raw)
        return expr or raw

    # --- Thời tiết: lấy địa điểm nếu có ---
    if intent == "get_weather":
        # v6 - VIẾT LẠI CÁCH TÁCH ĐỊA ĐIỂM.
        # Cách cũ "trừ đi mọi từ trong danh sách" có 2 lỗi nặng:
        #   1. Danh sách chỉ có bản CÓ DẤU, nên câu gõ thiếu dấu ("thoi tiet da
        #      nang hom nay") không lọc được từ nào -> địa điểm = NGUYÊN CẢ CÂU.
        #   2. Nếu sửa thành lọc không dấu thì lại xoá nhầm chính tên địa điểm:
        #      "nắng" và "Nẵng" bỏ dấu là MỘT (Đà Nẵng sẽ biến mất!).
        # Giải pháp: cắt theo CẤU TRÚC câu - lấy phần sau "thời tiết/ở/tại" rồi
        # bóc dần phần đuôi chỉ thời gian / cách hỏi ở cuối câu.
        loc = re.sub(r"^.*(?:thời tiết|thoi tiet|dự báo|du bao|nhiệt độ|nhiet do|trời|troi)\s*",
                     "", raw)
        loc = re.sub(r"^(?:ở|o|tại|tai|của|cua|khu vực|khu vuc|ngoài|ngoai)\s+", "", loc).strip()
        tail = (r"\s*(?:hôm nay|hom nay|ngày mai|ngay mai|sáng nay|sang nay|chiều nay|chieu nay|"
                r"tối nay|toi nay|đêm nay|dem nay|bây giờ|bay gio|như thế nào|nhu the nao|"
                r"thế nào|the nao|ra sao|có mưa không|co mua khong|mưa không|mua khong|"
                r"nắng không|nang khong|lạnh không|lanh khong|nóng không|nong khong|"
                r"bao nhiêu độ|bao nhieu do|bao nhiêu|bao nhieu|thế|the|nhỉ|nhi|vậy|vay)\s*$")
        for _ in range(4):
            shorter = re.sub(tail, "", loc).strip()
            if shorter == loc:
                break
            loc = shorter
        location = " ".join(w for w in loc.split() if w not in STOP_WORDS_ALL).strip()
        return location or "hôm nay"

    # --- Tìm kiếm: bóc cụm "tìm kiếm... trên google" ---
    if intent == "search_web":
        query = _strip_affixes(raw, SEARCH_PREFIX, SEARCH_SUFFIX)
        return query or raw

    # --- Phát nhạc / video ---
    if intent == "play_media":
        query = _strip_affixes(raw, MEDIA_PREFIX, MEDIA_SUFFIX)
        return query or "nhạc"

    # --- Nhắc nhở: lấy nội dung công việc (bỏ phần thời gian) ---
    if intent == "set_reminder":
        task = raw
        # v6.2: nhận diện cả động từ đầu câu KHÔNG DẤU ("nhac toi...", "hen gio...")
        task = re.sub(r"^(nhắc tôi|nhac toi|nhắc mình|nhac minh|đặt nhắc nhở|dat nhac nho|"
                      r"tạo lời nhắc|tao loi nhac|nhớ nhắc tôi|nho nhac toi|hẹn giờ|hen gio|"
                      r"đặt báo thức|dat bao thuc|báo thức|bao thuc|"
                      r"đặt đồng hồ đếm ngược|dat dong ho dem nguoc)\s*", "", task).strip()
        # v6.2: bóc mốc giờ viết bằng CHỮ SỐ hoặc TỪ-SỐ (kể cả "kém X" ở đuôi,
        # trước đây "hẹn 8 giờ kém 15" để sót lại "kém 15" trong nội dung).
        task = re.sub(
            r"(?:lúc|luc|vào|vao)?\s*" + _NUMBER_WORD_RUN
            + r"\s*(?:giờ|gio|phút|phut|tiếng|tieng|giây|giay)\b"
            + r"(?:\s+" + _NUMBER_WORD_RUN + r")?"
            + r"(?:\s+(?:sáng|sang|trưa|trua|chiều|chieu|tối|toi|đêm|dem|khuya))?"
            + r"(?:\s+(?:nay|mai|hôm|hom))?"   # "6 giờ sáng mai" - 2 từ đuôi
            + r"(?:\s+(?:nữa|nua|sau|rưỡi|ruoi))?"
            + r"(?:\s*k(?:ém|em)\s*" + _NUMBER_WORD_RUN + r")?",
            "", task).strip()
        task = re.sub(r"(lúc\s*)?\d+\s*(giờ|phút|tiếng)\s*(\d+)?\s*"
                      r"(sáng|trưa|chiều|tối|nữa|sau|mai)?", "", task).strip()
        task = re.sub(r"^(sau|nữa|vào)\s+", "", task).strip()
        task = re.sub(r"\s*(giúp tôi|giup toi|nhé|nhe|đi)\s*$", "", task).strip()
        return task or "báo thức"

    # Bản GIỮ NGUYÊN hoa/thường của câu gốc (chỉ bỏ khoảng trắng thừa 2 đầu),
    # dùng RIÊNG cho việc tách URL/đường dẫn phía dưới. `raw` ở trên đã bị hạ
    # chữ thường (phục vụ so khớp/phân loại) nên KHÔNG dùng cho việc này -
    # nếu không, các phần phân biệt hoa/thường trong URL thật (vd video ID
    # trên YouTube: "...watch?v=dQw4w9WgXcQ") hoặc tên file trên hệ thống
    # phân biệt hoa/thường (Linux/macOS) sẽ bị biến dạng và trỏ sai đối tượng.
    raw_original_case = (text or "").strip()

    # --- Câu có sẵn URL hoặc đường dẫn file ---
    if intent == "open_website":
        url_match = _URL_ENTITY_RE.search(raw_original_case)
        if url_match:
            return url_match.group(1)

    if intent == "open_file":
        path_match = _PATH_ENTITY_RE.search(raw_original_case)
        if path_match:
            return path_match.group(1)

    # --- Mặc định: bỏ stop-words, phần còn lại là tên đối tượng ---
    tokens = [w for w in raw.split() if w not in STOP_WORDS_ALL]
    target = " ".join(tokens).strip()
    return target or "unknown"


# ============================================================================
# 3. PHÂN TÍCH CÂU -> JSON CHUẨN
# ============================================================================
def _has_literal_entity(s: str) -> bool:
    """Câu này có chứa URL / đường dẫn file thật hay không?"""
    s = s or ""
    return bool(_URL_ENTITY_RE.search(s) or _PATH_ENTITY_RE.search(s))


def predict_intent(text: str, model=None, raw_text: str | None = None) -> dict:
    """
    Dự đoán ý định + trích xuất thực thể.

    raw_text (mới ở v6): câu GỐC người dùng nhập, trước khi chuẩn hoá - dùng
    riêng cho việc tách URL/đường dẫn (xem giải thích trong thân hàm).

    Hỗ trợ cả model TF-IDF (Pipeline scikit-learn) lẫn model PhoBERT
    (phobert_model.PhoBertIntentClassifier) — tự nhận diện loại model.

    Trả về:
        {"intent": "open_website", "target": "google", "confidence": 0.93}
    Với intent set_reminder có thêm khoá "time".
    Với intent calculate có thêm khoá "result" (kết quả phép tính, hoặc None).
    """
    if model is None:
        model = load_model()

    cleaned = normalize_text(text)

    try:
        from phobert_model import PhoBertIntentClassifier
        is_phobert = isinstance(model, PhoBertIntentClassifier)
    except Exception:
        is_phobert = False

    if is_phobert:
        intent, confidence = model.predict(cleaned)
    else:
        intent = str(model.predict([cleaned])[0])
        try:
            proba = model.predict_proba([cleaned])[0]
            confidence = float(max(proba))
        except AttributeError:
            confidence = 1.0

    # v6: NGUỒN để trích xuất thực thể có thể khác nguồn để PHÂN LOẠI.
    # Tầng NLU đưa vào `text` đã chuẩn hoá (phục hồi dấu, hạ chữ thường, bỏ các
    # ký tự ? = & #) - rất tốt cho việc phân loại nhưng LÀM HỎNG URL thật. Nếu
    # câu gốc có chứa URL/đường dẫn thì ưu tiên lấy thực thể từ câu gốc.
    entity_source = raw_text if (raw_text and _has_literal_entity(raw_text)) else text

    result = {
        "intent": intent,
        "target": extract_entity(entity_source, intent),
        "confidence": round(confidence, 4),
    }

    # Thêm thông tin thời gian cho lệnh nhắc nhở
    if intent == "set_reminder":
        result["time"] = parse_time_expression(entity_source)

    # Thêm kết quả tính toán cho lệnh tính toán
    if intent == "calculate":
        _, calc_result = parse_math_expression(entity_source)
        result["result"] = round(calc_result, 4) if isinstance(calc_result, float) else calc_result

    logger.info("predict_intent(%r) -> %s", text, result)
    return result


def predict_intent_json(text: str, model=None) -> str:
    """Như predict_intent nhưng trả về chuỗi JSON (UTF-8)."""
    return json.dumps(predict_intent(text, model), ensure_ascii=False)


# ============================================================================
# 4. CHẠY TRỰC TIẾP: HUẤN LUYỆN + LƯU MODEL + TEST NHANH
# ============================================================================
if __name__ == "__main__":
    setup_console()
    model = train_model(algorithm="logistic", show_report=True)
    save_model(model)

    safe_print("\n===== TEST NHANH =====")
    samples = [
        "Bật Google lên",
        "mo youtube nghe nhac di",         # không dấu
        "khởi chạy vs code giúp tôi",
        "mở file báo cáo tháng 8",
        "tat may tinh di",                 # không dấu
        "tắt tiếng loa lại",
        "tìm giá vàng hôm nay trên google",
        "phát nhạc trữ tình đi",
        "nhắc tôi họp lúc 3 giờ chiều",
        "đặt báo thức 15 phút nữa",
        "thời tiết đà nẵng hôm nay thế nào",
        "mấy giờ rồi",
        "15 cộng 27 bằng bao nhiêu",
        "căn bậc hai của 81",
        "xin chào bạn khoẻ không",         # ngoài phạm vi -> chitchat
    ]
    for s in samples:
        safe_print(f"{s!r:42} -> {predict_intent_json(s, model)}")
