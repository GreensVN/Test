# -*- coding: utf-8 -*-
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
from typing import Dict, List, Tuple

from text_utils import normalize_text

BASE_DIR = Path(__file__).resolve().parent
LITE_MODEL_PATH = BASE_DIR / "lite_model.pkl"

FORMAT_VERSION = 2  # tăng lên vì đổi protocol + cải tiến nhỏ
CHAR_NGRAM_SIZES = (3, 4)
TEMPERATURE_GRID = (0.02, 0.03, 0.05, 0.08, 0.12, 0.18, 0.25, 0.35, 0.5, 0.8)

__all__ = [
    "LiteIntentModel",
    "featurize",
    "dataset_fingerprint",
    "save_lite_model",
    "load_lite_model",
    "train_lite_model",
    "get_lite_model",
]


@lru_cache(maxsize=8192)
def _featurize_cached(cleaned: str) -> Tuple[str, ...]:
    """Phiên bản cache của featurize (input đã normalize)."""
    if not cleaned:
        return ()
    words = cleaned.split()
    feats: List[str] = []
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


def featurize(text: str | None) -> List[str]:
    cleaned = normalize_text(text or "")
    return list(_featurize_cached(cleaned))


class LiteIntentModel:
    """Naive Bayes đa thức thuần Python, API giống scikit-learn."""

    def __init__(self, alpha: float = 0.15, temperature: float = 0.08):
        self.alpha = alpha
        self.temperature = temperature
        self.classes_: List[str] = []
        self.fingerprint: str | None = None
        self.format_version: int = FORMAT_VERSION
        self._log_prior: Dict[str, float] = {}
        self._log_prob: Dict[str, Dict[str, float]] = {}
        self._log_default: Dict[str, float] = {}

    # -- huấn luyện --
    def fit(self, texts: List[str], labels: List[str], calibrate: bool = True) -> "LiteIntentModel":
        self._fit_counts(texts, labels)
        if calibrate:
            self.temperature = self._fit_temperature(texts, labels)
        return self

    def _fit_counts(self, texts: List[str], labels: List[str]) -> "LiteIntentModel":
        counts: Dict[str, Dict[str, int]] = {}
        totals: Dict[str, int] = {}
        docs: Dict[str, int] = {}
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

    def _fit_temperature(self, texts: List[str], labels: List[str]) -> float:
        train_idx = [i for i in range(len(texts)) if i % 7 != 0]
        val_idx = [i for i in range(len(texts)) if i % 7 == 0]
        if not train_idx or not val_idx:
            return self.temperature

        shadow = LiteIntentModel(alpha=self.alpha)
        shadow._fit_counts([texts[i] for i in train_idx], [labels[i] for i in train_idx])
        if set(shadow.classes_) != set(self.classes_):
            return self.temperature

        cached: List[Tuple[Dict[str, float], str]] = []
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
    def _raw_scores(self, feats: List[str]) -> Dict[str, float]:
        divisor = float(len(feats)) if feats else 1.0
        scores: Dict[str, float] = {}
        for label in self.classes_:
            table = self._log_prob[label]
            default = self._log_default[label]
            total = self._log_prior[label]
            for feat in feats:
                total += table.get(feat, default)
            scores[label] = total / divisor
        return scores

    @staticmethod
    def _softmax(scores: Dict[str, float], temperature: float) -> Dict[str, float]:
        temp = max(float(temperature), 1e-6)
        if not scores:
            return {}
        scaled = {label: value / temp for label, value in scores.items()}
        top = max(scaled.values())
        exps = {label: math.exp(value - top) for label, value in scaled.items()}
        total = sum(exps.values()) or 1.0
        return {label: value / total for label, value in exps.items()}

    def predict_proba_dict(self, text: str) -> Dict[str, float]:
        if not self.classes_:
            return {}
        return self._softmax(self._raw_scores(featurize(text)), self.temperature)

    def predict_one(self, text: str) -> Tuple[str, float]:
        probs = self.predict_proba_dict(text)
        if not probs:
            return "chitchat", 0.0
        label = max(probs, key=lambda k: probs[k])
        return label, probs[label]

    def predict(self, texts: List[str]) -> List[str]:
        return [self.predict_one(t)[0] for t in texts]

    def predict_proba(self, texts: List[str]) -> List[List[float]]:
        rows = []
        for text in texts:
            probs = self.predict_proba_dict(text)
            rows.append([probs.get(label, 0.0) for label in self.classes_])
        return rows

    def score(self, texts: List[str], labels: List[str]) -> float:
        if not texts:
            return 0.0
        hit = sum(1 for t, l in zip(texts, labels) if self.predict_one(t)[0] == l)
        return hit / float(len(texts))

    def explain(self, text: str, top_k: int = 5) -> List[Tuple[str, float]]:
        """Trả về top_k đặc trưng đóng góp nhiều nhất cho nhãn dự đoán."""
        label, _ = self.predict_one(text)
        feats = featurize(text)
        table = self._log_prob.get(label, {})
        default = self._log_default.get(label, 0.0)
        scored = [(f, table.get(f, default)) for f in feats]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    # -- lưu / nạp --
    def to_state(self) -> Dict:
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
    def from_state(cls, state: Dict) -> "LiteIntentModel":
        model = cls(alpha=state.get("alpha", 0.15), temperature=state.get("temperature", 0.08))
        model.format_version = state.get("format_version", 0)
        model.classes_ = list(state.get("classes", []))
        model.fingerprint = state.get("fingerprint")
        model._log_prior = state.get("log_prior", {})
        model._log_prob = state.get("log_prob", {})
        model._log_default = state.get("log_default", {})
        return model


def dataset_fingerprint(texts: List[str], labels: List[str]) -> str:
    digest = hashlib.sha1()
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


def load_lite_model(path: Path | str = LITE_MODEL_PATH, fingerprint: str | None = None) -> LiteIntentModel | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        with path.open("rb") as handle:
            state = pickle.load(handle)
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
    texts: List[str] | None = None, labels: List[str] | None = None, show_report: bool = False
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
            f"[MODEL NHẸ] {len(texts)} câu | {len(model.classes_)} nhãn | nhiệt độ {model.temperature}"
        )
        safe_print(f"[MODEL NHẸ] Độ chính xác holdout: {model.score(holdout_x, holdout_y):.1%}")
    return model


def get_lite_model(path: Path | str = LITE_MODEL_PATH, force_retrain: bool = False) -> LiteIntentModel:
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
