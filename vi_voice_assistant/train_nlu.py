# -*- coding: utf-8 -*-
"""
train_nlu.py
------------
FILE HUẤN LUYỆN "HIỂU Ý CON NGƯỜI" (bản nâng cao)

Khác gì so với intent_model.py?
  intent_model.py : huấn luyện nhanh, đơn giản, đủ dùng.
  train_nlu.py    : huấn luyện KỸ, cho mô hình thông minh hơn hẳn:

  1. GỘP NHIỀU NGUỒN DỮ LIỆU : dataset.py + my_dataset.csv + feedback.csv
  2. TĂNG CƯỜNG DỮ LIỆU       : tự sinh thêm biến thể (không dấu, teencode,
                                 gõ sai chính tả, thêm từ đệm) -> gấp ~4 lần
  3. ĐẶC TRƯNG KÉP            : TF-IDF từ + TF-IDF ký tự (FeatureUnion)
  4. TỰ CHỌN SIÊU THAM SỐ     : GridSearchCV tìm cấu hình tốt nhất
  5. ĐÁNH GIÁ CHÉO            : StratifiedKFold 5 fold
  6. PHÂN TÍCH LỖI            : in ra câu bị đoán sai + ma trận nhầm lẫn
  7. XUẤT BÁO CÁO             : nlu_report.txt để bạn biết nên bổ sung dữ liệu ở đâu

Cách chạy:
    python train_nlu.py               # huấn luyện đầy đủ (khuyên dùng)
    python train_nlu.py --fast        # bỏ GridSearch cho nhanh
    python train_nlu.py --no-augment  # không tăng cường dữ liệu

Kết quả: ghi đè intent_model.pkl -> main.py dùng được ngay, không cần sửa gì.
"""

import argparse
import csv
import os
import random
import sys
from collections import Counter

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import GridSearchCV, StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import FeatureUnion, Pipeline

from dataset import get_dataset_as_lists
from nlu_advanced import TEEN_CODE, smart_normalize, strip_accents
from platform_utils import safe_print, setup_console

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "intent_model.pkl")
REPORT_PATH = os.path.join(BASE_DIR, "nlu_report.txt")
EXTRA_CSV = os.path.join(BASE_DIR, "my_dataset.csv")
FEEDBACK_CSV = os.path.join(BASE_DIR, "feedback.csv")

random.seed(42)


