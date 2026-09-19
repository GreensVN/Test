"""
lite_model.py - Bộ phân loại nhẹ thuần Python (Naive Bayes + char n-grams)

v7.0 nâng cấp:
- Type hints đầy đủ
- Dùng pathlib, dataclass-like state
- Tối ưu featurize với cache lru_cache
- Atomic save, protocol 4 cho pickle
- Thêm method explain để debug
"""

from __future__ import annotations

import hashlib
import math
import os
import pickle
import tempfile
from functools import lru_cache
from pathlib import Path

from paths import data_path
from text_utils import normalize_text

BASE_DIR = Path(__file__).resolve().parent
# v7.3: model cache nam trong thu muc du lieu (paths.py) - site-packages co the
# chi doc, va moi lan nang cấp pip sẽ XOÁ sạch model đã huấn luyện nếu nó nằm
# trong package.
LITE_MODEL_PATH = data_path("lite_model.pkl")

FORMAT_VERSION = 2  # tăng lên vì đổi protocol + cải tiến nhỏ
CHAR_NGRAM_SIZES = (3, 4)
TEMPERATURE_GRID = (0.02, 0.03, 0.05, 0.08, 0.12, 0.18, 0.25, 0.35, 0.5, 0.8)

__all__ = [
    "LiteIntentModel",
    "dataset_fingerprint",
    "featurize",
    "get_lite_model",
    "load_lite_model",
    "save_lite_model",
    "train_lite_model",
]


@lru_cache(maxsize=8192)
def _featurize_cached(cleaned: str) -> tuple[str, ...]:
    """Phiên bản cache của featurize (input đã normalize)."""
    if not cleaned:
        return ()
    words = cleaned.split()
    feats: list[str] = []
    for word in words:
        feats.append(f"w:{word}")
        padded = f" {word} "
        for size in CHAR_NGRAM_SIZES:
            if len(padded) >= size:
                for i in range(len(padded) - size + 1):
                    feats.append(f"c:{padded[i:i+size]}")
    for i in range(len(words) - 1):
        feats.append(f"b:{words[i]} {words[i+1]}")
    # Khử trùng lặp giữ thứ tự
    return tuple(dict.fromkeys(feats))


def featurize(text: str | None) -> list[str]:
    cleaned = normalize_text(text or "")
    return list(_featurize_cached(cleaned))


