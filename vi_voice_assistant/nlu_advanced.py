"""
nlu_advanced.py v7.0
--------------------
TẦNG HIỂU Ý THÔNG MINH (Natural Language Understanding nâng cao) - TUỲ CHỌN.

v7.0 nâng cấp:
- Thêm from __future__ import annotations, type hints đầy đủ, pathlib
- Giữ nguyên 8 khả năng NLU, logic không đổi, tương thích 100% tests
- Thêm logging, validation, cache tối ưu


Mô-đun này NẰM GIỮA mô hình (intent_model.py) và executor.py, làm cho trợ lý
hiểu được cách nói tự nhiên của con người. Đây KHÔNG phải bước bắt buộc -
nếu bạn tích hợp STT riêng, vẫn có thể gọi thẳng predict_intent() +
execute_command() như mục IV.4 trong HUONG_DAN_SU_DUNG.txt. NLU chỉ đem lại
thêm 8 khả năng:

  1. GÕ KHÔNG DẤU      : "mo chrome len"        -> "mở chrome lên"
  2. TEENCODE / VIẾT TẮT: "ko", "dc", "fb", "yt" -> "không", "được", "facebook"
  3. SAI CHÍNH TẢ       : "chorme"               -> "chrome"  (fuzzy match)
  4. NHIỀU LỆNH 1 CÂU  : "mở chrome rồi phát nhạc" -> 2 lệnh (v6.2: tách
                          được cả khi gõ không dấu, vd "mo chrome roi phat nhac")
  5. HIỂU NGỮ CẢNH     : "mở google" ... "đóng nó lại" -> nó = google
  6. NGƯỠNG TỰ TIN     : điểm thấp -> hỏi lại thay vì làm bừa
  7. XÁC NHẬN LỆNH NGUY HIỂM: tắt máy / khởi động lại phải xác nhận (dùng
     chung danh sách "dangerous_actions" trong config.json với executor.py)
  8. HỌC TỪ NGƯỜI DÙNG : ghi câu đoán sai vào feedback.csv để huấn luyện lại

Cách dùng nhanh:
    from nlu_advanced import NLU
    nlu = NLU()
    for cmd in nlu.understand("mo chrome roi phat nhac tru tinh"):
        safe_print(cmd)
"""

import csv
import difflib
import logging
import math
import os
import re
from datetime import datetime

from platform_utils import safe_print, setup_console
from text_utils import normalize_text
from text_utils import strip_diacritics as strip_accents

# v6: đọc CẢ 2 ngưỡng tự tin từ config.json. Trước đây chúng bị VIẾT CỨNG
# trong file này, trong khi executor.py lại đọc một ngưỡng KHÁC từ config.json
# -> người dùng chỉnh confidence_threshold mãi mà trợ lý vẫn hỏi lại y như cũ,
# rất khó hiểu và không có cách nào biết lý do nếu không đọc mã nguồn.
# v7.2: việc đọc/hiệu chỉnh nằm trong _read_thresholds() để một giá trị sai
# kiểu trong config.json không còn làm sập cả chương trình ngay lúc import.
_DEFAULT_ACCEPT = 0.45
_DEFAULT_ASK = 0.25
_logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FEEDBACK_PATH = os.path.join(BASE_DIR, "feedback.csv")


