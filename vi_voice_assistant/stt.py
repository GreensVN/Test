"""
stt.py - Speech-To-Text v7.11.0

v7.0 nâng cấp:
- Type hints, pathlib, better error handling
- Thêm VAD đơn giản, timeout rõ ràng
- Tách Google STT và PhoWhisper thành class riêng
- Thêm context manager cho mic
"""

from __future__ import annotations

import io
import logging
import math
import os
import sys
import threading
import wave
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from platform_utils import safe_print, setup_console

logger = logging.getLogger(__name__)

MODEL_NAME = os.environ.get("STT_MODEL", "").strip() or "vinai/PhoWhisper-small"
SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 0.015
SILENCE_DURATION = 1.2
MAX_DURATION = 15.0
CHUNK_DURATION = 0.1

# v7.9: số lần thử tải model offline trước khi chuyển hẳn sang Google STT.
# Một lần là quá ít: lỗi tải thường là lỗi TẠM THỜI (mạng chập chờn, đĩa bận),
# và bỏ model sau một lần thất bại là mất nhầm.
_MAX_MODEL_LOAD_ATTEMPTS = 3


ENGINE = "auto"
ALLOW_CLOUD = False
ALLOW_DOWNLOAD = False
_policy_lock = threading.RLock()
_listen_lock = threading.Lock()


def configure(engine: str = "auto", *, allow_cloud: bool = False,
              allow_download: bool = False) -> None:
    """Select a transport. Google selection is explicit cloud consent.

    Auto is local-only unless allow_cloud is True. Offline forbids cloud even
    on load failure. Downloads are separate permission and default to False.
    Configuration applies to subsequent listens, not cancellation of in-flight audio.
    """
    global ENGINE, ALLOW_CLOUD, ALLOW_DOWNLOAD, _default_instance
    if not isinstance(engine, str) or engine not in ("auto", "offline", "google"):
        raise ValueError("STT engine phải là auto, offline hoặc google.")
    if type(allow_cloud) is not bool or type(allow_download) is not bool:
        raise TypeError("STT permission flags phải là bool.")
    if engine == "offline" and allow_cloud:
        raise ValueError("STT offline không được bật cloud fallback.")
    cloud = engine == "google" or allow_cloud
    with _policy_lock:
        if (ENGINE, ALLOW_CLOUD, ALLOW_DOWNLOAD) != (engine, cloud, allow_download):
            _default_instance = None
        ENGINE, ALLOW_CLOUD, ALLOW_DOWNLOAD = engine, cloud, allow_download


def _module_present(name: str) -> bool:
    if name in sys.modules:
        return sys.modules[name] is not None
    try:
        return find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def _offline_available() -> bool:
    return _SD_AVAILABLE and _module_present("torch") and _module_present("transformers")


def _google_available() -> bool:
    return _SR_AVAILABLE and (_SD_AVAILABLE or has_pyaudio())


