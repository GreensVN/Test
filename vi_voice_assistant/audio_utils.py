"""Small, stdlib-only validation for mono PCM16 / normalized floating buffers.

No implicit channel mixing, bit-depth guessing, sample-rate conversion, or
truncation. Returned float32 samples are suitable for a backend adapter.
"""

from __future__ import annotations

import math
import sys
from array import array
from typing import Any

__all__ = ["normalize_mono", "pcm16_bytes"]


def _sampling_rate(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("sampling_rate phải là integer.")
    if not 8000 <= value <= 192000:
        raise ValueError("sampling_rate phải trong [8000,192000].")
    return value


def normalize_mono(audio: object, *, sampling_rate: int = 16000,
                   max_duration: float = 15.0) -> array:
    """Accept native int16 or finite float buffers, mono or (frames, 1).

    Validate length/shape before tolist() allocation. Copy, never modify the
    caller's buffer. Unsupported/oversized data is refused rather than guessed.
    """
    rate = _sampling_rate(sampling_rate)
    if isinstance(max_duration, bool) or not math.isfinite(max_duration) or max_duration <= 0:
        raise ValueError("max_duration phải dương và hữu hạn.")
    try:
        # Runtime buffer probing supports Python 3.9, before a public typing.Buffer.
        view = memoryview(audio)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError("Audio cần typed PCM16/float buffer, không nhận bytes/list.") from error
    with view:
        shape = view.shape
        if shape is None or not (view.ndim == 1 or (view.ndim == 2 and shape[1] == 1)):
            raise ValueError("Chỉ nhận mono 1D hoặc (frames,1), không tự downmix stereo.")
        if not 0 < shape[0] <= int(rate * max_duration):
            raise ValueError("Audio rỗng hoặc vượt giới hạn thời lượng; không tự cắt bớt.")
        if (view.format, view.itemsize) not in (("h", 2), ("f", 4), ("d", 8)):
            raise ValueError("Chỉ nhận PCM int16 hoặc float32/64 native-endian.")
        values: list[Any] = view.tolist()  # Nested shape is validated above.
        if view.ndim == 2:
            values = [row[0] for row in values]
        if view.format == "h":
            return array("f", (value / 32768.0 for value in values))
        if any(not math.isfinite(value) or not -1.0 <= value <= 1.0 for value in values):
            raise ValueError("Float audio phải hữu hạn và nằm trong [-1,1].")
        return array("f", values)


def pcm16_bytes(samples: array) -> bytes:
    """Encode normalized mono as little-endian PCM16, clamping +1 to 32767."""
    pcm = array("h")
    for value in samples:
        if not math.isfinite(value) or not -1.0 <= value <= 1.0:
            raise ValueError("PCM encoder cần float trong [-1,1].")
        pcm.append(max(-32768, min(32767, round(value * 32768))))
    if sys.byteorder != "little":
        pcm.byteswap()
    return pcm.tobytes()
