"""
intent_model.py v7.5
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
v7.5 nâng cấp:
- `_EntityContext.build()` ép kiểu MỘT LẦN ở đầu hàm: `predict_intent(123)` từng
  crash ở `(text or "").strip()` *sau khi* `normalize_text` đã xử lý tử tế - hai quy
  tắc khác nhau trong cùng một đường gọi. `replace_number_words()` cũng chịu được giá trị
  không phải chuỗi.

"""

# v7.4: Python 3.9 KHONG danh gia duoc `dict | None`/`str | None` trong chur ky ham
# (PEP 604 can 3.10). File dung annotation kieu nay ma thieu dong nay thi lenh
# `import intent_model` chet bang TypeError tren 3.9 - xem
# tests/test_v74_py39_compat.py de khong ai quen lai.
from __future__ import annotations

import ast
import json
import logging
import math
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:                      # chi can cho type checker (xem ruff TC003)
    from collections.abc import Callable

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
from paths import data_path
from platform_utils import safe_print, setup_console
from text_utils import as_text, normalize_text, strip_diacritics

logger = logging.getLogger(__name__)

# v7.3: model đã huấn luyện nằm trong thư mục dữ liệu người dùng (paths.py) -
# trước đây nó bị ghi vào site-packages (read-only trên máy cài cho cả hệ thống)
# và bị xoá sạch mỗi lần `pip install -U`.
MODEL_PATH = str(data_path("intent_model.pkl"))


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
_NUMBER_DIGITS_PLAIN: dict[str, int] = {}
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


# Bảng phân loại các từ-số KHÔNG phải chữ số, dạng CÓ DẤU. Dựng từ chính các
# tập từ ở trên nên thêm/bớt từ chỉ cần sửa MỘT chỗ (bản cũ lặp lại danh sách
# từ trong 7 nhánh if/elif, dễ lệch giữa 2 bản có dấu/không dấu).
_NUMBER_KINDS_ACCENTED: dict[str, tuple] = {}
for _w in _NUMBER_TENS_WORDS:
    _NUMBER_KINDS_ACCENTED[_w] = ("tens", None)
_NUMBER_KINDS_ACCENTED[_NUMBER_TEN_WORD] = ("ten", None)
_NUMBER_KINDS_ACCENTED[_NUMBER_HUNDRED_WORD] = ("hundred", None)
for _w, _v in _NUMBER_SCALE_WORDS.items():
    _NUMBER_KINDS_ACCENTED[_w] = ("scale", _v)
for _w in _NUMBER_ZERO_WORDS:
    _NUMBER_KINDS_ACCENTED[_w] = ("zero", None)
_NUMBER_KINDS_ACCENTED[_NUMBER_DECIMAL_WORD] = ("decimal", None)

# Bảng cho token HOÀN TOÀN KHÔNG DẤU. "muoi" có loại riêng (ten_or_tens) vì nó
# vừa là "mười" (10) vừa là "mươi" (x10) - tuỳ từ đứng trước.
_NUMBER_KINDS_PLAIN: dict[str, tuple] = {
    "muoi": ("ten_or_tens", None),
    "chuc": ("tens", None),
    "tram": ("hundred", None),
    "nghin": ("scale", 1000),
    "ngan": ("scale", 1000),
    "trieu": ("scale", 10 ** 6),
    "ty": ("scale", 10 ** 9),
    "ti": ("scale", 10 ** 9),
    "le": ("zero", None),
    "linh": ("zero", None),
    "phay": ("decimal", None),
}


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
    # Từ CÓ DẤU tra bảng có dấu trước; chỉ token hoàn toàn không dấu mới tra
    # bảng không dấu - để "tâm" KHÔNG bị đọc thành "tám".
    kind = _NUMBER_KINDS_ACCENTED.get(token)
    if kind is not None:
        return kind
    if strip_diacritics(token) == token:
        return _NUMBER_KINDS_PLAIN.get(token)
    return None


def _classify_number_run(tokens, prev_token):
    """Chuyển danh sách token thành danh sách (loại, giá trị); None nếu có từ lạ."""
    kinds = []
    prev = prev_token
    for token in tokens:
        kind = _classify_number_token(token, prev)
        if kind is None:
            return None
        kinds.append(kind)
        prev = token
    return kinds


