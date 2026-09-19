"""
stt.py - Speech-To-Text

v7.0 nâng cấp:
- Type hints, pathlib, better error handling
- Thêm VAD đơn giản, timeout rõ ràng
- Tách Google STT và PhoWhisper thành class riêng
- Thêm context manager cho mic
"""

from __future__ import annotations

import io
import logging
import os
import wave
from typing import TYPE_CHECKING, Any

from platform_utils import safe_print, setup_console

if TYPE_CHECKING:  # Path chi xuat hien trong chu thich kieu (co __future__ annotations)
    from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_NAME = os.environ.get("STT_MODEL", "vinai/PhoWhisper-small")
SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 0.015
SILENCE_DURATION = 1.2
MAX_DURATION = 15.0
CHUNK_DURATION = 0.1


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
    """PhoWhisper offline + Google fallback."""

    def __init__(self, model_name: str = MODEL_NAME, device: str = "auto"):
        self.model_name = model_name
        self.device = device
        self._pipe: Any = None
        self._use_google = False
        self._sd: Any = None
        self._recognizer: Any = None

    def _load_model(self):
        if self._pipe is not None or self._use_google:
            return

        safe_print(f"[STT] Đang tải model {self.model_name} ...")
        safe_print("      (Lần đầu ~1GB, từ lần sau <10s)")
        try:
            import torch
            from transformers import pipeline

            dev = self.device
            if dev == "auto":
                dev = "cuda" if torch.cuda.is_available() else "cpu"

            self._pipe = pipeline(
                "automatic-speech-recognition",
                model=self.model_name,
                device=dev,
                chunk_length_s=30,
                generate_kwargs={"language": "vi", "task": "transcribe"},
            )
            safe_print(f"[STT] Đã tải model ({dev.upper()}). Sẵn sàng nghe.")
        except Exception as e:
            safe_print(f"[STT] Không tải được PhoWhisper ({e})")
            safe_print("[STT] Thử dùng Google STT (cần internet)...")
            try:
                import speech_recognition  # noqa: F401

                self._use_google = True
                safe_print("[STT] Dùng Google STT làm dự phòng.")
            except ImportError as err:
                raise RuntimeError(
                    "Không có module nào cho STT.\n"
                    "Cài bằng:  pip install transformers torch sounddevice\n"
                    "hoặc:      pip install SpeechRecognition sounddevice"
                ) from err

    def _record(self):
        import numpy as np

        if self._sd is None:
            import sounddevice as sd

            self._sd = sd

        sd = self._sd
        chunk_samples = int(SAMPLE_RATE * CHUNK_DURATION)
        silence_chunks = int(SILENCE_DURATION / CHUNK_DURATION)
        max_chunks = int(MAX_DURATION / CHUNK_DURATION)

        frames = []
        silent_count = 0
        speech_started = False

        safe_print("[MIC] Đang nghe... (nói xong im lặng ~1s là tự dừng)")

        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=chunk_samples
        ) as stream:
            for _ in range(max_chunks):
                chunk, _ = stream.read(chunk_samples)
                frames.append(chunk.copy())

                if _rms(chunk) > SILENCE_THRESHOLD:
                    speech_started = True
                    silent_count = 0
                else:
                    if speech_started:
                        silent_count += 1
                    if silent_count >= silence_chunks:
                        break

        audio = np.concatenate(frames, axis=0).flatten()
        safe_print(f"   Đã ghi {len(audio) / SAMPLE_RATE:.1f}s audio.")
        return audio

    def transcribe_array(self, audio) -> str:
        import numpy as np

        self._load_model()
        if self._use_google:
            return self._google_from_array(audio)

        audio_float = audio.astype(np.float32) / 32768.0
        result = self._pipe({"sampling_rate": SAMPLE_RATE, "raw": audio_float})
        return (result.get("text") or "").strip()

    def transcribe_file(self, path: str | Path) -> str:
        self._load_model()
        if self._use_google:
            return self._google_from_file(str(path))
        result = self._pipe(str(path))
        return (result.get("text") or "").strip()

    def listen(self) -> str:
        audio = self._record()
        text = self.transcribe_array(audio)
        safe_print(f"   Nhận diện: {text!r}")
        return text

    def _google_from_array(self, audio) -> str:
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
        try:
            return str(self._recognizer.recognize_google(audio_data, language="vi-VN"))
        except Exception:
            return ""

    def _google_from_file(self, path: str) -> str:
        import speech_recognition as sr

        if self._recognizer is None:
            self._recognizer = sr.Recognizer()
        with sr.AudioFile(path) as source:
            audio_data = self._recognizer.record(source)
        try:
            return str(self._recognizer.recognize_google(audio_data, language="vi-VN"))
        except Exception:
            return ""


