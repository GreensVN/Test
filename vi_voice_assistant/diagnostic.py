"""
diagnostic.py - Chẩn đoán cài đặt & môi trường (mới ở v7.3)
-----------------------------------------------------------

Vì sao cần: trước đây người dùng mới chỉ có ``--sysinfo`` (báo cáo khả năng
nền tảng) và một README dài. Khi trợ lý "chạy nhưng không nói", "mở app không
được" hay "nói mãi không hiểu", họ phải tự đoán:
thiếu thư viện? chưa huấn luyện model? config.json sai? thư mục không ghi
được? Mỗi câu hỏi đó là một lần mở Issue.

``python main.py --doctor`` trả lời hết trong một lần chạy, và QUAN TRỌNG HƠN:
in ra ĐÚNG LỆNH cần gõ để khắc phục (theo đúng nền tảng đang chạy).

Chạy độc lập: ``python diagnostic.py`` hoặc ``vi-doctor`` (khi cài bằng pip).
Không cần thư viện ngoài, không phát tiếng, không sửa gì - chỉ đọc.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import platform
import sys
import time
from pathlib import Path

from platform_utils import safe_print, setup_console

logger = logging.getLogger(__name__)

OK = "[OK]  "
WARN = "[!]  "
BAD = "[X]  "

# Lenh khac phuc in ra o cuoi bao cao. Viet chu don ben ngoai de khoi phai
# escape dau nhay kep ben trong (doan `python -c "..."` luon chu"a nhay kep).
FULL_INSTALL = 'pip install "vi-voice-assistant[full]"'
TTS_INSTALL = 'pip install "vi-voice-assistant[tts]"'
STT_INSTALL = 'pip install "vi-voice-assistant[stt]"'
AI_VOICE_INSTALL = 'pip install "vi-voice-assistant[ai-voice]" && python giong_noi_ai.py tai'
LITE_RETRAIN = 'python -c "from lite_model import train_lite_model as t; t()"'
CONFIG_WRITE = 'python -c "import config; config.save_config(config.DEFAULT_CONFIG)"'

OPTIONAL_LIBS = {
    # ten goi: (mo ngan, lenh cai)
    "numpy": ("cần cho sounddevice/STT và model ML", "pip install numpy"),
    "sklearn": ("model TF-IDF chính xác hơn lite (~98%)", FULL_INSTALL),
    "joblib": ("lưu/nạp model sklearn", FULL_INSTALL),
    "rapidfuzz": ("tìm kiếm mờ nhanh; thiếu -> dùng difflib (chậm hơn)", "pip install rapidfuzz"),
    "pyttsx3": ("đọc giọng nói offline trên Windows/macOS", TTS_INSTALL),
    "SpeechRecognition": ("nhận lệnh từ micro", STT_INSTALL),
    "sounddevice": ("ghi âm từ micro", STT_INSTALL),
}


def _module_available(name: str) -> bool:
    """Có module mà KHÔNG import nó (import pyttsx3/torch là mất vài giây)."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _package_mode() -> str:
    import paths

    return "source" if paths.is_source_checkout() else "đã cài bằng pip"


def check_runtime(version_info: tuple[int, ...] | None = None) -> list[tuple[str, str]]:
    """Kiểm tra Python/OS. ``version_info`` chỉ để test mô phỏng bản Python khác.

    v7.4: bản v7.3 gọi ``platform.major`` (không tồn tại - phải là
    ``sys.version_info.major``), nên chỉ cần chạy trên Python >= 3.14 là
    ``vi-doctor`` chết bằng AttributeError trước khi in được dòng nào.
    """
    py = tuple(version_info) if version_info is not None else tuple(sys.version_info[:3])
    rows = [
        (OK, f"Python {platform.python_version()} ({sys.executable})"),
        (OK, f"Hệ điều hành: {platform.system()} {platform.release()} - {platform.machine()}"),
        (OK, f"Chạy từ: {_package_mode()}"),
    ]
    if py[:2] < (3, 9):
        rows.insert(0, (BAD, f"Python {py[0]}.{py[1]} < 3.9 - dự án không hỗ trợ"))
    elif py[:2] >= (3, 14):
        rows.insert(0, (WARN, f"Python {py[0]}.{py[1]} mới hơn bản đã kiểm tra (3.13)"))
    return rows


