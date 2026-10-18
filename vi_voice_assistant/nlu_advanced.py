"""
nlu_advanced.py v7.10.6
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
v7.7 nâng cấp:
- `teach()`/`log_feedback()`/`confirm_message()` chịu được kiểu khác chuỗi:
  `teach("a", 123)` từng nổ `AttributeError: 'int' object has no attribute
  'strip'`, `confirm_message({})` nổ `KeyError: 'intent'`, và
  `log_feedback(..., confidence=None)` làm hỏng feedback.csv ngay bước
  `round(float(...))` - tức là hỏng luôn dữ liệu huấn luyện lần sau.

v7.5 nâng cấp:
- `understand()` trả `[]` cho câu rỗng thay vì một LỆNH BỊ BỊA
  (`open_website/unknown`): script lặp qua kết quả rồi thực thi đã đi mở thật một
  website tên "unknown".
- `split_commands()` ép kiểu trước khi vào regex - `re.search(123)` chỉ trả về
  "expected string or bytes-like object", không nói chỗ nào nên sửa.

"""

# v7.4: Python 3.9 KHONG danh gia duoc `dict | None`/`str | None` trong chur ky ham
# (PEP 604 can 3.10). File dung annotation kieu nay ma thieu dong nay thi lenh
# `import intent_model` chet bang TypeError tren 3.9 - xem
# tests/test_v74_py39_compat.py de khong ai quen lai.
from __future__ import annotations

import copy
import csv
import difflib
import logging
import math
import os
import re
from datetime import datetime

from config import CONFIG_LOCK
from csv_utils import append_keyed_csv
from paths import data_path
from platform_utils import safe_print, setup_console
from text_utils import as_text, normalize_text
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
FEEDBACK_PATH = str(data_path("feedback.csv"))   # v7.3: xem paths.py


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
        except (TypeError, ValueError, OverflowError):
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
        cfg: dict = load_config()
        return cfg
    except Exception as cfg_error:   # pragma: no cover
        # Không nuốt lỗi âm thầm nữa: ghi log để còn biết config.json có vấn đề.
        _logger.warning("Không đọc được config.json (%s) - dùng mặc định an toàn.", cfg_error)
        return {}


_CFG = _load_cfg_quietly()
_DEFAULT_DANGEROUS = frozenset({"shutdown", "restart", "logout", "sleep"})


def _dangerous_policy(cfg: dict) -> set[str]:
    if "dangerous_actions" not in cfg:
        return set(_DEFAULT_DANGEROUS)
    raw = cfg["dangerous_actions"]
    if (not isinstance(raw, list)
            or any(not isinstance(item, str) or not item.strip() for item in raw)):
        raise ValueError("dangerous_actions phải là list[str] hợp lệ.")
    return set(raw)  # An explicitly empty valid policy is not a missing policy.


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
    values = _load_cfg_quietly() if cfg is None else cfg
    if not isinstance(values, dict):
        raise TypeError("cfg phải là dict hoặc None.")
    dangerous = _dangerous_policy(values)
    accept, ask = _read_thresholds(values)
    with CONFIG_LOCK:
        CONFIDENCE_ACCEPT, CONFIDENCE_ASK = accept, ask
        DANGEROUS_TARGETS = dangerous
    return accept, ask


# Những hành động gây hậu quả nặng -> luôn hỏi xác nhận. Lấy từ
# config.json["dangerous_actions"] để đồng bộ với executor.py; nếu vì lý do
# gì đó không đọc được config (vd file hỏng), dùng lại danh sách mặc định an
# toàn bên dưới để tính năng xác nhận không bao giờ bị vô hiệu hoá âm thầm.
DANGEROUS_TARGETS = _dangerous_policy(_CFG)


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
    r"\bứng dụng đó\b", r"\bapp đó\b", r"\bchúng nó\b", r"\bnó\b",
]