class LiteIntentModel:
    """Naive Bayes đa thức thuần Python, API giống scikit-learn."""

    def __init__(self, alpha: float = 0.15, temperature: float = 0.08):
        self.alpha = alpha
        self.temperature = temperature
        self.classes_: list[str] = []
        self.fingerprint: str | None = None
        self.format_version: int = FORMAT_VERSION
        self._log_prior: dict[str, float] = {}
        self._log_prob: dict[str, dict[str, float]] = {}
        self._log_default: dict[str, float] = {}
        self._vocab: set[str] = set()

    # -- huấn luyện --
    def fit(self, texts: list[str], labels: list[str], calibrate: bool = True) -> LiteIntentModel:
        self._fit_counts(texts, labels)
        if calibrate:
            self.temperature = self._fit_temperature(texts, labels)
        return self

    def _fit_counts(self, texts: list[str], labels: list[str]) -> LiteIntentModel:
        counts: dict[str, dict[str, int]] = {}
        totals: dict[str, int] = {}
        docs: dict[str, int] = {}
        vocab: set[str] = set()

        for text, label in zip(texts, labels):
            feats = featurize(text)
            if label not in counts:
                counts[label] = {}
                totals[label] = 0
                docs[label] = 0
            docs[label] += 1
            bucket = counts[label]
            for feat in feats:
                bucket[feat] = bucket.get(feat, 0) + 1
                vocab.add(feat)
            totals[label] += len(feats)

        n_docs = sum(docs.values()) or 1
        vocab_size = len(vocab) + 1
        alpha = self.alpha

        self.classes_ = sorted(counts)
        self._vocab = set(vocab)      # dung tinh "bao chung tu dien" luc du doan
        self._log_prior = {}
        self._log_prob = {}
        self._log_default = {}
        for label in self.classes_:
            denominator = totals[label] + alpha * vocab_size
            self._log_prior[label] = math.log(docs[label] / float(n_docs))
            self._log_default[label] = math.log(alpha / denominator)
            self._log_prob[label] = {
                feat: math.log((count + alpha) / denominator)
                for feat, count in counts[label].items()
            }
        return self

    def _fit_temperature(self, texts: list[str], labels: list[str]) -> float:
        train_idx = [i for i in range(len(texts)) if i % 7 != 0]
        val_idx = [i for i in range(len(texts)) if i % 7 == 0]
        if not train_idx or not val_idx:
            return self.temperature

        shadow = LiteIntentModel(alpha=self.alpha)
        shadow._fit_counts([texts[i] for i in train_idx], [labels[i] for i in train_idx])
        if set(shadow.classes_) != set(self.classes_):
            return self.temperature

        cached: list[tuple[dict[str, float], str]] = []
        for i in val_idx:
            cached.append((shadow._raw_scores(featurize(texts[i])), labels[i]))

        best_temp = self.temperature
        best_nll = float("inf")
        for temp in TEMPERATURE_GRID:
            nll = 0.0
            for scores, label in cached:
                prob = shadow._softmax(scores, temp).get(label, 1e-12)
                nll -= math.log(max(prob, 1e-12))
            if nll < best_nll:
                best_nll = nll
                best_temp = temp
        return best_temp

    # -- suy luận --
    def _raw_scores(self, feats: list[str]) -> dict[str, float]:
        divisor = float(len(feats)) if feats else 1.0
        scores: dict[str, float] = {}
        for label in self.classes_:
            # .get() thay vi index thang: file .pkl tay tao/sua bang tay co the
            # co classes_ ma thieu bang _log_prob -> KeyError kho hieu luc chay.
            table = self._log_prob.get(label, {})
            default = self._log_default.get(label, -10.0)
            total = self._log_prior.get(label, 0.0)
            for feat in feats:
                total += table.get(feat, default)
            scores[label] = total / divisor
        return scores

    @staticmethod
    def _softmax(scores: dict[str, float], temperature: float) -> dict[str, float]:
        temp = max(float(temperature), 1e-6)
        if not scores:
            return {}
        scaled = {label: value / temp for label, value in scores.items()}
        top = max(scaled.values())
        exps = {label: math.exp(value - top) for label, value in scaled.items()}
        total = sum(exps.values()) or 1.0
        return {label: value / total for label, value in exps.items()}

    def _ensure_vocab(self) -> set[str]:
        """Tập hợp mọi feature đã biết. Suy ra từ chính `_log_prob` nên file
        model cũ (không lưu từ điển) vẫn dùng được, và dung lượng file không đổi.
        """
        if not self._vocab:
            vocab: set[str] = set()
            for table in self._log_prob.values():
                vocab.update(table)
            self._vocab = vocab
        return self._vocab

    def vocabulary_size(self) -> int:
        """Số feature đã thấy lúc huấn luyện (0 nếu model chưa fit)."""
        return len(self._ensure_vocab())

    def evidence_ratio(self, text: str) -> float:
        """Tỷ lệ feature của câu nằm TRONG từ điển huấn luyện: "bảo chứng" rằng
        mô hình thực sự nhận ra chữ, chứ không đoán mò.

        Lý do có con số này: softmax với temperature nhỏ (0.08) khuếch đại rất
        mạnh khoảng cách log-prob, nên một câu VÔ NGHĨA ("asdfgh jklzxbv") vẫn
        nhận được confidence ~0.5 và được trợ lý thực thi bừa. Tỷ lệ từ lạ thì
        ngược lại: câu tiếng Việt thật gần như luôn có từ đã biết, câu linh tinh
        thì không. Char-ngram chỉ tính 25% trọng số - nó giúp chịu lỗi chính tả
        chứ không chứng minh đã hiểu nội dung.
        """
        feats = featurize(text)
        if not feats:
            return 0.0
        vocab = self._ensure_vocab()
        words = [f for f in feats if f.startswith("w:")]
        chars = [f for f in feats if f.startswith("c:")]
        word_hits = sum(1 for f in words if f in vocab)
        char_hits = sum(1 for f in chars if f in vocab)
        word_part = word_hits / float(len(words) or 1)
        char_part = char_hits / float(len(chars) or 1)
        return max(0.0, min(1.0, 0.75 * word_part + 0.25 * char_part))

    def predict_proba_dict(self, text: str) -> dict[str, float]:
        if not self.classes_:
            return {}
        return self._softmax(self._raw_scores(featurize(text)), self.temperature)

    def predict_one(self, text: str) -> tuple[str, float]:
        probs = self.predict_proba_dict(text)
        if not probs:
            return "chitchat", 0.0
        label = max(probs, key=lambda k: probs[k])
        return label, probs[label] * self.evidence_ratio(text)

    def predict(self, texts: list[str]) -> list[str]:
        return [self.predict_one(t)[0] for t in texts]

    def predict_proba(self, texts: list[str]) -> list[list[float]]:
        """Xác suất theo từng lớp, đã NHÂN "bảo chứng từ điển" (evidence_ratio).

        Vì vậy mỗi hàng KHÔNG nhất thiết cộng đủ 1: đây là mức ĐÁNG TIN CẬY của
        câu trả lời chứ không phải phân phối xác suất thô. Tầng NLU dùng chính
        con số này để quyết định "làm luôn" hay "hỏi lại"; `predict_proba_dict()`
        vẫn trả về softmax nguyên bản cho ai cần phân phối thật.
        """
        rows = []
        for text in texts:
            probs = self.predict_proba_dict(text)
            evidence = self.evidence_ratio(text)
            rows.append([probs.get(label, 0.0) * evidence for label in self.classes_])
        return rows

    def score(self, texts: list[str], labels: list[str]) -> float:
        if not texts:
            return 0.0
        hit = sum(1 for text, label in zip(texts, labels) if self.predict_one(text)[0] == label)
        return hit / float(len(texts))

    def explain(self, text: str, top_k: int = 5) -> list[tuple[str, float]]:
        """Trả về top_k đặc trưng đóng góp nhiều nhất cho nhãn dự đoán."""
        label, _ = self.predict_one(text)
        feats = featurize(text)
        table = self._log_prob.get(label, {})
        default = self._log_default.get(label, 0.0)
        scored = [(f, table.get(f, default)) for f in feats]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    # -- lưu / nạp --
    def to_state(self) -> dict:
        return {
            "format_version": self.format_version,
            "alpha": self.alpha,
            "temperature": self.temperature,
            "classes": self.classes_,
            "fingerprint": self.fingerprint,
            "log_prior": self._log_prior,
            "log_prob": self._log_prob,
            "log_default": self._log_default,
        }

    @classmethod
    def from_state(cls, state: dict) -> LiteIntentModel:
        model = cls(alpha=state.get("alpha", 0.15), temperature=state.get("temperature", 0.08))
        model.format_version = state.get("format_version", 0)
        model.classes_ = list(state.get("classes", []))
        model.fingerprint = state.get("fingerprint")
        model._log_prior = state.get("log_prior", {})
        model._log_prob = state.get("log_prob", {})
        model._log_default = state.get("log_default", {})
        return model


