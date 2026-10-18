"""Cấu hình/data thật: kiểu sai, BOM, NaN, alias và symlink."""
import json
import os
from pathlib import Path

import config
import paths
import pytest


@pytest.mark.parametrize("value", [None, "shutdown", 123, {}, [None], [1], [""]])
def test_reject_invalid_dangerous_actions(tmp_path, value):
    file = tmp_path / "config.json"
    file.write_text(json.dumps({"dangerous_actions": value}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="dangerous_actions"):
        config.load_config(file)


@pytest.mark.parametrize("key", config.MAP_KEYS)
def test_null_map_is_rejected_at_load_not_in_executor(tmp_path, key):
    file = tmp_path / "config.json"
    file.write_text(json.dumps({key: None}), encoding="utf-8")
    with pytest.raises(RuntimeError, match=key):
        config.load_config(file)


@pytest.mark.parametrize("key", ["confidence_threshold", "confidence_accept", "confidence_ask"])
def test_threshold_bool_is_not_a_probability(tmp_path, key):
    file = tmp_path / "config.json"
    file.write_text(json.dumps({key: True}), encoding="utf-8")
    with pytest.raises(RuntimeError, match=key):
        config.load_config(file)


def test_config_accepts_notepad_utf8_bom(tmp_path):
    file = tmp_path / "config.json"
    file.write_text('{"confidence_accept": 0.7}', encoding="utf-8-sig")
    assert config.load_config(file)["confidence_accept"] == 0.7


def test_first_load_uses_shipped_config_before_creating_defaults(tmp_path, monkeypatch):
    shipped = tmp_path / "package"
    shipped.mkdir()
    (shipped / "config.json").write_text(
        '{"website_map": {"custom": "https://example.com"}}', encoding="utf-8")
    target = tmp_path / "user" / "config.json"
    monkeypatch.setattr(config, "BASE_DIR", shipped)
    monkeypatch.setattr(config, "CONFIG_PATH", target)
    result = config.load_config(target)
    assert result["website_map"]["custom"] == "https://example.com"
    assert json.loads(target.read_text(encoding="utf-8"))["website_map"]["custom"]


def test_merge_does_not_share_list_with_caller(tmp_path):
    updates = {"dangerous_actions": ["shutdown"], "custom": {"items": [1]}}
    result = config.update_config(updates, tmp_path / "config.json")
    updates["dangerous_actions"].clear()
    updates["custom"]["items"].append(2)
    assert result["dangerous_actions"] == ["shutdown"]
    assert result["custom"]["items"] == [1]


@pytest.mark.parametrize("number", [float("nan"), float("inf"), -float("inf")])
def test_atomic_json_rejects_nonstandard_numbers_without_touching_old_file(tmp_path, number):
    target = tmp_path / "data.json"
    target.write_text('{"old": 1}', encoding="utf-8")
    with pytest.raises(ValueError):
        paths.atomic_write_json(target, {"bad": number})
    assert target.read_text(encoding="utf-8") == '{"old": 1}'
    assert len(list(tmp_path.iterdir())) == 1


def test_atomic_write_preserves_existing_posix_permissions(tmp_path):
    if os.name == "nt":
        return  # Windows ACL không tương đương chmod POSIX.
    target = tmp_path / "shared.json"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o640)
    paths.atomic_write_json(target, {"new": True})
    assert target.stat().st_mode & 0o777 == 0o640


@pytest.mark.parametrize("filename", ["", ".", "C:/Windows/a", "C:relative", "../a", "a/../b",
                                        r"a\..\b", "a\x00b"])
def test_data_path_rejects_invalid_portable_names(filename):
    with pytest.raises(ValueError):
        paths.data_path(filename)


def test_data_path_rejects_symlink_escape(tmp_path, monkeypatch):
    base, outside = tmp_path / "home", tmp_path / "outside"
    base.mkdir()
    outside.mkdir()
    try:
        (base / "escape").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Máy không cho phép tạo symlink")
    monkeypatch.setattr(paths, "data_dir", lambda: base)
    with pytest.raises(ValueError):
        paths.data_path("escape/private.json")
    assert paths.data_path(Path("sub/ok.json")) == base / "sub/ok.json"


def test_reload_clears_previous_config_error(tmp_path, monkeypatch):
    import executor

    target = tmp_path / "config.json"
    config.save_config(config.DEFAULT_CONFIG, target)
    monkeypatch.setattr(executor, "CONFIG_ERROR", "lỗi cũ")
    monkeypatch.setattr(executor, "_ACTIVE_CONFIG_PATH", None)
    saved = dict(executor.CONFIG)
    try:
        executor.reload_config(target)
        assert executor.CONFIG_ERROR is None
    finally:
        executor.CONFIG.clear()
        executor.CONFIG.update(saved)