def _read_thresholds(cfg: dict | None):
    """Đọc + hiệu chỉnh 2 ngưỡng tự tin từ config, KHÔNG BAO GIỜ ném lỗi.

    v7.2 - SỬA LỖI LÀM SẬP CHƯƠNG TRÌNH: trước đây 2 dòng
    ``float(_CONFIG_ACCEPT)`` chạy NGÀO NGÀY lúc import module, nằm NGOÀI
    khối try/except đọc config. Chỉ cần một giá trị sai kiểu trong
    config.json (vd ``"confidence_accept": "0.45 phan tram"`` hay ``null``
    do sửa tay bằng Notepad) là ``ValueError/TypeError`` bay ra ngay lúc
    ``import nlu_advanced``, kéo theo cả ``main.py`` chết vì không import
    được NLU - trong khi toàn bộ phần còn lại của dự án (kể cả executor) vẫn
    chạy tốt. Nay giá trị hỏng -> cảnh báo + dùng mặc định an toàn.
    """
    cfg = cfg or {}

    def one(key: str, fallback: float) -> float:
        raw = cfg.get(key)
        if raw is None or isinstance(raw, bool):
            return fallback
        try:
            value = float(raw)
        except (TypeError, ValueError):
            _logger.warning(
                "Giá trị %r trong config.json không phải số (%r) - dùng mặc định %s.",
                key, raw, fallback,
            )
            return fallback
        if not math.isfinite(value):
            _logger.warning("Giá trị %r = %r không hữu hạn - dùng mặc định %s.", key, raw, fallback)
            return fallback
        return min(1.0, max(0.0, value))

    accept = one("confidence_accept", _DEFAULT_ACCEPT)
    ask = one("confidence_ask", _DEFAULT_ASK)
    if ask > accept:
        _logger.warning(
            "confidence_ask (%s) lớn hơn confidence_accept (%s) - mọi câu sẽ bị coi là "
            "'không hiểu'. Đã tự đổi chỗ 2 giá trị cho nhau.", ask, accept,
        )
        ask, accept = accept, ask
    return accept, ask


def _load_cfg_quietly() -> dict:
    try:
        from config import load_config
        return load_config()
    except Exception as cfg_error:   # pragma: no cover
        # Không nuốt lỗi âm thầm nữa: ghi log để còn biết config.json có vấn đề.
        _logger.warning("Không đọc được config.json (%s) - dùng mặc định an toàn.", cfg_error)
        return {}


_CFG = _load_cfg_quietly()
_DANGEROUS_TARGETS_CONFIG = {str(a) for a in _CFG.get("dangerous_actions", []) if a}

# Ngưỡng tự tin: dưới mức này trợ lý sẽ HỎI LẠI thay vì làm bừa. Đây là 2
# ngưỡng RIÊNG của tầng NLU (tinh tế hơn CONFIDENCE_THRESHOLD đơn giản trong
# executor.py / config.json), có 4 mức: ok / low_confidence / need_confirm /
# unknown. Chỉnh 2 số dưới nếu trợ lý hỏi lại quá nhiều hoặc làm bừa quá nhiều.
CONFIDENCE_ACCEPT, CONFIDENCE_ASK = _read_thresholds(_CFG)


def refresh_thresholds(cfg: dict | None = None) -> tuple[float, float]:
    """Nạp lại 2 ngưỡng tự tin + danh sách hành động nguy hiểm từ config.

    v7.2: trước đây lệnh ``nap lai`` / ``--config`` chỉ cập nhật executor, còn
    ngưỡng của tầng NLU vẫn đóng băng từ lúc import -> người dùng đổi
    ``confidence_accept`` trong config.json rồi "nap lai" nhưng trợ lý vẫn hỏi
    lại y hệt. Hàm này đồng bộ lại cả hai phía.
    """
    global CONFIDENCE_ACCEPT, CONFIDENCE_ASK, DANGEROUS_TARGETS
    cfg = _load_cfg_quietly() if cfg is None else cfg
    CONFIDENCE_ACCEPT, CONFIDENCE_ASK = _read_thresholds(cfg)
    dangerous = {str(a) for a in (cfg or {}).get("dangerous_actions", []) if a}
    DANGEROUS_TARGETS = dangerous or {"shutdown", "restart", "logout", "sleep"}
    return CONFIDENCE_ACCEPT, CONFIDENCE_ASK


# Những hành động gây hậu quả nặng -> luôn hỏi xác nhận. Lấy từ
# config.json["dangerous_actions"] để đồng bộ với executor.py; nếu vì lý do
# gì đó không đọc được config (vd file hỏng), dùng lại danh sách mặc định an
# toàn bên dưới để tính năng xác nhận không bao giờ bị vô hiệu hoá âm thầm.
DANGEROUS_TARGETS = _DANGEROUS_TARGETS_CONFIG or {"shutdown", "restart", "logout", "sleep"}


