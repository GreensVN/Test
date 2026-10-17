"""Không báo đã học khi ghi thất bại; CSV không trộn header/record khi ghi đồng thời."""
import builtins
import csv
import errno
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import csv_utils
import dataset
import nlu_advanced as nlu
import pytest

COLUMNS = ["time", "text", "intent", "confidence", "verified"]


@pytest.fixture
def feedback(tmp_path, monkeypatch):
    path = tmp_path / "feedback.csv"
    monkeypatch.setattr(nlu, "FEEDBACK_PATH", str(path))
    return path


def _rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_feedback_returns_success_after_persisting_multiline_record(feedback):
    text = 'mở "chrome", rồi\nxem tin'
    assert nlu.log_feedback(text, "open_app", 0.9, correct=True) is True
    assert _rows(feedback)[0]["text"] == text
    assert _rows(feedback)[0]["verified"] == "1"


def test_teach_never_claims_success_after_io_failure(feedback):
    feedback.mkdir()  # Đường dẫn đích không phải file, không phụ thuộc quyền root.
    model = nlu.NLU.__new__(nlu.NLU)
    message = model.teach("mở chrome", "open_app")
    assert "Đã ghi nhớ" not in message
    assert "Không" in message and "feedback.csv" in message
    assert nlu.log_feedback("mở chrome", "open_app", 1.0) is False


def test_feedback_rejects_invalid_utf8_without_losing_previous_records(feedback):
    assert nlu.log_feedback("câu cũ", "open_app", 1.0) is True
    before = feedback.read_bytes()
    assert nlu.log_feedback("\ud800", "open_app", 1.0, correct=True) is False
    assert feedback.read_bytes() == before


@pytest.mark.parametrize("flag,expected", [
    (True, "1"), (1, "1"), (False, "0"), (0, "0"), (None, "0"),
    ("false", "0"), ("0", "0"), ("1", "0"), (1.0, "0"), ([1], "0"), (2, "0"),
])
def test_only_explicit_boolean_or_integer_one_can_verify_feedback(feedback, flag, expected):
    nlu.log_feedback("câu nói", "open_app", 0.9, correct=flag)
    assert _rows(feedback)[0]["verified"] == expected


def test_bom_only_file_gets_header_before_first_record(feedback):
    feedback.write_bytes(b"\xef\xbb\xbf")
    assert nlu.log_feedback("mở chrome", "open_app", 1.0, correct=True) is True
    assert _rows(feedback)[0]["text"] == "mở chrome"
    assert feedback.read_bytes().count(b"\xef\xbb\xbf") == 1


def test_append_preserves_last_record_without_final_newline(feedback):
    feedback.write_text(
        "time,text,intent,confidence,verified\n2026,câu cũ,open_app,1.0,1", encoding="utf-8")
    assert nlu.log_feedback("câu mới", "open_app", 1.0, correct=True) is True
    assert [row["text"] for row in _rows(feedback)] == ["câu cũ", "câu mới"]
    assert all(row["verified"] == "1" for row in _rows(feedback))


def test_append_follows_existing_header_order(feedback):
    feedback.write_text("text,intent,time,verified,confidence\n", encoding="utf-8")
    assert nlu.log_feedback("mở chrome", "open_app", 0.75, correct=True) is True
    row = _rows(feedback)[0]
    assert (row["text"], row["intent"], row["verified"], row["confidence"]) == (
        "mở chrome", "open_app", "1", "0.75")


def test_header_missing_required_columns_is_not_silently_corrupted(feedback):
    feedback.write_text("text,intent\n", encoding="utf-8")
    before = feedback.read_bytes()
    assert nlu.log_feedback("mở chrome", "open_app", 1.0, correct=True) is False
    assert feedback.read_bytes() == before


def test_simultaneous_first_writers_create_exactly_one_header_and_bom(feedback, monkeypatch):
    barrier = threading.Barrier(2)
    original_open = builtins.open

    def synchronized_open(file, mode="r", *args, **kwargs):
        stream = original_open(file, mode, *args, **kwargs)
        if Path(file) == feedback and "a" in mode:
            barrier.wait(timeout=15)
        return stream

    monkeypatch.setattr(builtins, "open", synchronized_open)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(nlu.log_feedback, f"câu {i}", "open_app", 1.0) for i in range(2)]
        results = [future.result(timeout=30) for future in futures]
    data = feedback.read_bytes()
    assert data.count(b"time,text,intent,confidence,verified") == 1
    assert data.count(b"\xef\xbb\xbf") == 1
    assert len(_rows(feedback)) == 2
    assert results == [True, True]


def test_multiple_processes_append_complete_records(feedback):
    package = str(Path(nlu.__file__).resolve().parent)
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); import nlu_advanced as n;"
        "n.FEEDBACK_PATH=sys.argv[2];"
        "results=[n.log_feedback(sys.argv[3]+'-'+str(i), 'open_app', 1.0, correct=True)"
        " for i in range(20)];"
        "sys.exit(0 if all(results) else 1)"
    )
    children = []
    try:
        for worker in range(4):
            children.append(subprocess.Popen(
                [sys.executable, "-c", code, package, str(feedback), str(worker)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=dict(os.environ, VI_ASSISTANT_HOME=str(feedback.parent), PYTHONUTF8="1")))
        for child in children:
            out, err = child.communicate(timeout=120)
            assert child.returncode == 0, (out, err)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=30)
    rows = _rows(feedback)
    assert len(rows) == 80
    assert len({row["text"] for row in rows}) == 80
    assert all(row["verified"] == "1" for row in rows)
    assert feedback.read_bytes().count(b"\xef\xbb\xbf") == 1



