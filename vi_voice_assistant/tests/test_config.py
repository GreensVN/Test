# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


def test_default_config_has_all_four_maps():
    for key in ("website_map", "app_map_windows", "app_map_macos", "app_map_linux", "file_map"):
        assert key in config.DEFAULT_CONFIG
        assert len(config.DEFAULT_CONFIG[key]) > 0


def test_load_config_creates_file_if_missing(tmp_path):
    path = tmp_path / "config.json"
    assert not path.exists()
    cfg = config.load_config(str(path))
    assert path.exists()
    assert cfg["confidence_threshold"] == config.DEFAULT_CONFIG["confidence_threshold"]


def test_load_config_fills_missing_keys(tmp_path):
    path = tmp_path / "config.json"
    config.save_config({"website_map": {"custom": "https://example.com"}}, str(path))
    cfg = config.load_config(str(path))
    # Khoá người dùng đã đặt vẫn còn
    assert cfg["website_map"]["custom"] == "https://example.com"
    # Khoá thiếu (vd app_map_windows) được tự bổ sung từ DEFAULT_CONFIG
    assert "app_map_windows" in cfg
    assert "confidence_threshold" in cfg


def test_load_config_raises_on_invalid_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not valid json", encoding="utf-8")
    try:
        config.load_config(str(path))
        assert False, "phải ném lỗi khi JSON không hợp lệ"
    except RuntimeError:
        pass


def test_save_config_preserves_unicode(tmp_path):
    path = tmp_path / "config.json"
    config.save_config({"website_map": {"báo mới": "https://baomoi.com"}}, str(path))
    content = path.read_text(encoding="utf-8")
    assert "báo mới" in content  # ensure_ascii=False giữ nguyên tiếng Việt