# --- Máy đọc cụm từ-số: mỗi loại từ có MỘT quy tắc nhỏ, đăng ký trong bảng ---
# (Bản v6 là chuỗi if/elif 7 nhánh lồng 4 lớp guard trong cùng một hàm - thêm
# một cách nói tiếng Việt là phải chen thêm if vào giữa, rất dễ sai sót.)
_RUN_INVALID = object()      # sentinel: handler báo cụm từ-số không hợp lệ


def _run_state() -> dict:
    return {"total": 0, "current": 0, "last_digit": None, "seen": False}


def _run_digit(state: dict, value: int):
    """Chữ số đứng một mình. "hai ba" (2 chữ số cạnh nhau) là cụm không hợp lệ."""
    if state["last_digit"] is not None:
        return _RUN_INVALID
    state["current"] += value
    state["last_digit"] = value
    state["seen"] = True
    return None


def _run_ten(state: dict, _value=None):
    """"mười": chỉ đứng một đầu được ("hai mười" không dùng -> từ chối cho chắc)."""
    if state["last_digit"] is not None:
        return _RUN_INVALID
    state["current"] += 10
    state["seen"] = True
    return None


def _run_tens(state: dict, _value=None):
    """"mươi"/"chục"/"muoi": nhân chữ số đứng trước lên 10.

    Lưu ý: "muoi" không dấu (ten_or_tens) xử lý GIỐNG HỆT "mươi" - đứng sau chữ
    số thì là "mươi" (hai muoi = 20), đứng một mình thì là "mười" (muoi lam =
    15); cả hai đều là quy tắc "có chữ số trước thì nhân, không thì +10".
    """
    last = state["last_digit"]
    if last is not None:
        state["current"] = state["current"] - last + last * 10
        state["last_digit"] = None      # "mươi" đã tiêu thụ chữ số đứng trước
    else:
        state["current"] += 10
    state["seen"] = True
    return None


def _run_hundred(state: dict, _value=None):
    """"trăm": một trăm = 100, hai trăm = 200 (nhân chữ số trước lên 100)."""
    last = state["last_digit"]
    if last is not None:
        state["current"] = state["current"] - last + last * 100
        state["last_digit"] = None
    else:
        state["current"] += 100
    state["seen"] = True
    return None


def _run_scale(state: dict, value):
    """"nghìn/triệu/tỷ": chốt nhóm hiện tại rồi nhân lên đơn vị lớn."""
    group = state["current"] if (state["current"] or state["last_digit"] is not None) else 1
    state["total"] += group * value
    state["current"] = 0
    state["last_digit"] = None
    state["seen"] = True
    return None


def _run_zero(state: dict, _value=None):
    """"lẻ/linh": chữ số đứng SAU cộng thẳng vào (một trăm lẻ năm = 105).

    Không đánh dấu `seen`: bản cũ cũng không - "lẻ" một mình không phải số.
    """
    state["last_digit"] = None
    return None


# Bảng quy tắc nhận số: mỗi hàm nhận (state, value), trả về số nguyên hoặc
# _RUN_INVALID. Kiểu ghi rõ ở đây để "gọi một object" không còn là lỗi ẩn -
# bảng này do v7.2 tách ra từ 30 nhánh if/elif nên hợp đồng phải nằm ở kiểu.
_NUMBER_RUN_RULES: dict[str, Callable[..., object]] = {
    "digit": _run_digit,
    "ten": _run_ten,
    "tens": _run_tens,
    "ten_or_tens": _run_tens,   # "muoi" không dấu - xem _run_tens
    "hundred": _run_hundred,
    "scale": _run_scale,
    "zero": _run_zero,
}


def _run_integer_value(kinds) -> int | None:
    """Tổng phần NGUYÊN của cụm từ-số (không có "phẩy"), hoặc None nếu không hợp lệ.

    0 là giá trị HỢP LỆ ("không"), nên hàm phân biệt rõ 0 với None.
    """
    state = _run_state()
    for kind, value in kinds:
        handler = _NUMBER_RUN_RULES.get(kind)
        if handler is None:               # "decimal" lọt vào đây = cụm bất thường
            return None
        if handler(state, value) is _RUN_INVALID:
            return None
    if not state["seen"]:
        return None
    return int(state["total"]) + int(state["current"])


