"""
config.py
---------
Nạp cấu hình từ config.json.

v7.0 nâng cấp:
- Dùng pathlib, type hints đầy đủ
- Thêm validation schema
- Lưu file atomic (temp + rename) để tránh hỏng khi mất điện
- Thêm hàm get_config_value, update_config

v7.2 nâng cấp:
- Bỏ mô tả "cache với TTL" trong docstring: chưa từng tồn tại cache nào (đo
  thực tế load_config() chỉ ~0.3ms nên cache cũng không đáng đánh đổi độ phức
  tạp + nguy cơ đọc cấu hình cũ). Docstring nay mô dung đúng những gì code làm.
- _validate_config() TRƯỚC ĐÂY LÀ CODE CHẾT: nó tính ra `missing` rồi `pass`,
  tức mọi validation bị bỏ qua im lặng. Nay báo cáo thật (khoá thiếu / khoá lạ
  do gõ sai tên / sai kiểu map) qua logging, và bắt lỗi kiểu sớm ở những khoá
  mà executor.py sẽ crash nếu sai.
- save_config() thêm fsync trước khi rename: chỉ "temp + rename" KHÔNG đảm bảo
  nội dung đã nằm trên đĩa - mất điện đúng lúc rename có thể để lại file rỗng.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

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

MAP_KEYS = (
    "website_map",
    "app_map_windows",
    "app_map_macos",
    "app_map_linux",
    "file_map",
)

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, Any] = {
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


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _validate_config(cfg: dict[str, Any]) -> None:
    """Kiểm tra config: raise RuntimeError nếu sai nghiêm trọng, cảnh báo nếu nghi ngờ.

    v7.2: trước đây hàm này tính `missing = REQUIRED_KEYS - cfg.keys()` rồi
    `pass` - nghĩa là không kiểm tra gì cả, dù docstring nói "raise nếu sai
    nghiêm trọng". Hai hậu quả thật:
      * tên khoá viết SAI chính tả (vd "app_map_window") bị im lặng bỏ qua,
        người dùng thêm app vào file config mà trợ lý "không hiểu" mãi;
      * map sai kiểu (vd website_map là list) lọt qua tới executor.py mới nổ
        AttributeError ở giữa lệnh, báo lỗi khó hiểu.
    """
    if not isinstance(cfg, dict):
        raise RuntimeError(f"Config phải là dict, nhận được {type(cfg).__name__}")

    # Khoá thiết YẾU: _deep_merge luôn bù từ DEFAULT_CONFIG nên chỉ cảnh báo -
    # nhưng phải cảnh báo, vì nó thường là dấu hiệu của TÊN KHOÁ BỊ GÕ SAI.
    missing = REQUIRED_KEYS - set(cfg.keys())
    unknown = set(cfg.keys()) - set(DEFAULT_CONFIG.keys())
    if missing:
        logger.warning(
            "config.json thiếu khoá %s - đã tự bù giá trị mặc định. "
            "Nếu bạn gõ tên khoá khác đi, hãy viết ĐÚNG tên.", ", ".join(sorted(missing))
        )
    if unknown:
        logger.warning(
            "config.json có khoá LẠ không được chương trình biết tới: %s - "
            "nó sẽ bị BỎ QUA. Kiểm tra lại chính tả tên khoá.", ", ".join(sorted(unknown))
        )

    # Ngưỡng tự tin: sai là fail cứng (rất khó gỡ nếu để lọt).
    for k in ("confidence_threshold", "confidence_accept", "confidence_ask"):
        if k in cfg:
            try:
                v = float(cfg[k])
            except (TypeError, ValueError) as e:
                raise RuntimeError(f"Giá trị {k} không hợp lệ: {e}") from e
            if not 0.0 <= v <= 1.0:
                raise RuntimeError(f"{k} phải trong [0,1], nhận {v}")

    # Map phải là dict str->str, nếu không executor.py sẽ crash lúc dùng.
    for k in MAP_KEYS:
        value = cfg.get(k)
        if value is None:
            continue
        if not isinstance(value, dict):
            raise RuntimeError(
                f'"{k}" phải là JSON object {{"ten": "gia tri"}}, '
                f"nhưng đang là {type(value).__name__}."
            )
        bad = [str(key) for key, val in value.items() if not isinstance(val, str)]
        if bad:
            # Lưu ý khi sửa dòng dưới: không được đặt nháy kép cùng loại BÊN
            # TRONG biểu thức f-string - cú pháp đó chỉ hợp lệ từ Python 3.12,
            # mà dự án hỗ trợ từ 3.9 (sẽ SyntaxError trên Python phổ biến).
            bad_list = ", ".join(sorted(bad)[:5])
            raise RuntimeError(
                f'"{k}" có giá trị KHÔNG phải chuỗi cho các khoá: {bad_list}. '
                'Mọi giá trị phải là chuỗi, ví dụ: "chrome": "chrome.exe".'
            )


def load_config(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
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


def save_config(config: dict[str, Any], path: str | Path = CONFIG_PATH) -> None:
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
            # v7.2: rename CHƯA đủ để an toàn khi mất điện - nội dung có thể
            # còn nằm trong buffer của OS. fsync trước rồi mới replace.
            f.flush()
            os.fsync(f.fileno())
        # Atomic rename
        Path(tmp_path).replace(path)
    except Exception:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError as cleanup_error:
            # File tạm nằm lại trên đĩa không nguy hiểm bằng việc che mất lỗi
            # chính (đang `raise` ở dưới) - ghi lại để lần sau còn truy.
            logger.debug("Không dọn được file tạm %s: %s", tmp_path, cleanup_error)
        raise


def get_config_value(key: str, default: Any = None, config_path: str | Path = CONFIG_PATH) -> Any:
    """Lấy 1 giá trị từ config, trả về default nếu không có."""
    cfg = load_config(config_path)
    return cfg.get(key, default)


def update_config(updates: dict[str, Any], path: str | Path = CONFIG_PATH) -> dict[str, Any]:
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