def _duration(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("timeout phải là số dương hữu hạn.")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("timeout phải là số dương hữu hạn.")
    return number


def _build_offline_pipeline(model_name: str, device: str, allow_download: bool):
    import torch
    from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline

    actual = ("cuda" if torch.cuda.is_available() else "cpu") if device == "auto" else device
    options = {"local_files_only": not allow_download, "trust_remote_code": False}
    processor = AutoProcessor.from_pretrained(model_name, **options)
    model = AutoModelForSpeechSeq2Seq.from_pretrained(model_name, **options)
    return pipeline(
        "automatic-speech-recognition", model=model, tokenizer=processor.tokenizer,
        feature_extractor=processor.feature_extractor, device=actual,
        chunk_length_s=30, generate_kwargs={"language": "vi", "task": "transcribe"},
    )


def _decoded_text(result: object) -> str:
    text = result.get("text") if isinstance(result, dict) else None
    if isinstance(text, str):
        return text.strip()
    logger.warning("STT decoder không trả về text hợp lệ.")
    return ""


def _rms(chunk) -> float:
    try:
        import numpy as np

        return float(np.sqrt(np.mean(chunk.astype("float32") ** 2))) / 32768.0
    except ImportError:
        # Fallback không có numpy
        import math
        import struct

        # chunk là bytes hoặc array
        try:
            # Giả sử int16
            count = len(chunk) // 2
            if count == 0:
                return 0.0
            fmt = f"{count}h"
            samples = struct.unpack(fmt, chunk[: count * 2])
            sum_squares = sum(s * s for s in samples)
            return math.sqrt(sum_squares / count) / 32768.0
        except Exception:
            return 0.0


class STT:
    """Cached local PhoWhisper; Google fallback only with explicit permission."""

    def __init__(self, model_name: str = MODEL_NAME, device: str = "auto", *,
                 allow_cloud: bool = False, allow_download: bool = False):
        if not isinstance(model_name, str) or not model_name.strip():
            raise ValueError("model_name không được rỗng.")
        if not isinstance(device, str) or not device.strip():
            raise ValueError("device phải là chuỗi hợp lệ.")
        if type(allow_cloud) is not bool or type(allow_download) is not bool:
            raise TypeError("STT permission flags phải là bool.")
        self.model_name, self.device = model_name, device
        self.allow_cloud, self.allow_download = allow_cloud, allow_download
        self._pipe: Any = None
        self._use_google = False
        self._sd: Any = None
        self._recognizer: Any = None
        self._load_attempts = 0
        self._google_failures = 0
        self._language = "vi-VN"

    def _load_model(self):
        if self._pipe is not None or self._use_google:
            return
        safe_print(f"[STT] Nạp model {self.model_name} "
                   f"({'cho phép tải' if self.allow_download else 'chỉ cache cục bộ'})...")
        while self._load_attempts < _MAX_MODEL_LOAD_ATTEMPTS:
            self._load_attempts += 1
            try:
                self._pipe = _build_offline_pipeline(self.model_name, self.device,
                                                     self.allow_download)
                return
            except Exception as error:
                logger.warning("Không nạp được STT local (%d/%d): %s", self._load_attempts,
                               _MAX_MODEL_LOAD_ATTEMPTS, error)
        if not self.allow_cloud:
            raise RuntimeError("Không nạp được STT local; không gửi audio lên cloud. "
                               "Dùng --stt-download để cho phép tải model, hoặc chọn "
                               "--stt-engine google nếu đồng ý gửi audio.")
        try:
            import speech_recognition  # noqa: F401
        except ImportError as error:
            raise RuntimeError("Không có STT local hay Google backend khả dụng.") from error
        self._use_google = True
        safe_print("[STT] Dùng Google theo quyền đã chọn; audio được gửi tới dịch vụ Google.")

    def _record(self, timeout: float = 6.0, phrase_limit: float = 8.0):
        if self._sd is None:
            import sounddevice as sd

            self._sd = sd
        return _record_pcm_sd(timeout, phrase_limit, device=self._sd)

    def transcribe_array(self, audio) -> str:
        try:
            import numpy as np

            self._load_model()
            if self._use_google:
                return self._google_from_array(audio)
            audio_float = audio.astype(np.float32) / 32768.0
            return _decoded_text(self._pipe({"sampling_rate": SAMPLE_RATE, "raw": audio_float}))
        except Exception as error:
            logger.warning("STT array lỗi: %s", error)
            safe_print(f"[STT] Lỗi khi xử lý âm thanh: {error}")
            return ""

    def transcribe_file(self, path: str | Path) -> str:
        try:
            local = Path(path).expanduser().absolute()
            if not local.is_file():
                raise ValueError("transcribe_file chỉ nhận file local có thật, không nhận URL.")
            self._load_model()
            if self._use_google:
                return self._google_from_file(str(local))
            return _decoded_text(self._pipe(str(local)))
        except Exception as error:
            logger.warning("STT file lỗi: %s", error)
            safe_print(f"[STT] Lỗi khi xử lý file: {error}")
            return ""

    def listen(self, *, language: str = "vi-VN", timeout: float = 6.0) -> str:
        try:
            duration = _duration(timeout)
            self._language = language
            self._load_model()  # Never open the microphone before a usable backend.
            audio = self._record(timeout=duration)
            return "" if audio is None else self.transcribe_array(audio)
        except Exception as error:
            safe_print(f"[STT] {error} -> dùng gõ phím.")
            return ""

    def _google_transcribe(self, audio_data) -> str:
        """Gọi Google STT, PHÂN BIỆT rõ hai kiểi hỏng.

        v7.9: bản cũ nuốt mọi lỗi vào `return ""` - người dùng nghe im rồi tưởng
        mình nói không ra, trong khi thật ra là mất mạng hoặc hết hạn mức. Nói
        không rõ và mất mạng cần hai cách xử lý KHÁC nhau (nói lại vs gõ tay), và
        hàm `listen_once` ở tầng trên vốn đã phân biệt được; lớp này thì không.
        """
        if not self.allow_cloud:
            safe_print("[STT] Cloud chưa được cho phép; không gửi audio.")
            return ""
        import speech_recognition as sr

        if self._recognizer is None:
            self._recognizer = sr.Recognizer()
        try:
            raw = self._recognizer.recognize_google(audio_data, language=self._language)
            text = raw.strip() if isinstance(raw, str) else ""
            # Nghe được rồi thì số lần hỏng liên tiếp tính lại từ đầu. Không
            # reset thì một lần mất mạng 3 giây giữa phiên làm bộ đếm leo lên
            # mãi, và cảnh báo "lần 1001" xuất hiện ở câu nói hoàn toàn bình
            # thường.
            self._google_failures = 0
            return text
        except sr.UnknownValueError:
            safe_print("[STT] Không nghe rõ, bạn thử nói lại nhé.")
            self._google_failures = 0
            return ""
        except Exception as e:  # mất mạng, hết hạn mức, dịch vụ lỗi...
            self._google_failures += 1
            logger.warning("Lỗi Google STT (lần %d liên tiếp): %s",
                           self._google_failures, e)
            # Chỉ cảnh báo một lần cho mỗi 10 lần liên tiếp, nếu không thì mỗi
            # câu nói hỏng lại in thêm một dòng, thành spam ngay trong lúc dùng.
            if self._google_failures == 1 or self._google_failures % 10 == 0:
                safe_print(f"[STT] Lỗi kết nối dịch vụ STT: {e}")
                safe_print("      (không có mạng, hoặc dịch vụ bị giới hạn) "
                           "- bạn có thể gõ tay.")
            return ""

    def _google_from_array(self, audio) -> str:
        if not self.allow_cloud:
            safe_print("[STT] Cloud chưa được cho phép; không gửi audio.")
            return ""
        import speech_recognition as sr

        if self._recognizer is None:
            self._recognizer = sr.Recognizer()

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio.tobytes())
        buf.seek(0)

        with sr.AudioFile(buf) as source:
            audio_data = self._recognizer.record(source)
        return self._google_transcribe(audio_data)

    def _google_from_file(self, path: str) -> str:
        if not self.allow_cloud:
            safe_print("[STT] Cloud chưa được cho phép; không gửi audio.")
            return ""
        import speech_recognition as sr

        if self._recognizer is None:
            self._recognizer = sr.Recognizer()
        with sr.AudioFile(path) as source:
            audio_data = self._recognizer.record(source)
        return self._google_transcribe(audio_data)