def dataset_fingerprint(texts: list[str], labels: list[str]) -> str:
    # usedforsecurity=False: day chi la MA NHAN DIEN dataset (phat hien model
    # cu), khong phai muc dich an toan. Python bien chay trong che do FIPS
    # (may co quan, Windows EnableFIPSMode) tu choi hashlib.sha1() -> ValueError
    # va toan bo tro ly chet ngay luc nap model. Chi dinh ro "khong dung cho bao
    # mat" giup chay duoc tren moi may (hashlib ho tro tu Python 3.9).
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(str(FORMAT_VERSION).encode("utf-8"))
    for text, label in zip(texts, labels):
        digest.update(text.encode("utf-8", "ignore"))
        digest.update(b"\x00")
        digest.update(label.encode("utf-8", "ignore"))
        digest.update(b"\x01")
    return digest.hexdigest()


def save_lite_model(model: LiteIntentModel, path: Path | str = LITE_MODEL_PATH) -> bool:
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".lite_tmp_", suffix=".pkl")
        with os.fdopen(fd, "wb") as handle:
            pickle.dump(model.to_state(), handle, protocol=4)
        Path(tmp).replace(path)
        return True
    except OSError:
        return False
    except Exception:  # pragma: no cover - pickle/encoding bi hong
        # Goi bao luon `return False` truoc day, nen loi khac (pickling, duong
        # dan toi han tren Windows) bay thang ra ngoai va lam mat ca lan huan
        # luyen vua chay xong. Save model la buoc cuoi - khong duoc phep sap.
        try:
            Path(tmp).unlink(missing_ok=True)
        except OSError:
            pass
        return False