# ============================================================================
# 1. GỐP DỮ LIỆU TỪ NHIỀU NGUỒN
# ============================================================================
def load_all_data():
    """Gộp dataset gốc + my_dataset.csv + câu đã xác nhận trong feedback.csv."""
    texts, labels = get_dataset_as_lists()
    texts, labels = list(texts), list(labels)
    safe_print(f"[1] Dataset gốc        : {len(texts)} câu")

    # (a) Dữ liệu bạn tự thêm: my_dataset.csv (2 cột text,intent)
    n_extra = 0
    if os.path.exists(EXTRA_CSV):
        with open(EXTRA_CSV, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                text = (row.get("text") or "").strip()
                intent = (row.get("intent") or "").strip()
                if text and intent:
                    texts.append(text)
                    labels.append(intent)
                    n_extra += 1
    safe_print(f"[2] my_dataset.csv     : {n_extra} câu")

    # (b) Câu bạn đã dạy lại (verified = 1) trong feedback.csv
    n_fb = 0
    if os.path.exists(FEEDBACK_CSV):
        with open(FEEDBACK_CSV, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if str(row.get("verified", "0")).strip() != "1":
                    continue
                text = (row.get("text") or "").strip()
                intent = (row.get("intent") or "").strip()
                if text and intent:
                    # nhân 3 lần để mô hình ưu tiên học câu bạn đã sửa
                    texts.extend([text] * 3)
                    labels.extend([intent] * 3)
                    n_fb += 1
    safe_print(f"[3] feedback đã xác nhận: {n_fb} câu (nhân 3)")

    return texts, labels


# ============================================================================
# 2. TĂNG CƯỜNG DỮ LIỆU (DATA AUGMENTATION)
# ============================================================================
FILLERS_HEAD = ["ừ thì", "ủa", "này", "ủa mà", "cho hỏi", "ạ", "alo"]
FILLERS_TAIL = ["nhé", "nha", "đi", "giúp tôi", "cái", "ngay", "giùm cái", "ạ"]
REVERSE_TEEN = {v: k for k, v in TEEN_CODE.items() if len(k) >= 2}


def aug_no_accent(text: str) -> str:
    """Giả lập người dùng gõ không dấu."""
    return strip_accents(text)


def aug_teencode(text: str) -> str:
    """Giả lập viết tắt: facebook -> fb, không -> ko."""
    out = text
    for full, short in REVERSE_TEEN.items():
        out = out.replace(full, short)
    return out


def aug_typo(text: str) -> str:
    """Giả lập gõ sai phím: đảo 2 ký tự trong một từ dài."""
    words = text.split()
    candidates = [i for i, w in enumerate(words) if len(w) >= 5]
    if not candidates:
        return text
    i = random.choice(candidates)
    w = list(words[i])
    j = random.randint(0, len(w) - 2)
    w[j], w[j + 1] = w[j + 1], w[j]
    words[i] = "".join(w)
    return " ".join(words)


def aug_filler(text: str) -> str:
    """Thêm từ đệm đầu/cuối câu như khi nói chuyện thật."""
    if random.random() < 0.5:
        return f"{random.choice(FILLERS_HEAD)} {text}"
    return f"{text} {random.choice(FILLERS_TAIL)}"


def augment(texts, labels):
    """Sinh thêm biến thể cho mọi câu; loại trùng lặp."""
    aug_texts, aug_labels = list(texts), list(labels)
    for text, label in zip(texts, labels):
        for fn in (aug_no_accent, aug_teencode, aug_typo, aug_filler):
            new_text = fn(text)
            if new_text and new_text != text:
                aug_texts.append(new_text)
                aug_labels.append(label)

    # loại cặp trùng
    seen, X, y = set(), [], []
    for text, label in zip(aug_texts, aug_labels):
        key = (text, label)
        if key in seen:
            continue
        seen.add(key)
        X.append(text)
        y.append(label)
    return X, y


# ============================================================================
# 3. PIPELINE ĐẶC TRƯNG KÉP (TỪ + KÝ TỰ)
# ============================================================================
def build_pipeline() -> Pipeline:
    """
    Kết hợp 2 góc nhìn:
      - word ngram : hiểu cụm từ ("mở file", "trên google")
      - char ngram : chịu được gõ sai / không dấu ("chorme", "mo chrome")
    """
    features = FeatureUnion([
        ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2),
                                 sublinear_tf=True, min_df=1)),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
                                 sublinear_tf=True, min_df=1)),
    ])
    return Pipeline([
        ("features", features),
        ("clf", LogisticRegression(max_iter=3000, C=10, class_weight="balanced")),
    ])


PARAM_GRID = {
    "features__word__ngram_range": [(1, 2), (1, 3)],
    "features__char__ngram_range": [(2, 5), (1, 5)],
    "clf__C": [1, 5, 10, 30],
}


