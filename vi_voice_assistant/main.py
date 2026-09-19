"""
main.py - Trợ lý ảo tiếng Việt v7.5

v7.5 nâng cấp (ĐIỂM VÀO CHỊU ĐƯỢC DỮ LIỆU THẬT):
- config.json hỏng (danh sách, thiếu dấu phẩy) KHÔNG giết cả ứng dụng nữa:
  `load_config_safe()` trả về giá trị mặc định + mô tả lỗi, `main` in cảnh báo,
  mọi lệnh khác vẫn chạy được - trước đây `import executor` raise nên không gõ
  nổi cả `--doctor` là thứ đáng ra phải chỉ chỗ hỏng.
- `--once ""` phân biệt được với "không có --once": in "Câu rỗng" rồi thoát, thay
  vì im lặng rơi vào REPL - kiểu đó làm script/CI treo mãi không dứt.

v7.4 nâng cấp (TOÀN VẸN DỮ LIỆU):
- .history.json ghi bằng paths.atomic_write_json(): tiến trình chết giữa chừng
  không còn để lại file rỗng; --doctor không bao giờ ném traceback ra người dùng
- text/`target` do model trả về được ép kiểu TRƯỚC khi xử lý (int/None không làm
  dispatcher nổ AttributeError)

v7.3 nâng cấp (CÀI ĐẶT & TIỆN NGHI):
- Nói THẲNG ra lệnh: `python main.py "mở youtube"` (giống --once, khỏi nhớ cờ)
- --doctor: chẩn đoán cài đặt (thư viện, model, config, quyền ghi, giọng nói)
  và in ĐÚNG lệnh cần gõ để khắc phục; --yes cho script/CI
- REPL: ↑/↓ gọi lại lệnh cũ + Tab hoàn thành tên lệnh (khi có readline); gõ SAI
  tên lệnh thì gợi ý lệnh đúng - trước đây rơi vào "tôi chưa hiểu ý bạn"
- history/model/log chuyển sang THƯ MỤC DỮ LIỆU (paths.py): `pip install .`
  không còn ghi vào site-packages (máy cài system-wide từng dính PermissionError)

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

from paths import atomic_write_json, data_path
from platform_utils import safe_print, setup_console

setup_console()

import executor
from executor import ACTIVE_REMINDERS, execute_command
from logging_setup import setup_logging
from nlu_advanced import NLU

logger = logging.getLogger(__name__)

APP_VERSION = "7.5"
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

HISTORY_PATH = data_path(".history.json")   # v7.3: thu muc du lieu - xem paths.py
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
        epilog=(
            'Ví dụ:\n'
            '  python main.py "mở youtube"              # noi thang ra lenh, khong can --once\n'
            '  python main.py --dry-run "tắt máy tính"  # chi phan tich\n'
            '  python main.py --yes "mở firefox"        # khong hoi lai lenh nguy hiem\n'
            '  python main.py --doctor                  # chan doan cai dat / moi truong\n'
            '  python main.py --once "15 + 27" --json   # xuat JSON cho may doc'
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Chỉ phân tích, không thực thi")
    parser.add_argument("--voice", action="store_true", help="Nhận lệnh qua micro")
    parser.add_argument("--speak", action="store_true", help="Đọc phản hồi bằng giọng nói")
    parser.add_argument(
        "--once", metavar="CÂU_LỆNH", help='Chạy 1 lệnh rồi thoát (vd: --once "mở youtube")'
    )
    # v7.3: cho phép noi thang ra lenh nhu moi CLI khac (`vi-assistant mo youtube`)
    # thay vi phai nho co --once; thieu no thi nguoi dung goi
    #     python main.py "mở youtube"
    # va nhan "unrecognized arguments" - nghe nhu tro ly bi hong.
    parser.add_argument(
        "text", nargs="?", metavar="CÂU_LỆNH",
        help="Chạy ngay một câu lệnh rồi thoát (giống --once, cho tiện gõ)",
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
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Tự động xác nhận các lệnh nguy hiểm (tắt máy/khoá máy...) - cho script/CI",
    )
    parser.add_argument(
        "--doctor", action="store_true",
        help="Chẩn đoán cài đặt: thư viện, model, config, quyền ghi, giọng nói + in lệnh khắc phục",
    )
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
        # v7.4: open("w") cắt file ngay lập tức - tiến trình chết giữa chừng
        # để lại .history.json rỗng/hỏng và mất luôn lịch sử cũ. Dùng hàm ghi
        # atomic chung của paths.py.
        atomic_write_json(HISTORY_PATH, hist, prefix=".history_tmp_")
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
                    return str(text)
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
        status = result.get("status")
        # v7.3: `--yes` phai co tac dung o CAI che do `--once`. Trc day no chi
        # duoc executor dung den, con run_once luon tra ma 2 cho `need_confirm`
        # -> nguoi dung dung script (vi-assistant --yes "tat may tinh") bi tu
        # choi chinh lenh ma ho da bao "khoi hoi", va khong co loi bao nao.
        if status == "need_confirm" and executor.AUTO_CONFIRM:
            status = "ok"
        if status in ("ok", "low_confidence"):
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
    """Áp --yes / --config / --engine. Trả về mã lỗi (1) nếu không đi tiếp được."""
    if args.yes:
        # executor._confirm() trả về True mà không hỏi - chủ ý cho script/CI.
        # Chỉ cắt BƯỚC XÁC NHẬN, không cắt bước CHẶN lệnh ngoài whitelist.
        executor.set_auto_confirm(True)
        safe_print("[CHẾ ĐỘ --yes] Các lệnh nguy hiểm sẽ chạy mà không hỏi lại.")
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
# Các lệnh điều khiển trong REPL
# (v7.2: tách khỏi main() - trước đây main() chứa cả vòng lặp + 13 lệnh, độ
# phức tạp 55 nhánh nên sửa một lệnh phải đọc hết 200 dòng. Mỗi lệnh giờ là một
# hàm nhỏ đăng ký trong BẢNG tra; handle_control_command() chỉ còn vài nhánh.)
# ---------------------------------------------------------------------------
@dataclass
class ReplContext:
    """Mọi thứ một lệnh điều khiển cần biết về phiên hiện tại."""

    nlu: NLU
    state: ReplState
    text: str
    low: str


# Lệnh thoát: dùng ở HAI nơi (dispatcher + bộ gợi ý gõ sai) nên đặt thành hằng
# số; trước đây là tuple chữ kê khai ngay trong if -> muốn loại nó ra khỏi gợi ý
# phải copy lại danh sách, dễ lệch.
_EXIT_COMMANDS = ("thoat", "thoát", "exit", "quit", "q")

_CONTROL_COMMANDS: dict = {}      # từ khoá đúng -> hàm xử lý
_CONTROL_PREFIXES: list = []      # (các prefix, hàm xử lý) - cho lệnh có tham số


def _control(*words: str):
    """Decorator đăng ký một lệnh điều khiển theo đúng chuỗi từ khoá."""

    def decorator(fn):
        for word in words:
            _CONTROL_COMMANDS[word] = fn
        return fn

    return decorator


def _control_prefix(*words: str):
    """Decorator đăng ký lệnh dạng '<từ khoá> <tham số>' (khớp tiền tố)."""

    def decorator(fn):
        _CONTROL_PREFIXES.append((words, fn))
        return fn

    return decorator


def _format_reminder(item: dict) -> str:
    """Một dòng liệt kê nhắc nhở, chịu được dữ liệu thiếu/hỏng (v7.2)."""
    task = item.get("task", "?") or "?"
    at = executor._reminder_at(item)
    if at is None:
        return f"{task} - ??:??"
    return f"{task} - {at:%H:%M %d/%m}"


@_control("help", "giup", "giúp", "?")
def _cmd_help(ctx: ReplContext) -> None:
    safe_print(BANNER)


@_control("lich su", "lịch sử", "history")
def _cmd_history(ctx: ReplContext) -> None:
    print_history()


@_control("mic")
def _cmd_mic(ctx: ReplContext) -> None:
    state = ctx.state
    state.mic_mode = not state.mic_mode
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


@_control("voice")
def _cmd_voice(ctx: ReplContext) -> None:
    try:
        import tts

        executor.set_speech_enabled(not executor.SPEAK_ENABLED)
        if executor.SPEAK_ENABLED and not tts.is_available():
            safe_print("[VOICE] Chưa cài engine giọng nói nào - sẽ chỉ in chữ.")
        safe_print(f"[VOICE] Đọc phản hồi bằng giọng nói = {executor.SPEAK_ENABLED}")
    except Exception as e:
        safe_print(f"[VOICE] Lỗi: {e}")


@_control("test")
def _cmd_test(ctx: ReplContext) -> None:
    ctx.state.dry_run = not ctx.state.dry_run
    safe_print(f"[TEST] Chỉ phân tích = {ctx.state.dry_run}")


@_control("nhac nho", "nhắc nhở")
def _cmd_list_reminders(ctx: ReplContext) -> None:
    if not ACTIVE_REMINDERS:
        safe_print("(Chưa có nhắc nhở nào đang chờ)")
        return
    for i, r in enumerate(ACTIVE_REMINDERS, 1):
        safe_print(f"  {i}. {_format_reminder(r)}")
    safe_print("   (Gõ 'huy nhac <từ khoá>' để huỷ, hoặc 'huy nhac' để huỷ tất cả)")


@_control_prefix("huy nhac", "huỷ nhắc", "hủy nhắc")
def _cmd_cancel_reminder(ctx: ReplContext) -> None:
    parts = ctx.text.split(None, 2)
    removed = executor.cancel_reminder(parts[2] if len(parts) > 2 else None)
    if not removed:
        safe_print("(Không tìm thấy nhắc nhở nào khớp để huỷ)")
        return
    for r in removed:
        safe_print(f"[ĐÃ HUỶ] {_format_reminder(r)}")


@_control("nap lai", "nạp lại", "reload")
def _cmd_reload_config(ctx: ReplContext) -> None:
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


@_control("he thong", "hệ thống", "sysinfo")
def _cmd_sysinfo(ctx: ReplContext) -> None:
    print_sysinfo()


@_control("quen", "quên", "reset")
def _cmd_forget_context(ctx: ReplContext) -> None:
    if ctx.nlu.context:
        ctx.nlu.context.clear()
    safe_print("[NGỮ CẢNH] Đã xoá trí nhớ hội thoại.")


@_control_prefix("day ", "dạy ")
def _cmd_teach(ctx: ReplContext) -> None:
    body = ctx.text[4:]
    if "=" not in body:
        safe_print("Cú pháp:  day <câu nói> = <tên intent>")
        return
    try:
        sentence, intent = (p.strip() for p in body.split("=", 1))
        safe_print(ctx.nlu.teach(sentence, intent))
    except Exception as e:
        safe_print(f"[LỖI] Không dạy được: {e}")


def handle_control_command(text: str, nlu: NLU, state: ReplState) -> bool:
    """Xử lý một dòng lệnh điều khiển. Trả về True nếu dòng đó ĐÃ được tiêu.

    Lệnh thoát được nhận ra ngay tại đây (không đăng ký vào bảng) vì nó là
    lệnh duy nhất cần báo hiệu "dừng vòng lặp" cho main().
    """
    low = text.lower()
    if low in _EXIT_COMMANDS:
        safe_print("Tạm biệt!")
        logger.info("Kết thúc phiên làm việc.")
        state.stop = True
        return True

    ctx = ReplContext(nlu=nlu, state=state, text=text, low=low)

    handler = _CONTROL_COMMANDS.get(low)
    if handler is not None:
        handler(ctx)
        return True

    for prefixes, fn in _CONTROL_PREFIXES:
        if low.startswith(prefixes):
            fn(ctx)
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


def _control_candidates() -> list[str]:
    """Mọi từ khoá điều khiển (bỏ dấu kết thúc prefix) - dùng cho gợi ý + Tab."""
    words = set(_CONTROL_COMMANDS) - {"?"}
    words.update(p.rstrip() for pair in _CONTROL_PREFIXES for p in pair[0])
    words.update(_EXIT_COMMANDS)
    return sorted(words)


def _setup_readline() -> bool:
    """Bật phím ↑/↓ (xem lại lệnh đã gõ) + Tab completion cho REPL.

    ``readline`` chỉ có sẵn trên Linux/macOS; Windows cần ``pip install
    pyreadline`` - thiếu thì REPL chạy y hệt trước, chỉ mất phím mũi tên, nên
    đây là NÂNG CẤP tuỳ chọn chứ không phải yêu cầu mới.

    History của readline NHẠP LUÔN từ ``.history.json`` mà dự án đã lưu từ bản
    v6 -> lên máy mới, xóa file log, đổi thư mục... vẫn gọi lại được lệnh cũ.
    """
    try:
        import readline
    except ImportError:
        logger.debug("không có readline - REPL không hỗ trợ phím ↑/↓")
        return False
    try:
        for entry in load_history():
            readline.add_history(entry)
        readline.set_completer(_make_completer())
        readline.parse_and_bind("tab: complete")
    except Exception as e:                       # readline trên Windows vài bản thiếu API
        logger.debug("cấu hình readline thất bại: %s", e)
        return False
    return True


def _make_completer():
    """Tab hoàn thành tên lệnh điều khiển (``nap<Tab>`` -> ``nap lai``)."""
    candidates = _control_candidates()

    def completer(text: str, state: int):
        matches = [c for c in candidates if c.startswith(text)]
        return matches[state] if state < len(matches) else None

    return completer


def _suggest_control_command(text: str) -> str | None:
    """Gợi ý lệnh điều khiển gần đúng nhất khi người dùng gõ SAU chính tả.

    Chỉ áp cho câu NGẮN (<= 2 từ) - câu dài là lệnh nói bình thường, không phải
    lệnh gõ sai._cutoff 0.8 để "mở youtube" không bị gợi ý thành... gì đó.
    """
    import difflib

    candidate = text.strip().lower()
    if not candidate or len(candidate.split()) > 2 or len(candidate) < 3:
        return None
    # LOAI BENH: khong bao gio GOI Y lenh thoat. "hat" (hat noi) rat gan "thoat"
    # theo do tuong dong ky tu, ma gui nguoi dung "co phai ban muon thoat?" khi
    # ho muoi hat nhac la kind - va neu ho go theo thi CHET phien lam viec.
    pool = [w for w in _control_candidates() if w not in _EXIT_COMMANDS]
    close = difflib.get_close_matches(candidate, pool, n=1, cutoff=0.7)
    if not close or close[0] == candidate:
        return None
    return close[0]


def _run_repl(nlu: NLU, state: ReplState) -> int:
    if _setup_readline():
        safe_print("(Mẹo: phím ↑/↓ gọi lại lệnh cũ, phím Tab hoàn thành tên lệnh.)")
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

        # v7.3: "he thogng"/"napllai"... trước đây rơi thẳng vào NLU và nhận về
        # câu "tôi chưa hiểu ý bạn" - người dùng không biết mình chỉ gõ sai một
        # lệnh có sẵn. Gợi ý đúng lệnh đó rồi cho gõ lại.
        suggestion = _suggest_control_command(text)
        if suggestion:
            safe_print(f"   Có phải bạn muốn gõ  {suggestion} ?  (gõ lại để thực hiện)")
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


def _run_info_command(args: argparse.Namespace) -> int | None:
    """Xử lý các cờ "in thông tin rồi thoát". Trả về None nếu phải chạy tiếp.

    Tách khỏi main() vì chúng là 4 nhánh độc lập, không liên quan vòng đời
    NLU/REPL - và ``--doctor`` PHẢI chạy trước khi nạp model: mục đích của nó là
    chẩn đoán lúc cài đặt hỏng, mà cài hỏng thì model không nạp được.
    """
    if args.doctor:
        import diagnostic

        code: int = diagnostic.main()
        return code
    if args.sysinfo:
        print_sysinfo()
        return 0
    if args.history:
        print_history()
        return 0
    if args.version:
        setup_logging(level=logging.DEBUG if args.debug else logging.INFO)
        _print_version()
        return 0
    return None


def _adopt_shipped_data() -> list[str]:
    """Lần đầu chạy bản cài bằng pip: lấy config/whitelist đi theo gói làm điểm khởi đầu.

    Không có bước này thì người dùng ``pip install`` sẽ chạy với DEFAULT_CONFIG
    trong code (và mọi tự chỉnh sửa trước đó trong ``config.json`` ở thư mục
    source bị mất khi chuyển sang cài đặt) - im lặng, không báo lỗi, nên rất
    khó nhận ra. Hàm chỉ COPY khi file đích chưa tồn tại -> không bao giờ ghi đè.
    """
    try:
        import paths

        if paths.describe()["from_source"]:
            return []
        return list(paths.migrate_from_package_dir(
            ("config.json", "reminders.json", ".history.json", "feedback.csv")
        ))
    except Exception as e:                      # khong duoc phep lam chet tro ly vi sao chep
        logger.debug("không chép được dữ liệu từ gói: %s", e)
        return []


def _warn_broken_config() -> None:
    """Báo (một lần, rõ ràng) nếu config.json đang bị bỏ qua vì hỏng.

    Tách khỏi `main()` (v7.5) vì hàm đó đã chạm ngưỡng C901=10. Lỗi được ghi lúc
    import nên phải in ở đây: nếu im lặng, người dùng sẽ sửa file config mãi mà
    không thấy tác dụng - kiểu lỗi khó tự đoán nhất.
    """
    if not getattr(executor, "CONFIG_ERROR", None):
        return
    safe_print("[CẤU HÌNH] config.json không dùng được -> đang chạy với giá trị mặc định.")
    safe_print(f"   {str(executor.CONFIG_ERROR).splitlines()[0]}")
    from config import CONFIG_PATH

    safe_print(f"   Sửa hoặc xoá file: {CONFIG_PATH}")


def _one_shot_text(args: argparse.Namespace) -> tuple[str | None, bool]:
    """(câu cần chạy ngay, có_phải_câu_rỗng) - tách ra để `main` còn dưới ngưỡng C901.

    v7.5: `--once ""` phải KHÁC "không có --once". Trước đây cả hai cùng rơi vào một
    phép thử (`args.once or args.text`), nên ai gõ `--once ""` trong script/CI bị
    đẩy vào REPL một cách im lặng - một lệnh "chạy 1 câu rồi thoát" không bao giờ
    thoát. Vì thế lấy giá trị theo `is not None` rồi mới xét nội dung rỗng.
    """
    one_shot = args.once if args.once is not None else args.text
    if one_shot is None:
        return None, False
    if not one_shot.strip():
        return "", True
    return one_shot, False


def main() -> int:
    args = parse_args()

    early = _run_info_command(args)
    if early is not None:
        return early

    setup_logging(level=logging.DEBUG if args.debug else logging.INFO)

    _warn_broken_config()

    adopted = _adopt_shipped_data()
    if adopted:
        safe_print(f"[CẤU HÌNH] Đã lấy {', '.join(adopted)} từ gói cài đặt vào thư mục dữ liệu.")

    option_error = _apply_cli_options(args)
    if option_error is not None:
        return option_error

    one_shot, blank_once = _one_shot_text(args)

    if one_shot is None:
        if not args.no_banner:
            safe_print(BANNER)
        safe_print("Đang nạp mô hình hiểu ý...")
    elif blank_once:
        # `--once ""`/`--once "   "`: da chi dinh che do mot-cau thi phai thoat,
        # khong im lang roi roi vao REPL (kieu im lang do giết script/CI).
        safe_print("[CÂU LỆNH] Câu rỗng - không có gì để thực hiện.")
        safe_print("   Muốn hội thoại liên tục: chạy mà không kèm --once.")
        return 0

    _warn_missing_optional_features(args)
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

    if one_shot:
        save_history_entry(one_shot)
        return run_once(one_shot, nlu, dry_run=args.dry_run, as_json=args.json)

    return _run_repl(nlu, ReplState(dry_run=args.dry_run, mic_mode=args.voice))


if __name__ == "__main__":
    sys.exit(main() or 0)
