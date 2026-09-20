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
import os
from typing import Any

from platform_utils import safe_print, setup_console

# v6.1: neo đường dẫn vào thư mục chứa file này. Trước đây là đường dẫn
# TƯƠNG ĐỐI "phobert_model" - nếu chạy từ thư mục khác (vd Task Scheduler gọi
# "python C:\...\main.py --once ..."), is_trained() tìm sai chỗ và PhoBERT âm
# thầm không được dùng dù đã huấn luyện xong.
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "phobert_model")
BASE_CHECKPOINT = "vinai/phobert-base"
MAX_LENGTH = 64


class PhoBertIntentClassifier:
    """Bọc quanh model PhoBERT đã fine-tune để phân loại ý định (intent)."""

    def __init__(self, model_dir: str = MODEL_DIR, max_length: int = MAX_LENGTH):
        self.model_dir = model_dir
        self.max_length = max_length
        self.model: Any = None
        self.tokenizer: Any = None
        self.labels = None
        self.device = None

    # ------------------------------------------------------------------
    def is_trained(self) -> bool:
        """Kiểm tra đã có model PhoBERT đã fine-tune trong model_dir chưa."""
        if not os.path.isdir(self.model_dir):
            return False
        labels_path = os.path.join(self.model_dir, "labels.json")
        config_path = os.path.join(self.model_dir, "config.json")
        return os.path.isfile(labels_path) and os.path.isfile(config_path)

    # ------------------------------------------------------------------
    def load(self):
        """Nạp model + tokenizer + danh sách nhãn vào bộ nhớ (chỉ 1 lần)."""
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        labels_path = os.path.join(self.model_dir, "labels.json")
        with open(labels_path, encoding="utf-8") as f:
            self.labels = json.load(f)

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_dir)
        self.model = AutoModelForSequenceClassification.from_pretrained(self.model_dir)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)
        self.model.eval()
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

        intent = self.labels[idx] if self.labels and idx < len(self.labels) else str(idx)
        return intent, confidence

    def predict_proba_dict(self, text: str) -> dict:
        """Trả về xác suất của TẤT CẢ nhãn (dùng để debug / hiển thị chi tiết)."""
        import torch

        if self.model is None or self.tokenizer is None:
            self.load()

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
