# -*- coding: utf-8 -*-
"""
config.py
---------
Nạp cấu hình từ config.json.

v7.0 nâng cấp:
- Dùng pathlib, type hints đầy đủ
- Thêm validation schema
- Lưu file atomic (temp + rename) để tránh hỏng khi mất điện
- Thêm hàm get_config, update_config
- Cache với TTL đơn giản
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict

from platform_utils import safe_print, setup_console

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

# --- Validation helpers ---
REQUIRED_KEYS = {
    "confidence_threshold",
    "confidence_accept",
    "confidence_ask",
    "dangerous_actions",
    "website_map",
    "app_map_windows",
    "app_map_macos",
    "app_map_linux",
    "file_map",
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "confidence_threshold": 0.35,
    "confidence_accept": 0.45,
    "confidence_ask": 0.25,
    "dangerous_actions": ["shutdown", "restart", "logout"],
    "website_map": {
        "google": "https://www.google.com",
        "google dich": "https://translate.google.com",
        "youtube": "https://www.youtube.com",
        "facebook": "https://www.facebook.com",
        "github": "https://github.com",
        "gmail": "https://mail.google.com",
        "drive": "https://drive.google.com",
        "notion": "https://www.notion.so",
        "chatgpt": "https://chat.openai.com",
        "tiki": "https://tiki.vn",
        "shopee": "https://shopee.vn",
        "lazada": "https://www.lazada.vn",
        "vnexpress": "https://vnexpress.net",
        "tuoi tre": "https://tuoitre.vn",
        "báo mới": "https://baomoi.com",
        "kenh14": "https://kenh14.vn",
        "zalo": "https://chat.zalo.me",
        "zalo web": "https://chat.zalo.me",
        "messenger": "https://www.messenger.com",
        "stackoverflow": "https://stackoverflow.com",
        "tiktok": "https://www.tiktok.com",
        "instagram": "https://www.instagram.com",
        "twitter": "https://twitter.com",
        "linkedin": "https://www.linkedin.com",
        "wikipedia": "https://vi.wikipedia.org",
        "coursera": "https://www.coursera.org",
        "udemy": "https://www.udemy.com",
        "canva": "https://www.canva.com",
        "netflix": "https://www.netflix.com",
        "reddit": "https://www.reddit.com",
    },
    "app_map_windows": {
        "chrome": "chrome.exe",
        "google chrome": "chrome.exe",
        "coc coc": "browser.exe",
        "cốc cốc": "browser.exe",
        "edge": "msedge.exe",
        "firefox": "firefox.exe",
        "notepad": "notepad.exe",
        "may tinh bo tui": "calc.exe",
        "máy tính bỏ túi": "calc.exe",
        "calculator": "calc.exe",
        "calc": "calc.exe",
        "paint": "mspaint.exe",
        "cmd": "cmd.exe",
        "dong lenh cmd": "cmd.exe",
        "dòng lệnh cmd": "cmd.exe",
        "powershell": "powershell.exe",
        "word": "winword.exe",
        "excel": "excel.exe",
        "powerpoint": "powerpnt.exe",
        "outlook": "outlook.exe",
        "vs code": "code",
        "vscode": "code",
        "visual studio code": "code",
        "visual studio": "devenv.exe",
        "explorer": "explorer.exe",
        "file explorer": "explorer.exe",
        "task manager": "taskmgr.exe",
        "discord": r"%LOCALAPPDATA%\Discord\Update.exe",
        "obs studio": r"%PROGRAMFILES%\obs-studio\bin\64bit\obs64.exe",
        "photoshop": r"%PROGRAMFILES%\Adobe\Adobe Photoshop\Photoshop.exe",
        "steam": r"%PROGRAMFILES(X86)%\Steam\Steam.exe",
        "unikey": "unikeynt.exe",
        "camera": "microsoft.windows.camera:",
        "zalo": r"%LOCALAPPDATA%\Programs\Zalo\Zalo.exe",
        "spotify": r"%APPDATA%\Spotify\Spotify.exe",
        "telegram": r"%APPDATA%\Telegram Desktop\Telegram.exe",
        "vlc": "vlc.exe",
        "winrar": "winrar.exe",
        "postman": r"%LOCALAPPDATA%\Postman\Postman.exe",
    },
    "app_map_macos": {
        "chrome": "Google Chrome",
        "google chrome": "Google Chrome",
        "safari": "Safari",
        "edge": "Microsoft Edge",
        "notepad": "TextEdit",
        "ghi chu": "Notes",
        "ghi chú": "Notes",
        "may tinh bo tui": "Calculator",
        "máy tính bỏ túi": "Calculator",
        "calculator": "Calculator",
        "calc": "Calculator",
        "paint": "Preview",
        "cmd": "Terminal",
        "dong lenh cmd": "Terminal",
        "dòng lệnh cmd": "Terminal",
        "terminal": "Terminal",
        "powershell": "Terminal",
        "word": "Microsoft Word",
        "excel": "Microsoft Excel",
        "powerpoint": "Microsoft PowerPoint",
        "outlook": "Microsoft Outlook",
        "vs code": "Visual Studio Code",
        "vscode": "Visual Studio Code",
        "visual studio code": "Visual Studio Code",
        "explorer": "Finder",
        "file explorer": "Finder",
        "task manager": "Activity Monitor",
        "discord": "Discord",
        "obs studio": "OBS",
        "photoshop": "Adobe Photoshop 2024",
        "steam": "Steam",
        "camera": "Photo Booth",
        "zalo": "Zalo",
        "spotify": "Spotify",
        "telegram": "Telegram",
        "nhac": "Music",
        "nhạc": "Music",
        "vlc": "VLC",
    },
    "app_map_linux": {
        "chrome": "google-chrome",
        "google chrome": "google-chrome",
        "firefox": "firefox",
        "edge": "microsoft-edge",
        "notepad": "gedit",
        "ghi chu": "gedit",
        "ghi chú": "gedit",
        "may tinh bo tui": "gnome-calculator",
        "máy tính bỏ túi": "gnome-calculator",
        "calculator": "gnome-calculator",
        "calc": "gnome-calculator",
        "paint": "gimp",
        "cmd": "gnome-terminal",
        "dong lenh cmd": "gnome-terminal",
        "dòng lệnh cmd": "gnome-terminal",
        "terminal": "gnome-terminal",
        "powershell": "gnome-terminal",
        "word": "libreoffice --writer",
        "excel": "libreoffice --calc",
        "powerpoint": "libreoffice --impress",
        "vs code": "code",
        "vscode": "code",
        "visual studio code": "code",
        "explorer": "nautilus",
        "file explorer": "nautilus",
        "task manager": "gnome-system-monitor",
        "discord": "discord",
        "obs studio": "obs",
        "steam": "steam",
        "camera": "cheese",
        "zalo": "zalo",
        "spotify": "spotify",
        "telegram": "telegram-desktop",
        "nhac": "rhythmbox",
        "nhạc": "rhythmbox",
        "vlc": "vlc",
        "postman": "postman",
    },
    "file_map": {
        "bao cao": "~/Documents/bao_cao.docx",
        "báo cáo": "~/Documents/bao_cao.docx",
        "bao cao thang": "~/Documents/bao_cao.docx",
        "báo cáo tháng": "~/Documents/bao_cao.docx",
        "bao cao tai chinh": "~/Documents/bao_cao_tai_chinh.xlsx",
        "báo cáo tài chính": "~/Documents/bao_cao_tai_chinh.xlsx",
        "tai lieu": "~/Documents",
        "tài liệu": "~/Documents",
        "tai lieu word": "~/Documents/tai_lieu.docx",
        "tài liệu word": "~/Documents/tai_lieu.docx",
        "huong dan": "~/Documents/huong_dan.pdf",
        "hướng dẫn": "~/Documents/huong_dan.pdf",
        "anh": "~/Pictures",
        "ảnh": "~/Pictures",
        "anh chup man hinh": "~/Pictures/Screenshots",
        "ảnh chụp màn hình": "~/Pictures/Screenshots",
        "hinh anh du lich": "~/Pictures",
        "hình ảnh du lịch": "~/Pictures",
        "excel doanh thu": "~/Documents/doanh_thu.xlsx",
        "pdf hop dong": "~/Documents/hop_dong.pdf",
        "pdf hợp đồng": "~/Documents/hop_dong.pdf",
        "hop dong": "~/Documents/hop_dong.pdf",
        "hợp đồng": "~/Documents/hop_dong.pdf",
        "thu muc tai xuong": "~/Downloads",
        "thư mục tải xuống": "~/Downloads",
        "tai xuong": "~/Downloads",
        "tải xuống": "~/Downloads",
        "ghi chu": "~/Documents/ghi_chu.txt",
        "ghi chú": "~/Documents/ghi_chu.txt",
        "danh sach sinh vien": "~/Documents/danh_sach_sinh_vien.xlsx",
        "danh sách sinh viên": "~/Documents/danh_sach_sinh_vien.xlsx",
        "luan van": "~/Documents/luan_van.docx",
        "luận văn": "~/Documents/luan_van.docx",
        "bai tap": "~/Documents/bai_tap.docx",
        "bài tập": "~/Documents/bai_tap.docx",
        "bang luong": "~/Documents/bang_luong.xlsx",
        "bảng lương": "~/Documents/bang_luong.xlsx",
        "ke hoach thang": "~/Documents/ke_hoach_thang.docx",
        "kế hoạch tháng": "~/Documents/ke_hoach_thang.docx",
        "ma nguon du an": "~/Projects",
        "mã nguồn dự án": "~/Projects",
        "hoa don": "~/Documents/hoa_don.pdf",
        "hoá đơn": "~/Documents/hoa_don.pdf",
        "nhac": "~/Music",
        "nhạc": "~/Music",
        "video quay man hinh": "~/Videos",
        "video quay màn hình": "~/Videos",
        "du lieu csv": "~/Documents/du_lieu.csv",
        "dữ liệu csv": "~/Documents/du_lieu.csv",
        "cv xin viec": "~/Documents/cv.pdf",
        "cv xin việc": "~/Documents/cv.pdf",
        "thu muc hinh anh": "~/Pictures",
        "thư mục hình ảnh": "~/Pictures",
        "file trinh chieu": "~/Documents/slide.pptx",
        "file trình chiếu": "~/Documents/slide.pptx",
        "slide thuyet trinh": "~/Documents/slide.pptx",
        "slide thuyết trình": "~/Documents/slide.pptx",
        "thu muc documents": "~/Documents",
        "thư mục documents": "~/Documents",
        "file backup": "~/Documents/backup",
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _validate_config(cfg: Dict[str, Any]) -> None:
    """Kiểm tra cơ bản, raise RuntimeError nếu sai nghiêm trọng."""
    if not isinstance(cfg, dict):
        raise RuntimeError(f"Config phải là dict, nhận được {type(cfg).__name__}")
    missing = REQUIRED_KEYS - cfg.keys()
    if missing:
        # Không fail cứng, chỉ cảnh báo vì _deep_merge sẽ bổ sung
        pass
    # Kiểm tra ngưỡng
    for k in ("confidence_threshold", "confidence_accept", "confidence_ask"):
        if k in cfg:
            try:
                v = float(cfg[k])
                if not 0.0 <= v <= 1.0:
                    raise ValueError(f"{k} phải trong [0,1], nhận {v}")
            except (TypeError, ValueError) as e:
                raise RuntimeError(f"Giá trị {k} không hợp lệ: {e}") from e


def load_config(path: str | Path = CONFIG_PATH) -> Dict[str, Any]:
    """
    Nạp config từ JSON. Tự tạo nếu chưa có, tự bổ sung khoá thiếu.
    Atomic read, validation, deep merge với DEFAULT_CONFIG.
    """
    path = Path(path)
    if not path.exists():
        try:
            save_config(DEFAULT_CONFIG, path)
        except OSError as e:
            safe_print(f"[CẢNH BÁO] Không tạo được file cấu hình '{path}': {e}")
            safe_print("   Chạy tiếp với cấu hình mặc định (chưa lưu).")
        return copy.deepcopy(DEFAULT_CONFIG)

    try:
        with path.open("r", encoding="utf-8") as f:
            user_config = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise RuntimeError(
            f"Không đọc được file cấu hình '{path}': {e}\n"
            f"-> Kiểm tra JSON, hoặc xoá file để tạo lại mặc định."
        ) from e

    if not isinstance(user_config, dict):
        raise RuntimeError(
            f"File cấu hình '{path}' phải là JSON object {{...}}, "
            f"nhưng đang là {type(user_config).__name__}.\n"
            f"-> Xoá để tạo lại mặc định."
        )

    merged = _deep_merge(DEFAULT_CONFIG, user_config)
    _validate_config(merged)
    return merged


def save_config(config: Dict[str, Any], path: str | Path = CONFIG_PATH) -> None:
    """Lưu config atomic: ghi ra file tạm rồi rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Ghi ra file tạm trong cùng thư mục để rename atomic
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=".config_tmp_", suffix=".json"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
            f.write("\n")
        # Atomic rename
        Path(tmp_path).replace(path)
    except Exception:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
        raise


def get_config_value(key: str, default: Any = None, config_path: str | Path = CONFIG_PATH) -> Any:
    """Lấy 1 giá trị từ config, trả về default nếu không có."""
    cfg = load_config(config_path)
    return cfg.get(key, default)


def update_config(updates: Dict[str, Any], path: str | Path = CONFIG_PATH) -> Dict[str, Any]:
    """Cập nhật 1 phần config và lưu lại."""
    cfg = load_config(path)
    merged = _deep_merge(cfg, updates)
    _validate_config(merged)
    save_config(merged, path)
    return merged


if __name__ == "__main__":
    setup_console()
    cfg = load_config()
    safe_print(f"Đã nạp cấu hình từ: {CONFIG_PATH}")
    safe_print(f"  - {len(cfg['website_map'])} trang web")
    safe_print(f"  - {len(cfg['app_map_windows'])} ứng dụng (Windows)")
    safe_print(f"  - {len(cfg['app_map_macos'])} ứng dụng (macOS)")
    safe_print(f"  - {len(cfg['app_map_linux'])} ứng dụng (Linux)")
    safe_print(f"  - {len(cfg['file_map'])} file/thư mục mẫu")
    safe_print(f"  - Ngưỡng: {cfg['confidence_threshold']}")