# ============================================================================
# 1. TỪ ĐIỂN VIẾT TẮT / TEENCODE
# ============================================================================
TEEN_CODE = {
    "ko": "không", "k": "không", "kh": "không", "khong": "không",
    "dc": "được", "đc": "được", "j": "gì", "z": "vậy", "v": "vậy",
    "bh": "bây giờ", "h": "giờ", "hnay": "hôm nay", "hqua": "hôm qua",
    "mn": "mọi người", "m": "mày", "t": "tôi", "tui": "tôi", "tớ": "tôi",
    "pls": "giúp tôi", "plz": "giúp tôi", "ok": "đồng ý",
    # Tên riêng hay viết tắt
    "fb": "facebook", "yt": "youtube", "gg": "google", "ytb": "youtube",
    "gh": "github", "tt": "tiktok", "ig": "instagram", "zl": "zalo",
    "vscode": "vs code", "pts": "photoshop", "cal": "calculator",
    "pc": "máy tính", "lap": "máy tính", "laptop": "máy tính",
}

# Từ chỉ định (anaphora) -> thay bằng đối tượng đã nói trước đó
ANAPHORA = [
    r"\bcái đó\b", r"\bcái ấy\b", r"\bthằng đó\b", r"\btrang đó\b",
    r"\bứng dụng đó\b", r"\bapp đó\b", r"\bnó\b", r"\bchúng nó\b",
]

# Từ nối để tách nhiều lệnh trong một câu.
# v6.2: nhận diện cả dạng KHÔNG DẤU ("roi", "sau do", "tiep theo"...) -
# trước đây "mo chrome roi phat nhac" không bị tách vì "roi" chưa được nhận
# ra là "rồi" (giới hạn đã ghi nhận ở HUONG_DAN_SU_DUNG.txt mục 0-D).
SPLIT_PATTERN = re.compile(
    r"\s*(?:,|;"
    r"|\brồi sau đó\b|\broi sau do\b|\bsau đó\b|\bsau do\b"
    r"|\btiếp theo\b|\btiep theo\b|\brồi\b|\broi\b"
    r"|\bđồng thời\b|\bdong thoi\b|\bvà cũng\b|\bva cung\b)\s*"
)

# Những cụm KHÔNG được tách dù có từ nối (tránh cắt nhầm nội dung công việc /
# cụm tìm kiếm). v6.2: bổ sung dạng không dấu. Cố ý KHÔNG đưa "tính/tinh" vào
# danh sách: "tinh" là một phần của từ "trữ tình", chặn nó sẽ làm mất khả
# năng tách đúng câu "mo chrome roi phat nhac tru tinh".
NO_SPLIT_GUARD = re.compile(
    r"(nhắc tôi|nhac toi|nhắc mình|nhac minh|hẹn giờ|hen gio|báo thức|bao thuc"
    r"|đếm ngược|dem nguoc|tìm|tim|tra cứu|tra cuu|search)"
)


# ============================================================================
# 2. CHUẨN HOÁ VĂN BẢN THÔNG MINH
# ============================================================================
def _build_accent_map():
    """
    Tự động dựng từ điển "không dấu -> có dấu" từ chính dataset.
    Ví dụ: 'mo' -> 'mở', 'tat' -> 'tắt'.
    Từ nào xuất hiện nhiều nhất trong dataset sẽ được ưu tiên.
    """
    counter = {}
    try:
        from dataset import get_dataset_as_lists
        texts, _ = get_dataset_as_lists(augment_no_diacritics=False)
    except Exception:
        texts = []

    for sentence in texts:
        for word in sentence.lower().split():
            word = re.sub(r"[^\w]", "", word)
            if not word:
                continue
            counter.setdefault(word, 0)
            counter[word] += 1

    accent_map, best_count = {}, {}
    for word, count in counter.items():
        plain = strip_accents(word)
        if plain == word:
            continue                      # từ vốn đã không dấu
        if count > best_count.get(plain, 0):
            accent_map[plain] = word
            best_count[plain] = count
    # v6.2: KHÔNG phục hồi dấu cho một dạng không dấu mà BẢN THÂN nó cũng là
    # một từ thật có trong dataset (vd "hai" = số 2, đồng thời là dạng không
    # dấu của "hải" trong "hải phòng" - trước đây "hai mươi" bị đổi thành
    # "hải mươi" khiến số viết bằng chữ không đọc được).
    for plain in list(accent_map):
        if plain in counter:
            del accent_map[plain]
    return accent_map, set(counter)


