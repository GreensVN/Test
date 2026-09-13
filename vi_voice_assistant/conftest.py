"""Đảm bảo pytest tìm thấy các module gốc của dự án khi chạy từ thư mục khác."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