# --- Simple utility (Google STT via sounddevice) ---
_sr: Any = None
try:
    import speech_recognition as _speech_recognition

    _sr = _speech_recognition
    _SR_AVAILABLE = True
except ImportError:
    _SR_AVAILABLE = False

try:
    import sounddevice as _sd

    _SD_AVAILABLE = True
except Exception:
    _SD_AVAILABLE = False


def has_pyaudio() -> bool:
    try:
        import pyaudio  # noqa: F401

        return True
    except Exception:
        return False


def is_available() -> bool:
    """Library/recording availability for the selected policy, not hardware proof."""
    if ENGINE == "google":
        return _google_available()
    return _offline_available() or (ENGINE == "auto" and ALLOW_CLOUD and _google_available())


def _record_pcm_sd(timeout: float = 6.0, phrase_limit: float = 8.0, *, device=None):
    import numpy as np

    timeout, phrase_limit = _duration(timeout), _duration(phrase_limit)
    backend = _sd if device is None else device

    chunk_samples = int(SAMPLE_RATE * CHUNK_DURATION)
    silence_chunks = int(SILENCE_DURATION / CHUNK_DURATION)
    timeout_chunks = int(timeout / CHUNK_DURATION)
    max_chunks = int(min(MAX_DURATION, phrase_limit + timeout) / CHUNK_DURATION)

    frames = []
    silent_count = 0
    speech_started = False

    safe_print("[STT] Đang nghe... (nói vào micro, im lặng ~1s là tự dừng)")

    with backend.InputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=chunk_samples
    ) as stream:
        for i in range(max_chunks):
            chunk, _overflow = stream.read(chunk_samples)
            if _rms(chunk) > SILENCE_THRESHOLD:
                speech_started = True
                silent_count = 0
            else:
                if speech_started:
                    silent_count += 1
                elif i >= timeout_chunks:
                    return None
            if speech_started:
                frames.append(chunk.copy())
            if speech_started and silent_count >= silence_chunks:
                break

    if not frames:
        return None

    audio = np.concatenate(frames, axis=0).flatten()
    safe_print("   Đã ghi %.1fs audio." % (len(audio) / SAMPLE_RATE))

    # v7.2: AudioData nhận thẳng PCM gốc, không cần đóng/mở WAV giả rồi cắt
    # cứng 44 byte đầu. Con số 44 chỉ ĐÚNG với header PCM "canonical" - nếu
    # wave thêm chunk mở rộng (hoặc ai đó đổi định dạng) là dữ liệu bị lệch
    # một vài byte và nhận diện ra kết quả rác mà không báo lỗi nào.
    return audio