# Từ thông dụng bổ sung (phòng khi dataset chưa có đủ từ để suy ra)
COMMON_ACCENTS = {
    "giup": "giúp", "gium": "giùm", "dum": "dùm", "ho": "hộ", "di": "đi",
    "dong": "đóng", "tim": "tìm", "nhac": "nhạc", "tinh": "tình",
    "cho": "cho", "toi": "tôi", "minh": "mình", "ban": "bạn",
    "gio": "giờ", "ngay": "ngày", "mai": "mai", "toi_nay": "tối nay",
    "nghe": "nghe", "xem": "xem", "lam": "làm", "gi": "gì",
    "the": "thế", "nao": "nào", "bao": "bao", "nhieu": "nhiêu",
    "nhac_nho": "nhắc nhở", "bao_thuc": "báo thức",
}

ACCENT_MAP, VOCAB = _build_accent_map()
# Từ trong dataset được ưu tiên; từ thông dụng chỉ điền vào chỗ còn thiếu
for _plain, _accented in COMMON_ACCENTS.items():
    ACCENT_MAP.setdefault(_plain, _accented)
PLAIN_VOCAB = {strip_accents(w) for w in VOCAB}


def smart_normalize(text: str) -> str:
    """
    Chuẩn hoá thông minh trước khi đưa vào mô hình:
      - chuyển thường, chuẩn Unicode (dùng chung text_utils.normalize_text)
      - bạn viết tắt -> viết đầy đủ
      - bạn gõ không dấu -> phục hồi dấu
      - gõ sai chính tả nhẹ -> sửa bằng fuzzy match
    """
    text = normalize_text(text)

    words, out = text.split(), []
    for word in words:
        # (a) viết tắt / teencode
        if word in TEEN_CODE:
            out.append(TEEN_CODE[word])
            continue
        # (b) tên riêng / từ tiếng Anh có sẵn trong từ vựng -> giữ nguyên
        #     (trừ khi từ đó chỉ là bản không dấu của một từ tiếng Việt)
        if not word.isalpha() or (word in VOCAB and word not in ACCENT_MAP):
            out.append(word)
            continue
        # (c) gõ không dấu -> phục hồi dấu
        if word in ACCENT_MAP:
            out.append(ACCENT_MAP[word])
            continue
        # (d) sai chính tả nhẹ -> tìm từ gần giống nhất
        if len(word) >= 4:
            near = difflib.get_close_matches(word, VOCAB, n=1, cutoff=0.82)
            if near:
                out.append(near[0])
                continue
            near = difflib.get_close_matches(strip_accents(word), ACCENT_MAP, n=1, cutoff=0.85)
            if near:
                out.append(ACCENT_MAP[near[0]])
                continue
        out.append(word)

    return " ".join(out)


# ============================================================================
# 3. TÁCH NHIỀU LỆNH TRONG MỘT CÂU
# ============================================================================
def split_commands(text: str):
    """
    "mở chrome rồi phát nhạc trữ tình" -> ["mở chrome", "phát nhạc trữ tình"]
    Câu nhắc nhở / tìm kiếm được giữ nguyên để không cắt nhầm nội dung.
    """
    if NO_SPLIT_GUARD.search(text):
        return [text]

    parts = [p.strip() for p in SPLIT_PATTERN.split(text) if p and p.strip()]
    # Cắt thêm bằng "và"/"va" chỉ khi vế sau bắt đầu bằng động từ ra lệnh
    # (v6.2: thêm động từ KHÔNG DẤU - "mo chrome va tat may").
    verbs = (r"(?:mở|mo|bật|bat|tắt|tat|phát|phat|chạy|chay|khởi|khoi|tìm|tim"
             r"|chụp|chup|đóng|dong|khóa|khoa|khoá)")
    final = []
    for part in parts:
        pieces = re.split(rf"\s+(?:và|va)\s+(?={verbs}\b)", part)
        final.extend(p.strip() for p in pieces if p.strip())
    return final or [text]