def _run_fraction_value(kinds):
    """Giá trị phần THẬP PHÂN sau "phẩy" (0.x), hoặc None nếu cụm không hợp lệ."""
    digits = []
    for kind, value in kinds:
        if kind == "digit":
            digits.append(str(value))
        elif kind == "ten":
            digits.extend(("1", "0"))       # "hai phẩy mười" = 2.10
        elif kind == "zero":
            digits.append("0")
        else:
            return None                       # "trăm"/"nghìn" sau phẩy -> vô nghĩa
    if not digits:
        return None                           # "hai phẩy" cụt
    return int("".join(digits)) / float(10 ** len(digits))


def _parse_number_run(tokens, prev_token):
    """Đọc 1 cụm từ-số -> int/float. Trả về None nếu cụm không hợp lệ (caller
    sẽ giữ nguyên văn cụm đó, không thay thế bừa).

    v7.2: tách từ một hàm 25 nhánh thành bảng quy tắc + 3 hàm nhỏ (phần nguyên /
    phần thập phân / ráp lại) để từng quy tắc tiếng Việt đọc và test được riêng.
    """
    kinds = _classify_number_run(tokens, prev_token)
    if kinds is None:
        return None

    dot = next((i for i, (kind, _) in enumerate(kinds) if kind == "decimal"), None)
    if dot is None:
        whole, fraction = _run_integer_value(kinds), None
    else:
        # "phẩy" xuất hiện 2 lần ("hai phẩy ba phẩy tư") là cụm không hợp lệ
        if any(kind == "decimal" for kind, _ in kinds[dot + 1:]):
            return None
        whole = _run_integer_value(kinds[:dot])
        fraction = _run_fraction_value(kinds[dot + 1:])
        if whole is None or fraction is None:
            return None

    result = whole if fraction is None else whole + fraction
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

    v7.5: nhận được cả giá trị không phải chuỗi (xem `text_utils.as_text`) vì
    hàm này được gọi trực tiếp từ `parse_time_expression`/`parse_math_expression`,
    tức từ mọi nơi dùng hai hàm đó như tài liệu hướng dẫn.
    """
    text = as_text(text)
    tokens = text.split()
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


def _result(**kwargs) -> dict:
    """Kết quả parse_time_expression - LUÔN đủ khoá (v6) với giá trị mặc định 0."""
    base = {"type": None, "minutes": 0, "hour": 0, "minute": 0, "day_offset": 0}
    base.update(kwargs)
    return base


def _parse_half_hour(t: str, u: str, plain_input: bool) -> dict | None:
    """"nửa tiếng / nửa giờ (nữa)" = 30 phút (v6.2).

    "nửa" và "nữa" bỏ dấu đều là "nua": câu CÓ DẤU bắt buộc khớp đúng "nửa";
    chỉ câu hoàn toàn không dấu mới khớp "nua tieng/gio".
    """
    if re.search(r"\bnửa\s+(?:tiếng|giờ)\b", t) or (
            plain_input and re.search(r"\bnua\s+(?:tieng|gio)\b", u)):
        return _result(type="delay", minutes=30)
    return None


def _delay_minutes(durations, u: str) -> float:
    """Cộng dồn các mốc "X giây / phút / giờ" thành số phút (kể cả "rưỡi")."""
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
    if any(dur.group(2) in ("tieng", "gio") for dur in durations) and re.search(r"\bruoi\b", u):
        minutes += 30
    return minutes


def _parse_delay(t: str, u: str, plain_input: bool) -> dict | None:
    """Dạng đếm ngược: "sau/nữa X giây / phút / tiếng" (v6.2 viết lại)."""
    durations = list(_DURATION_RE.finditer(u))
    if not durations:
        return None
    # Dấu hiệu khoảng thời gian: kiểm tra trên bản CÓ DẤU khi có thể -
    # tránh nhầm tên riêng "Sáu" (bỏ dấu -> "sau") với từ nối "sau".
    if plain_input:
        has_marker = bool(_DELAY_MARKER_PLAIN_RE.search(u))
    else:
        has_marker = bool(_DELAY_MARKER_ACCENTED_RE.search(t))
    preceded_by_luc = bool(re.search(r"(?:lúc|luc)\s*$", u[: durations[0].start()]))
    only_small_units = all(m.group(2) in ("phut", "giay") for m in durations)
    # "lúc 3 giờ" / "3 giờ" trần là GIỜ ĐỒNG HỒ, không phải khoảng chờ;
    # "5 phút" trần (vd "đặt hẹn giờ 5 phút") hiểu là đếm ngược (v6.2).
    if not (has_marker or (only_small_units and not preceded_by_luc)):
        return None
    return _result(type="delay", minutes=round(_delay_minutes(durations, u), 4))


# Bảng quy tắc đổi giờ 12-hour -> 24-hour theo BUỔI, thay cho chuỗi if/elif lồng
# nhau (bản cũ 11 nhánh trong một hàm; thêm một cách nói buổi là phải chen elif).
def _shift_afternoon(hour: int) -> int:
    """"chiều"/"tối": 1..11 -> +12 (chiều 3h = 15h, tối 7h = 19h)."""
    return hour + 12 if hour < 12 else hour


def _shift_night(hour: int) -> int:
    """"đêm"/"khuya".

    v6.2: "1 giờ đêm" vẫn là 1h (chưa ngủ), "11 giờ đêm" = 23h, còn
    "12 giờ đêm" = nửa đêm = 0h - trước đây cả hai câu đầu bị đổi thành 13h.
    """
    if 5 <= hour < 12:
        return hour + 12
    if hour == 12:
        return 0
    return hour


def _shift_noon(hour: int) -> int:
    """"trưa": 1..10 -> +12; 11 và 12 giữ nguyên ("11 giờ trưa" = 11h)."""
    return hour + 12 if hour < 11 else hour


def _shift_morning(hour: int) -> int:
    """"sáng": "12 giờ sáng" = 0h, còn giữa giữ nguyên ("sáng 7h" = 7h)."""
    return 0 if hour == 12 else hour


_PERIOD_SHIFTERS: dict[str, Callable[[int], int]] = {
    "chieu": _shift_afternoon, "toi": _shift_afternoon,
    "dem": _shift_night, "khuya": _shift_night,
    "trua": _shift_noon, "sang": _shift_morning,
}


def _apply_period(hour: int, minute: int, period: str | None) -> tuple[int, int]:
    """Quy đổi (giờ, phút) theo buổi; chốt giờ trong 0-23 và phút trong 0-59.

    v7.2: chuyển từ 4 cặp if/elif so chuỗi sang BẢNG TRA buổi -> hàm quy tắc,
    mỗi quy tắc là một hàm 1 dòng dễ đọc/dễ test riêng.
    """
    shifter = _PERIOD_SHIFTERS.get(period) if period else None
    if shifter is not None:
        hour = shifter(hour)
    return hour % 24, max(0, min(59, minute))


def _find_period_around_time(t: str, u: str, plain_input: bool, time_end: int) -> str | None:
    """Tìm buổi (sáng/trưa/chiều/tối/đêm/khuya) liên quan tới mốc giờ.

    v6.2 - SỬA LỖI NGHIÊM TRỌNG: buổi chỉ được nhận diện trong phần SAU biểu
    thức giờ (hoặc cụm "tối nay/mai" đứng trước giờ). Trước đây tìm trong TOÀN
    CÂU bằng pattern "chieu|toi\\b" nên chữ "tôi" trong "nhắc tôi..." bị nhận
    nhầm thành "tối" -> "nhắc tôi họp lúc 9 giờ" bị hẹn thành 21h thay vì 9h.
    """
    period = _detect_period(t, u[time_end:], plain_input)
    if period is not None:
        return str(period)
    compound = re.search(r"\b(sang|trua|chieu|toi|dem|khuya)\s+(?:nay|mai|hom)\b", u)
    if not compound:
        return None
    candidate = compound.group(1)
    if candidate == "toi":
        # "tôi mai..." (đại từ) không được tính là "tối mai"
        if plain_input:
            before = u[: compound.start()].split()
            if before and before[-1] in _PRONOUN_PRECEDERS:
                return None
        elif not re.search(r"\btối\b", t):
            return None
    return candidate


def _parse_clock(t: str, u: str, plain_input: bool) -> dict | None:
    """Dạng giờ cụ thể: "lúc X giờ [Y] [sáng/chiều]", "3h30", "3 giờ rưỡi"."""
    m = re.search(r"(\d{1,2})\s*(?:gio|h)\s*(\d{1,2})?", u)
    if not m:
        return None
    hour = int(m.group(1))
    has_minute_group = m.group(2) is not None
    minute = int(m.group(2)) if has_minute_group else 0
    # "3 giờ rưỡi" -> 3:30. Chỉ áp khi KHÔNG có phút tường minh, để "3 giờ 00"
    # không bị chữ "rưỡi" lạc chỗ nào đó trong câu làm đổi thành 3:30.
    if not has_minute_group and "ruoi" in u:
        minute = 30
    kem = re.search(r"kem\s*(\d{1,2})", u)
    if kem:                                          # "8 giờ kém 15" = 7:45
        hour -= 1
        minute = 60 - int(kem.group(1))
    period = _find_period_around_time(t, u, plain_input, m.end())
    hour, minute = _apply_period(hour, minute, period)
    return _result(
        type="clock",
        hour=hour,
        minute=minute,
        day_offset=1 if _TOMORROW_RE.search(u) else 0,
    )


def _parse_tomorrow_only(t: str, u: str, plain_input: bool) -> dict | None:
    """Không kèm số giờ: chỉ "sáng mai", "trưa mai", "tối mai"..."""
    if not _TOMORROW_RE.search(u):
        return None
    # v6.2: dùng _detect_period thay vì tìm chuỗi con - trước đây "toi"
    # trong "nhắc tôi" cũng bị tính là buổi tối ("sáng mai nhắc tôi dậy"
    # thành 19h thay vì 7h).
    hour_by_period = {"trua": 12, "chieu": 15, "toi": 19, "dem": 19, "khuya": 23}
    return _result(type="clock", hour=hour_by_period.get(_detect_period(t, u, plain_input), 7),
                   day_offset=1)


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

    v7.2: thân hàm được tách thành 4 máy phân tích nhỏ (nửa tiếng / đếm ngược /
    giờ đồng hồ / chỉ buổi) - trước đây một hàm 28 nhánh, thêm một cách nói là
    phải chen if/elif vào giữa đống logic đã có.
    """
    t = normalize_text(text)
    # v6.2: đổi từ-số thành chữ số TRƯỚC ("bảy giờ sáng" -> "7 giờ sáng",
    # "tám giờ kém mười lăm" -> "8 giờ kém 15") để các regex bên dưới hiểu được.
    t = replace_number_words(t)
    u = strip_diacritics(t)   # so khớp trên bản không dấu để bao được cả 2 kiểu gõ
    plain_input = (t == u)    # người dùng gõ hoàn toàn không dấu

    return (
        _parse_half_hour(t, u, plain_input)
        or _parse_delay(t, u, plain_input)
        or _parse_clock(t, u, plain_input)
        or _parse_tomorrow_only(t, u, plain_input)
        or _result()
    )


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