def test_busy_csv_times_out_without_writing_and_can_be_retried(feedback, monkeypatch):
    monkeypatch.setattr(csv_utils, "_FILE_LOCK_TIMEOUT", 0.02)
    with feedback.open("a+b") as owner:
        csv_utils._file_lock_operation(owner.fileno())
        try:
            assert nlu.log_feedback("đang bị khóa", "open_app", 1.0) is False
            assert feedback.read_bytes() == b""
        finally:
            csv_utils._file_lock_operation(owner.fileno(), release=True)
    assert nlu.log_feedback("đã mở khóa", "open_app", 1.0) is True
    assert _rows(feedback)[0]["text"] == "đã mở khóa"


def test_non_contention_lock_error_is_not_retried(feedback, monkeypatch):
    calls = []

    def denied(*args, **kwargs):
        calls.append(1)
        raise OSError(errno.EPERM, "không hỗ trợ khóa")

    monkeypatch.setattr(csv_utils, "_file_lock_operation", denied)
    assert nlu.log_feedback("không được ghi", "open_app", 1.0) is False
    assert len(calls) == 1
    assert feedback.read_bytes() == b""


def test_fsync_failure_does_not_claim_teaching_success_or_leak_lock(feedback, monkeypatch):
    original = csv_utils.os.fsync

    def fail(fd):
        raise OSError("đĩa lỗi")

    monkeypatch.setattr(csv_utils.os, "fsync", fail)
    message = nlu.NLU.__new__(nlu.NLU).teach("lần đầu", "open_app")
    assert "Đã ghi nhớ" not in message
    monkeypatch.setattr(csv_utils.os, "fsync", original)
    assert nlu.log_feedback("lần sau", "open_app", 1.0) is True
    assert _rows(feedback)[-1]["text"] == "lần sau"


@pytest.mark.parametrize("progress", [True, False])
def test_short_binary_writes_are_completed_or_explicitly_fail(feedback, monkeypatch, progress):
    original_open = builtins.open

    class Writer:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def __iter__(self):
            return iter(self.stream)

        def write(self, data):
            return self.stream.write(data[:3]) if progress else 0

    def short_open(file, mode="r", *args, **kwargs):
        stream = original_open(file, mode, *args, **kwargs)
        return Writer(stream) if Path(file) == feedback and "a" in mode else stream

    monkeypatch.setattr(builtins, "open", short_open)
    assert nlu.log_feedback("mở chrome", "open_app", 1.0) is progress
    if progress:
        assert _rows(feedback)[0]["text"] == "mở chrome"
    else:
        assert feedback.read_bytes() == b""


def test_duplicate_header_names_are_not_appended_to(feedback):
    feedback.write_text("time,text,intent,confidence,verified,verified\n", encoding="utf-8")
    before = feedback.read_bytes()
    assert nlu.log_feedback("mở chrome", "open_app", 1.0) is False
    assert feedback.read_bytes() == before


def test_legacy_headerless_csv_remains_readable_when_appended(feedback):
    feedback.write_text("2026,cũ,open_app,1.0,1", encoding="utf-8")
    assert nlu.log_feedback("mới", "open_app", 1.0, correct=True) is True
    rows = csv_utils.read_keyed_csv(feedback, tuple(COLUMNS))
    assert [row["text"] for row in rows] == ["cũ", "mới"]
    assert all(row["verified"] == "1" for row in rows)


@pytest.mark.parametrize("intents", [None, {}, []])
def test_teach_does_not_disable_label_validation_when_dataset_is_broken(
        feedback, monkeypatch, intents):
    monkeypatch.setattr(dataset, "INTENT_DATA", intents)
    message = nlu.NLU.__new__(nlu.NLU).teach("câu dạy", "open_app")
    assert "Đã ghi nhớ" not in message
    assert not feedback.exists()


@pytest.mark.parametrize("release", [False, True])
def test_windows_lock_operation_uses_byte_zero_and_correct_mode(monkeypatch, release):
    calls = []
    fake_os = SimpleNamespace(name="nt", SEEK_SET=0,
                              lseek=lambda *args: calls.append(("seek", *args)))
    fake_msvcrt = SimpleNamespace(LK_UNLCK=0, LK_NBLCK=1,
                                  locking=lambda *args: calls.append(("lock", *args)))
    monkeypatch.setattr(csv_utils, "os", fake_os)
    monkeypatch.setattr(csv_utils, "import_module", lambda name: fake_msvcrt)
    csv_utils._file_lock_operation(123, release=release)
    assert calls == [("seek", 123, 0, 0), ("lock", 123, 0 if release else 1, 1)]



def test_csv_reader_never_reads_an_in_progress_append(feedback, monkeypatch):
    assert nlu.log_feedback("cũ", "open_app", 1.0) is True
    monkeypatch.setattr(csv_utils, "_FILE_LOCK_TIMEOUT", 0.02)
    with feedback.open("a+b") as owner:
        csv_utils._file_lock_operation(owner.fileno())
        try:
            with pytest.raises(TimeoutError):
                csv_utils.read_keyed_csv(feedback, tuple(COLUMNS))
        finally:
            csv_utils._file_lock_operation(owner.fileno(), release=True)
    assert csv_utils.read_keyed_csv(feedback, tuple(COLUMNS))[0]["text"] == "cũ"
