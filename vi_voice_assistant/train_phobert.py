# -*- coding: utf-8 -*-
"""
train_phobert.py
-----------------
FINE-TUNE PhoBERT để phân loại ý định (intent) — thay thế nâng cao cho
intent_model.pkl (TF-IDF). Độ chính xác cao hơn hẳn với câu lạ, câu dài,
câu viết không theo khuôn mẫu có sẵn trong dataset.py.

Yêu cầu cài thêm (xem requirements.txt):
    pip install torch transformers

Cách chạy:
    python train_phobert.py                       # mặc định 4 epoch
    python train_phobert.py --epochs 6 --batch-size 16
    python train_phobert.py --no-feedback          # bỏ qua feedback.csv

Kết quả: lưu model + tokenizer + labels.json vào thư mục phobert_model/.
Sau khi chạy xong, intent_model.py sẽ tự động dùng PhoBERT thay vì TF-IDF.

GỢI Ý: nếu máy không có GPU, hãy huấn luyện trên Google Colab (có GPU miễn
phí) rồi tải thư mục phobert_model/ về máy.
"""

import argparse
import csv
import json
import os

from dataset import get_dataset_as_lists
from platform_utils import safe_print, setup_console

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "phobert_model")
CHECKPOINT_DIR = os.path.join(BASE_DIR, "phobert_checkpoints")
EXTRA_CSV = os.path.join(BASE_DIR, "my_dataset.csv")
FEEDBACK_CSV = os.path.join(BASE_DIR, "feedback.csv")
BASE_CHECKPOINT = "vinai/phobert-base"


