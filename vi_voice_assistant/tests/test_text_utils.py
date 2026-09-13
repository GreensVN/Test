# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from text_utils import normalize_text, strip_diacritics, normalize_no_diacritics


def test_normalize_text_lowercases_and_trims():
    assert normalize_text("  Bật GOOGLE Lên  ") == "bật google lên"


def test_normalize_text_collapses_whitespace():
    assert normalize_text("mở   google    lên") == "mở google lên"


def test_strip_diacritics_basic():
    assert strip_diacritics("bật google lên") == "bat google len"


def test_strip_diacritics_dam_chu_d():
    assert strip_diacritics("đăng xuất") == "dang xuat"


def test_strip_diacritics_leaves_ascii_unchanged():
    assert strip_diacritics("vs code") == "vs code"


def test_normalize_no_diacritics_combines_both():
    assert normalize_no_diacritics("  Tắt Máy Tính Đi ") == "tat may tinh di"
