"""History is not empty just because it has a BOM, a read error, or a racing writer."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import main
import pytest


@pytest.fixture
def history(tmp_path, monkeypatch):
    path = tmp_path / "history.json"
    monkeypatch.setattr(main, "HISTORY_PATH", path)
    return path


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
@pytest.mark.parametrize("as_string", [False, True])
def test_history_accepts_bom_and_pathlike_compatibility(history, monkeypatch, encoding, as_string):
    original = ["mở chrome", "việc trước"]
    history.write_text(json.dumps(original, ensure_ascii=False), encoding=encoding)
    if as_string:
        monkeypatch.setattr(main, "HISTORY_PATH", str(history))
    assert main.load_history() == original


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
@pytest.mark.parametrize("as_string", [False, True])
def test_append_keeps_previous_history_instead_of_replacing_it(history, monkeypatch, encoding,
                                                              as_string):
    history.write_text('["previous"]', encoding=encoding)
    if as_string:
        monkeypatch.setattr(main, "HISTORY_PATH", str(history))
    main.save_history_entry("next command")
    assert json.loads(history.read_text(encoding="utf-8")) == ["previous", "next command"]


@pytest.mark.parametrize("original", [b'{"wrong": "root"}', b'["half"', b"\xff", b"", b"null"])
def test_corrupt_or_unrecognized_history_is_not_overwritten(history, original):
    history.write_bytes(original)
    assert main.load_history() == []
    main.save_history_entry("new command")
    assert history.read_bytes() == original


@pytest.mark.parametrize("value", [None, True, 123, object(), ["one", "two"], {"a": 1, "b": 2}])
def test_non_string_entries_do_not_break_or_pollute_history(history, value):
    history.write_text('["previous"]', encoding="utf-8")
    before = history.read_bytes()
    main.save_history_entry(value)
    assert history.read_bytes() == before


def test_history_still_filters_non_strings_and_applies_capacity(history):
    values = [f"command {i}" for i in range(main.MAX_HISTORY + 5)]
    history.write_text(json.dumps([1, None, {}, *values]), encoding="utf-8-sig")
    assert main.load_history() == values[-main.MAX_HISTORY:]


def test_consecutive_duplicate_and_short_input_rules_are_preserved(history):
    for text in ("command", "command", "x", "", "next"):
        main.save_history_entry(text)
    assert main.load_history() == ["command", "next"]


@pytest.mark.parametrize("workers", [2, 8])
def test_threaded_append_does_not_lose_entries(history, monkeypatch, workers):
    history.write_text('["seed"]', encoding="utf-8")
    real_write = main.atomic_write_json
    entered, release, another_done = threading.Event(), threading.Event(), threading.Event()
    start, guard = threading.Barrier(workers), threading.Lock()
    counter = [0]

    def write(path, payload, **kwargs):
        with guard:
            counter[0] += 1
            first = counter[0] == 1
        if first:
            entered.set()
            assert release.wait(timeout=5)
        real_write(path, payload, **kwargs)
        if not first:
            another_done.set()

    def append(index):
        start.wait(timeout=5)
        main.save_history_entry(f"thread {index}")

    monkeypatch.setattr(main, "atomic_write_json", write)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(append, i) for i in range(workers)]
        try:
            assert entered.wait(timeout=5)
            # A locked implementation blocks the other read/modify/write calls.
            # An unlocked one lets another writer finish before the first snapshot.
            another_done.wait(timeout=0.2)
        finally:
            release.set()
        for future in futures:
            future.result(timeout=5)
    assert set(main.load_history()) == {"seed", *(f"thread {i}" for i in range(workers))}
    assert len(main.load_history()) == workers + 1


def test_read_error_does_not_turn_existing_data_into_empty_history(history, monkeypatch):
    history.write_text('["previous"]', encoding="utf-8")
    original_open = Path.open

    def blocked(path, mode="r", *args, **kwargs):
        if path == history and "r" in mode:
            raise PermissionError("read denied")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", blocked)
    assert main.load_history() == []
    main.save_history_entry("new command")
    with original_open(history, "rb") as stream:
        assert stream.read() == b'["previous"]'


def test_failed_atomic_write_preserves_previous_bytes(history, monkeypatch):
    history.write_text('["previous"]', encoding="utf-8")

    def fail(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(main, "atomic_write_json", fail)
    main.save_history_entry("new command")
    assert history.read_bytes() == b'["previous"]'


def test_history_path_that_is_a_directory_remains_untouched(history):
    history.mkdir()
    assert main.load_history() == []
    main.save_history_entry("new command")
    assert history.is_dir() and list(history.iterdir()) == []