# Từ nối để tách nhiều lệnh trong một câu.
# v6.2: nhận diện cả dạng KHÔNG DẤU ("roi", "sau do", "tiep theo"...) -
# trước đây "mo chrome roi phat nhac" không bị tách vì "roi" chưa được nhận
# ra là "rồi" (giới hạn đã ghi nhận ở HUONG_DAN_SU_DUNG.txt mục 0-D).
SPLIT_PATTERN = re.compile(
    # v7.8: phẩy CHỈ tách lệnh khi không nằm giữa hai chữ số. Trước đây ","
    # tách vô điều kiện, nên "2,5 nhân 4" thành HAI lệnh ("2" và "5 nhân 4") và
    # câu đó ra 20 thay vì 10 - sai mà không báo. Lookbehind chỉ dùng ở nhánh
    # phẩy; các nhánh còn lại (từ nối) vẫn so khớp như cũ.
    r"\s*(?:(?<!\d),|,(?!\d)|;"
    r"|\brồi sau đó\b|\broi sau do\b|\bsau đó\b|\bsau do\b"
    r"|\btiếp theo\b|\btiep theo\b|\brồi\b|\broi\b"
    r"|\bđồng thời\b|\bdong thoi\b|\bvà cũng\b|\bva cung\b)\s*",
    re.IGNORECASE,
)