def _section_result(title: str, fn) -> tuple[list[tuple[str, str]], list[str]]:
    """Gọi một hàm kiểm tra và biến mọi lỗi bất ngờ thành một dòng [X].

    Mỗi mục của báo cáo đọc dữ liệu người dùng (config.json, model.pkl, thư
    mục giọng nói) - một file hỏng là đủ để ``vi-doctor`` chết và người dùng
    MẤT LUÔN phần còn lại của báo cáo, đúng lúc họ cần nó nhất.
    """
    try:
        result = fn()
    except Exception as e:          # cý ý bất mọi loại lỗi: báo cáo phải in ra được
        logger.warning("Mục %s của --doctor lỗi: %s", title, e, exc_info=True)
        return ([(BAD, f"{title}: bộ kiểm tra lỗi ({type(e).__name__}: {e})")], [])
    rows, extra = result
    return list(rows), list(extra)


def check_data_dir() -> tuple[list[tuple[str, str]], list[str]]:
    rows: list[tuple[str, str]] = []
    fixes: list[str] = []
    try:
        import paths

        info = paths.describe()
    except Exception as e:                        # paths luôn import được; bảo vệ cho file cài lệch
        return [(BAD, f"không đọc được paths.py: {e}")], []

    data_dir = str(info["data_dir"])
    if info["writable"]:
        rows.append((OK, f"Thư mục dữ liệu ghi được: {data_dir}"))
    else:
        rows.append((BAD, f"THƯ MỤC DỮ LIỆU KHÔNG GHI ĐƯỢC: {data_dir}"))
        rows.append((WARN, "  -> lời nhắc/log/history sẽ KHÔNG lưu được giữa các phiên"))
        if platform.system().lower().startswith("window"):
            fixes.append(f'icacls "{data_dir}" /grant "%USERNAME%:(OI)(CI)F"')
        else:
            fixes.append(f'mkdir -p "{data_dir}" && chmod u+w "{data_dir}"')
    if not info["from_source"]:
        rows.append((OK, "đang dùng thư mục dữ liệu người dùng (đúng, vì đã cài bằng pip)"))
    return rows, fixes


def check_config() -> tuple[list[tuple[str, str]], list[str]]:
    rows: list[tuple[str, str]] = []
    fixes: list[str] = []
    import config

    path = Path(str(config.CONFIG_PATH))
    if not path.is_file():
        rows.append((WARN, f"chưa có config.json -> dùng giá trị mặc định trong code: {path}"))
        fixes.append(CONFIG_WRITE)
        return rows, fixes
    try:
        cfg = config.load_config(path)
    except Exception as e:
        rows.append((BAD, f"config.json KHÔNG ĐỌC ĐƯỢC: {e}"))
        fixes.append(f"mở {path} bằng trình soạn thảo, sửa JSON cho đúng cú pháp")
        return rows, fixes

    # app_map RỖNG trong config không có nghĩa là "mở app không được": executor
    # gộp thêm app_map_<nền tảng> + APP_DEFAULTS, nên phải đếm bằng chính hàm
    # mà executor dùng lúc chạy lệnh.
    try:
        import executor

        n_apps = len(executor._app_map_for_platform())
    except Exception:
        n_apps = len(cfg.get("app_map") or {})
    counts = {
        "ứng dụng (nền tảng này)": n_apps,
        "website (website_map)": len(cfg.get("website_map") or {}),
        "đường dẫn (file_map)": len(cfg.get("file_map") or {}),
        "hành động nguy hiểm": len(cfg.get("dangerous_actions") or []),
    }
    rows.append((OK, f"config.json hợp lệ: {path}"))
    rows.append((OK, "  " + " | ".join(f"{k}={v}" for k, v in counts.items())))
    low = float(cfg.get("confidence_accept") or 0)
    if low and not 0.2 <= low <= 0.9:
        rows.append((WARN, f"  confidence_accept={low:.2f} hơi cực đoan (nên 0.3-0.8)"))
    return rows, fixes