# --- Cụm regex cho từng intent (biên dịch 1 lần, v7.2) ---
# Trước đây các pattern này nằm CHÊNH VẾNH trong extract_entity() và được truyền
# dưới dạng CHUỖI cho re.sub() -> mỗi câu nói lại phải tra cache biên dịch.
_WEATHER_HEAD_RE = re.compile(
    r"^.*(?:thời tiết|thoi tiet|dự báo|du bao|nhiệt độ|nhiet do|trời|troi)\s*"
)
_WEATHER_LOC_PREFIX_RE = re.compile(
    r"^(?:ở|o|tại|tai|của|cua|khu vực|khu vuc|ngoài|ngoai)\s+"
)
_WEATHER_TAIL_RE = re.compile(
    r"\s*(?:hôm nay|hom nay|ngày mai|ngay mai|sáng nay|sang nay|chiều nay|chieu nay|"
    r"tối nay|toi nay|đêm nay|dem nay|bây giờ|bay gio|như thế nào|nhu the nao|"
    r"thế nào|the nao|ra sao|có mưa không|co mua khong|mưa không|mua khong|"
    r"nắng không|nang khong|lạnh không|lanh khong|nóng không|nong khong|"
    r"bao nhiêu độ|bao nhieu do|bao nhiêu|bao nhieu|thế|the|nhỉ|nhi|vậy|vay)\s*$"
)
_REMINDER_LEAD_RE = re.compile(
    r"^(nhắc tôi|nhac toi|nhắc mình|nhac minh|đặt nhắc nhở|dat nhac nho|"
    r"tạo lời nhắc|tao loi nhac|nhớ nhắc tôi|nho nhac toi|hẹn giờ|hen gio|"
    r"đặt báo thức|dat bao thuc|báo thức|bao thuc|"
    r"đặt đồng hồ đếm ngược|dat dong ho dem nguoc)\s*"
)
_REMINDER_TIME_RE = re.compile(
    r"(?:lúc|luc|vào|vao)?\s*" + _NUMBER_WORD_RUN
    + r"\s*(?:giờ|gio|phút|phut|tiếng|tieng|giây|giay)\b"
    + r"(?:\s+" + _NUMBER_WORD_RUN + r")?"
    + r"(?:\s+(?:sáng|sang|trưa|trua|chiều|chieu|tối|toi|đêm|dem|khuya))?"
    r"(?:\s+(?:nay|mai|hôm|hom))?"      # "6 giờ sáng mai" - 2 từ đuôi
    r"(?:\s+(?:nữa|nua|sau|rưỡi|ruoi))?"
    r"(?:\s*k(?:ém|em)\s*" + _NUMBER_WORD_RUN + r")?"
)
_REMINDER_TIME_DIGIT_RE = re.compile(
    r"(lúc\s*)?\d+\s*(giờ|phút|tiếng)\s*(\d+)?\s*"
    r"(sáng|trưa|chiều|tối|nữa|sau|mai)?"
)
_REMINDER_TAIL_RES = (
    re.compile(r"^(sau|nữa|vào)\s+"),
    re.compile(r"\s*(giúp tôi|giup toi|nhé|nhe|đi)\s*$"),
)
_DATE_WORDS_RE = re.compile(r"ngày|thứ|tháng|năm|lịch")