# --- Simple utility (Google STT via sounddevice) ---
try:
    import speech_recognition as _sr

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
    if _SR_AVAILABLE and (_SD_AVAILABLE or has_pyaudio()):
        return True
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401

        return _SD_AVAILABLE
    except ImportError:
        return False


def _record_audiodata_sd(timeout: float = 6.0, phrase_limit: float = 8.0):
    import numpy as np

    chunk_samples = int(SAMPLE_RATE * CHUNK_DURATION)
    silence_chunks = int(SILENCE_DURATION / CHUNK_DURATION)
    timeout_chunks = int(timeout / CHUNK_DURATION)
    max_chunks = int(min(MAX_DURATION, phrase_limit + timeout) / CHUNK_DURATION)

    frames = []
    silent_count = 0
    speech_started = False

    safe_print("[STT] Đang nghe... (nói vào micro, im lặng ~1s là tự dừng)")

    with _sd.InputStream(
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
    return _sr.AudioData(audio.tobytes(), SAMPLE_RATE, 2)


def _report_missing_stt() -> None:
    """Hướng dẫn cài đặt khi máy chưa đủ thư viện STT (không ném lỗi - gõ tay vẫn dùng được)."""
    if _SR_AVAILABLE:
        safe_print("[STT] Đã có SpeechRecognition nhưng thiếu thư viện thu âm.")
        safe_print("      Cài bằng:  pip install sounddevice numpy")
    else:
        safe_print("[STT] Chưa cài thư viện nhận diện giọng nói -> dùng gõ phím.")
        safe_print("      Cài bằng:  pip install SpeechRecognition sounddevice numpy")


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
    try:
        text = str(recognizer.recognize_google(audio, language=language))
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


def listen_once(language: str = "vi-VN", timeout: float = 6.0) -> str:
    """Nghe một câu qua micro và trả về văn bản. Trả về "" nếu không nghe được."""
    if not is_available():
        _report_missing_stt()
        return ""

    if _SR_AVAILABLE:
        recognizer = _sr.Recognizer()
        audio, _gave_up = _capture_audio(timeout)
        if audio is None:
            return ""
        return _recognize(recognizer, audio, language)

    # Không có SpeechRecognition -> chỉ còn đường PhoWhisper offline.
    try:
        return _default_stt().listen()
    except Exception as e:
        safe_print(f"[STT] Lỗi: {e}")
        return ""


_default_instance: STT | None = None


def _default_stt() -> STT:
    global _default_instance
    if _default_instance is None:
        _default_instance = STT()
    return _default_instance


if __name__ == "__main__":
    setup_console()
    safe_print("[STT] Kiểm tra module nhận diện giọng nói")
    safe_print(f"      Model mặc định: {MODEL_NAME}")
    safe_print(f"      Sample rate    : {SAMPLE_RATE} Hz")
    safe_print(f"      Khả dụng       : {is_available()}")
    safe_print("")

    if _SD_AVAILABLE:
        try:
            import sounddevice as sd

            devices = sd.query_devices()
            safe_print("Thiết bị âm thanh:")
            for i, d in enumerate(devices):
                if d["max_input_channels"] > 0:
                    safe_print(f"  [{i}] {d['name']} (in: {d['max_input_channels']} ch)")
        except Exception as e:
            safe_print(f"(Không liệt kê được thiết bị âm thanh: {e})")
    else:
        safe_print("Chưa cài sounddevice: pip install sounddevice")
