"""
train_phobert.py v7.4
---------------------
v7.0 nâng cấp:
- Thêm type hints, pathlib, logging
- Atomic save, validation
-----------------
FINE-TUNE PhoBERT
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

from __future__ import annotations

import argparse
import inspect
import math
import os
import sys

from csv_utils import read_keyed_csv
from dataset import get_dataset_as_lists
from paths import atomic_write_json, data_path
from phobert_model import MODEL_DIR
from platform_utils import safe_print, setup_console

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_DIR = str(data_path("phobert_checkpoints"))
EXTRA_CSV = str(data_path("my_dataset.csv"))
FEEDBACK_CSV = str(data_path("feedback.csv"))
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
        for row in read_keyed_csv(EXTRA_CSV, ("text", "intent")):
            text = (row.get("text") or "").strip()
            intent = (row.get("intent") or "").strip()
            if text and intent:
                texts.append(text)
                labels.append(intent)
                n_extra += 1
    safe_print(f"[2] my_dataset.csv     : {n_extra} câu")

    n_fb = 0
    if use_feedback and os.path.exists(FEEDBACK_CSV):
        columns = ("time", "text", "intent", "confidence", "verified")
        for row in read_keyed_csv(FEEDBACK_CSV, columns):
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
    options = {"local_files_only": getattr(args, "local_files_only", False),
               "trust_remote_code": False}
    tokenizer = AutoTokenizer.from_pretrained(args.model, **options)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model, num_labels=len(label_names), **options
    )

    model.config.id2label = {i: label for label, i in label2id.items()}
    model.config.label2id = dict(label2id)

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

    common_kwargs = {
        "output_dir": CHECKPOINT_DIR,
        "num_train_epochs": args.epochs,
        "per_device_train_batch_size": args.batch_size,
        "per_device_eval_batch_size": args.batch_size,
        "learning_rate": args.lr,
        "weight_decay": 0.01,
        "logging_steps": 20,
        "save_total_limit": 1,
        "load_best_model_at_end": True,
        "metric_for_best_model": "f1_macro",
        "report_to": [],
    }

    parameters = inspect.signature(TrainingArguments).parameters
    strategy = "eval_strategy" if "eval_strategy" in parameters else "evaluation_strategy"
    if strategy not in parameters:
        raise RuntimeError("Transformers TrainingArguments không hỗ trợ evaluation strategy.")
    training_args = TrainingArguments(**{strategy: "epoch", "save_strategy": "epoch"},
                                      **common_kwargs)

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
    atomic_write_json(os.path.join(MODEL_DIR, "labels.json"), label_names)

    safe_print(f"\nĐã lưu model vào: {MODEL_DIR}/")
    safe_print("Từ giờ main.py / intent_model.py sẽ tự động dùng PhoBERT.")

    # --- Kiểm tra nhanh ---
    safe_print("\n[Test nhanh]")
    from phobert_model import PhoBertIntentClassifier

    clf = PhoBertIntentClassifier(model_dir=MODEL_DIR, max_length=args.max_length)
    clf.load()
    for sample in [
        "mở giúp tôi facebook",
        "15 cộng 27 bằng bao nhiêu",
        "mấy giờ rồi",
        "hát cho tôi nghe một bài",
    ]:
        intent, conf = clf.predict(sample)
        safe_print(f"  {sample!r:40} -> {intent} ({conf:.2%})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fine-tune PhoBERT cho phân loại ý định")
    parser.add_argument(
        "--model",
        default=BASE_CHECKPOINT,
        help=(
            "Checkpoint gốc (mặc định vinai/phobert-base). Kiểm tra giấy phép "
            "code/trọng số/dataset của checkpoint cụ thể trước phân phối hoặc thương mại."
        ),
    )
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--max-length", type=int, default=64)
    parser.add_argument(
        "--no-feedback", action="store_true", help="Bỏ qua feedback.csv khi gộp dữ liệu"
    )
    parser.add_argument("--local-files-only", action="store_true",
                        help="chỉ dùng checkpoint/tokenizer đã có trong cache local")
    args = parser.parse_args(argv)
    if args.epochs < 1 or args.batch_size < 1 or not 1 <= args.max_length <= 512:
        parser.error("epochs/batch-size phải dương và max-length trong [1,512].")
    if not math.isfinite(args.lr) or args.lr <= 0:
        parser.error("learning rate phải dương và hữu hạn.")
    try:
        train(args)
    except Exception as error:
        safe_print(f"[LỖI] Huấn luyện PhoBERT chưa hoàn tất: {error}")
        return 1
    return 0


if __name__ == "__main__":
    setup_console()
    sys.exit(main())
