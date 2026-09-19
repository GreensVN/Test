"""
paths.py - Xác định nơi lưu DỮ LIỆU NGƯỜI DÙNG (v7.2 -> v7.3)
-------------------------------------------------------------

VẤN ĐỀ BẢN CŨ
Mọi module đều tự tính ``BASE_DIR = Path(__file__).parent`` rồi ghi
``config.json`` / ``reminders.json`` / ``feedback.csv`` / ``logs/`` / model
``.pkl`` NGAY VÀO THƯ MỤC CÀI ĐẶT. Chạy từ thư mục source thì ổn, nhưng
``pip install .`` thì thư mục đó là ``site-packages``:

  * máy cài cho CẢ HỆ THỐNG (sudo pip / C:\\Program Files) -> thư mục chỉ đọc ->
    ``save_config()``/``_save_reminders()`` ném PermissionError giữa phiên, hoặc
    trầm trọng hơn: lời nhắc "đã lưu" nhưng thật ra không ghi được gì;
  * dữ liệu cá nhân (lịch sử lệnh, phản hồi, log) nằm lẫn trong thư viện, bị
    XÓA MỖI KHI NÂNG CẤP/GỠ CÀI ĐẶT;
  * hai người dùng trên cùng một máy chia sẻ chung một ``config.json``.

QUY TẮC CHỌN THƯ MỤC (thứ tự ưu tiên)
  1. ``$VI_ASSISTANT_HOME`` nếu được đặt (mọi trường hợp khác bị bỏ qua) - cần
     cho CI, cho môi trường test, và cho người muốn di chuyển dữ liệu;
  2. thư mục source, NẾU nó ghi được và trông giống một bản checkout (có
     ``run_tests.py``) - giữ nguyên hành vi quen thuộc của dự án từ v6;
  3. thư mục dữ liệu chuẩn của người dùng:
       Windows  %LOCALAPPDATA%\\vi_voice_assistant
       macOS    ~/Library/Application Support/vi_voice_assistant
       Linux    $XDG_DATA_HOME/vi_voice_assistant  (mặc định ~/.local/share/...)
     - không bao giờ cần quyền quản trị, không bị xoá khi nâng cấp gói.

LƯU Ý TƯƠNG THÍCH
  * ``HOME`` có thể bị monkeypatch bằng CHUỖI trong test (bài học từ v7.0) ->
    mọi chỗ dùng home đều đi qua ``Path`` trước khi gọi phương thức;
  * các module anh em giữ nguyên TÊN biến ({CONFIG_PATH, REMINDERS_PATH, ...})
    nên test cũ và ``monkeypatch.setattr`` vẫn hoạt động;
  * không import gì ngoài stdlib -> dùng được cả khi chưa cài gì (hợp đồng
    "chỉ cần stdlib" của dự án).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = [
    "PACKAGE_DIR",
    "app_name",
    "data_dir",
    "data_path",
    "describe",
    "is_source_checkout",
    "migrate_from_package_dir",
    "reset_cache",
]

_ENV_HOME = "VI_ASSISTANT_HOME"
_DIR_NAME = "vi_voice_assistant"

PACKAGE_DIR = Path(__file__).resolve().parent

# Bật/tắt in ấn khi resolve thư mục (main.py bật sau khi đọc cờ --debug).
_verbose: list[str] = []
_cached: Path | None = None


def app_name() -> str:
    return _DIR_NAME


def is_source_checkout(directory: Path | None = None) -> bool:
    """Có đang chạy từ một bản checkout của dự án không (hay đã cài bằng pip)?

    Dấu hiệu dùng được là ``pyproject.toml`` ở CHA của thư mục gói - nó KHÔNG
    bao giờ đi vào wheel. (Chi tiết ``run_tests.py`` thoạt trông hợp lý nhưng SAI:
    file nằm trong gói nên ``pip install .`` cũng copy nó sang site-packages,
    và mọi bản đã cài sẽ bị nhận nhầm là "source" - tức lại ghi dữ liệu vào
    site-packages, đúng cái bug mà bản này sinh ra để sửa.)
    """
    here = PACKAGE_DIR if directory is None else Path(directory)
    return (here.parent / "pyproject.toml").is_file()


def _user_data_dir() -> Path:
    """Thư mục dữ liệu chuẩn theo nền tảng (không cần quyền quản trị)."""
    env_override = os.environ.get("XDG_DATA_HOME", "").strip()
    if env_override:
        return Path(env_override) / _DIR_NAME
    home = Path(str(os.path.expanduser("~")))     # str() cho phép HOME bị patch bằng chuỗi
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA", "").strip()
        # FALLBACK quan trọng: LOCALAPPDATA vắng mặt khi chạy service/CI tren
        # Windows -> neu tin tuyet doi vao no thi chu "." se ghi du lieu vao
        # thu muc lam viec cua tien trinh (rat kho tim khi can xoa).
        return (Path(base) if base else home / "AppData" / "Local") / _DIR_NAME
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / _DIR_NAME
    return home / ".local" / "share" / _DIR_NAME


def data_dir() -> Path:
    """Thư mục chứa dữ liệu người dùng; tự tạo nếu chưa có (im lặng khi lỗi)."""
    global _cached
    if _cached is not None:
        return _cached

    override = os.environ.get(_ENV_HOME, "").strip()
    if override:
        # expanduser + abspath: mot duong dan TUONG DOI ma de nguyen thi khi
        # tro ly doi cwd giua chung (lenh mo file/anh co the lam vay) la toan bo
        # du lieu "nhảy" theo thu muc moi - tim khong ra nua.
        chosen = Path(os.path.abspath(os.path.expanduser(override)))
        source = f"${_ENV_HOME}"
    elif is_source_checkout() and _writable(PACKAGE_DIR):
        chosen = PACKAGE_DIR
        source = "thu muc source"
    else:
        chosen = _user_data_dir()
        source = "thu muc du lieu nguoi dung"

    try:
        chosen.mkdir(parents=True, exist_ok=True)
    except OSError as e:                       # đĩa đầy / thiếu quyền / đường dẫn lạ
        # KHÔNG ném lỗi ở đây: trợ lý vẫn phải chạy được (lời nhắc + log khi đó
        # chỉ nằm trong RAM). Rơi về temp dir - luôn ghi được trên mọi nền tảng.
        # /tmp chỉ là FALLBACK, tên thư mục mang PID riêng nên không ghi đè ai.
        tmp_root = os.environ.get("TEMP", "/tmp")       # noqa: S108 - fallback, co PID rieng
        chosen = Path(os.path.join(tmp_root, f"{_DIR_NAME}-{os.getpid()}"))
        try:
            chosen.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        _verbose.append(f"không tạo được {source} ({e}) -> dùng {chosen}")
    _cached = chosen
    if _verbose:
        for line in _verbose:
            print(f"[PATHS] {line}")
        _verbose.clear()
    return chosen


def data_path(filename: str | Path) -> Path:
    """Đường dẫn một file dữ liệu (``data_path("config.json")``)."""
    return data_dir() / Path(str(filename))


def describe() -> dict[str, object]:
    """Tóm tắt để ``--doctor``/``--sysinfo`` in ra."""
    d = data_dir()
    return {
        "data_dir": str(d),
        "writable": _writable(d),
        "from_source": d == PACKAGE_DIR,
        "package_dir": str(PACKAGE_DIR),
    }


def reset_cache() -> None:
    """Quên kết quả đã cache - dùng trong test và sau khi đổi biến môi trường."""
    global _cached
    _cached = None


def migrate_from_package_dir(names: tuple[str, ...]) -> list[str]:
    """Sao chép dữ liệu cũ từ thư mục package sang thư mục người dùng.

    Chỉ áp dụng khi thư mục package KHÔNG phải nơi đang dùng và file đích chưa
    tồn tại - tức một lần duy nhất, không bao giờ ghi đè dữ liệu mới. Người dùng
    chuyển từ "chạy source" sang "pip install" sẽ không mất lời nhắc/logic đã
    dạy, thay vì âm thầm bắt đầu lại từ đầu.
    """
    target_dir = data_dir()
    moved: list[str] = []
    if target_dir == PACKAGE_DIR:
        return moved
    for name in names:
        src, dst = PACKAGE_DIR / name, target_dir / name
        try:
            if src.is_file() and not dst.exists():
                dst.write_bytes(src.read_bytes())
                moved.append(name)
        except OSError:
            continue          # không có quyền đọc file cũ -> bỏ qua, chạy tiếp
    return moved


def _writable(directory: Path) -> bool:
    """Thử ghi thật chứ ĐỪNG chỉ tin ``os.access`` (nó nói dối trên một số NFS/sandbox)."""
    directory = Path(directory)
    if not directory.is_dir():
        return False
    probe = directory / f".write_probe_{os.getpid()}"
    try:
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        try:
            probe.unlink()
        except OSError:
            pass
        return False


if __name__ == "__main__":      # python paths.py -> in ra nơi sẽ lưu dữ liệu
    info = describe()
    print("package dir :", info["package_dir"])
    print("data dir    :", info["data_dir"], "(nguon: source)" if info["from_source"] else "")
    print("ghi duoc    :", "co" if info["writable"] else "KHONG")
