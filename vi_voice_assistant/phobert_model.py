"""
phobert_model.py v7.4
---------------------
v7.0 nâng cấp:
- Thêm type hints, pathlib, logging
- Dùng Path thay cho os.path
- Atomic save, validation
-----------------
Bộ phân loại ý định (intent) dùng PhoBERT
Bộ phân loại ý định (intent) dùng PhoBERT — lựa chọn NÂNG CAO thay cho
TF-IDF trong intent_model.py, hiểu câu tốt hơn nhiều (kể cả câu dài, câu lạ,
câu chưa từng thấy) vì PhoBERT đã học sẵn tiếng Việt trên khối dữ liệu khổng lồ.

Cách dùng:
    1. Cài thư viện (xem requirements.txt, phần PhoBERT):
           pip install torch transformers
    2. Huấn luyện: python train_phobert.py
       -> tạo ra thư mục phobert_model/ (chứa model + tokenizer + labels.json)
    3. intent_model.py sẽ TỰ ĐỘNG ưu tiên dùng PhoBERT nếu đã huấn luyện xong.
       Nếu chưa huấn luyện, hệ thống tự quay lại dùng model TF-IDF cũ — không lỗi.

Lưu ý: mọi import torch/transformers được đặt BÊN TRONG hàm/phương thức
(không đặt ở đầu file) để file này và intent_model.py vẫn import được
bình thường ngay cả khi máy CHƯA cài torch/transformers.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from paths import data_path
from platform_utils import safe_print, setup_console

# Runtime assets use the selected user data home; explicit legacy model_dir
# remains available, but installed package weights are not silently adopted.
MODEL_DIR = str(data_path("phobert_model"))
BASE_CHECKPOINT = "vinai/phobert-base"
MAX_LENGTH = 64


class PhoBertIntentClassifier:
    """Bọc quanh model PhoBERT đã fine-tune để phân loại ý định (intent)."""

    def __init__(self, model_dir: str | Path | None = None, max_length: int = MAX_LENGTH):
        if isinstance(max_length, bool) or not isinstance(max_length, int):
            raise TypeError("max_length phải là integer.")
        if not 1 <= max_length <= 512:
            raise ValueError("max_length phải trong [1,512].")
        selected = MODEL_DIR if model_dir is None else model_dir
        self.model_dir = str(Path(selected).expanduser().absolute())
        self.max_length = max_length
        self.model: Any = None
        self.tokenizer: Any = None
        self.labels: list[str] | None = None
        self.device: Any = None

    def _metadata(self) -> list[str]:
        root = Path(self.model_dir)
        with (root / "labels.json").open(encoding="utf-8-sig") as stream:
            labels = json.load(stream)
        if (not isinstance(labels, list) or not labels
                or any(not isinstance(item, str) or not item.strip() for item in labels)
                or len(set(labels)) != len(labels)):
            raise ValueError("PhoBERT labels.json phải là list[str] không rỗng, không trùng.")
        with (root / "config.json").open(encoding="utf-8-sig") as stream:
            configuration = json.load(stream)
        if not isinstance(configuration, dict):
            raise ValueError("PhoBERT config.json phải là object.")
        weights = ("model.safetensors", "pytorch_model.bin", "model.safetensors.index.json",
                   "pytorch_model.bin.index.json")
        if not any((root / name).is_file() for name in weights):
            raise ValueError("PhoBERT chưa có trọng số local.")
        return labels

    def is_trained(self) -> bool:
        """Bundle metadata/weight presence, not proof of successful inference."""
        try:
            self._metadata()
            return True
        except (OSError, ValueError, TypeError, RecursionError):
            return False

    @staticmethod
    def _validate_mapping(model, labels: list[str], max_length: int) -> None:
        config = model.config
        count = getattr(config, "num_labels", None)
        if isinstance(count, bool) or not isinstance(count, int) or count != len(labels):
            raise ValueError("PhoBERT num_labels không khớp labels.json.")
        mapping = getattr(config, "id2label", None)
        if mapping is not None:
            if not isinstance(mapping, dict) or len(mapping) != len(labels):
                raise ValueError("PhoBERT id2label không hợp lệ.")
            ordered = [mapping.get(i, mapping.get(str(i))) for i in range(len(labels))]
            if ordered not in (labels, [f"LABEL_{i}" for i in range(len(labels))]):
                raise ValueError("PhoBERT id2label không khớp labels.json.")
        capacity = getattr(config, "max_position_embeddings", None)
        if isinstance(capacity, int) and max_length > capacity:
            raise ValueError("max_length vượt capacity của checkpoint.")

    def load(self):
        """Load local assets without remote code, publish state only after validation."""
        labels = self._metadata()
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        options = {"local_files_only": True, "trust_remote_code": False}
        tokenizer = AutoTokenizer.from_pretrained(self.model_dir, **options)
        model = AutoModelForSequenceClassification.from_pretrained(self.model_dir, **options)
        self._validate_mapping(model, labels, self.max_length)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model.to(device)
        model.eval()
        self.labels, self.tokenizer, self.model, self.device = labels, tokenizer, model, device
        return self

    # ------------------------------------------------------------------
    def _encode(self, text: str):
        return self.tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            padding=True,
            max_length=self.max_length,
        ).to(self.device)

    def predict(self, text: str):
        """Dự đoán 1 câu -> (intent: str, confidence: float 0..1)."""
        import torch

        if self.model is None or self.tokenizer is None:
            self.load()

        inputs = self._encode(text)
        with torch.no_grad():
            logits = self.model(**inputs).logits
            probs = torch.softmax(logits, dim=-1)[0]
            idx = int(torch.argmax(probs).item())
            confidence = float(probs[idx].item())

        if (not self.labels or not 0 <= idx < len(self.labels)
                or not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0):
            raise ValueError("PhoBERT prediction không khớp label/probability hợp lệ.")
        return self.labels[idx], confidence

    def predict_proba_dict(self, text: str) -> dict:
        """Trả về xác suất của TẤT CẢ nhãn (dùng để debug / hiển thị chi tiết)."""
        import torch

        if self.model is None or self.tokenizer is None:
            self.load()

        # v7.2: self.labels = None khi label.json thuat/duoc goi ma chua load ->
        # zip(None, ...) nem TypeError kho hieu. Tra ve dict trong khi cho doi.
        if not self.labels:
            return {}

        inputs = self._encode(text)
        with torch.no_grad():
            logits = self.model(**inputs).logits
            probs = torch.softmax(logits, dim=-1)[0].tolist()

        if (len(probs) != len(self.labels)
                or any(not math.isfinite(p) or not 0 <= p <= 1 for p in probs)):
            raise ValueError("PhoBERT probability row không hợp lệ.")
        return {label: round(p, 4) for label, p in zip(self.labels, probs)}


if __name__ == "__main__":
    setup_console()
    clf = PhoBertIntentClassifier()
    if not clf.is_trained():
        safe_print("Chưa có model PhoBERT. Hãy chạy: python train_phobert.py")
    else:
        clf.load()
        for s in ["mở giúp tôi facebook", "15 cộng 27 bằng bao nhiêu", "mấy giờ rồi"]:
            intent, conf = clf.predict(s)
            safe_print(f"{s!r:40} -> {intent} ({conf:.2%})")