# ============================================================================
# 4. BỘ NHỚ NGỮ CẢNH
# ============================================================================
class ContextMemory:
    """Ghi nhớ lệnh gần nhất để hiểu được "nó", "cái đó", "trang đó"."""

    def __init__(self, max_items: int = 10):
        self.history = []
        self.max_items = max_items

    def remember(self, result: dict):
        self.history.append(result)
        self.history = self.history[-self.max_items:]

    @property
    def last_target(self):
        for item in reversed(self.history):
            target = item.get("target")
            if target and target not in ("unknown", "time", "date"):
                return target
        return None

    @property
    def last_intent(self):
        return self.history[-1]["intent"] if self.history else None

    def resolve(self, text: str) -> str:
        """Thay từ chỉ định bằng đối tượng đã nhắc đến trước đó."""
        target = self.last_target
        if not target:
            return text
        for pattern in ANAPHORA:
            if re.search(pattern, text):
                # QUAN TRỌNG: dùng HÀM (lambda) làm replacement, KHÔNG dùng
                # chuỗi target trực tiếp. re.sub() với replacement là CHUỖI
                # sẽ hiểu các dấu \ trong đó là escape đặc biệt của regex
                # (vd \1 = backreference nhóm 1). target rất hay là đường
                # dẫn Windows (vd "C:\Users\...") - dấu \U, \A trong đó sẽ
                # bị hiểu nhầm thành escape không hợp lệ và ném
                # `re.error: bad escape` ngay khi user nói "đóng nó lại"
                # sau khi vừa mở 1 file bằng đường dẫn đầy đủ. Dùng lambda
                # trả về nguyên văn, không bị regex diễn giải thêm.
                text = re.sub(pattern, lambda m: target, text)
        return text

    def clear(self):
        self.history.clear()


# ============================================================================
# 5. GHI NHẬT KÝ ĐỂ MÁY HỌC THÊM (ACTIVE LEARNING)
# ============================================================================
def log_feedback(text: str, intent: str, confidence: float, correct: bool = False):
    """
    Ghi câu nói vào feedback.csv. File này sẽ được train_nlu.py / train_phobert.py
    đọc lại để huấn luyện, giúp trợ lý ngày càng hiểu đúng ý bạn hơn.

    Cột: time, text, intent, confidence, verified
    - verified = 1 : nhãn đã được bạn xác nhận đúng -> được dùng để huấn luyện
    - verified = 0 : máy đoán, chưa chắc đúng -> chỉ để bạn xem lại
    """
    try:
        is_new = not os.path.exists(FEEDBACK_PATH)
        with open(FEEDBACK_PATH, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow(["time", "text", "intent", "confidence", "verified"])
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                text, intent, round(float(confidence), 4), 1 if correct else 0,
            ])
    except OSError as e:
        # Hàm này được gọi TỰ ĐỘNG mỗi khi độ tự tin thấp (rất thường xuyên
        # trong lúc dùng bình thường) - đây chỉ là tính năng "học thêm" phụ,
        # không quan trọng bằng việc hiểu lệnh chính, nên lỗi ghi file (thiếu
        # quyền, đĩa đầy...) KHÔNG được phép làm gián đoạn trải nghiệm chính.
        # Chỉ ghi log 1 dòng cảnh báo, không safe_print ra console (tránh
        # spam liên tục nếu lỗi lặp lại ở mọi câu nói).
        logging.getLogger(__name__).warning("Không ghi được feedback.csv: %s", e)


