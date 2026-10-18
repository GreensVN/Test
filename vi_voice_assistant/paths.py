"""
paths.py - Dữ liệu người dùng và xuất bản file an toàn (v7.10.4)
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
v7.6 nâng cấp:
- thêm `atomic_write_text()`: `voice_cache/index.csv` là file người dùng CŨNG sửa
  bằng tay nên cần đúng một cách ghi an toàn; `atomic_write_json()` giờ gọi qua nó
  để KHÔNG còn hai bản sao thủ tục (fsync, dọn file tạm) lệch nhau được.

v7.8 nâng cấp:
- `data_path()` chặn đường dẫn tuyệt đối và `..`: từ nay mọi file người dùng
  đều nằm TRONG thư mục dữ liệu, không thể trèo ra ngoài chỉ bằng một tên file.

v7.4 nâng cấp:
- `atomic_write_json()`: ghi file tạm -> flush -> fsync -> `os.replace` -> fsync
  thư mục, dọn file tạm khi lỗi, tự tạo thư mục cha, giữ nguyên quyền file gốc.
  Mọi nơi ghi dữ liệu runtime (config, danh sách nhắc việc, lịch sử) đi qua đây.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import sys
import tempfile
from pathlib import Path, PureWindowsPath
from typing import Any

__all__ = [
    "PACKAGE_DIR",
    "app_name",
    "create_json_if_absent",
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
        chosen = Path(tempfile.mkdtemp(prefix=f"{_DIR_NAME}-{os.getpid()}-"))
        _verbose.append(f"không tạo được {source} ({e}) -> dùng {chosen}")
    _cached = chosen
    if _verbose:
        for line in _verbose:
            print(f"[PATHS] {line}", file=sys.stderr)
        _verbose.clear()
    return chosen


def _relative_data_name(filename: str | Path) -> Path:
    """Reject portable absolute/traversing names before any filesystem probe."""
    raw = str(filename)
    name, portable = Path(raw), PureWindowsPath(raw)
    if (not name.parts or "\x00" in raw or name.anchor or portable.anchor or portable.drive
            or ".." in name.parts or ".." in portable.parts):
        raise ValueError(f"Cần đường dẫn tương đối trong thư mục dữ liệu: {raw!r}")
    return name


def _path_within(base: Path, name: Path) -> Path:
    candidate = base / name
    try:
        candidate.resolve().relative_to(base.resolve())
    except (OSError, ValueError, RuntimeError) as error:
        raise ValueError(f"Không cho phép thoát ra ngoài {base}: {str(name)!r}") from error
    return candidate


def data_path(filename: str | Path) -> Path:
    """Return a contained path; reject traversal, drives and static symlink escapes.

    Validate before resolving data_dir(), so an invalid name causes no startup
    directory creation. Both native and Windows-rooted paths are refused on
    every platform; contained relative subdirectories remain supported.
    """
    name = _relative_data_name(filename)
    return _path_within(data_dir(), name)


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
    """Adopt contained legacy files, without ever replacing a concurrent winner.

    Source and destination symlinks must stay inside their respective roots.
    Publication uses a complete temporary file and a no-replace primitive;
    unsupported filesystems fail closed instead of using an overwriting copy.
    """
    target_dir = data_dir()
    moved: list[str] = []
    if target_dir == PACKAGE_DIR:
        return moved
    for name in names:
        try:
            relative = _relative_data_name(name)
            source = _path_within(PACKAGE_DIR, relative)
            target = _path_within(target_dir, relative)
            if os.path.lexists(target):
                continue
            if source.is_file() and _create_bytes_if_absent(target, source.read_bytes()):
                moved.append(name)
        except (OSError, ValueError, TypeError) as error:
            logging.getLogger(__name__).warning("Không nhận dữ liệu cũ %r: %s", name, error)
    return moved


def _fsync_directory(parent: Path) -> None:
    """Best-effort metadata sync; not all filesystems support directory fsync."""
    if os.name == "nt":
        return
    try:
        fd = os.open(str(parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _create_bytes_if_absent(path: str | Path, payload: bytes) -> bool:
    """Publish complete bytes atomically, never replacing an existing pathname.

    NT rename refuses an existing destination; POSIX hard-link publication is
    exclusive. There is intentionally no overwriting fallback if unsupported.
    Parent-directory replacement by a hostile writer is outside this contract.
    """
    target = Path(path)
    if os.path.lexists(target):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=str(target.parent),
                                         prefix=".adopt_tmp_", delete=False) as stream:
            temporary = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            if os.name == "nt":
                os.rename(temporary, target)
                temporary = None
            else:
                os.link(temporary, target)
        except FileExistsError:
            return False  # Only a publication conflict means another writer won.
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            except OSError as error:
                logging.getLogger(__name__).warning("Không dọn được %s: %s", temporary, error)
    _fsync_directory(target.parent)
    return True


def create_json_if_absent(path: str | Path, payload: Any) -> bool:
    """Strict JSON first creation: True if published, False if already present.

    Serialize/encode before touching disk. New files are private (0600 on
    POSIX). Existing files, directories and dangling symlinks are not replaced.
    """
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    return _create_bytes_if_absent(path, text.encode("utf-8"))


def _writable(directory: Path) -> bool:
    """Thử ghi thật chứ ĐỪNG chỉ tin ``os.access`` (nó nói dối trên một số NFS/sandbox)."""
    directory = Path(directory)
    if not directory.is_dir():
        return False
    probe: str | None = None
    try:
        fd, probe = tempfile.mkstemp(dir=str(directory), prefix=".write_probe_")
        os.close(fd)
        return True
    except OSError:
        return False
    finally:
        if probe is not None:
            try:
                os.unlink(probe)
            except OSError:
                pass



def atomic_write_text(path: str | Path, content: str, *, prefix: str | None = None,
                      encoding: str = "utf-8") -> None:
    """Ghi một file VĂN BẢN theo cùng kiểu an toàn như ``atomic_write_json``.

    Tồn tại vì ``voice_cache/index.csv`` (mới v7.6) là file mà người dùng và
    chương trình CÙNG sửa: mở ``"w"`` trực tiếp sẽ cắt mất chỉ mục cũ, và một lần
    ghi hỏng giữa chừng biến cả kho giọng thành "không tìm thấy file nào" - mất
    công tạo lại mà không ai giải thích được vì sao.
    """
    target = Path(str(path))
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp_name = prefix or f".{target.stem}_tmp_"
    fd, tmp_path = tempfile.mkstemp(dir=str(parent), prefix=tmp_name, suffix=target.suffix)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if os.name != "nt":
            try:
                mode = stat.S_IMODE(target.stat().st_mode)
            except FileNotFoundError:
                pass
            else:
                os.chmod(tmp_path, mode)
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError as cleanup_error:
            logging.getLogger(__name__).debug("Không dọn được %s: %s", tmp_path, cleanup_error)
        raise
    _fsync_directory(parent)


def atomic_write_json(path: str | Path, payload: Any, *, prefix: str | None = None,
                      indent: int = 2, trailing_newline: bool = True) -> None:
    """Ghi một file JSON sao cho file cũ KHÔNG BAO GIỜ hỏng giữa chừng.

    Vì sao phải có một hàm chung thay vì mỗi nơi tự viết (v7.4): config.json và
    reminders.json mỗi nơi copy một biến thể - chỗ có fsync, chỗ không - còn
    ``.history.json`` thì mở ``"w"`` trực tiếp, nghĩa là tiến trình chết giữa
    lúc ghi (Ctrl+C, hết đĩa, mất điện) để lại file rỗng/hỏng và người dùng mất
    sạch lịch sử lẫn nhắc nhở đang có.

    Trình tự an toàn trên mọi OS: ghi file tạm CÙNG thư mục (rename trong cùng
    filesystem mới atomic) -> flush + fsync -> ``os.replace`` -> fsync thư mục
    (để chính bản thân rename nằm bền trên đĩa). Lỗi ở bước nào cũng dọn file
    tạm rồi ném lại, không để rác nằm chờ.
    """
    # v7.6: phần ghi đĩa gộp về atomic_write_text() - MỘT chỗ duy nhất biết cách
    # ghi an toàn (JSON chi khac cho chuoi + xuong dong). Truoc day hai ham PHAI
    # giu dong bo tay, va do la noi loi lo ra: them mot kieu file la lai quyen
    # "quen" fsync hoac quen don file tam.
    #
    # Đổi nhỏ có chủ đích: file JSON giờ dùng LF ở mọi nền tảng (trước đây
    # Windows nhận CRLF do dịch ký tự xuống dòng). `json.load` đọc cả hai, và một
    # thư mục dữ liệu có hai kiểu xuống dòng khó xử lý hơn.
    target = Path(str(path))
    text = json.dumps(payload, ensure_ascii=False, indent=indent, allow_nan=False)
    if trailing_newline:
        text += "\n"
    atomic_write_text(target, text, prefix=prefix or f".{target.stem}_tmp_")


if __name__ == "__main__":      # python paths.py -> in ra nơi sẽ lưu dữ liệu
    info = describe()
    print("package dir :", info["package_dir"])
    print("data dir    :", info["data_dir"], "(nguon: source)" if info["from_source"] else "")
    print("ghi duoc    :", "co" if info["writable"] else "KHONG")