def _weather_location(raw: str) -> str:
    """Tách ĐỊA ĐIỂM từ câu hỏi thời tiết (v6 - viết lại cách tách).

    Cách cũ "trừ đi mọi từ trong danh sách" có 2 lỗi nặng:
      1. Danh sách chỉ có bản CÓ DẤU, nên câu gõ thiếu dấu ("thoi tiet da
         nang hom nay") không lọc được từ nào -> địa điểm = NGUYÊN CẢ CÂU.
      2. Nếu sửa thành lọc không dấu thì lại xoá nhầm chính tên địa điểm:
         "nắng" và "Nẵng" bỏ dấu là MỘT (Đà Nẵng sẽ biến mất!).
    Giải pháp: cắt theo CẤU TRÚC câu - lấy phần sau "thời tiết/ở/tại" rồi bóc
    dần phần đuôi chỉ thời gian / cách hỏi ở cuối câu.
    """
    loc = _WEATHER_LOC_PREFIX_RE.sub("", _WEATHER_HEAD_RE.sub("", raw)).strip()
    # Bóc lặp tối đa 4 lần: "hôm nay" + "thế nào" + "nhỉ" xếp chồng ở cuối câu.
    for _ in range(4):
        shorter = _WEATHER_TAIL_RE.sub("", loc).strip()
        if shorter == loc:
            break
        loc = shorter
    location = " ".join(w for w in loc.split() if w not in STOP_WORDS_ALL).strip()
    return location or "hôm nay"