# ============================================================================
# 4. HUẤN LUYỆN + ĐÁNH GIÁ + PHÂN TÍCH LỖI
# ============================================================================
def train(fast: bool = False, use_augment: bool = True):
    lines = []   # nội dung báo cáo

    def log(msg=""):
        safe_print(msg)
        lines.append(str(msg))

    log("=" * 70)
    log("HUẤN LUYỆN MÔ HÌNH HIỂU Ý – BẢN NÂNG CAO")
    log("=" * 70)

    # --- Nạp dữ liệu ---
    texts, labels = load_all_data()

    if use_augment:
        before = len(texts)
        texts, labels = augment(texts, labels)
        log(f"[4] Tăng cường dữ liệu : {before} -> {len(texts)} câu")
    else:
        log("[4] Tăng cường dữ liệu : bỏ qua (--no-augment)")

    # Chuẩn hoá giống hệt lúc chạy thực tế
    texts = [smart_normalize(t) for t in texts]

    dist = Counter(labels)
    log(f"\nTỔNG: {len(texts)} câu / {len(dist)} nhóm ý định")
    for intent, count in dist.most_common():
        bar = "#" * max(1, count * 40 // max(dist.values()))
        log(f"  {intent:<16} {count:>5}  {bar}")

    # --- Tách train / test ---
    X_train, X_test, y_train, y_test = train_test_split(
        texts, labels, test_size=0.2, random_state=42, stratify=labels
    )

    pipeline = build_pipeline()

    # --- Tìm siêu tham số tốt nhất ---
    if fast:
        log("\n[5] Chế độ nhanh: dùng tham số mặc định")
        pipeline.fit(X_train, y_train)
        best = pipeline
    else:
        log("\n[5] Đang tìm siêu tham số tốt nhất (GridSearchCV)...")
        log("    (mất 1-3 phút, dùng --fast để bỏ qua)")
        search = GridSearchCV(
            pipeline, PARAM_GRID, cv=3, n_jobs=-1, scoring="f1_macro", verbose=0
        )
        search.fit(X_train, y_train)
        best = search.best_estimator_
        log(f"    Tham số tốt nhất: {search.best_params_}")
        log(f"    Điểm F1 (macro) : {search.best_score_:.4f}")

    # --- Đánh giá chéo 5 fold ---
    log("\n[6] ĐÁNH GIÁ CHÉO 5 FOLD")
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(best, texts, labels, cv=skf, scoring="f1_macro", n_jobs=-1)
    log(f"    F1 từng fold: {[round(s, 4) for s in scores]}")
    log(f"    Trung bình  : {scores.mean():.4f} (độ lệch {scores.std():.4f})")

    # --- Báo cáo chi tiết trên tập test ---
    y_pred = best.predict(X_test)
    log("\n[7] BÁO CÁO TRÊN TẬP TEST")
    log(classification_report(y_test, y_pred, zero_division=0))

    # --- Ma trận nhầm lẫn ---
    log("[8] MA TRẬN NHẦM LẪN (hàng = đúng, cột = máy đoán)")
    names = sorted(set(labels))
    matrix = confusion_matrix(y_test, y_pred, labels=names)
    header = "    " + "".join(f"{n[:6]:>8}" for n in names)
    log(header)
    for name, row in zip(names, matrix):
        log(f"{name[:16]:<16}" + "".join(f"{v:>8}" for v in row))

    # --- Phân tích lỗi: câu nào bị đoán sai ---
    log("\n[9] CÁC CÂU BỊ ĐOÁN SAI (bổ sung thêm câu tương tự vào dataset sẽ tốt hơn)")
    wrong = [(t, y, p) for t, y, p in zip(X_test, y_test, y_pred) if y != p]
    if not wrong:
        log("    Không có câu nào sai. Tuyệt vời!")
    for text, truth, pred in wrong[:25]:
        log(f"    {text[:52]:<54} đúng={truth:<14} đoán={pred}")
    if len(wrong) > 25:
        log(f"    ... và {len(wrong) - 25} câu khác")

    # --- Huấn luyện lại trên TOÀN BỘ dữ liệu rồi lưu ---
    log("\n[10] Huấn luyện lại trên toàn bộ dữ liệu và lưu model...")
    best.fit(texts, labels)
    joblib.dump(best, MODEL_PATH)
    log(f"     Đã lưu: {MODEL_PATH}")

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    safe_print(f"\nĐã ghi báo cáo chi tiết: {REPORT_PATH}")

    return best


# ============================================================================
# 5. TEST NHANH SAU KHI HUẤN LUYỆN
# ============================================================================
DEMO_SENTENCES = [
    "mo chrome len di",                     # không dấu
    "bat gg giup toi",                      # không dấu + viết tắt
    "ủa mở giùm cái vs code",               # có từ đệm
    "mở chorme ra",                         # gõ sai chính tả
    "cho tôi xem báo cáo tháng 8",
    "tắt tiếng loa lại",
    "tìm giá vàng hôm nay",
    "nghe nhạc trữ tình đi",
    "nhắc tôi uống thuốc lúc 9 giờ tối",
    "hôm nay trời ở hải phòng thế nào",
    "bây giờ là mấy giờ",
    "bạn tên gì vậy",
]


def quick_test(model):
    from intent_model import predict_intent
    safe_print("\n" + "=" * 70)
    safe_print("TEST NHANH VỚI CÂU NÓI “KHÓ”")
    safe_print("=" * 70)
    for s in DEMO_SENTENCES:
        r = predict_intent(smart_normalize(s), model)
        safe_print(f"  {s:<40} -> {r['intent']:<15} | {r['target'][:22]:<22} | {r['confidence']}")


if __name__ == "__main__":
    setup_console()
    parser = argparse.ArgumentParser(description="Huấn luyện mô hình hiểu ý nâng cao")
    parser.add_argument("--fast", action="store_true", help="bỏ GridSearch cho nhanh")
    parser.add_argument("--no-augment", action="store_true", help="không tăng cường dữ liệu")
    args = parser.parse_args()

    model = train(fast=args.fast, use_augment=not args.no_augment)
    try:
        quick_test(model)
    except Exception as e:
        safe_print(f"(Bỏ qua test nhanh: {e})", file=sys.stderr)

    safe_print("\nXONG! Giờ chạy:  python main.py")
