"""
main.py - Trợ lý ảo tiếng Việt v7.1

v7.1 nâng cấp (tiếp nối v7.0):
- Thêm --debug, --no-banner, --config, --engine
- Signal handling (Ctrl+C) gọn gàng
- Thêm history (lưu lịch sử lệnh)
- Type hints, pathlib, logging chi tiết
- Banner mới, version 7.0
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
from dataclasses import dataclass
from pathlib import Path

from platform_utils import safe_print, setup_console

setup_console()

import executor
from executor import ACTIVE_REMINDERS, execute_command
from logging_setup import setup_logging
from nlu_advanced import NLU

logger = logging.getLogger(__name__)

APP_VERSION = "7.1"
APP_NAME = "Trợ lý ảo tiếng Việt"

BANNER = rf"""
==============================================================
   {APP_NAME} v{APP_VERSION} - 11 Ý ĐỊNH + HIỂU Ý THÔNG MINH
==============================================================
VÍ DỤ (gõ tay hoặc nói):
   Bật Google lên              mo chrome len       (không dấu vẫn hiểu)
   mở chorme ra                 (sai chính tả vẫn hiểu)
   mở chrome rồi phát nhạc trữ tình   (2 lệnh trong 1 câu)
   nhắc tôi họp lúc 3 giờ chiều
   thời tiết Đà Nẵng hôm nay thế nào
   15 cộng 27 bằng bao nhiêu
   mười lăm cộng hai mươi bảy bằng mấy   (số viết bằng chữ)   [v6.2]
   mo chrome roi phat nhac              (không dấu vẫn tách) [v6.2]
   mấy giờ rồi

LỆNH ĐIỀU KHIỂN:
   mic          -> bật/tắt nghe qua micro (cần SpeechRecognition/PhoWhisper)
   voice        -> bật/tắt đọc phản hồi bằng giọng nói
   test         -> bật/tắt chế độ CHỈ PHÂN TÍCH (không thực thi)
   nhac nho     -> xem danh sách nhắc nhở đang chờ
   huy nhac [kw]-> huỷ nhắc nhở (bỏ trống = huỷ tất cả)      [v6]
   nap lai      -> nạp lại config.json, không cần khởi động lại [v6]
   he thong     -> báo cáo khả năng của máy (OS, công cụ)    [v6.3]
   lich su      -> xem lịch sử lệnh vừa gõ                  [v7.0]
   day <câu> = <intent>  -> dạy trợ lý hiểu đúng câu đó
   quen         -> xoá trí nhớ ngữ cảnh hội thoại
   help / giup  -> hiện lại hướng dẫn này
   thoat / exit -> thoát chương trình