def check_models() -> tuple[list[tuple[str, str]], list[str]]:
    rows: list[tuple[str, str]] = []
    fixes: list[str] = []
    import intent_model
    import lite_model

    ml = Path(str(intent_model.MODEL_PATH))
    lite = Path(str(lite_model.LITE_MODEL_PATH))
    if ml.is_file():
        rows.append((OK, f"model sklearn: {ml.name} ({ml.stat().st_size // 1024} KB)"))
    elif lite.is_file():
        age_h = (time.time() - lite.stat().st_mtime) / 3600
        fingerprint_ok = None
        try:
            # Tai dung check cua get_lite_model(): nap model CHI NEU fingerprint
            # khop voi dataset hien tai -> None nghia la model da cai bien.
            from dataset import get_dataset_as_lists

            texts, labels = get_dataset_as_lists()
            want = lite_model.dataset_fingerprint(texts, labels)
            fingerprint_ok = lite_model.load_lite_model(lite, fingerprint=want) is not None
        except Exception as e:
            logger.debug("không kiểm tra được fingerprint model lite: %s", e)
        note = ""
        if fingerprint_ok is False:
            note = " - LỖI THỜI GIAN: dataset đã đổi, model cũ có thể nhận diện lệch"
        rows.append((OK if fingerprint_ok is not False else WARN,
                     f"model lite đã cache: {lite.name} ({age_h:.0f} giờ trước){note}"))
        if fingerprint_ok is False:
            fixes.append(LITE_RETRAIN)
    else:
        rows.append((WARN, "chưa có model nào -> sẽ tự huấn luyện model lite khi chạy (~1 giây)"))
        fixes.append(LITE_RETRAIN)
    if not ml.is_file() and not _module_available("sklearn"):
        rows.append((WARN, "chưa cài scikit-learn -> chỉ dùng được model lite (thuần Python)"))
        # Chi them lenh cai, KHONG ganh chu thich vao sau -> danh sach khac phuc
        # o cung mot chuoi moi truung lap duoc (xem dict.fromkeys ben duoi).
        fixes.append(FULL_INSTALL)
    return rows, fixes


def check_libraries() -> tuple[list[tuple[str, str]], list[str]]:
    rows: list[tuple[str, str]] = []
    fixes: list[str] = []
    have_speech = _module_available("SpeechRecognition") and _module_available("sounddevice")
    for name, (why, install) in OPTIONAL_LIBS.items():
        if _module_available(name):
            rows.append((OK, f"{name:19} đã cài"))
        elif name == "sklearn":
            rows.append((WARN, f"{name:19} chưa cài    -> {why}"))
            fixes.append(install)
        else:
            rows.append((WARN, f"{name:19} chưa cài    -> {why}"))
    if not have_speech:
        rows.append((WARN, "micro (STT) chưa dùng được -> vẫn gõ phím bình thường"))
    return rows, fixes


def check_voice() -> tuple[list[tuple[str, str]], list[str]]:
    rows: list[tuple[str, str]] = []
    fixes: list[str] = []
    try:
        import tts

        order = [getattr(fn, "__name__", "?") for fn in tts._engine_order()]
        chain = " -> ".join(order) if order else "chỉ in chữ (print)"
        rows.append((OK if order else WARN, f"TTS engine={tts.ENGINE!r} -> {chain}"))
    except Exception as e:
        rows.append((BAD, f"TTS lỗi khi kiểm tra: {e}"))

    try:
        import giong_noi_ai

        if giong_noi_ai.is_clone_available():
            rows.append((OK, "giọng AI VieNeu: sẵn sàng (có torch + vieneu)"))
        elif giong_noi_ai.is_available():
            rows.append((WARN, "giọng AI VieNeu: đã có vieneu nhưng thiếu torch"))
            fixes.append("pip install torch torchaudio")
        else:
            rows.append((WARN, "giọng AI VieNeu: chưa cài (không bắt buộc)"))
            fixes.append(AI_VOICE_INSTALL)
    except Exception as e:
        rows.append((WARN, f"không kiểm tra được giọng AI: {e}"))
    return rows, fixes