def load_lite_model(
    path: Path | str = LITE_MODEL_PATH, fingerprint: str | None = None
) -> LiteIntentModel | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        with path.open("rb") as handle:
            # pickle CHỈ được nạp từ file model do chính dự án này
            # sinh ra (lite_model.pkl trong thư mục cài đặt), tức vùng tin cậy
            # (trust boundary) là đĩa của người dùng. Nếu sau này cho phép nạp
            # model tải từ nơi khác thì PHẢI đổi sang định dạng dữ liệu thuần
            # (JSON/npz) - pickle từ nguồn lạ tương đương thực thi mã tuỳ ý.
            state = pickle.load(handle)  # noqa: S301
    except Exception:
        return None
    if not isinstance(state, dict):
        return None
    # Chấp nhận cả version 1 và 2 để tương thích ngược
    if state.get("format_version") not in (1, FORMAT_VERSION):
        return None
    if fingerprint is not None and state.get("fingerprint") != fingerprint:
        return None
    model = LiteIntentModel.from_state(state)
    # Cập nhật version lên mới nhất khi load
    model.format_version = FORMAT_VERSION
    return model if model.classes_ else None


def train_lite_model(
    texts: list[str] | None = None, labels: list[str] | None = None, show_report: bool = False
) -> LiteIntentModel:
    if texts is None or labels is None:
        from dataset import get_dataset_as_lists

        texts, labels = get_dataset_as_lists()

    model = LiteIntentModel().fit(texts, labels)
    model.fingerprint = dataset_fingerprint(texts, labels)

    if show_report:
        from platform_utils import safe_print

        holdout_x = [texts[i] for i in range(len(texts)) if i % 7 == 0]
        holdout_y = [labels[i] for i in range(len(labels)) if i % 7 == 0]
        safe_print(
            f"[MODEL NHẸ] {len(texts)} câu | {len(model.classes_)} nhãn "
            f"| nhiệt độ {model.temperature}"
        )
        safe_print(f"[MODEL NHẸ] Độ chính xác holdout: {model.score(holdout_x, holdout_y):.1%}")
    return model


def get_lite_model(
    path: Path | str = LITE_MODEL_PATH, force_retrain: bool = False
) -> LiteIntentModel:
    from dataset import get_dataset_as_lists

    texts, labels = get_dataset_as_lists()
    fingerprint = dataset_fingerprint(texts, labels)

    if not force_retrain:
        cached = load_lite_model(path, fingerprint=fingerprint)
        if cached is not None:
            return cached

    model = train_lite_model(texts, labels)
    save_lite_model(model, path)
    return model


if __name__ == "__main__":
    from platform_utils import safe_print, setup_console

    setup_console()
    lite = train_lite_model(show_report=True)
    safe_print("")
    for sample in [
        "Bật Google lên",
        "mo youtube nghe nhac di",
        "khởi chạy vs code giúp tôi",
        "tat may tinh di",
        "nhắc tôi họp lúc 3 giờ chiều",
        "15 cộng 27 bằng bao nhiêu",
        "xin chào bạn",
        "asdkjh qwe zxc khong lien quan gi ca",
    ]:
        intent, confidence = lite.predict_one(sample)
        safe_print(f"{sample!r:44} -> {intent:<14} ({confidence:.1%})")
