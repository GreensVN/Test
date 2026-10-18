"""Legacy adoption and first-run config creation must never overwrite a winner."""

import json
import os
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import config
import paths
import pytest


@pytest.fixture
def migration(tmp_path, monkeypatch):
    source, target = tmp_path / "legacy" / "package", tmp_path / "new" / "data"
    source.mkdir(parents=True)
    target.mkdir(parents=True)
    monkeypatch.setattr(paths, "PACKAGE_DIR", source)
    monkeypatch.setattr(paths, "data_dir", lambda: target)
    return source, target


def _symlink(link, target, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this host")


def test_regular_migration_copies_complete_bytes_with_private_permissions(migration):
    source, target = migration
    (source / "config.json").write_bytes(b'{"old": true}')
    assert paths.migrate_from_package_dir(("config.json",)) == ["config.json"]
    assert (target / "config.json").read_bytes() == b'{"old": true}'
    if os.name != "nt":
        assert stat.S_IMODE((target / "config.json").stat().st_mode) == 0o600
    assert [item.name for item in target.iterdir()] == ["config.json"]


def test_migration_leaves_an_existing_destination_unchanged(migration):
    source, target = migration
    (source / "config.json").write_bytes(b"legacy")
    (target / "config.json").write_bytes(b"newer")
    assert paths.migrate_from_package_dir(("config.json",)) == []
    assert (target / "config.json").read_bytes() == b"newer"


@pytest.mark.parametrize("name", ["../escape", r"..\escape", r"\escape", r"C:\escape",
                                 r"C:escape", "", ".", r"\\server\share\escape", "nul\x00name"])
def test_invalid_migration_names_are_rejected_before_filesystem_probe(migration, monkeypatch, name):
    source, _ = migration
    forbidden, original = source / name, Path.is_file

    def forbidden_probe(path):
        if path == forbidden:
            pytest.fail("an invalid migration name reached filesystem probing")
        return original(path)

    monkeypatch.setattr(Path, "is_file", forbidden_probe)
    assert paths.migrate_from_package_dir((name,)) == []


def test_real_parent_traversal_cannot_copy_outside_either_root(migration):
    source, target = migration
    (source.parent / "secret.txt").write_bytes(b"private legacy data")
    outside = target.parent / "secret.txt"
    assert paths.migrate_from_package_dir(("../secret.txt",)) == []
    assert not outside.exists()


def test_source_symlink_escape_is_not_followed(migration, tmp_path):
    source, target = migration
    secret = tmp_path / "secret"
    secret.write_bytes(b"private")
    _symlink(source / "config.json", secret)
    assert paths.migrate_from_package_dir(("config.json",)) == []
    assert not (target / "config.json").exists()


def test_dangling_destination_symlink_does_not_create_file_outside_root(migration, tmp_path):
    source, target = migration
    (source / "config.json").write_bytes(b"legacy")
    outside = tmp_path / "must-not-create.json"
    _symlink(target / "config.json", outside)
    assert paths.migrate_from_package_dir(("config.json",)) == []
    assert not outside.exists()


def test_destination_parent_symlink_cannot_redirect_copy(migration, tmp_path):
    source, target = migration
    (source / "nested").mkdir()
    (source / "nested" / "item.json").write_bytes(b"legacy")
    outside = tmp_path / "outside"
    outside.mkdir()
    _symlink(target / "nested", outside, directory=True)
    assert paths.migrate_from_package_dir(("nested/item.json",)) == []
    assert list(outside.iterdir()) == []


def test_source_symlink_that_stays_inside_root_is_supported(migration):
    source, target = migration
    (source / "real.json").write_bytes(b"safe")
    _symlink(source / "alias.json", source / "real.json")
    assert paths.migrate_from_package_dir(("alias.json",)) == ["alias.json"]
    assert (target / "alias.json").read_bytes() == b"safe"


def test_contained_subdirectory_can_be_adopted(migration):
    source, target = migration
    (source / "nested").mkdir()
    (source / "nested" / "item.json").write_bytes(b"legacy")
    assert paths.migrate_from_package_dir(("nested/item.json",)) == ["nested/item.json"]
    assert (target / "nested" / "item.json").read_bytes() == b"legacy"


def test_destination_created_during_source_read_always_wins(migration, monkeypatch):
    source, target = migration
    old, new = source / "config.json", target / "config.json"
    old.write_bytes(b"legacy")
    original = Path.read_bytes

    def raced(path):
        data = original(path)
        if path == old:
            new.write_bytes(b"new user data")
        return data

    monkeypatch.setattr(Path, "read_bytes", raced)
    assert paths.migrate_from_package_dir(("config.json",)) == []
    assert new.read_bytes() == b"new user data"


@pytest.mark.parametrize("workers", [2, 6])
def test_racing_migrations_publish_exactly_one_complete_copy(migration, monkeypatch, workers):
    source, target = migration
    old = source / "config.json"
    old.write_bytes(b"legacy bytes" * 1000)
    original = Path.read_bytes
    barrier = threading.Barrier(workers)

    def raced(path):
        data = original(path)
        if path == old:
            barrier.wait(timeout=5)
        return data

    monkeypatch.setattr(Path, "read_bytes", raced)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(paths.migrate_from_package_dir, ("config.json",))
                   for _ in range(workers)]
        results = [future.result(timeout=10) for future in futures]
    assert sum(len(result) for result in results) == 1
    assert (target / "config.json").read_bytes() == b"legacy bytes" * 1000
    assert [item.name for item in target.iterdir()] == ["config.json"]


