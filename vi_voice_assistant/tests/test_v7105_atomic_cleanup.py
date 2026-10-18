"""Interrupted writes and invalid temp parameters must not leave private debris."""

import os
from pathlib import Path

import paths
import pytest

KINDS = ["text", "json", "create"]


def _write(kind, target, *, prefix=None):
    if kind == "text":
        return paths.atomic_write_text(target, "new data", prefix=prefix)
    if kind == "json":
        return paths.atomic_write_json(target, {"new": "data"}, prefix=prefix)
    return paths.create_json_if_absent(target, {"new": "data"})


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit])
def test_interruption_during_file_sync_closes_handle_and_cleans_temp(tmp_path, monkeypatch, kind,
                                                                   error):
    target = tmp_path / "data.json"
    if kind != "create":
        target.write_bytes(b"old bytes")
    descriptors = []

    def interrupt(fd):
        descriptors.append(fd)
        raise error("cancelled")

    monkeypatch.setattr(paths.os, "fsync", interrupt)
    with pytest.raises(error):
        _write(kind, target)
    if kind == "create":
        assert not target.exists()
    else:
        assert target.read_bytes() == b"old bytes"
    assert [p for p in tmp_path.iterdir() if p != target] == []
    assert descriptors
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit])
def test_interruption_before_publication_preserves_destination(tmp_path, monkeypatch, kind, error):
    target = tmp_path / "data.json"
    if kind != "create":
        target.write_bytes(b"old bytes")

    def interrupt(*args, **kwargs):
        raise error("cancelled before publication")

    primitive = ("rename" if os.name == "nt" else "link") if kind == "create" else "replace"
    monkeypatch.setattr(paths.os, primitive, interrupt)
    with pytest.raises(error):
        _write(kind, target)
    assert not target.exists() if kind == "create" else target.read_bytes() == b"old bytes"
    assert [p for p in tmp_path.iterdir() if p != target] == []


@pytest.mark.parametrize("prefix", ["absolute", "../outside_", "nested/part_", r"..\outside_",
                                   r"\rooted_", "C:relative_", r"C:\rooted_", "x\x00x",
                                   "file:stream_"])
@pytest.mark.parametrize("kind", ["text", "json"])
def test_invalid_prefix_is_refused_before_directory_or_temp_creation(tmp_path, monkeypatch,
                                                                   prefix, kind):
    target = tmp_path / "must-not-create" / "data.json"
    if prefix == "absolute":
        prefix = str(tmp_path / "outside_")

    def forbidden(*args, **kwargs):
        pytest.fail("invalid prefix reached temporary-file allocation")

    monkeypatch.setattr(paths.tempfile, "mkstemp", forbidden)
    monkeypatch.setattr(paths.tempfile, "NamedTemporaryFile", forbidden)
    with pytest.raises(ValueError):
        _write(kind, target, prefix=prefix)
    assert not target.parent.exists()


@pytest.mark.parametrize("content,encoding,error", [("abc", "unknown-codec", LookupError),
                                                  ("\ud800", "utf-8", UnicodeError),
                                                  ("tiếng Việt", "ascii", UnicodeError)])
def test_encoding_error_happens_before_filesystem_changes(tmp_path, content, encoding, error):
    target = tmp_path / "must-not-create" / "data.txt"
    with pytest.raises(error):
        paths.atomic_write_text(target, content, encoding=encoding)
    assert not target.parent.exists()


@pytest.mark.parametrize("kind", KINDS)
def test_sync_failure_closes_descriptor_and_preserves_original(tmp_path, monkeypatch, kind):
    target = tmp_path / "data.json"
    if kind != "create":
        target.write_bytes(b"old bytes")
    descriptors = []

    def fail(fd):
        descriptors.append(fd)
        raise OSError("disk error")

    monkeypatch.setattr(paths.os, "fsync", fail)
    with pytest.raises(OSError, match="disk error"):
        _write(kind, target)
    assert not target.exists() if kind == "create" else target.read_bytes() == b"old bytes"
    assert [p for p in tmp_path.iterdir() if p != target] == []
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "latin-1"])
@pytest.mark.parametrize("content", ["café\r\nline two\n", ""])
def test_text_encoding_and_newlines_round_trip(tmp_path, encoding, content):
    target = tmp_path / "data.txt"
    paths.atomic_write_text(target, content, encoding=encoding)
    with target.open(encoding=encoding, newline="") as stream:
        assert stream.read() == content
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("content", [None, 123, b"bytes", []])
def test_non_text_content_is_rejected_before_creating_parent(tmp_path, content):
    target = tmp_path / "must-not-create" / "data.txt"
    with pytest.raises(TypeError):
        paths.atomic_write_text(target, content)
    assert not target.parent.exists()


@pytest.mark.parametrize("prefix", [None, "", "custom_"])
def test_valid_temp_prefixes_keep_existing_contract(tmp_path, prefix):
    target = Path(tmp_path) / "data.txt"
    paths.atomic_write_text(target, "valid", prefix=prefix)
    assert target.read_text(encoding="utf-8") == "valid"
    assert list(tmp_path.iterdir()) == [target]