def _reminder_task(raw: str) -> str:
    """Nội dung công việc của lời nhắc, sau khi bỏ động từ đầu + mốc giờ."""
    task = _REMINDER_LEAD_RE.sub("", raw).strip()
    # v6.2: bóc mốc giờ viết bằng CHỮ SỐ hoặc TỪ-SỐ (kể cả "kém X" ở đuôi,
    # trước đây "hẹn 8 giờ kém 15" để sót lại "kém 15" trong nội dung).
    task = _REMINDER_TIME_RE.sub("", task).strip()
    task = _REMINDER_TIME_DIGIT_RE.sub("", task).strip()
    for pattern in _REMINDER_TAIL_RES:
        task = pattern.sub("", task).strip()
    return task or "báo thức"


def _system_action(raw: str, raw_no_dia: str) -> str:
    """system_control -> hành động chuẩn (shutdown/lock/volume_up...)."""
    for pattern, action in SYSTEM_KEYWORDS:
        if _match_any_pattern(pattern, raw, raw_no_dia):
            return action
    return "unknown"


@dataclass(frozen=True)
class _EntityContext:
    """Ba bản của cùng một câu, đưa vào các handler trích xuất thực thể.

    Tách thành đối tượng riêng để mỗi handler chỉ nhận ĐÚNG thứ nó cần và bảng
    dispatch không phải truyền 3 tham số theo vị trí.
    """
    raw: str                 # đã normalize (thường hoá) - dùng để so khớp
    raw_no_dia: str          # bản không dấu - cho câu gõ không dấu
    original: str            # GIỮ NGUYÊN hoa/thường - dùng cho URL / đường dẫn

    @classmethod
    def build(cls, text: str) -> _EntityContext:
        # v7.5: `text` co the KHONG phai chuoi khi goi truc tiep
        # (`predict_intent(123)`, ket qua nlp tu file JSON, batch truong).
        # `normalize_text` da ep kieu ho, nhung `original` thi (text or "")
        # .strip() -> `'int' object has no attribute 'strip'`. Ep kieu MOT LAN
        # o dau, roi moi dung; None -> "" (git nguoi dung thay "None" trong URL).
        if not isinstance(text, str):
            text = "" if text is None else str(text)
        raw = normalize_text(text)
        return cls(raw=raw, raw_no_dia=strip_diacritics(raw), original=text.strip())


