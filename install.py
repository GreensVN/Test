#!/usr/bin/env python3
"""
install.py - Bộ cài đặt & tự kiểm tra cho Trợ lý ảo tiếng Việt (mới v7.3)
-------------------------------------------------------------------------

Vấn đề của cách cũ: người dùng mới phải đọc README, tự nhớ 4-5 lệnh pip, tự
đoán xem máy mình thiếu gì, và sau khi cài thì KHÔNG BIẾT đã thành công chưa.
Ba chỗ hay hỏng nhất thực tế:

  1. Linux bản mới (Debian 12, Fedora 38, Ubuntu 23.04+) chặn ``pip install``
     vào hệ thống (PEP 668 "externally-managed-environment") -> người dùng thấy
     lỗi đỏ, tưởng dự án hỏng, trong khi chỉ cần ``--user`` hoặc venv;
  2. cài nhầm vào Python hệ thống rồi thiếu quyền ghi -> ``PermissionError``;
  3. cài xong không biết model đã huấn luyện chưa, micro/TTS có dùng được không.

Script này chỉ dùng THƯ VIỆN CHUẨN (chạy được trước khi cài bất cứ gì):

    python install.py                  # tu van + cai goi "du dung" cho may nay
    python install.py --check          # chi chan doan, KHONG cai gi
    python install.py --profile ml     # them scikit-learn (chinh xac hon)
    python install.py --profile voice  # them TTS/STT (doc + nghe)
    python install.py --profile all
    python install.py --offline        # khong mang -> kiem tra che do stdlib
    python install.py --dry-run        # in lenh se chay, khong chay

Mọi quyết định (chọn cờ pip, suy ra PEP 668) nằm trong hàm THUẦN nên có test
đơn vị mà không cần gọi pip thật - xem tests/test_v73_ux.py.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE / "vi_voice_assistant"

PROFILES: dict[str, tuple[str, ...]] = {
    "core": (),                                    # khong can gi - model lite + print
    "ml": ("scikit-learn", "joblib", "rapidfuzz"),
    "voice": ("pyttsx3", "gTTS", "SpeechRecognition", "sounddevice", "numpy"),
    "dev": ("pytest", "ruff"),
}
PROFILES["full"] = tuple(dict.fromkeys(PROFILES["ml"] + PROFILES["voice"]))
PROFILES["all"] = PROFILES["full"] + PROFILES["dev"]

PEP668_MARKER = "externally-managed-environment"


def log(msg: str = "") -> None:
    print(msg, flush=True)


def detect_python() -> tuple[tuple[int, int], bool]:
    """(phiên bản, có phải Python được hỗ trợ không)."""
    return sys.version_info[:2], sys.version_info[:2] >= (3, 9)


def venv_hint() -> str:
    """Lời khuyên tạo môi trường riêng theo ĐÚNG nền tảng đang chạy."""
    if os.name == "nt":
        return ("python -m venv .venv\n"
                "  .venv\\Scripts\\activate\n"
                "  python -m pip install -U pip")
    return ("python3 -m venv .venv\n"
            "  source .venv/bin/activate\n"
            "  python -m pip install -U pip")


def plan_commands(packages: tuple[str, ...], editable: bool) -> list[list[str]]:
    """Các lệnh pip sẽ chạy, theo đúng thứ tự.

    Gộp mọi thư viện của một profile vào MỘT lệnh pip: mỗi lần gọi pip là ~1-3
    giây tự kiểm tra PyPI, gọi 5 lần cho 5 gói chính là cảm giác "cài đặt treo
    máy" mà người dùng hay phàn nàn.
    """
    commands: list[list[str]] = []
    if packages:
        commands.append([*base_pip_args(), "install", "--upgrade", *packages])
    if editable:
        commands.append([*base_pip_args(), "install", "-e", str(HERE)])
    return commands


def base_pip_args() -> list[str]:
    """Luôn gọi pip qua ``sys.executable -m pip``.

    ``pip install`` trẩn trơi có thể thuộc Python KHÁC (máy có 3.9 + 3.12 cùng
    lúc, hoặc pip của bản cài hệ thống) -> cài xong vẫn "thiếu thư viện".
    """
    return [sys.executable, "-m", "pip"]


def retry_flags_for(stderr: str, already: list[str]) -> list[str] | None:
    """Đề xuất cờ cài lại dựa trên lỗi pip thật sự. None = bó tay (báo người)."""
    text = (stderr or "").lower()
    # Thu theo thu tu "it hai long nhat" -> "rang tay nhat": --user van ghi vao
    # nha nguoi dung, con --break-system-packages moi cham vao site-packages.
    if PEP668_MARKER in text or "break-system-packages" in text:
        if "--user" not in already:
            return ["--user"]
        if "--break-system-packages" not in already:
            return ["--break-system-packages"]
        return None
    if "permission denied" in text or "could not create" in text or "read-only file system" in text:
        return ["--user"] if "--user" not in already else None
    return None


def run(cmd: list[str], dry_run: bool = False, cwd: Path | None = None) -> tuple[int, str]:
    """Chạy một lệnh, trả về (mã exit, gộp stdout+stderr).

    ``cwd`` mặc định là thư mục dự án: toàn bộ mã nguồn dùng import PHẲNG
    (``from lite_model import ...``) nên phải chạy từ trong ``vi_voice_assistant``
    thì mới tìm thấy nhau.
    """
    log("  $ " + " ".join(cmd))
    if dry_run:
        return 0, ""
    try:
        proc = subprocess.run(      # argv dang list, khong qua shell
            cmd, capture_output=True, text=True, timeout=1800,
            cwd=str(cwd or PKG),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def install_with_fallbacks(cmd: list[str], dry_run: bool = False,
                           max_retries: int = 2) -> tuple[bool, str]:
    """Cài một lệnh pip, tự thử lại với cờ phù hợp khi dính PEP 668/thiếu quyền.

    Trả về (thành_công, thông_báo_cho_người_dùng). Không bao giờ ném lỗi: mục
    tiêu của script là DẪN người dùng tới lệnh đúng, không phải crash thay họ.
    """
    extra: list[str] = []
    note = ""
    for attempt in range(max_retries + 1):
        code, output = run(cmd + extra, dry_run=dry_run)
        if code == 0:
            return True, note
        suggested = retry_flags_for(output, extra)
        if not suggested or attempt >= max_retries:
            break
        note = f"pip từ chối (lỗi môi trường), thử lại với {' '.join(suggested)}"
        log(f"  [!] {note}")
        extra = extra + suggested
    tail = "\n".join(line for line in output.splitlines() if line.strip())[-900:]
    hint = (f"\n  Gợi ý: tạo môi trường riêng rồi chạy lại script:\n\n  {venv_hint()}\n")
    return False, f"pip thất bại.\n{tail}{hint}"


def check_imports(packages: tuple[str, ...]) -> list[str]:
    """Những gói ĐÃ yêu cầu cài mà vẫn không import được (pip im lặng fail)."""
    import importlib.util

    module_names = {"scikit-learn": "sklearn", "pillow": "PIL"}
    missing: list[str] = []
    for name in packages:
        module = module_names.get(name, name.replace("-", "_"))
        if importlib.util.find_spec(module) is None:
            missing.append(name)
    return missing


def doctor(check_only: bool) -> int:
    """Gọi đúng bộ chẩn đoán của dự án (diagnostic.py) - không tự viết lại."""
    if not PKG.is_dir():
        log(f"[X] Không tìm thấy {PKG} - chạy install.py từ thư mục chứa dự án.")
        return 1
    code = subprocess.call([sys.executable, "diagnostic.py"], cwd=str(PKG))
    if check_only:
        log("\n(--check: chỉ chẩn đoán, không cài gì thêm)")
    return code


def ensure_model(dry_run: bool = False) -> bool:
    """Sinh model lite ngay lần cài đầu để lần chạy ĐẦU TIÊN không phải chờ.

    Model được cache trong thư mục dữ liệu (paths.py) và tự vô hiệu theo
    fingerprint dataset, nên việc này chỉ tốn ~0.2 giây MỘT lần.
    """
    log("\n[4/4] Chuẩn bị mô hình hiểu ý (lần đầu ~1 giây)...")
    code, _out = run([sys.executable, "-c",
                      "from lite_model import get_lite_model; get_lite_model()"],
                     dry_run=dry_run)
    if code == 0:
        log("  đã sẵn sàng.")
    else:
        log("  [!] chưa tạo được model - trợ lý sẽ tự tạo khi chạy lần đầu.")
    return code == 0


def run_tests(dry_run: bool = False) -> int:
    log("\n[3/4] Chạy bộ kiểm thử của dự án...")
    code, _ = run([sys.executable, "run_tests.py", "-q"], dry_run=dry_run)
    if code == 0:
        log("  tất cả test ĐẠT.")
    else:
        log(f"  [!] bộ test báo lỗi (mã {code}) - xem chi tiết: python run_tests.py -v")
    return code


def _describe_command(cmd: list[str], profile: str) -> str:
    """Nhãn bước trong log: phân biệt 'cài dự án' và 'cài thư viện'."""
    return "cài dự án (để có lệnh `vi-assistant`)" if "-e" in cmd else f"cài thư viện ({profile})"


def _first_line(text: str, limit: int = 110) -> str:
    """Dòng đầu của output lỗi pip, cắt ngắn cho vừa dòng log."""
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()[:limit]
    return "(không có chi tiết lỗi)"


def _install_phase(args: argparse.Namespace, packages: tuple[str, ...]) -> int | None:
    """Toàn bộ bước pip. Trả về 1 nếu phải dừng, None nếu đi tiếp được.

    Tách khỏi main() để main() chỉ còn là "kịch bản" (kiểm tra Python -> cài ->
    test -> tạo model) thay vì một hàm 13 nhánh vừa in log vừa quyết định lỗi.
    """
    if args.offline:
        if packages:
            log(f"\n[!] --offline: BỎ qua {len(packages)} thư viện của profile '{args.profile}'.")
            log("    Trợ lý vẫn chạy được: model lite (thuần Python) + engine in chữ.")
        return None

    commands = plan_commands(packages, args.editable)
    total = 1 + len(commands)
    log(f"\n[1/{total}] Nâng pip")
    ok, note = install_with_fallbacks([*base_pip_args(), "install", "--upgrade", "pip"],
                                      dry_run=args.dry_run)
    if not ok:
        # Pip cu thuong van cai duoc thi ta bao duoc: day la canh bao, KHONG
        # duoc phep lam fail ca qua trinh cai.
        log(f"  [!] không nâng được pip ({_first_line(note)}) - tiếp tục với pip hiện có")

    for index, cmd in enumerate(commands, start=2):
        log(f"\n[{index}/{total}] {_describe_command(cmd, args.profile)}")
        ok, note = install_with_fallbacks(cmd, dry_run=args.dry_run)
        if not ok:
            log(f"[X] {_first_line(note, 300)}")
            return 1

    if packages:
        missing = [] if args.dry_run else check_imports(packages)
        if missing:
            log(f"  [!] đã chạy pip xong nhưng vẫn thiếu: {', '.join(missing)}")
            log(f"      Tạo môi trường riêng rồi chạy lại là sạch nhất:\n\n      {venv_hint()}")
            return 1
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cài đặt + tự kiểm tra Trợ lý ảo tiếng Việt (chỉ cần stdlib)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Goi y:\n"
            "  python install.py --check        chi xem may da du gi\n"
            "  python install.py                cai goi co ban + kiem tra\n"
            "  python install.py --profile all  day du nhat (ML + giong + dev)\n"
        ),
    )
    parser.add_argument("--profile", choices=sorted(PROFILES), default="core",
                        help="bộ thư viện sẽ cài thêm (mặc định: core = không cần gì)")
    parser.add_argument("--check", action="store_true", help="chỉ chẩn đoán, không cài")
    parser.add_argument("--offline", action="store_true",
                        help="không gọi pip (máy không có mạng) - vẫn kiểm tra + tạo model")
    parser.add_argument("--no-editable", dest="editable", action="store_false",
                        help="không cài dự án ở chế độ -e (chỉ cài thư viện)")
    parser.add_argument("--skip-tests", action="store_true", help="bỏ qua bước chạy test")
    parser.add_argument("--dry-run", action="store_true", help="in lệnh, không chạy")
    parser.add_argument("--index-url", default=os.environ.get("PIP_INDEX_URL"),
                        help="dùng mirror pip riêng (máy công ty thường cần)")
    args = parser.parse_args(argv)

    version, supported = detect_python()
    log("=" * 62)
    log(f" Cài Trợ lý ảo tiếng Việt - Python {version[0]}.{version[1]}")
    log("=" * 62)
    if not supported:
        log(f"[X] Cần Python >= 3.9 (đang có {version[0]}.{version[1]}).")
        log("    Cách an toàn nhất: tải bản 3.11/3.12 rồi chạy lại script này.")
        return 1

    if args.check:
        return doctor(True)

    packages = PROFILES[args.profile]
    if args.index_url:
        os.environ["PIP_INDEX_URL"] = args.index_url

    error = _install_phase(args, packages)
    if error:
        return error

    if not args.skip_tests:
        run_tests(args.dry_run)
    ensure_model(args.dry_run)

    log("\n" + "=" * 62)
    log(" XONG. Chạy thử:")
    log('   python vi_voice_assistant/main.py "mở youtube" --dry-run')
    log("   python vi_voice_assistant/main.py            # REPL, gõ help để xem lệnh")
    if args.editable and not args.offline:
        log("   vi-assistant --doctor                      # nếu đã cài bằng pip")
    log("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