def run_checks() -> dict:
    """Chạy toàn bộ kiểm tra, trả về dict (in được bằng --json)."""
    sections: dict[str, list] = {}
    fixes: list[str] = []

    # check_runtime chi tra ve cac dong (khong co lenh sua) -> boc no dung dang
# (rows, fixes) nhu cac muc khac.
    rows, extra = _section_result("Môi trường", lambda: (check_runtime(), []))
    sections["Môi trường"] = rows
    fixes.extend(extra)
    for title, fn in (("Dữ liệu", check_data_dir), ("Cấu hình", check_config),
                      ("Model", check_models), ("Thư viện", check_libraries),
                      ("Giọng nói", check_voice)):
        rows, extra = _section_result(title, fn)
        sections[title] = rows
        fixes.extend(extra)

    # Trung lap xuat hien khi nhieu thieu thu cung cuong mot lenh cai -> gộp lại,
    # giu thu tu lan dau xuat de nguoi dung khong phai doc mot lenh 2 lan.
    fixes = list(dict.fromkeys(fixes))

    problems = sum(1 for rows in sections.values() for mark, _ in rows if mark == BAD)
    warnings = sum(1 for rows in sections.values() for mark, _ in rows if mark == WARN)
    return {
        "ok": problems == 0,
        "problems": problems,
        "warnings": warnings,
        "sections": sections,
        "fixes": fixes,
    }


def print_report(report: dict) -> None:
    for title, rows in report["sections"].items():
        safe_print(f"\n{title}")
        safe_print("-" * 60)
        for mark, line in rows:
            safe_print(f"  {mark} {line}")
    fixes = report["fixes"]
    safe_print("\n" + "=" * 60)
    if not fixes:
        # v7.4: "không có lệnh nào để chạy" KHONG dong nghia "moi thu on".
        # Mục [X] không kèm được lệnh sửa (vd file model hỏng) từng in ra dòng
        # "Mọi thứ ổn" trong khi exit code là 1 - báo cáo tự mâu thuẫn.
        if report.get("problems"):
            note = f'Có {report["problems"]} mục cần chú ý - xem các dòng [X] ở trên.'
            safe_print(f"  {note}")
            safe_print("  (Mục này không có lệnh sửa tự động - xem hướng dẫn trong từng dòng,")
            safe_print("   sửa xong chạy lại: python main.py --doctor)")
        else:
            safe_print("  Mọi thứ ổn - chạy:  python main.py")
        return
    safe_print("  CẦN LÀM THÊM (copy-paste từng dòng):")
    for cmd in fixes:
        safe_print(f"    $ {cmd}")
    safe_print("  (Bỏ qua các dòng 'chưa cài' cũng được: dự án cố ý chạy được")
    safe_print("   bằng thuần stdlib, model lite + engine print.)")


def main(argv: list[str] | None = None) -> int:
    """Điểm vào CLI: ``vi-doctor`` / ``python -m vi_voice_assistant.diagnostic``."""
    setup_console()
    as_json = "--json" in (argv if argv is not None else sys.argv[1:])
    try:
        report = run_checks()
    except Exception as e:          # CLI khong duoc nem traceback ra nguoi dung
        logger.warning("Bộ chẩn đoán lỗi: %s", e, exc_info=True)
        report = {
            "ok": False,
            "problems": 1,
            "warnings": 0,
            "sections": {"Bộ chẩn đoán": [(BAD, f"không chạy được: {type(e).__name__}: {e}")]},
            "fixes": [],
        }
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print_report(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