def test_migration_fsync_failure_leaves_no_partial_destination_or_temp(migration, monkeypatch):
    source, target = migration
    (source / "config.json").write_bytes(b"legacy")

    def fail(fd):
        raise OSError("fsync unavailable")

    monkeypatch.setattr(paths.os, "fsync", fail)
    assert paths.migrate_from_package_dir(("config.json",)) == []
    assert list(target.iterdir()) == []


def test_source_read_failure_preserves_both_roots(migration, monkeypatch):
    source, target = migration
    (source / "config.json").write_bytes(b"legacy")

    def fail(path):
        raise OSError("read unavailable")

    monkeypatch.setattr(Path, "read_bytes", fail)
    assert paths.migrate_from_package_dir(("config.json",)) == []
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("error", [OSError, PermissionError])
def test_publication_failure_never_uses_an_overwriting_fallback(migration, monkeypatch, error):
    source, target = migration
    (source / "config.json").write_bytes(b"legacy")

    def fail(*args, **kwargs):
        raise error("exclusive publication unavailable")

    primitive = "rename" if os.name == "nt" else "link"
    monkeypatch.setattr(paths.os, primitive, fail)
    assert paths.migrate_from_package_dir(("config.json",)) == []
    assert list(target.iterdir()) == []


def test_migration_into_source_is_a_noop(migration, monkeypatch):
    source, _ = migration
    (source / "config.json").write_bytes(b"legacy")
    monkeypatch.setattr(paths, "data_dir", lambda: source)
    assert paths.migrate_from_package_dir(("config.json",)) == []


def test_missing_source_does_not_create_destination(migration):
    _, target = migration
    assert paths.migrate_from_package_dir(("missing.json",)) == []
    assert list(target.iterdir()) == []


def test_bad_name_does_not_prevent_later_valid_migration(migration):
    source, target = migration
    (source / "config.json").write_bytes(b"legacy")
    assert paths.migrate_from_package_dir(("../escape", "config.json")) == ["config.json"]
    assert (target / "config.json").read_bytes() == b"legacy"


def test_data_path_rejects_windows_rooted_name_on_every_platform(migration):
    with pytest.raises(ValueError):
        paths.data_path(r"\escape")


def test_atomic_create_json_publishes_once_without_overwriting(tmp_path):
    target = tmp_path / "nested" / "config.json"
    assert paths.create_json_if_absent(target, {"first": True}) is True
    original = target.read_bytes()
    assert paths.create_json_if_absent(target, {"second": True}) is False
    assert target.read_bytes() == original
    assert json.loads(original) == {"first": True}
    assert [item.name for item in target.parent.iterdir()] == ["config.json"]


@pytest.mark.parametrize("payload", [float("nan"), float("inf"), -float("inf"), object()])
def test_atomic_create_rejects_invalid_json_before_touching_disk(tmp_path, payload):
    target = tmp_path / "must-not-create" / "config.json"
    with pytest.raises((ValueError, TypeError)):
        paths.create_json_if_absent(target, payload)
    assert not target.parent.exists()


def test_atomic_create_does_not_replace_existing_directory(tmp_path):
    target = tmp_path / "config.json"
    target.mkdir()
    assert paths.create_json_if_absent(target, {}) is False
    assert target.is_dir() and list(target.iterdir()) == []


def test_atomic_create_new_json_is_private(tmp_path):
    target = tmp_path / "config.json"
    assert paths.create_json_if_absent(target, {}) is True
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_atomic_create_sync_failure_does_not_publish(tmp_path, monkeypatch):
    target = tmp_path / "config.json"

    def fail(fd):
        raise OSError("fsync failed")

    monkeypatch.setattr(paths.os, "fsync", fail)
    with pytest.raises(OSError, match="fsync failed"):
        paths.create_json_if_absent(target, {})
    assert list(tmp_path.iterdir()) == []


def test_atomic_create_never_follows_dangling_destination_symlink(tmp_path):
    target, outside = tmp_path / "config.json", tmp_path / "outside.json"
    _symlink(target, outside)
    assert paths.create_json_if_absent(target, {}) is False
    assert not outside.exists()


@pytest.mark.parametrize("winner,valid", [(b'{"confidence_accept": 0.9}', True),
                                         (b'{"broken"', False)])
def test_first_config_load_does_not_overwrite_a_concurrent_winner(tmp_path, monkeypatch, winner,
                                                                valid):
    target = tmp_path / "config.json"
    original = Path.exists
    raced = [False]

    def exists(path):
        if path == target and not raced[0]:
            raced[0] = True
            path.write_bytes(winner)
            return False
        return original(path)

    monkeypatch.setattr(Path, "exists", exists)
    if valid:
        assert config.load_config(target)["confidence_accept"] == 0.9
    else:
        with pytest.raises(RuntimeError, match="Không đọc được"):
            config.load_config(target)
    assert target.read_bytes() == winner


def test_first_config_can_run_in_memory_if_exclusive_creation_is_unavailable(tmp_path, monkeypatch):
    target = tmp_path / "config.json"

    def fail(*args, **kwargs):
        raise OSError("publication unsupported")

    primitive = "rename" if os.name == "nt" else "link"
    monkeypatch.setattr(paths.os, primitive, fail)
    assert config.load_config(target) == config.DEFAULT_CONFIG
    assert not target.exists()


def test_temp_allocation_conflict_is_an_error_not_a_false_existing_destination(tmp_path,
                                                                             monkeypatch):
    target = tmp_path / "config.json"

    def fail(*args, **kwargs):
        raise FileExistsError("temporary allocation failed")

    monkeypatch.setattr(paths.tempfile, "NamedTemporaryFile", fail)
    with pytest.raises(FileExistsError, match="temporary allocation failed"):
        paths.create_json_if_absent(target, {})
    assert not target.exists()