def _entity_chitchat(ctx: _EntityContext) -> str:
    """Trò chuyện vặt: giữ nguyên câu để chọn câu trả lời phù hợp."""
    return ctx.raw


def _entity_calculate(ctx: _EntityContext) -> str:
    expr, _ = parse_math_expression(ctx.raw)
    return expr or ctx.raw


def _entity_search_web(ctx: _EntityContext) -> str:
    """Tìm kiếm: bóc cụm "tìm kiếm... trên google"."""
    return _strip_affixes(ctx.raw, SEARCH_PREFIX, SEARCH_SUFFIX) or ctx.raw


def _entity_play_media(ctx: _EntityContext) -> str:
    return _strip_affixes(ctx.raw, MEDIA_PREFIX, MEDIA_SUFFIX) or "nhạc"


def _entity_open_website(ctx: _EntityContext) -> str:
    # Bản GIỮ NGUYÊN hoa/thường: URL phân biệt hoa/thường (video ID trên YouTube
    # "...watch?v=dQw4w9WgXcQ"), nên không được lấy từ `raw` đã bị hạ chữ thường.
    url_match = _URL_ENTITY_RE.search(ctx.original)
    if url_match:
        return url_match.group(1)
    return _entity_default(ctx)


def _entity_open_file(ctx: _EntityContext) -> str:
    path_match = _PATH_ENTITY_RE.search(ctx.original)
    if path_match:
        return path_match.group(1)
    return _entity_default(ctx)


def _entity_get_datetime(ctx: _EntityContext) -> str:
    return "date" if _DATE_WORDS_RE.search(ctx.raw) else "time"


def _entity_system_control(ctx: _EntityContext) -> str:
    return _system_action(ctx.raw, ctx.raw_no_dia)


def _entity_default(ctx: _EntityContext) -> str:
    """Mặc định: bỏ stop-words, phần còn lại là tên đối tượng."""
    tokens = [w for w in ctx.raw.split() if w not in STOP_WORDS_ALL]
    return " ".join(tokens).strip() or "unknown"


# intent -> hàm trích xuất. Intent mới chỉ cần thêm một hàm + một dòng ở đây,
# không phải chen thêm if/elif vào giữa một hàm 20 nhánh như bản v6.
_ENTITY_HANDLERS = {
    "system_control": _entity_system_control,
    "get_datetime": _entity_get_datetime,
    "chitchat": _entity_chitchat,
    "calculate": _entity_calculate,
    "get_weather": lambda ctx: _weather_location(ctx.raw),
    "search_web": _entity_search_web,
    "play_media": _entity_play_media,
    "set_reminder": lambda ctx: _reminder_task(ctx.raw),
    "open_website": _entity_open_website,
    "open_file": _entity_open_file,
}


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

    v7.2: mỗi intent có handler RIÊNG đăng ký trong _ENTITY_HANDLERS.
    """
    ctx = _EntityContext.build(text)

    # v6: nếu câu chứa URL THẬT thì luôn trả về URL nguyên vẹn (giữ hoa/thường
    # và các ký tự ? = & #) BẤT KỂ intent model nhận ra là gì. Trước đây nhánh
    # bảo toàn URL chỉ chạy khi intent đã đúng là open_website/open_file, nên
    # một khi phân loại lệch (vd "mở youtube.com/watch?v=..." bị nhận thành
    # play_media) thì liên kết vẫn bị băm nát ở tầng trích xuất.
    if intent in ("open_website", "play_media", "open_file", "search_web"):
        url_match = _URL_ENTITY_RE.search(ctx.original)
        if url_match:
            return url_match.group(1)

    handler = _ENTITY_HANDLERS.get(intent) or _entity_default
    return handler(ctx)


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