# ============================================================================
# 6. LỚP NLU CHÍNH
# ============================================================================
class NLU:
    """
    Tầng hiểu ý thông minh, bọc quanh mô hình phân loại.

    understand(text) trả về DANH SÁCH lệnh, mỗi lệnh có dạng:
        {
          "intent": "open_app",
          "target": "chrome",
          "confidence": 0.91,
          "status": "ok" | "low_confidence" | "unknown" | "need_confirm",
          "raw": "câu gốc bạn nói",
          "normalized": "câu sau khi chuẩn hoá"
        }
    """

    def __init__(self, model=None, use_context: bool = True):
        from intent_model import load_model
        self.model = model or load_model()
        self.context = ContextMemory() if use_context else None

    # ------------------------------------------------------------------
    def understand(self, text: str):
        from intent_model import predict_intent

        results = []
        for chunk in split_commands(text):
            # v6: GIỮ lại câu gốc của từng vế trước khi chuẩn hoá (xem phần
            # truyền raw_text bên dưới).
            original_chunk = chunk
            # QUAN TRỌNG: phục hồi dấu (smart_normalize) TRƯỚC khi thử nhận
            # diện từ chỉ định ("nó", "cái đó"...). Làm ngược lại (bản cũ)
            # khiến câu gõ KHÔNG DẤU (vd "dong no lai") không khớp được các
            # mẫu ANAPHORA vốn viết CÓ DẤU (vd \bnó\b), làm tính năng "hiểu
            # ngữ cảnh" ÂM THẦM KHÔNG HOẠT ĐỘNG với input không dấu - dù "gõ
            # không dấu" cũng là 1 tính năng được quảng cáo của chính module
            # này (xem 2 mục đầu docstring ở đầu file).
            normalized = smart_normalize(chunk)
            if self.context:
                normalized = self.context.resolve(normalized)
                chunk = normalized  # "raw" hiển thị bản đã thay từ chỉ định, giữ đúng hành vi cũ

            # v6: truyền THÊM câu gốc để tầng trích xuất thực thể giữ nguyên
            # hoa/thường và các ký tự ? = & # của URL. Trước đây chỉ có bản
            # `normalized` được truyền vào, nên câu "mở youtube.com/watch?v=dQw4w9WgXcQ"
            # bị biến thành "youtube.com/watch v dqw4w9wgxcq" -> mở sai/hỏng liên kết.
            result = predict_intent(normalized, self.model, raw_text=original_chunk)
            result["raw"] = chunk
            result["normalized"] = normalized
            result["status"] = self._judge(result)

            if self.context and result["status"] == "ok":
                self.context.remember(result)
            if result["status"] in ("low_confidence", "unknown"):
                log_feedback(chunk, result["intent"], result["confidence"])

            results.append(result)
        return results

    # ------------------------------------------------------------------
    @staticmethod
    def _judge(result: dict) -> str:
        """Quyết định nên làm ngay, hỏi lại, hay báo không hiểu."""
        conf = result.get("confidence", 0.0)
        if conf < CONFIDENCE_ASK:
            return "unknown"
        # CHỈ coi là hành động nguy hiểm khi intent thật sự là system_control
        # - target của các intent KHÁC mang ý nghĩa hoàn toàn khác (tên bài
        # hát, nội dung tìm kiếm, câu chitchat...) nên có thể vô tình TRÙNG
        # KHỚP CHÍNH XÁC với 1 từ khoá nguy hiểm (vd ai đó tìm kiếm/phát
        # nhạc/chitchat với nội dung đúng là "sleep") mà không hề liên quan
        # gì tới việc điều khiển hệ thống - không kiểm tra intent sẽ hỏi xác
        # nhận nhầm cho 1 lệnh hoàn toàn vô hại.
        if result.get("intent") == "system_control" and result.get("target") in DANGEROUS_TARGETS:
            return "need_confirm"
        if conf < CONFIDENCE_ACCEPT:
            return "low_confidence"
        return "ok"

    # ------------------------------------------------------------------
    def confirm_message(self, result: dict) -> str:
        """Câu hỏi lại bằng tiếng Việt cho trường hợp chưa chắc chắn."""
        friendly = {
            "open_website": "mở trang", "open_app": "mở ứng dụng",
            "open_file": "mở file", "system_control": "thực hiện lệnh hệ thống",
            "search_web": "tìm kiếm", "play_media": "phát",
            "set_reminder": "đặt nhắc nhở", "get_weather": "xem thời tiết",
            "get_datetime": "xem giờ", "calculate": "tính", "chitchat": "trò chuyện",
        }.get(result["intent"], result["intent"])
        return f"Bạn muốn tôi {friendly} {result['target']} phải không? (có/không)"

    # ------------------------------------------------------------------
    def teach(self, text: str, intent: str):
        """Dạy trợ lý: gán nhãn đúng cho một câu để lần sau huấn luyện sẽ nhớ.

        v6.2: kiểm tra tên intent hợp lệ TRƯỚC khi ghi - trước đây gõ nhầm
        (vd "day mở chrome = open_ap") vẫn được ghi thẳng vào feedback.csv,
        tạo thêm 1 lớp mới chỉ có đúng 1 mẫu, khiến lần huấn luyện sau bị
        nhiễu (và train_test_split(stratify=...) có thể ném lỗi vì lớp quá
        ít mẫu).
        """
        intent = (intent or "").strip()
        try:
            from dataset import INTENT_DATA
            valid_intents = sorted(INTENT_DATA.keys())
        except Exception:
            valid_intents = []
        if valid_intents and intent not in valid_intents:
            return (f"Tên intent \u201c{intent}\u201d không hợp lệ. "
                    f"Các intent hiện có: {', '.join(valid_intents)}.\n"
                    f"   Ví dụ đúng:  day mở chrome = open_app")
        log_feedback(text, intent, 1.0, correct=True)
        return f"Đã ghi nhớ: \u201c{text}\u201d = {intent}. Chạy `python train_nlu.py` để học lại."