# ============================================================================
# 1. GỘP Dữ LIỆU TỪ NHIỀU NGUỒN (giống train_nlu.py)
# ============================================================================
def load_training_data(use_feedback: bool = True):
    """Gộp dataset gốc (dataset.py) + my_dataset.csv + feedback.csv đã xác nhận."""
    texts, labels = get_dataset_as_lists()
    texts, labels = list(texts), list(labels)
    safe_print(f"[1] Dataset gốc        : {len(texts)} câu")

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

    n_fb = 0
    if use_feedback and os.path.exists(FEEDBACK_CSV):
        with open(FEEDBACK_CSV, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if str(row.get("verified", "0")).strip() != "1":
                    continue
                text = (row.get("text") or "").strip()
                intent = (row.get("intent") or "").strip()
                if text and intent:
                    texts.append(text)
                    labels.append(intent)
                    n_fb += 1
    safe_print(f"[3] feedback đã xác nhận: {n_fb} câu")

    return texts, labels


# ============================================================================
# 2. DATASET CHO PYTORCH
# ============================================================================
def build_torch_dataset(tokenizer, texts, label_ids, max_length):
    import torch

    class IntentTorchDataset(torch.utils.data.Dataset):
        def __init__(self, texts, label_ids, tokenizer, max_length):
            self.encodings = tokenizer(
                list(texts),
                truncation=True,
                padding=True,
                max_length=max_length,
            )
            self.labels = list(label_ids)

        def __len__(self):
            return len(self.labels)

        def __getitem__(self, idx):
            item = {k: torch.tensor(v[idx]) for k, v in self.encodings.items()}
            item["labels"] = torch.tensor(self.labels[idx])
            return item

    return IntentTorchDataset(texts, label_ids, tokenizer, max_length)


# ============================================================================
# 3. HUẤN LUYỆN
# ============================================================================
def train(args):
    import numpy as np
    from sklearn.model_selection import train_test_split
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
    )

    safe_print("=" * 70)
    safe_print("FINE-TUNE PhoBERT CHO PHÂN LOẠI Ý ĐỊNH")
    safe_print("=" * 70)

    texts, labels = load_training_data(use_feedback=not args.no_feedback)
    label_names = sorted(set(labels))
    label2id = {label: i for i, label in enumerate(label_names)}
    label_ids = [label2id[label] for label in labels]

    safe_print(f"\nTỔNG: {len(texts)} câu / {len(label_names)} nhóm ý định")
    for name in label_names:
        count = labels.count(name)
        safe_print(f"  {name:<16} {count:>5}")

    X_train, X_val, y_train, y_val = train_test_split(
        texts, label_ids, test_size=0.15, random_state=42, stratify=label_ids
    )

    safe_print(f"\n[Model] Nạp checkpoint gốc: {args.model}")
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model, num_labels=len(label_names)
    )

    train_ds = build_torch_dataset(tokenizer, X_train, y_train, args.max_length)
    val_ds = build_torch_dataset(tokenizer, X_val, y_val, args.max_length)

    def compute_metrics(eval_pred):
        from sklearn.metrics import accuracy_score, f1_score

        logits, refs = eval_pred
        preds = np.argmax(logits, axis=-1)
        return {
            "accuracy": accuracy_score(refs, preds),
            "f1_macro": f1_score(refs, preds, average="macro"),
        }

    common_kwargs = dict(
        output_dir=CHECKPOINT_DIR,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        learning_rate=args.lr,
        weight_decay=0.01,
        logging_steps=20,
        save_total_limit=1,
        load_best_model_at_end=True,
        metric_for_best_model="f1_macro",
        report_to=[],
    )

    # Phiên bản transformers mới đổi tên tham số evaluation_strategy -> eval_strategy
    try:
        training_args = TrainingArguments(
            eval_strategy="epoch", save_strategy="epoch", **common_kwargs
        )
    except TypeError:
        training_args = TrainingArguments(
            evaluation_strategy="epoch", save_strategy="epoch", **common_kwargs
        )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        compute_metrics=compute_metrics,
    )

    safe_print("\n[Train] Bắt đầu huấn luyện...")
    trainer.train()

    safe_print("\n[Eval] Kết quả trên tập validation:")
    metrics = trainer.evaluate()
    for k, v in metrics.items():
        safe_print(f"  {k}: {v}")

    os.makedirs(MODEL_DIR, exist_ok=True)
    trainer.save_model(MODEL_DIR)
    tokenizer.save_pretrained(MODEL_DIR)
    with open(os.path.join(MODEL_DIR, "labels.json"), "w", encoding="utf-8") as f:
        json.dump(label_names, f, ensure_ascii=False, indent=2)

    safe_print(f"\nĐã lưu model vào: {MODEL_DIR}/")
    safe_print("Từ giờ main.py / intent_model.py sẽ tự động dùng PhoBERT.")

    # --- Kiểm tra nhanh ---
    safe_print("\n[Test nhanh]")
    from phobert_model import PhoBertIntentClassifier

    clf = PhoBertIntentClassifier(model_dir=MODEL_DIR, max_length=args.max_length)
    clf.load()
    for sample in ["mở giúp tôi facebook", "15 cộng 27 bằng bao nhiêu", "mấy giờ rồi", "hát cho tôi nghe một bài"]:
        intent, conf = clf.predict(sample)
        safe_print(f"  {sample!r:40} -> {intent} ({conf:.2%})")


def main():
    parser = argparse.ArgumentParser(description="Fine-tune PhoBERT cho phân loại ý định")
    parser.add_argument("--model", default=BASE_CHECKPOINT, help="Checkpoint gốc (mặc định vinai/phobert-base — giấy phép MIT, an toàn cho dùng thương mại; TRÁNH dùng vinai/phobert-base-v2 vì license AGPL-3.0 có thể buộc bạn phải mở mã nguồn toàn bộ ứng dụng nếu host qua mạng)")
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--max-length", type=int, default=64)
    parser.add_argument("--no-feedback", action="store_true", help="Bỏ qua feedback.csv khi gộp dữ liệu")
    args = parser.parse_args()
    train(args)


if __name__ == "__main__":
    setup_console()
main()