# Những cụm KHÔNG được tách dù có từ nối (tránh cắt nhầm nội dung công việc /
# cụm tìm kiếm). v6.2: bổ sung dạng không dấu. Cố ý KHÔNG đưa "tính/tinh" vào
# danh sách: "tinh" là một phần của từ "trữ tình", chặn nó sẽ làm mất khả
# năng tách đúng câu "mo chrome roi phat nhac tru tinh".
NO_SPLIT_GUARD = re.compile(
    r"(nhắc tôi|nhac toi|nhắc mình|nhac minh|hẹn giờ|hen gio|báo thức|bao thuc"
    r"|đếm ngược|dem nguoc|tìm|tim|tra cứu|tra cuu|search"
    r"|nhắc nhở|nhac nho|đặt nhắc|dat nhac|tạo nhắc|tao nhac|đặt lịch|dat lich|remind)",
    re.IGNORECASE,
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
    counter: dict[str, int] = {}
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

    accent_map: dict[str, str] = {}
    best_count: dict[str, int] = {}
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

# ---------------------------------------------------------------------------
# KHÔNG tự sửa lỗi gõ thành một từ khoá HỆ THỐNG (v7.9 bổ sung 7)
# ---------------------------------------------------------------------------
# "alarm clock" bị đổi thành "alarm lock" rồi KHOÁ MÁY thật. "tôi đang asleep"
# thành "tôi đang sleep" rồi cho máy ngủ. Nguyên nhân là nhánh (d) sửa lỗi gõ:
# "clock" không có trong VOCAB nên bị kéo về "lock" (ratio 0.889), "asleep" về
# "sleep" (0.909), "block"/"locks" cũng về "lock".
#
# Đã cân nhắc nâng ngưỡng cho riêng nhóm này nhưng KHÔNG khả thi, và đây là
# số đo: độ tương đồng của lỗi gõ THẬT ("slep"->"sleep" 0.889, "slep"->"sleep",
# "hutdown"->"shutdown" 0.875) trùng với từ tiếng Anh bị bắt ("clock"->"lock"
# 0.889, "asleep"->"sleep" 0.909). Hai nhóm CHỒNG LÊN nhau ở 0.86-0.91, nên
# không có ngưỡng nào tách được chúng.
#
# Vì vậy chọn theo CHI PHÍ: sửa sai một từ thường thì người dùng gõ lại được;
# sửa sai thành lệnh khoá máy/ngủ/shutdown thì hậu quả là hành động trên máy
# thật, và người dùng không có cách nào biết vì sao. Bỏ 22 lỗi gõ thật để đổi
# lấy việc không khoá nhầm máy là chấp nhận đáng kể.
_UNSAFE_TO_CORRECT = frozenset({
    "lock", "sleep", "restart", "shutdown", "logout", "mute", "unmute",
    "screenshot", "volumeup", "volumedown",
})


def _safe_to_correct_to(candidate: str) -> bool:
    """Không tự kéo một từ lạ thành từ khoá hệ thống."""
    return strip_accents(candidate).replace("_", "").lower() not in _UNSAFE_TO_CORRECT


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
        #
        # v7.8 - CHỈ chạy khi từ KHÔNG DẤU. Bản cũ áp cho MỌI từ dài ≥4 ký tự,
        # kể cả từ người dùng đã gõ CÓ DẤU đúng - và đo được 12/41 từ thông dụng
        # bị đổi thành MỘT TỪ KHÁC, trong đó có từ mất hẳn âm tiết:
        #
        #   "chơi" -> "cho"      (chơi -> cho,   ratio 0.86)
        #   "nhanh" -> "nhân"    "chậm" -> "cảm"   "xinh" -> "xin"
        #   "giấy" -> "giá"      "thường" -> "trường"   "tiền" -> "thiền"
        #
        # Nguyên nhân: `difflib` so độ TƯƠNG ĐỒNG, nên một từ 4 ký tự và một từ
        # 3 ký tự chung 3 ký tự vẫn đạt 2*3/7 = 0.86 > 0.82. Cắt/thêm một nguyên
        # âm tiết vẫn "giống nhau" theo thang đo đó - và kết quả là câu nói đổi
        # NGHĨA mà không có gì báo: "chơi nhạc" -> "cho nhạc".
        #
        # Sửa: từ đã CÓ DẤU thì giữ nguyên. Người gõ dấu là cố ý, nên gần đúng
        # với một từ khác nhiều khả năng là từ khác thật chứ không phải lỗi gõ;
        # còn lỗi gõ thật sự (gõ nhanh, STT) đều ra từ KHÔNG dấu - đúng cái mà
        # nhánh này sinh ra để sửa. Sửa sai còn tệ hơn không sửa: sai thì người
        # dùng gõ lại được, còn đổi nghĩa thì trợ lý làm sai việc.
        if len(word) >= 4 and strip_accents(word) == word:
            near = difflib.get_close_matches(word, VOCAB, n=1, cutoff=0.82)
            if near and _safe_to_correct_to(near[0]):
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
_SPLIT_LITERAL_RE = re.compile(
    r"\b(?:https?://|www\.)\S+|\b[\w.-]+\.[a-z]{2,}[/?#]\S*", re.IGNORECASE
)


def _protect_split_literals(text: str) -> tuple[str, dict[str, str]]:
    prefix = "zzliteralz"
    while prefix in text:
        prefix += "z"
    literals: dict[str, str] = {}

    def protect(match: re.Match) -> str:
        token = f"{prefix}{len(literals)}zz"
        literals[token] = match.group()
        return token

    return _SPLIT_LITERAL_RE.sub(protect, text), literals


def split_commands(text: str):
    """
    "mở chrome rồi phát nhạc trữ tình" -> ["mở chrome", "phát nhạc trữ tình"]
    Câu nhắc nhở / tìm kiếm được giữ nguyên để không cắt nhầm nội dung.

    v7.5: `text` được ép sang chuỗi TRƯỚC khi vào regex. `understand()`/CLI có thể
    nhận số/dict từ người gọi khác (vd lặp qua một trường JSON), và `re.search(123)`
    chỉ trả về `TypeError: expected string or bytes-like object, got 'int'` - câu
    lỗi không chỉ ra chỗ nên sửa.
    """
    text = as_text(text)
    protected, literals = _protect_split_literals(text)
    if NO_SPLIT_GUARD.search(protected):
        return [text]

    parts = [p.strip() for p in SPLIT_PATTERN.split(protected) if p and p.strip()]
    # Cắt thêm bằng "và"/"va" chỉ khi vế sau bắt đầu bằng động từ ra lệnh
    # (v6.2: thêm động từ KHÔNG DẤU - "mo chrome va tat may").
    verbs = (r"(?:mở|mo|bật|bat|tắt|tat|phát|phat|chạy|chay|khởi|khoi|tìm|tim"
             r"|chụp|chup|đóng|dong|khóa|khoa|khoá)")
    final: list[str] = []
    for part in parts:
        pieces = re.split(rf"\s+(?:và|va)\s+(?={verbs}\b)", part, flags=re.IGNORECASE)
        final.extend(p.strip() for p in pieces if p.strip())
    for i, chunk in enumerate(final):
        for token, literal in literals.items():
            chunk = chunk.replace(token, literal)
        final[i] = chunk
    return final or [text]


# ============================================================================
# 4. BỘ NHỚ NGỮ CẢNH
# ============================================================================
_ANAPHORA_PATTERN = "|".join(dict.fromkeys(
    pattern for original in ANAPHORA for pattern in (original, strip_accents(original))
))
_CONTEXT_REFERENCE_RE = re.compile(
    rf"(?P<literal>{_SPLIT_LITERAL_RE.pattern}"
    r"|\b[a-z]:[\\/]\S+|(?<!\w)/\S+"
    r"|\b[\w-]+(?:\.[\w-]+)+\b(?:[/?#]\S*)?)"
    rf"|{_ANAPHORA_PATTERN}",
    re.IGNORECASE,
)


class ContextMemory:
    """Ghi nhớ lệnh gần nhất để hiểu được "nó", "cái đó", "trang đó"."""

    def __init__(self, max_items: int = 10):
        if isinstance(max_items, bool) or not isinstance(max_items, int):
            raise TypeError("max_items phải là số nguyên không âm.")
        if max_items < 0:
            raise ValueError("max_items không được âm.")
        self.history: list[dict] = []
        self.max_items = max_items

    def remember(self, result: dict):
        if not isinstance(result, dict):
            raise TypeError("result phải là dict.")
        if self.max_items == 0:
            return
        self.history.append(copy.deepcopy(result))
        self.history = self.history[-self.max_items:]

    @property
    def last_target(self):
        for item in reversed(self.history):
            target = item.get("target")
            if isinstance(target, str) and target and target not in ("unknown", "time", "date"):
                return target
        return None

    @property
    def last_intent(self):
        # v7.8: `.get()` thay vì index thẳng: `remember()` nhận dict bất kỳ
        # (script đọc JSON của mình, test tự dựng lịch sử), nên một mục thiếu
        # "intent" làm property này nổ `KeyError` thay vì trả None.
        return self.history[-1].get("intent") if self.history else None

    def resolve(self, text: str) -> str:
        """Thay một lần trên câu gốc; không diễn giải URL/path hay dữ liệu chèn."""
        text = as_text(text)
        target = self.last_target
        if not target:
            return text
        return _CONTEXT_REFERENCE_RE.sub(
            lambda match: match.group() if match.group("literal") is not None else target,
            text,
        )

    def clear(self):
        self.history.clear()


# ============================================================================
# 5. GHI NHẬT KÝ ĐỂ MÁY HỌC THÊM (ACTIVE LEARNING)
# ============================================================================
def _as_confidence(value: object) -> float:
    """Ép `confidence` về số trong [0,1]; giá trị hỏng -> 0.0 ("không hiểu").

    Dùng chung cho `_judge()` và `log_feedback()` để một câu lệnh không thể
    mang đồng thời hai nghĩa: "tôi không chắc" (0.0) và "tôi chắc tuyệt đối"
    (NaN so sánh sai theo mọi hướng). `bool` bị loại có chủ đích: `True` là 1.0
    thì một kết quả cờ `true` trong file JSON sẽ bị coi là tự tin tuyệt đối.
    """
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        return 0.0
    return number


def log_feedback(text: str, intent: str, confidence: float, correct: bool = False) -> bool:
    """Ghi feedback dưới khóa OS; chỉ trả True sau khi record đã flush/fsync.

    `verified=1` chỉ khi người gọi xác nhận bằng True hoặc integer 1, không
    đánh đồng chuỗi "false"/"0" hay container khác với phản hồi đã xác nhận.
    """
    try:
        conf = round(_as_confidence(confidence), 4)
        verified = int(correct is True or (type(correct) is int and correct == 1))
        append_keyed_csv(
            FEEDBACK_PATH, ("time", "text", "intent", "confidence", "verified"),
            [datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             as_text(text), as_text(intent), conf, verified],
        )
        return True
    except (OSError, ValueError, TypeError, csv.Error) as error:
        # Phản hồi tự động là phụ; lỗi quyền/encoding/khóa không làm chết NLU.
        # teach() sử dụng kết quả này, không được báo "đã ghi nhớ" khi chưa lưu.
        _logger.warning("Không ghi được feedback.csv: %s", error)
        return False


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
        """Hiểu một câu -> danh sách lệnh. Câu rỗng trả về ``[]`` (không bịa lệnh).

        v7.5: trước đây câu rỗng/chỉ có khoảng trắng (`"   "`) đi hết tầng phân
        loại và cho ra `{'intent': 'open_website', 'target': 'unknown'}` - một
        LỆNH BỊ BỊA. Với ai dùng thử (`run_once`, `--json`, script lặp qua kết quả
        rồi thực thi), trợ lý đi mở thật một website tên là "unknown". Không có
        nội dung thì không có lệnh: đó là hợp đồng của hàm.
        """
        from intent_model import predict_intent

        if not as_text(text).strip():
            return []

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
            entity_text = original_chunk
            if self.context:
                normalized = self.context.resolve(normalized)
                entity_text = self.context.resolve(original_chunk)

            # v6: truyền THÊM câu gốc để tầng trích xuất thực thể giữ nguyên
            # hoa/thường và các ký tự ? = & # của URL. Trước đây chỉ có bản
            # `normalized` được truyền vào, nên câu "mở youtube.com/watch?v=dQw4w9WgXcQ"
            # bị biến thành "youtube.com/watch v dqw4w9wgxcq" -> mở sai/hỏng liên kết.
            result = predict_intent(normalized, self.model, raw_text=entity_text)
            result["raw"] = original_chunk
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
        """Quyết định nên làm ngay, hỏi lại, hay báo không hiểu.

        v7.8: `confidence` được ép về số HỢP LỆ trước khi so sánh. Bản cũ lấy
        thẳng `result.get("confidence", 0.0)` rồi `conf < CONFIDENCE_ASK`, nên
        kết quả đi qua tay nơi khác (script đọc file JSON của mình, model trả
        `None`) làm nổ ``TypeError: '<' not supported between 'NoneType' and
        'float'`` ngay giữa lúc hiển thị kết quả. Tệ hơn: `nan` so sánh với gì
        cũng cho False nên câu đó rơi thẳng xuống cuối hàm và được đánh dấu
        ``ok`` - tức được THỰC THI. Nay giá trị hỏng/NaN/vô hạn/ngoài [0,1] đều
        thành 0.0, tức "không hiểu" chứ không phải "làm luôn".
        """
        with CONFIG_LOCK:
            accept, ask = CONFIDENCE_ACCEPT, CONFIDENCE_ASK
            dangerous = frozenset(DANGEROUS_TARGETS)
        conf = _as_confidence(result.get("confidence"))
        # 0 còn là kết quả của hàng rào phủ định/dữ liệu hỏng: config 0
        # không được vô hiệu hóa từ chối an toàn rồi cho --yes chạy lệnh.
        if conf <= 0.0 or conf < ask:
            return "unknown"
        # CHỈ coi là hành động nguy hiểm khi intent thật sự là system_control
        # - target của các intent KHÁC mang ý nghĩa hoàn toàn khác (tên bài
        # hát, nội dung tìm kiếm, câu chitchat...) nên có thể vô tình TRÙNG
        # KHỚP CHÍNH XÁC với 1 từ khoá nguy hiểm (vd ai đó tìm kiếm/phát
        # nhạc/chitchat với nội dung đúng là "sleep") mà không hề liên quan
        # gì tới việc điều khiển hệ thống - không kiểm tra intent sẽ hỏi xác
        # nhận nhầm cho 1 lệnh hoàn toàn vô hại.
        if result.get("intent") == "system_control" and result.get("target") in dangerous:
            return "need_confirm"
        if conf < accept:
            return "low_confidence"
        return "ok"

    # ------------------------------------------------------------------
    def confirm_message(self, result: dict) -> str:
        """Câu hỏi lại bằng tiếng Việt cho trường hợp chưa chắc chắn."""
        raw_intent = result.get("intent")
        # khoa cua bang duoi la chuoi -> chuyen ve chuoi truoc khi tra: `intent`
        # co the la so/None khi ket qua di qua tay noi khac (xem doan duoi).
        friendly = {
            "open_website": "mở trang", "open_app": "mở ứng dụng",
            "open_file": "mở file", "system_control": "thực hiện lệnh hệ thống",
            "search_web": "tìm kiếm", "play_media": "phát",
            "set_reminder": "đặt nhắc nhở", "get_weather": "xem thời tiết",
            "get_datetime": "xem giờ", "calculate": "tính", "chitchat": "trò chuyện",
        }.get(str(raw_intent if raw_intent is not None else ""), as_text(raw_intent))
        # `target`/`intent` co the thieu khi ket qua di qua tay noi khac (script
        # doc file JSON): index thang vao do thi nguoi dung nhan duoc KeyError
        # thay vi mot cau hoi "ban muon toi ... phai khong?". Khong co gi de hoi
        # thi hoi chung, dung de in "None" vao mieng nguoi dung.
        if not friendly:
            return "Bạn muốn tôi làm việc đó phải không? (có/không)"
        target = as_text(result.get("target")).strip()
        return f"Bạn muốn tôi {friendly} {target} phải không? (có/không)"

    # ------------------------------------------------------------------
    def teach(self, text: str, intent: str):
        """Dạy trợ lý: gán nhãn đúng cho một câu để lần sau huấn luyện sẽ nhớ.

        v6.2: kiểm tra tên intent hợp lệ TRƯỚC khi ghi - trước đây gõ nhầm
        (vd "day mở chrome = open_ap") vẫn được ghi thẳng vào feedback.csv,
        tạo thêm 1 lớp mới chỉ có đúng 1 mẫu, khiến lần huấn luyện sau bị
        nhiễu (và train_test_split(stratify=...) có thể ném lỗi vì lớp quá
        ít mẫu).
        """
        # Ep kieu TRUOC khi strip: tu REPL thi la chuoi, ma goi truc tiep (script,
        # `--json`) co the tra so/None - va `(123 or "")` thi khong co `.strip()`.
        text = as_text(text).strip()
        if not text:
            return "Câu dạy không được rỗng."
        intent = as_text(intent).strip()
        try:
            from dataset import INTENT_DATA
            valid_intents = sorted(INTENT_DATA.keys())
        except Exception as error:
            _logger.warning("Không đọc được danh sách intent khi dạy: %s", error)
            return "Không đọc được danh sách intent hợp lệ; chưa ghi nhớ câu dạy."
        if intent not in valid_intents:
            return (f"Tên intent \u201c{intent}\u201d không hợp lệ. "
                    f"Các intent hiện có: {', '.join(valid_intents)}.\n"
                    f"   Ví dụ đúng:  day mở chrome = open_app")
        if not log_feedback(text, intent, 1.0, correct=True):
            return "Không lưu được vào feedback.csv; chưa ghi nhớ câu dạy. Kiểm tra quyền ghi/đĩa."
        return (f"Đã ghi nhớ: \u201c{text}\u201d = {intent}. "
                "Chạy `python -m vi_voice_assistant.train_nlu --fast` để học lại.")


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