==============================================================
"""

YES_WORDS = {"có", "co", "ừ", "u", "ủ", "đúng", "dung", "ok", "y", "yes", "vâng", "ừừ", "o", "k"}

HISTORY_PATH = Path(__file__).resolve().parent / ".history.json"
MAX_HISTORY = 200


@dataclass
class ReplState:
    """Trạng thái bật/tắt của phiên REPL (tách khỏi main() để test được từng lệnh)."""

    dry_run: bool = False
    mic_mode: bool = False
    stop: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} - demo hiểu ý + thực thi",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Ví dụ: python main.py --once "mở youtube" --json',
    )
    parser.add_argument("--dry-run", action="store_true", help="Chỉ phân tích, không thực thi")
    parser.add_argument("--voice", action="store_true", help="Nhận lệnh qua micro")
    parser.add_argument("--speak", action="store_true", help="Đọc phản hồi bằng giọng nói")
    parser.add_argument(
        "--once", metavar="CÂU_LỆNH", help='Chạy 1 lệnh rồi thoát (vd: --once "mở youtube")'
    )
    parser.add_argument("--json", action="store_true", help="In kết quả JSON (dùng kèm --once)")
    parser.add_argument(
        "--version", action="store_true", help="In phiên bản + loại model rồi thoát"
    )
    parser.add_argument(
        "--sysinfo", action="store_true", help="In báo cáo khả năng của máy rồi thoát"
    )
    parser.add_argument("--debug", action="store_true", help="Bật log DEBUG chi tiết")
    parser.add_argument("--no-banner", action="store_true", help="Không in banner khi khởi động")
    parser.add_argument("--config", metavar="PATH", help="Đường dẫn config.json tuỳ chỉnh")
    parser.add_argument(
        "--engine",
        # v7.2: thêm "nc" (nhân bản giọng) - tts.py hỗ trợ engine này từ lâu
        # nhưng CLI không cho chọn, nên muốn dùng phải sửa mã nguồn.
        choices=["auto", "piper", "nc", "pyttsx3", "sapi", "gtts", "print"],
        help="Chọn engine TTS",
    )
    parser.add_argument("--history", action="store_true", help="In lịch sử lệnh rồi thoát")
    return parser.parse_args()


# --- History ---
def load_history() -> list[str]:
    if not HISTORY_PATH.exists():
        return []
    try:
        with HISTORY_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def save_history_entry(text: str) -> None:
    if not text or len(text) < 2:
        return
    try:
        hist = load_history()
        hist.append(text)
        # Giữ tối đa MAX_HISTORY, bỏ trùng liên tiếp
        if len(hist) >= 2 and hist[-1] == hist[-2]:
            hist.pop()
        hist = hist[-MAX_HISTORY:]
        with HISTORY_PATH.open("w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.debug("Không lưu được history: %s", e)


def print_history() -> None:
    hist = load_history()
    if not hist:
        safe_print("(Chưa có lịch sử)")
        return
    safe_print(f"Lịch sử {len(hist)} lệnh gần nhất:")
    for i, h in enumerate(hist[-20:], 1):
        safe_print(f"  {i:2}. {h}")


# --- Input ---
def get_input(use_voice: bool) -> str:
    if use_voice:
        try:
            import stt

            if stt.is_available():
                text = stt.listen_once()
                if text:
                    return text
                safe_print("(Không nhận diện được giọng nói, bạn có thể gõ tay bên dưới)")
            else:
                safe_print("[CẢNH BÁO] Chưa cài SpeechRecognition, chuyển sang gõ phím.")
        except Exception as e:
            logger.debug("STT lỗi: %s", e)
            safe_print(f"[LỖI STT] {e} -> chuyển sang gõ phím")

    try:
        return input("\nBạn nói > ").strip()
    except (KeyboardInterrupt, EOFError):
        safe_print("\nTạm biệt!")
        sys.exit(0)


def handle_result(result: dict, nlu: NLU, dry_run: bool) -> None:
    status = result.get("status", "unknown")
    safe_print("Kết quả phân tích (JSON):")
    safe_print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ("raw", "normalized")},
            ensure_ascii=False,
            indent=2,
        )
    )

    if status == "unknown":
        executor.respond("Xin lỗi, tôi chưa hiểu ý bạn")
        safe_print("   Mẹo: gõ  day <câu> = <intent>  để dạy tôi câu này.")
        return

    if status in ("low_confidence", "need_confirm"):
        question = nlu.confirm_message(result)
        executor.respond(question)
        safe_print(f"   [{result.get('confidence', 0):.0%} tự tin] ", end="")
        try:
            answer = input("").strip().lower()
        except (KeyboardInterrupt, EOFError):
            answer = ""
        if answer not in YES_WORDS:
            executor.respond("Đã huỷ lệnh")
            return
        nlu.teach(result.get("raw", ""), result.get("intent", ""))

    if dry_run:
        safe_print("   (Chế độ test: không thực thi)")
        return

    try:
        ok = execute_command(result)
    except Exception as e:
        logger.exception("Lỗi khi thực thi lệnh (intent=%s)", result.get("intent"))
        safe_print(f"[LỖI] Có lỗi không mong muốn khi thực thi: {e}")
        safe_print("   (Đã ghi logs/assistant.log - thử lại hoặc nói câu khác nhé)")
        ok = False
    safe_print("=> " + ("Đã thực thi xong." if ok else "Không thực thi được."))


def print_sysinfo() -> None:
    from platform_utils import capability_report, format_capability_report

    safe_print(format_capability_report(capability_report()))


def run_once(text: str, nlu: NLU, dry_run: bool = False, as_json: bool = False) -> int:
    try:
        commands = nlu.understand(text)
    except Exception as e:
        logger.exception("Lỗi khi phân tích câu: %r", text)
        if as_json:
            print(json.dumps({"ok": False, "error": str(e), "raw": text}, ensure_ascii=False))
        else:
            safe_print(f"[LỖI] Không phân tích được: {e}")
        return 2

    if as_json:
        print(json.dumps(commands, ensure_ascii=False, indent=2, default=str))

    exit_code = 0
    for result in commands:
        if not as_json:
            safe_print(
                "-> {} | {} | {:.0%} | {}".format(
                    result.get("intent"),
                    result.get("target"),
                    result.get("confidence", 0),
                    result.get("status"),
                )
            )
        if dry_run:
            continue
        if result.get("status") in ("ok", "low_confidence"):
            if not execute_command(result):
                exit_code = 1
        else:
            exit_code = 2
    return exit_code


def setup_signal_handlers():
    def _handler(signum, frame):
        safe_print("\n\nTạm biệt! (nhận signal)")
        logger.info("Kết thúc do signal %s", signum)
        sys.exit(0)

    try:
        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)
    except (ValueError, OSError, AttributeError) as e:
        # Không bật được signal handler (Python chạy ngoài luồng chính, hoặc
        # Windows không hỗ trợ SIGTERM) -> Ctrl+C vẫn xử lý bằng KeyboardInterrupt
        # ở vòng lặp, chỉ là thông báo chào tạm biệt có thể không in ra.
        logger.debug("Không đăng ký được signal handler: %s", e)


def _print_version() -> None:
    """In phiên bản + loại model đang dùng rồi thoát (--version)."""
    try:
        from intent_model import describe_engine

        engine_desc = describe_engine()
    except Exception:
        engine_desc = "không xác định (chưa nạp model)"
    safe_print(f"{APP_NAME} - phiên bản {APP_VERSION}")
    safe_print(f"Bộ hiểu ý: {engine_desc}")
    safe_print(f"Python: {sys.version.split()[0]} | Platform: {sys.platform}")


def _apply_cli_options(args: argparse.Namespace) -> int | None:
    """Áp --config / --engine. Trả về mã lỗi (1) nếu không đi tiếp được."""
    if args.config:
        try:
            executor.reload_config(args.config)
            safe_print(f"[CẤU HÌNH] Dùng config tuỳ chỉnh: {args.config}")
        except Exception as e:
            safe_print(f"[LỖI] Không nạp được config {args.config}: {e}")
            return 1

    if args.engine:
        try:
            import tts

            tts.ENGINE = args.engine
            safe_print(f"[TTS] Engine: {args.engine}")
        except Exception as e:
            safe_print(f"[LỖI] Không đặt được engine TTS: {e}")
    return None


def _warn_missing_optional_features(args: argparse.Namespace) -> None:
    """Báo (không chết) nếu người dùng bật --voice/--speak mà máy thiếu thư viện."""
    if args.voice:
        try:
            import stt

            if not stt.is_available():
                safe_print(
                    "[LƯU Ý] Bạn bật --voice nhưng chưa cài SpeechRecognition/sounddevice.\n"
                    "         Cài bằng:  pip install SpeechRecognition sounddevice\n"
                    "         Tạm thời chuyển sang chế độ gõ phím.\n"
                )
        except Exception as e:
            safe_print(f"[LƯU Ý] Lỗi kiểm tra STT: {e}")

    if args.speak:
        try:
            import tts

            if not tts.is_available():
                safe_print(
                    "[LƯU Ý] Bạn bật --speak nhưng chưa cài engine giọng nói nào.\n"
                    "         Cài bằng:  pip install pyttsx3\n"
                    "         Tạm thời chỉ in chữ, không đọc.\n"
                )
            executor.set_speech_enabled(tts.is_available())
        except Exception as e:
            safe_print(f"[LƯU Ý] Lỗi kiểm tra TTS: {e}")


# ---------------------------------------------------------------------------
# Các lệnh điều khiển trong REPL (v7.2: tách khỏi main() - trước đây main()
# chứa cả vòng lặp + 13 lệnh, độ phức tạp 55 nhánh, sửa một lệnh là phải đọc
# hết 200 dòng. Mỗi lệnh giờ là một hàm nhỏ, độc lập và test được.)
# ---------------------------------------------------------------------------
def _cmd_toggle_mic(state: ReplState) -> None:
    if not state.mic_mode:
        safe_print("[MIC] Tắt chế độ mic, quay về gõ tay.")
        return
    try:
        import stt

        if stt.is_available():
            safe_print("[MIC] Bật chế độ nghe qua mic.")
        else:
            safe_print("[MIC] Chưa cài SpeechRecognition, không bật được.")
            state.mic_mode = False
    except Exception:
        safe_print("[MIC] Lỗi khi bật mic.")
        state.mic_mode = False


def _cmd_toggle_voice() -> None:
    try:
        import tts

        executor.set_speech_enabled(not executor.SPEAK_ENABLED)
        if executor.SPEAK_ENABLED and not tts.is_available():
            safe_print("[VOICE] Chưa cài engine giọng nói nào - sẽ chỉ in chữ.")
        safe_print(f"[VOICE] Đọc phản hồi bằng giọng nói = {executor.SPEAK_ENABLED}")
    except Exception as e:
        safe_print(f"[VOICE] Lỗi: {e}")


def _format_reminder(item: dict) -> str:
    """Một dòng liệt kê nhắc nhở, chịu được dữ liệu thiếu/hỏng (v7.2)."""
    task = item.get("task", "?") or "?"
    at = executor._reminder_at(item)
    if at is None:
        return f"{task} - ??:??"
    return f"{task} - {at:%H:%M %d/%m}"


def _cmd_list_reminders() -> None:
    if not ACTIVE_REMINDERS:
        safe_print("(Chưa có nhắc nhở nào đang chờ)")
        return
    for i, r in enumerate(ACTIVE_REMINDERS, 1):
        safe_print(f"  {i}. {_format_reminder(r)}")
    safe_print("   (Gõ 'huy nhac <từ khoá>' để huỷ, hoặc 'huy nhac' để huỷ tất cả)")


def _cmd_cancel_reminder(text: str) -> None:
    parts = text.split(None, 2)
    removed = executor.cancel_reminder(parts[2] if len(parts) > 2 else None)
    if not removed:
        safe_print("(Không tìm thấy nhắc nhở nào khớp để huỷ)")
        return
    for r in removed:
        safe_print(f"[ĐÃ HUỶ] {_format_reminder(r)}")


def _cmd_reload_config() -> None:
    try:
        cfg = executor.reload_config()
        safe_print(
            f"[CẤU HÌNH] Đã nạp lại config.json "
            f"({len(cfg['website_map'])} web, {len(cfg['file_map'])} file)."
        )
        # v7.2: in ra ngưỡng đang dùng để người dùng THẤY được config có thực sự
        # có tác dụng hay không (trước đây đổi ngưỡng rồi "nap lai" nhưng tầng
        # NLU vẫn dùng số cũ, không cách nào biết được).
        import nlu_advanced

        safe_print(
            f"   Ngưỡng NLU hiện tại: accept={nlu_advanced.CONFIDENCE_ACCEPT}, "
            f"ask={nlu_advanced.CONFIDENCE_ASK} | ngưỡng executor="
            f"{executor.CONFIDENCE_THRESHOLD}"
        )
    except Exception as e:
        safe_print(f"[LỖI] Không nạp lại được config: {e}")


def _cmd_teach(nlu: NLU, text: str) -> None:
    body = text[4:]
    if "=" not in body:
        safe_print("Cú pháp:  day <câu nói> = <tên intent>")
        return
    try:
        sentence, intent = (p.strip() for p in body.split("=", 1))
        safe_print(nlu.teach(sentence, intent))
    except Exception as e:
        safe_print(f"[LỖI] Không dạy được: {e}")


def handle_control_command(text: str, nlu: NLU, state: ReplState) -> bool:
    """Xử lý một dòng lệnh điều khiển. Trả về True nếu dòng đó ĐÃ được tiêu.

    Trả về qua biến logic chứ không `continue` để main() đọc gọn và để test có
    thể gọi thẳng từng lệnh mà không cần chạy cả vòng REPL.
    """
    low = text.lower()

    if low in ("thoat", "thoát", "exit", "quit", "q"):
        safe_print("Tạm biệt!")
        logger.info("Kết thúc phiên làm việc.")
        state.stop = True
        return True

    if low in ("help", "giup", "giúp", "?"):
        safe_print(BANNER)
        return True

    if low in ("lich su", "lịch sử", "history"):
        print_history()
        return True

    if low == "mic":
        state.mic_mode = not state.mic_mode
        _cmd_toggle_mic(state)
        return True

    if low == "voice":
        _cmd_toggle_voice()
        return True

    if low == "test":
        state.dry_run = not state.dry_run
        safe_print(f"[TEST] Chỉ phân tích = {state.dry_run}")
        return True

    if low in ("nhac nho", "nhắc nhở"):
        _cmd_list_reminders()
        return True

    if low.startswith(("huy nhac", "huỷ nhắc", "hủy nhắc")):
        _cmd_cancel_reminder(text)
        return True

    if low in ("nap lai", "nạp lại", "reload"):
        _cmd_reload_config()
        return True

    if low in ("he thong", "hệ thống", "sysinfo"):
        print_sysinfo()
        return True

    if low in ("quen", "quên", "reset"):
        if nlu.context:
            nlu.context.clear()
        safe_print("[NGỮ CẢNH] Đã xoá trí nhớ hội thoại.")
        return True

    if low.startswith(("day ", "dạy ")):
        _cmd_teach(nlu, text)
        return True

    return False


def _execute_commands(commands: list, nlu: NLU, dry_run: bool) -> None:
    """In kết quả + cho người dùng xác nhận với từng lệnh trong câu."""
    if len(commands) > 1:
        safe_print(f"(Phát hiện {len(commands)} lệnh trong câu)")

    for i, result in enumerate(commands, 1):
        if len(commands) > 1:
            safe_print(f"\n--- LỆNH {i}: {result.get('raw','')} ---\n")
        try:
            handle_result(result, nlu, dry_run)
        except Exception as e:
            logger.exception("Lỗi không mong muốn khi xử lý lệnh")
            safe_print(f"[LỖI] Có lỗi không mong muốn: {e}")
            safe_print("   Phiên làm việc vẫn tiếp tục bình thường.")


def _run_repl(nlu: NLU, state: ReplState) -> int:
    safe_print("Sẵn sàng! (gõ 'help' để xem hướng dẫn)\n")
    while True:
        text = get_input(state.mic_mode)
        if not text:
            continue

        save_history_entry(text)
        if handle_control_command(text, nlu, state):
            if state.stop:
                return 0
            continue

        if state.mic_mode:
            safe_print(f"[MIC] Bạn nói: {text}")

        try:
            commands = nlu.understand(text)
        except Exception as e:
            logger.exception("Lỗi khi phân tích câu nói: %r", text)
            safe_print(f"[LỖI] Không phân tích được câu vừa rồi: {e}")
            safe_print("   (Đã ghi log - bạn thử nói lại câu khác nhé)")
            continue

        _execute_commands(commands, nlu, state.dry_run)


def main() -> int:
    args = parse_args()

    if args.sysinfo:
        print_sysinfo()
        return 0

    if args.history:
        print_history()
        return 0

    setup_logging(level=logging.DEBUG if args.debug else logging.INFO)

    if args.version:
        _print_version()
        return 0

    option_error = _apply_cli_options(args)
    if option_error is not None:
        return option_error

    if not args.once and not args.no_banner:
        safe_print(BANNER)

    _warn_missing_optional_features(args)

    if not args.once:
        safe_print("Đang nạp mô hình hiểu ý...")
    try:
        nlu = NLU()
    except Exception as e:
        logger.exception("Không nạp được model NLU")
        safe_print(f"[LỖI NGHIÊM TRỌNG] Không nạp được mô hình hiểu ý: {e}")
        safe_print("   Thử chạy: python -m dataset hoặc python train_nlu.py --fast")
        return 1

    logger.info("Đã nạp model, bắt đầu phiên làm việc mới.")
    setup_signal_handlers()

    restored = executor.restore_reminders()
    if restored:
        safe_print(f"[NHẮC NHỞ] Đã khôi phục {restored} lời nhắc còn hạn từ lần chạy trước.")

    if args.once:
        save_history_entry(args.once)
        return run_once(args.once, nlu, dry_run=args.dry_run, as_json=args.json)

    return _run_repl(nlu, ReplState(dry_run=args.dry_run, mic_mode=args.voice))


if __name__ == "__main__":
    sys.exit(main() or 0)