def _record_audiodata_sd(timeout: float = 6.0, phrase_limit: float = 8.0):
    audio = _record_pcm_sd(timeout, phrase_limit)
    return None if audio is None else _sr.AudioData(audio.tobytes(), SAMPLE_RATE, 2)


def _report_missing_stt() -> None:
    safe_print("[STT] Backend theo policy hiện tại chưa sẵn sàng; dùng gõ phím.")
    safe_print("      Local: cài .[stt-offline], dùng --stt-download nếu cần tải model.")
    safe_print("      Cloud: chọn --stt-engine google hoặc --allow-cloud-stt khi đồng ý gửi audio.")


def _capture_audio(timeout: float, phrase_limit: float = 8.0):
    """Thu âm từ micro -> trả về (audio, đã_hết_cách).

    audio là `sr.AudioData` hoặc None. Khi None + đã_hết_cách=True, lời khuyên
    đã được in ra sẵn và caller chỉ việc quay về gõ tay.

    Tách khỏi listen_once() (v7.2) vì hàm cũ trộn 3 việc - chọn backend, thu
    âm, gọi dịch vụ - nên có tới 15 nhánh; sửa một backend là phải đọc hết.
    """
    if _SD_AVAILABLE:
        try:
            audio = _record_audiodata_sd(timeout=timeout, phrase_limit=phrase_limit)
            if audio is None:
                safe_print(f"[STT] Không nghe thấy gì trong {timeout:.0f}s, quay về gõ tay.")
                return None, True
            return audio, False
        except Exception as e:
            safe_print(f"[STT] Thu âm bằng sounddevice lỗi: {e}")
            logger.warning("sounddevice lỗi: %s", e)
            # chưa hết cách: còn backend _sr.Microphone bên dưới

    try:
        recognizer = _sr.Recognizer()
        with _sr.Microphone() as source:
            safe_print("[STT] Đang nghe... (nói vào micro)")
            recognizer.adjust_for_ambient_noise(source, duration=0.4)
            return recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_limit), False
    except AttributeError as e:
        safe_print(f"[STT] Không thu âm được: {e}")
        safe_print("      KHẮC PHỤC:  pip install sounddevice numpy")
        logger.warning("Thiếu backend thu âm: %s", e)
    except OSError as e:
        safe_print(f"[STT] Không tìm thấy micro: {e}")
        logger.warning("Không tìm thấy micro: %s", e)
    except Exception as e:
        msg = str(e)
        if "PyAudio" in msg:
            # Dự án dùng sounddevice, KHÔNG cần PyAudio. Nói rõ để người dùng
            # thôi đi tìm cách cài PyAudio (lỗi rất hay gặp trên Linux).
            safe_print("[STT] Thiếu PyAudio — nhưng dự án này KHÔNG cần nó.")
            safe_print("      KHẮC PHỤC:  pip install sounddevice numpy")
        else:
            safe_print(f"[STT] Lỗi khi ghi âm: {msg}")
        logger.warning("Lỗi khi ghi âm: %s", msg)
    return None, True


