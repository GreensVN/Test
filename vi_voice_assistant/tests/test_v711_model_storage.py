"""Optional PhoBERT assets belong to the data home, and malformed bundles stay unloaded."""

import importlib
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import phobert_model
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _bundle(directory, labels=None, *, weight=True):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "config.json").write_text('{"num_labels": 2}', encoding="utf-8")
    (directory / "labels.json").write_text(json.dumps(["open_app", "chitchat"] if labels is None
                                                    else labels), encoding="utf-8-sig")
    if weight:
        (directory / "model.safetensors").write_bytes(b"fake weights; never loaded by torch")
    return directory


@pytest.mark.parametrize("module,attribute,leaf", [("phobert_model", "MODEL_DIR", "phobert_model"),
                                                 ("train_phobert", "MODEL_DIR", "phobert_model"),
                                                 ("train_phobert", "CHECKPOINT_DIR",
                                                  "phobert_checkpoints"),
                                                 ("train_phobert", "EXTRA_CSV", "my_dataset.csv"),
                                                 ("train_nlu", "EXTRA_CSV", "my_dataset.csv")])
def test_model_and_training_paths_respect_explicit_data_home(tmp_path, module, attribute, leaf):
    home = tmp_path / "private"
    code = (f"import importlib, pathlib; m=importlib.import_module('vi_voice_assistant.{module}'); "
            f"assert pathlib.Path(getattr(m, {attribute!r})) == pathlib.Path({str(home / leaf)!r})")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                            env=dict(os.environ, VI_ASSISTANT_HOME=str(home)), timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("labels", [{"0": "open_app"}, "open_app", [], [1], [None],
                                    ["open_app", "open_app"], [""]])
def test_invalid_label_metadata_is_not_a_trained_model(tmp_path, labels):
    directory = _bundle(tmp_path / "model", labels)
    assert phobert_model.PhoBertIntentClassifier(str(directory)).is_trained() is False


def test_metadata_without_weights_does_not_claim_to_be_trained(tmp_path):
    directory = _bundle(tmp_path / "model", weight=False)
    assert phobert_model.PhoBertIntentClassifier(str(directory)).is_trained() is False


def test_valid_bom_label_metadata_is_supported_without_loading_ai(tmp_path):
    directory = _bundle(tmp_path / "model")
    assert phobert_model.PhoBertIntentClassifier(str(directory)).is_trained() is True


@pytest.mark.parametrize("length", [0, -1, True, "64", 10 ** 20])
def test_invalid_token_limit_is_rejected_before_tokenizer(length):
    with pytest.raises((TypeError, ValueError)):
        phobert_model.PhoBertIntentClassifier(max_length=length)


def _fake_transformers(monkeypatch, *, fail=False, count=2, mapping=None):
    calls = []
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    torch.device = lambda value: value
    tf = types.ModuleType("transformers")

    class Tokenizer:
        @classmethod
        def from_pretrained(cls, name, **kwargs):
            calls.append(("tokenizer", kwargs))
            return object()

    class Model:
        @classmethod
        def from_pretrained(cls, name, **kwargs):
            calls.append(("model", kwargs))
            if fail:
                raise OSError("weights unavailable")
            cfg = types.SimpleNamespace(num_labels=count, id2label=mapping)
            return types.SimpleNamespace(config=cfg, to=lambda dev: None, eval=lambda: None)

    tf.AutoTokenizer, tf.AutoModelForSequenceClassification = Tokenizer, Model
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", tf)
    return calls


def test_model_loading_is_local_only_and_does_not_execute_remote_code(tmp_path, monkeypatch):
    directory = _bundle(tmp_path / "model")
    calls = _fake_transformers(monkeypatch)
    instance = phobert_model.PhoBertIntentClassifier(str(directory))
    assert instance.load() is instance
    assert instance.labels == ["open_app", "chitchat"]
    assert len(calls) == 2
    assert all(options["local_files_only"] is True and options["trust_remote_code"] is False
               for _, options in calls)


def test_failed_model_load_does_not_publish_partial_instance_state(tmp_path, monkeypatch):
    directory = _bundle(tmp_path / "model")
    _fake_transformers(monkeypatch, fail=True)
    instance = phobert_model.PhoBertIntentClassifier(str(directory))
    with pytest.raises(OSError):
        instance.load()
    assert instance.model is None and instance.tokenizer is None and instance.labels is None


@pytest.mark.parametrize("count,mapping", [(3, None), (2, {0: "chitchat", 1: "open_app"})])
def test_model_label_count_or_semantic_mapping_mismatch_is_refused(tmp_path, monkeypatch, count,
                                                                 mapping):
    directory = _bundle(tmp_path / "model")
    _fake_transformers(monkeypatch, count=count, mapping=mapping)
    instance = phobert_model.PhoBertIntentClassifier(str(directory))
    with pytest.raises(ValueError):
        instance.load()
    assert instance.model is None and instance.labels is None


def test_legacy_generic_huggingface_label_names_are_still_supported(tmp_path, monkeypatch):
    directory = _bundle(tmp_path / "model")
    _fake_transformers(monkeypatch, mapping={0: "LABEL_0", 1: "LABEL_1"})
    assert phobert_model.PhoBertIntentClassifier(str(directory)).load().labels == \
        ["open_app", "chitchat"]


def test_training_feedback_reader_handles_headerless_verified_rows(tmp_path, monkeypatch):
    training = importlib.import_module("train_phobert")
    feedback = tmp_path / "feedback.csv"
    feedback.write_text("2026,new verified example,open_app,1.0,1\n", encoding="utf-8-sig")
    monkeypatch.setattr(training, "FEEDBACK_CSV", str(feedback))
    monkeypatch.setattr(training, "EXTRA_CSV", str(tmp_path / "missing.csv"))
    monkeypatch.setattr(training, "get_dataset_as_lists", lambda: (["seed"], ["chitchat"]))
    texts, labels = training.load_training_data()
    assert texts == ["seed", "new verified example"] and labels == ["chitchat", "open_app"]


@pytest.mark.parametrize("flags", [["--epochs", "0"], ["--batch-size", "-1"],
                                   ["--max-length", "0"], ["--max-length", "10000"],
                                   ["--lr", "nan"], ["--lr", "-1"]])
def test_training_rejects_invalid_parameters_before_importing_ai(monkeypatch, flags):
    training = importlib.import_module("train_phobert")
    monkeypatch.setattr(training, "train", lambda args: pytest.fail("invalid training was started"))
    with pytest.raises(SystemExit) as error:
        training.main(flags)
    assert error.value.code == 2