# ============================================================================
# 7. CHẠY THỬ
# ============================================================================
if __name__ == "__main__":
    setup_console()
    safe_print(f"Từ điển phục hồi dấu: {len(ACCENT_MAP)} từ | Từ vựng: {len(VOCAB)} từ\n")

    safe_print("===== TEST CHUẨN HOÁ THÔNG MINH =====")
    for s in [
        "mo chrome len",
        "bat gg giup toi",
        "mo chorme ra di",
        "tat may tinh di",
        "phat nhac tru tinh tren yt",
    ]:
        safe_print(f"  {s!r:32} -> {smart_normalize(s)!r}")

    safe_print("\n===== TEST TÁCH NHIỀU LỆNH =====")
    for s in [
        "mở chrome rồi phát nhạc trữ tình",
        "bật google, mở vs code và tắt tiếng",
        "nhắc tôi họp và gọi khách hàng lúc 3 giờ",
    ]:
        safe_print(f"  {s!r}\n    -> {split_commands(s)}")

    safe_print("\n===== TEST NGỮ CẢNH =====")
    ctx = ContextMemory()
    ctx.remember({"intent": "open_website", "target": "google"})
    safe_print(f"  đóng nó lại  -> {ctx.resolve('đóng nó lại')}")
    safe_print(f"  mở trang đó -> {ctx.resolve('mở trang đó')}")

    # Phần dưới cần scikit-learn và model đã huấn luyện
    try:
        nlu = NLU()
        safe_print("\n===== TEST HIỂU Ý ĐẦY ĐỦ =====")
        for s in ["mo chrome roi phat nhac tru tinh", "tat may di", "bat gg len"]:
            safe_print(f"\n  Bạn: {s}")
            for r in nlu.understand(s):
                safe_print(
                    f"    -> [{r['status']}] {r['intent']} | {r['target']} | {r['confidence']}"
                )
    except Exception as e:
        safe_print(f"\n(Bỏ qua phần cần model: {e})")