def _recognize(recognizer, audio, language: str) -> str:
    """Gửi audio tới Google Web Speech API, trả về chuỗi rỗng khi không nhận được."""
    if ENGINE != "google" and not (ENGINE == "auto" and ALLOW_CLOUD):
        return ""
    try:
        raw = recognizer.recognize_google(audio, language=language)
        text = raw.strip() if isinstance(raw, str) else ""
        safe_print(f"[STT] Nhận diện được: {text}")
        return text
    except _sr.UnknownValueError:
        safe_print("[STT] Không nghe rõ, bạn thử nói lại nhé.")
        return ""
    except _sr.RequestError as e:
        # Mất mạng / dịch vụ hỏng: phân biệt rõ với "nói không rõ" để người
        # dùng biết quay về gõ tay là do kết nối, không phải do phát âm.
        safe_print(f"[STT] Lỗi kết nối dịch vụ STT: {e}")
        logger.warning("Lỗi kết nối STT: %s", e)
        return ""


def _listen_google(language: str, timeout: float) -> str:
    if not _google_available():
        _report_missing_stt()
        return ""
    safe_print("[STT] Google được chọn/cho phép; audio gửi tới Google.")
    recognizer = _sr.Recognizer()
    audio, _gave_up = _capture_audio(timeout)
    return "" if audio is None else _recognize(recognizer, audio, language)


def listen_once(language: str = "vi-VN", timeout: float = 6.0) -> str:
    """Local-first, never cloud by default; no model download without permission."""
    try:
        duration = _duration(timeout)
        with _listen_lock:
            if ENGINE == "google":
                return _listen_google(language, duration)
            if _offline_available():
                return _default_stt().listen(language=language, timeout=duration)
            if ENGINE == "auto" and ALLOW_CLOUD:
                return _listen_google(language, duration)
            _report_missing_stt()
    except Exception as error:
        logger.warning("STT không thực hiện được: %s", error)
        safe_print(f"[STT] {error} -> dùng gõ phím.")
    return ""


_default_instance: STT | None = None


def _default_stt() -> STT:
    global _default_instance
    with _policy_lock:
        if _default_instance is None:
            _default_instance = STT(allow_cloud=ENGINE == "auto" and ALLOW_CLOUD,
                                    allow_download=ALLOW_DOWNLOAD)
        return _default_instance


def main(argv: list[str] | None = None) -> int:
    """Inspect policy by default; recording always requires --listen."""
    import argparse

    parser = argparse.ArgumentParser(description="Nhận giọng nói với cloud opt-in")
    parser.add_argument("--engine", choices=["auto", "offline", "google"], default="auto")
    parser.add_argument("--allow-cloud", action="store_true",
                        help="cho phép fallback gửi audio Google")
    parser.add_argument("--download", action="store_true", help="cho phép tải model STT chưa cache")
    parser.add_argument("--listen", action="store_true", help="bắt đầu thu một câu qua microphone")
    args = parser.parse_args(argv)
    try:
        configure(args.engine, allow_cloud=args.allow_cloud, allow_download=args.download)
    except (TypeError, ValueError) as error:
        parser.error(str(error))
    setup_console()
    if args.listen:
        text = listen_once()
        safe_print(f"[STT] Kết quả: {text}")
        return 0 if text else 1
    safe_print(f"[STT] engine={ENGINE}, cloud={ALLOW_CLOUD}, download={ALLOW_DOWNLOAD}")
    safe_print("      Thêm --listen để thu âm; mặc định không mở microphone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
