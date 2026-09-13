# -*- coding: utf-8 -*-
"""
giong_noi_ai.py
---------------
GIỌNG NÓI AI TIẾNG VIỆT v7.0 — CHỈ DÙNG MÔ HÌNH/DỮ LIỆU CHO PHÉP THƯƠNG MẠI
VÀ CHO PHÉP BẠN MỞ MÃ NGUỒN.

v6.4: đổi engine chính từ Piper (vi_VN-vais1000-medium, CC BY 4.0) sang
VieNeu-TTS v3-Turbo (pnnbao-ump, Apache 2.0). Lý do đổi:
  - Apache 2.0 KHÔNG bắt buộc ghi công như CC BY (dù vẫn nên ghi công).
  - Chất lượng tự nhiên hơn Piper rõ rệt (48kHz, kiến trúc train từ đầu
    trên ~10.000 giờ dữ liệu Việt-Anh, không phải fine-tune).
  - Có 10 giọng dựng sẵn (nam + nữ) thay vì 1 giọng nữ cố định như Piper.
  - Có NHÂN BẢN GIỌNG (voice cloning) tức thời từ 3-5 giây audio mẫu —
    thay thế hoàn toàn quy trình fine-tune Piper vốn cần WSL/Linux/Colab
    và vài giờ GPU (xem huong_dan_train() bên dưới, giờ chỉ còn vài dòng).
  - Chạy được cả CPU (qua ONNX, tự động) lẫn GPU (qua PyTorch, tự động).

QUAN TRỌNG — 10 giọng dựng sẵn (lệnh "thu") chạy thuần CPU qua ONNX, KHÔNG
cần cài torch. Nhưng NHÂN BẢN GIỌNG (tham số ref_audio / lệnh "nhan-ban")
thì khác: gói vieneu dùng torchaudio để trích đặc trưng giọng nói từ audio
mẫu, kể cả khi mọi thứ khác vẫn chạy trên CPU/ONNX — nên "pip install
vieneu" KHÔNG CÔNG SUỐT ĐỦ cho nhân bản giọng, phải cài thêm:
    pip install torch torchaudio
KHÔNG cần GPU/CUDA thật (bản CPU của torch là đủ), nhưng đây vẫn là một
lượt tải thêm ~150-250MB — không "chỉ vài dòng, không cần gì thêm" như
có thể hiểu lầm từ câu trên. Dùng is_clone_available() bên dưới để kiểm
tra trước khi gọi nhan_ban_giong().

Piper vẫn được giữ lại làm engine dự phòng nếu bạn đã lỡ tải giọng cũ —
xem PIPER_VOICES_LEGACY bên dưới — nhưng KHÔNG còn là lựa chọn mặc định.

Dùng nhanh:
    python giong_noi_ai.py giay-phep         # xem bảng giấy phép (bắt buộc đọc)
    python giong_noi_ai.py tai               # tải model VieNeu (~vài trăm MB, 1 lần)
    python giong_noi_ai.py thu "Xin chào"    # đọc thử (giọng mặc định: Ngọc Lan)
    python giong_noi_ai.py thu "Xin chào" --giong "Xuân Vĩnh"   # đổi giọng
    python giong_noi_ai.py kiem-tra          # xem đã cài được chưa
    python giong_noi_ai.py nhan-ban mau.wav "Câu cần đọc"   # nhân bản giọng
    python giong_noi_ai.py huong-dan-train   # (giờ chỉ là hướng dẫn nhân bản giọng)

Dùng trong code:
    import giong_noi_ai
    giong_noi_ai.speak("Xin chào, tôi là trợ lý ảo")
    giong_noi_ai.speak("Xin chào", voice="Xuân Vĩnh")

CÀI:
    pip install vieneu
"""

import argparse
import os

from platform_utils import safe_print, setup_console

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VOICE_DIR = os.path.join(BASE_DIR, "giong_ai")  # giữ lại cho tương thích ngược (Piper)
CLONE_DIR = os.path.join(BASE_DIR, "giong_nhan_ban")
DATASET_DIR = os.path.join(BASE_DIR, "dataset_giong")

# ============================================================================
# ENGINE MẶC ĐỊNH — VieNeu-TTS v3-Turbo (Apache 2.0)
# ============================================================================
MODEL_INFO = {
    "ten": "VieNeu-TTS-v3-Turbo",
    "tac_gia": "Phạm Nguyễn Ngọc Bảo (pnnbao-ump / pnnbao97)",
    "nguon_model": "https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Turbo",
    "nguon_code": "https://github.com/pnnbao97/VieNeu-TTS",
    "giay_phep": "Apache 2.0 (code + weights + dataset train)",
    "thuong_mai": True,
    "ma_nguon_mo": True,
    "sample_rate": 48000,
    "kien_truc": "Train từ đầu (không fine-tune) trên ~10.000 giờ dữ liệu "
                  "Việt-Anh, codec MOSS-Audio-Tokenizer-Nano",
    "ghi_chu": "Apache 2.0 không bắt buộc ghi công (khác CC BY 4.0 của Piper "
               "trước đây), nhưng nên giữ thông báo giấy phép khi phát hành.",
}

# 10 giọng dựng sẵn — không cần audio mẫu, gọi thẳng bằng tên
DEFAULT_VOICES = {
    "Ngọc Lan": {"gioi_tinh": "nữ", "phong_cach": "nhẹ nhàng, dịu dàng", "mac_dinh": True},
    "Ngọc Linh": {"gioi_tinh": "nữ", "phong_cach": "tươi sáng"},
    "Trúc Ly": {"gioi_tinh": "nữ", "phong_cach": "trẻ trung"},
    "Mỹ Duyên": {"gioi_tinh": "nữ", "phong_cach": "mượt mà"},
    "Xuân Vĩnh": {"gioi_tinh": "nam", "phong_cach": "sôi nổi"},
    "Thái Sơn": {"gioi_tinh": "nam", "phong_cach": "chắc chắn"},
    "Gia Bảo": {"gioi_tinh": "nam", "phong_cach": "mượt mà"},
    "Đức Trí": {"gioi_tinh": "nam", "phong_cach": "rõ ràng"},
    "Trọng Hữu": {"gioi_tinh": "nam", "phong_cach": "am hiểu"},
    "Bình An": {"gioi_tinh": "nam", "phong_cach": "điềm đạm"},
}
DEFAULT_VOICE = "Ngọc Lan"

# Mô hình KHÔNG dùng được NẾU BẠN MUỐN THƯƠNG MẠI.
# NẾU BẠN CHẤP NHẬN PHI THƯƠNG MẠI: những mô hình này đều dùng được
# và vẫn cho phép bạn mở mã nguồn — xem file  giong_nc.py
BLACKLIST = {
    "xtts": ("Coqui XTTS v2", "CPML — phi thương mại. Coqui đã đóng cửa 01/2024 "
                              "nên KHÔNG còn ai bán giấy phép thương mại."),
    "vixtts": ("viXTTS", "Fine-tune từ XTTS v2 → thừa hưởng CPML phi thương mại."),
    "f5-tts": ("F5-TTS", "Code MIT nhưng checkpoint gốc CC BY-NC 4.0 — phi thương mại."),
    "mms": ("facebook/mms-tts-vie", "CC BY-NC 4.0 — phi thương mại."),
    "viet-tts": ("dangvansam/viet-tts", "Metadata ghi apache-2.0 nhưng bản model "
                                        "card cũ từng ghi weights CC BY-NC — chưa "
                                        "thống nhất, tránh cho tới khi rõ ràng."),
    "viterbox": ("dolly-vn/viterbox", "Fine-tune Chatterbox cho tiếng Việt nhưng "
                                       "weights CC BY-NC 4.0 — phi thương mại."),
    "fish-audio-s2": ("Fish Audio S2 Pro", "Fish Audio Research License — "
                                            "phi thương mại."),
}

# Mô hình Piper vais1000-medium — GIỮ LẠI làm tham khảo lịch sử / dự phòng.
# Không còn là DEFAULT_VOICE nhưng vẫn dùng thương mại được nếu bạn thích
# giọng đó hoặc máy quá yếu cho VieNeu.
PIPER_VOICES_LEGACY = {
    "vais1000": {
        "file": "vi_VN-vais1000-medium",
        "path": "vi/vi_VN/vais1000/medium",
        "sample_rate": 22050,
        "giong": "nữ",
        "chat_luong": "medium",
        "dataset": "VAIS-1000 (IEEE DataPort)",
        "giay_phep": "CC BY 4.0",
        "thuong_mai": True,
        "ma_nguon_mo": True,
        "ghi_chu": "PHẢI ghi công (attribution) nếu dùng bản này.",
    },
}

# Dataset tiếng Việt sạch giấy phép — vẫn hữu ích nếu bạn muốn TỰ TRAIN một
# model từ đầu (hiếm khi cần, vì VieNeu đã hỗ trợ nhân bản giọng tức thời).
DATASETS = {
    "common_voice_vi": {
        "ten": "Mozilla Common Voice (vi)",
        "giay_phep": "CC0 (public domain)",
        "thuong_mai": True,
        "url": "https://commonvoice.mozilla.org/vi/datasets",
        "ghi_chu": "Sạch nhất về pháp lý. Nhiều người nói, nhiễu — tốt cho STT, "
                   "phải lọc kỹ nếu dùng cho TTS.",
    },
    "vais1000": {
        "ten": "VAIS-1000",
        "giay_phep": "CC BY 4.0",
        "thuong_mai": True,
        "url": "https://ieee-dataport.org/documents/"
               "vais-1000-vietnamese-speech-synthesis-corpus",
        "ghi_chu": "1000 câu, 1 giọng nữ, thu phòng studio. Phải ghi công.",
    },
    "fleurs_vi": {
        "ten": "Google FLEURS (vi_vn)",
        "giay_phep": "CC BY 4.0",
        "thuong_mai": True,
        "url": "https://huggingface.co/datasets/google/fleurs",
        "ghi_chu": "~10 giờ. Phải ghi công.",
    },
    "giong_cua_ban": {
        "ten": "Giọng chính bạn tự thu (chỉ cần 3-5 giây!)",
        "giay_phep": "Bạn sở hữu 100%",
        "thuong_mai": True,
        "url": "python giong_noi_ai.py nhan-ban mau.wav \"Câu cần đọc\"",
        "ghi_chu": "VieNeu nhân bản giọng TỨC THÌ từ 3-5 giây audio mẫu — "
                   "không cần 300-500 câu hay GPU train nhiều giờ như Piper nữa.",
    },
    # --- TRÁNH ---
    "vivos": {
        "ten": "VIVOS",
        "giay_phep": "CC BY-NC-SA 4.0",
        "thuong_mai": False,
        "url": "https://ailab.hcmus.edu.vn/vivos",
        "ghi_chu": "TRÁNH — phi thương mại.",
    },
}


# ============================================================================
# NẠP MODEL / TỔNG HỢP
# ============================================================================
_vieneu_cache = None


def _load_vieneu():
    """Nạp Vieneu() 1 lần rồi cache lại (lần đầu sẽ tự tải model từ HF Hub).

    Tự động chọn CPU (ONNX, không cần torch) hoặc GPU (PyTorch) tuỳ máy.
    """
    global _vieneu_cache
    if _vieneu_cache is not None:
        return _vieneu_cache

    from vieneu import Vieneu
    _vieneu_cache = Vieneu()
    return _vieneu_cache


def is_available() -> bool:
    """True nếu đã cài gói `vieneu` (model sẽ tự tải khi gọi lần đầu).

    Chỉ đủ cho 10 giọng DỰNG SẴN (tham số voice=...). Nhân bản giọng
    (ref_audio=...) cần thêm điều kiện — xem is_clone_available().
    """
    try:
        import vieneu  # noqa: F401
        return True
    except ImportError:
        return False


def is_clone_available() -> bool:
    """True nếu đã đủ điều kiện NHÂN BẢN GIỌNG (tham số ref_audio=...).

    Giọng dựng sẵn chạy thuần CPU/ONNX (torch-free), nhưng bước trích đặc
    trưng giọng nói khi nhân bản (speaker encoder trong gói vieneu) dùng
    torchaudio cho phần fbank front-end — nên dù vẫn chạy trên CPU, vẫn
    cần cài thêm 2 gói này (KHÔNG cần GPU/CUDA thật):
        pip install torch torchaudio
    """
    if not is_available():
        return False
    try:
        import torch  # noqa: F401
        import torchaudio  # noqa: F401
        return True
    except ImportError:
        return False


def download_voice(force: bool = False):
    """'Tải' model = nạp Vieneu() một lần cho xong (gói vieneu tự tải file
    weights từ Hugging Face Hub và cache lại ở ~/.cache/huggingface).

    Giữ tên hàm `download_voice` để tương thích với code cũ gọi tới nó.
    """
    if not is_available():
        safe_print("[LỖI] Chưa cài gói vieneu.  pip install vieneu")
        return False
    try:
        safe_print("Đang tải model VieNeu-TTS-v3-Turbo (lần đầu, có thể mất vài phút)...")
        _load_vieneu()
    except Exception as e:
        safe_print(f"[LỖI] Tải/nạp model thất bại: {e}")
        return False

    _write_attribution()
    safe_print("\n[XONG] VieNeu-TTS-v3-Turbo đã sẵn sàng.")
    safe_print("Thử ngay:  python giong_noi_ai.py thu \"Xin chào Việt Nam\"")
    return True


def _write_attribution():
    """Ghi file ghi công — Apache 2.0 không bắt buộc nhưng nên giữ lại."""
    os.makedirs(VOICE_DIR, exist_ok=True)
    path = os.path.join(VOICE_DIR, "ATTRIBUTION.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "GHI CÔNG (ATTRIBUTION) — KHÔNG BẮT BUỘC (Apache 2.0) NHƯNG NÊN GIỮ\n"
            "=" * 70 + "\n\n"
            f"Mô hình      : {MODEL_INFO['ten']}\n"
            f"Tác giả      : {MODEL_INFO['tac_gia']}\n"
            f"Giấy phép    : {MODEL_INFO['giay_phep']}\n"
            f"Kiến trúc    : {MODEL_INFO['kien_truc']}\n\n"
            "Nguồn:\n"
            f"  - Model : {MODEL_INFO['nguon_model']}\n"
            f"  - Code  : {MODEL_INFO['nguon_code']}\n"
            "  - Apache 2.0 : https://www.apache.org/licenses/LICENSE-2.0\n"
        )
    safe_print(f"   Đã ghi {os.path.basename(path)}")


def synth_to_file(text: str, out_path: str, voice: str = DEFAULT_VOICE,
                   ref_audio: str = None) -> bool:
    """Tổng hợp `text` thành file WAV. Trả về True nếu thành công.

    v7.0: tự tạo thư mục cha nếu chưa có, kiểm tra text rỗng.
    """
    if not text or not text.strip():
        safe_print("[GIỌNG AI] Text rỗng, không tổng hợp.")
        return False

    # Đảm bảo thư mục cha tồn tại
    try:
        from pathlib import Path
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    if ref_audio and not is_clone_available():
        safe_print(
            "[GIỌNG AI] Nhân bản giọng cần thêm torch + torchaudio (giọng "
            "dựng sẵn thì không cần). Cài thêm rồi thử lại:\n"
            "           pip install torch torchaudio\n"
            "           (bản CPU thôi, không cần GPU thật, ~150-250MB.)"
        )
        return False

    try:
        tts = _load_vieneu()
    except Exception as e:
        safe_print(f"[GIỌNG AI] Không nạp được model: {e}")
        return False

    try:
        if ref_audio:
            audio = tts.infer(text, ref_audio=ref_audio)
        else:
            audio = tts.infer(text, voice=voice)
        tts.save(audio, out_path)
        return True
    except Exception as e:
        safe_print(f"[GIỌNG AI] Lỗi tổng hợp: {e}")
        return False


def speak(text: str, voice: str = DEFAULT_VOICE, ref_audio: str = None) -> bool:
    """Đọc `text` bằng giọng AI. Trả về True nếu đọc được.

    Đây là hàm tts.py gọi tới (engine 'piper' / '_speak_piper', tên hàm giữ
    nguyên trong tts.py để không phải sửa dây chuyền engine).
    """
    import tempfile

    if not text or not text.strip():
        return False

    fd, path = tempfile.mkstemp(suffix=".wav", prefix="giongai_")
    os.close(fd)
    try:
        if not synth_to_file(text, path, voice=voice, ref_audio=ref_audio):
            return False
        import tts
        tts._play_audio(path)
        return True
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def nhan_ban_giong(ref_audio: str, text: str, out_path: str = None) -> bool:
    """Nhân bản giọng tức thời từ 1 file audio mẫu 3-5 giây.

    Thay thế hoàn toàn quy trình fine-tune Piper (WSL/Linux/Colab, vài giờ
    GPU, 300-500 câu). Với VieNeu chỉ cần:
        python giong_noi_ai.py nhan-ban mau.wav "Câu cần đọc"
    """
    if not os.path.isfile(ref_audio):
        safe_print(f"[LỖI] Không thấy file mẫu: {ref_audio}")
        return False

    if out_path:
        ok = synth_to_file(text, out_path, ref_audio=ref_audio)
        if ok:
            safe_print(f"[XONG] Đã lưu: {out_path}")
        return ok
    return speak(text, ref_audio=ref_audio)


# ============================================================================
# CHUẨN BỊ DATASET ĐỂ TRAIN TỪ ĐẦU (hiếm khi cần — xem nhan_ban_giong ở trên)
# ============================================================================
def chuan_bi_data():
    """Gom bản ghi từ train_tts.py record thành định dạng LJSpeech.

    Vẫn giữ hàm này cho ai muốn TỰ TRAIN một model từ đầu (không phải nhân
    bản giọng), nhưng với VieNeu, đa số trường hợp chỉ cần nhan_ban_giong()
    ở trên với đúng 1 file audio 3-5 giây, không cần bước này.
    """
    rec_dir = os.path.join(BASE_DIR, "my_voice")
    if not os.path.isdir(rec_dir):
        safe_print("[!] Chưa có thư mục my_voice/.")
        safe_print("    Thu giọng trước:  python train_tts.py record --count 300")
        return False

    wavs = sorted(f for f in os.listdir(rec_dir) if f.lower().endswith(".wav"))
    if not wavs:
        safe_print("[!] my_voice/ chưa có file .wav nào.")
        return False

    meta_src = os.path.join(rec_dir, "metadata.csv")
    if not os.path.isfile(meta_src):
        safe_print(f"[!] Thiếu {meta_src} (file ghi câu tương ứng mỗi wav).")
        return False

    os.makedirs(os.path.join(DATASET_DIR, "wav"), exist_ok=True)
    import shutil

    rows = []
    with open(meta_src, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 2:
                continue
            stem, text = parts[0], parts[1]
            src = os.path.join(rec_dir, stem if stem.endswith(".wav") else stem + ".wav")
            if not os.path.isfile(src):
                continue
            base = os.path.basename(src)
            shutil.copy2(src, os.path.join(DATASET_DIR, "wav", base))
            rows.append(f"{os.path.splitext(base)[0]}|{text}")

    out = os.path.join(DATASET_DIR, "metadata.csv")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(rows) + "\n")

    safe_print(f"[XONG] {len(rows)} câu trong {DATASET_DIR}")
    return True


def huong_dan_train():
    """In hướng dẫn có giọng riêng — giờ chỉ là NHÂN BẢN GIỌNG, không train."""
    setup_console()
    safe_print("=" * 74)
    safe_print("  CÓ GIỌNG RIÊNG VỚI VieNeu-TTS-v3-Turbo — KHÔNG CẦN TRAIN NỮA")
    safe_print("=" * 74)
    safe_print("""
TRƯỚC ĐÂY (Piper): fine-tune từ checkpoint vais1000, cần WSL2/Linux/Colab,
300-500 câu (~30-45 phút audio) và 2-6 giờ GPU.

BÂY GIỜ (VieNeu): NHÂN BẢN GIỌNG TỨC THÌ — chỉ cần 1 file audio 3-5 giây,
chạy ngay trên Windows, KHÔNG cần GPU thật (vẫn chạy trên CPU bình thường).

LƯU Ý: "không cần GPU" KHÁC với "không cần cài gì thêm". Phần trích đặc
trưng giọng nói khi nhân bản dùng torchaudio, nên ngoài `pip install
vieneu` (đủ cho 10 giọng dựng sẵn), nhân bản giọng cần cài thêm 1 lần:
    pip install torch torchaudio
(bản CPU, không cần GPU/CUDA thật, thêm ~150-250MB). Script
cai_dat_giong_ai.bat sẽ hỏi bạn có muốn cài phần này luôn không.

--------------------------------------------------------------------
BƯỚC 1 — Thu 1 đoạn mẫu 3-5 giây
--------------------------------------------------------------------
  Phòng yên tĩnh, nói rõ ràng, lưu thành file .wav (VD: mau.wav).
  Có thể dùng lệnh có sẵn của dự án:
      python train_tts.py record --count 1

--------------------------------------------------------------------
BƯỚC 2 — Nhân bản & đọc thử (cần đã cài torch + torchaudio ở trên)
--------------------------------------------------------------------
      python giong_noi_ai.py nhan-ban mau.wav "Xin chào, đây là giọng của tôi"

  Hoặc trong code:
      import giong_noi_ai
      giong_noi_ai.speak("Xin chào", ref_audio="mau.wav")

--------------------------------------------------------------------
NẾU MUỐN TRAIN MỘT MODEL HOÀN TOÀN MỚI TỪ ĐẦU (hiếm khi cần)
--------------------------------------------------------------------
  VieNeu-TTS-v3-Turbo được tác giả train từ đầu trên ~10.000 giờ dữ liệu,
  đây là việc rất tốn kém (không khuyến khích tự làm lại). Nếu vẫn muốn
  đóng góp/tinh chỉnh sâu hơn nhân bản giọng, xem hướng dẫn của tác giả:
      https://github.com/pnnbao97/VieNeu-TTS
  và dùng chuan_bi_data() ở trên để gom dữ liệu theo định dạng LJSpeech.
""")
    safe_print("=" * 74)


# ============================================================================
# BẢNG GIẤY PHÉP
# ============================================================================
def in_giay_phep():
    setup_console()
    safe_print("=" * 78)
    safe_print("  MÔ HÌNH GIỌNG AI TIẾNG VIỆT — LỌC THEO: THƯƠNG MẠI + MÃ NGUỒN MỞ")
    safe_print("=" * 78)

    safe_print("\n### ĐANG DÙNG (mặc định) ###\n")
    safe_print(f"  [OK] {MODEL_INFO['ten']}")
    safe_print(f"       Tác giả   : {MODEL_INFO['tac_gia']}")
    safe_print(f"       Giấy phép : {MODEL_INFO['giay_phep']}  -> thương mại OK")
    safe_print(f"       Kiến trúc : {MODEL_INFO['kien_truc']}")
    safe_print("       Giọng     : 10 giọng dựng sẵn (5 nữ, 5 nam) + nhân bản "
               "tức thời từ audio mẫu")
    safe_print("       Cài đặt   : `pip install vieneu` (đủ cho giọng dựng sẵn, "
               "cần Python 3.10+)")
    safe_print("                   Nhân bản giọng cần cài thêm: "
               "`pip install torch torchaudio`")
    safe_print(f"       Lưu ý     : {MODEL_INFO['ghi_chu']}\n")

    safe_print("  Danh sách giọng dựng sẵn:")
    for ten, v in DEFAULT_VOICES.items():
        mark = " (mặc định)" if v.get("mac_dinh") else ""
        phong_cach = v.get("phong_cach", "")
        safe_print(f"    - {ten}{mark}: {v['gioi_tinh']}, {phong_cach}")

    safe_print("\n### DỰ PHÒNG / LỊCH SỬ ###\n")
    for key, v in PIPER_VOICES_LEGACY.items():
        safe_print(f"  [OK] Piper {key}  ({v['file']})")
        safe_print(f"       Giấy phép : {v['giay_phep']} -> thương mại OK "
                   "(PHẢI ghi công, khác VieNeu)")
        safe_print("       Lưu ý     : nhẹ hơn (63MB) nhưng chất lượng thấp hơn "
                   "VieNeu rõ rệt. Chỉ nên dùng nếu máy quá yếu.\n")

    safe_print("### TRÁNH (dù được quảng cáo là 'open source') ###\n")
    safe_print("  (NẾu bạn CHẤP NHẬN phi thương mại thì dùng "
               "được hết — chạy: python giong_nc.py giay-phep)")
    safe_print("")
    for _, (ten, ly_do) in BLACKLIST.items():
        safe_print(f"  [X] {ten}")
        safe_print(f"      {ly_do}\n")

    safe_print("### DATASET / CÁCH CÓ GIỌNG RIÊNG ###\n")
    for key, d in DATASETS.items():
        mark = "OK" if d["thuong_mai"] else "X "
        safe_print(f"  [{mark}] {d['ten']}  —  {d['giay_phep']}")
        safe_print(f"      {d['url']}")
        safe_print(f"      {d['ghi_chu']}\n")

    safe_print("=" * 78)
    safe_print("BẪY LỚN NHẤT: 'code MIT/Apache' KHÔNG có nghĩa 'weights dùng")
    safe_print("thương mại được'. Engine và mô hình là HAI giấy phép riêng biệt.")
    safe_print("XTTS, F5-TTS, MMS, viet-tts, viterbox đều vướng đúng chỗ này.")
    safe_print("=" * 78)


def kiem_tra():
    setup_console()
    safe_print("[GIỌNG AI] Kiểm tra")
    safe_print("-" * 60)

    try:
        import vieneu
        ver = getattr(vieneu, "__version__", "?")
        safe_print(f"  vieneu          : đã cài (bản {ver})")
    except ImportError:
        safe_print("  vieneu          : CHƯA CÀI  ->  pip install vieneu")

    safe_print(f"  Sẵn sàng đọc (giọng dựng sẵn) : {is_available()}")
    if is_available():
        safe_print("  Model sẽ tự tải về ~/.cache/huggingface khi gọi lần đầu "
                   "(python giong_noi_ai.py tai để tải trước).")

    if is_clone_available():
        safe_print("  Sẵn sàng nhân bản giọng       : True")
    elif is_available():
        safe_print("  Sẵn sàng nhân bản giọng       : False  "
                   "->  pip install torch torchaudio")
    else:
        safe_print("  Sẵn sàng nhân bản giọng       : False  (cần cài vieneu trước)")
    safe_print("-" * 60)


# ============================================================================
# CLI
# ============================================================================
def main():
    setup_console()
    p = argparse.ArgumentParser(
        description="Giọng nói AI tiếng Việt — VieNeu-TTS-v3-Turbo (Apache 2.0)"
    )
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("giay-phep", help="bảng giấy phép mô hình + dataset")
    sub.add_parser("kiem-tra", help="kiểm tra đã cài/tải xong chưa")
    sub.add_parser("chuan-bi-data", help="gom bản thu thành dataset LJSpeech (hiếm khi cần)")
    sub.add_parser("huong-dan-train", help="hướng dẫn có giọng riêng (nhân bản, không train)")

    p_tai = sub.add_parser("tai", help="tải/nạp model VieNeu về máy")
    p_tai.add_argument("--force", action="store_true")

    p_thu = sub.add_parser("thu", help="đọc thử một câu")
    p_thu.add_argument("text", nargs="?",
                       default="Xin chào, tôi là trợ lý ảo tiếng Việt.")
    p_thu.add_argument("--giong", default=DEFAULT_VOICE, help="tên giọng dựng sẵn")
    p_thu.add_argument("--luu", default=None, help="lưu ra file wav thay vì phát")

    p_clone = sub.add_parser("nhan-ban", help="nhân bản giọng từ audio mẫu 3-5s")
    p_clone.add_argument("mau_wav", help="đường dẫn file audio mẫu (.wav)")
    p_clone.add_argument("text", nargs="?",
                         default="Đây là giọng được nhân bản tức thì.")
    p_clone.add_argument("--luu", default=None, help="lưu ra file wav thay vì phát")

    args = p.parse_args()

    if args.cmd == "giay-phep":
        in_giay_phep()
    elif args.cmd == "kiem-tra":
        kiem_tra()
    elif args.cmd == "tai":
        download_voice(force=args.force)
    elif args.cmd == "chuan-bi-data":
        chuan_bi_data()
    elif args.cmd == "huong-dan-train":
        huong_dan_train()
    elif args.cmd == "nhan-ban":
        nhan_ban_giong(args.mau_wav, args.text, out_path=args.luu)
    elif args.cmd == "thu":
        if args.luu:
            ok = synth_to_file(args.text, args.luu, voice=args.giong)
            if ok:
                safe_print(f"[XONG] Đã lưu: {args.luu}")
        else:
            if not speak(args.text, voice=args.giong):
                safe_print("[!] Không đọc được. Chạy:  python giong_noi_ai.py kiem-tra")
    else:
        p.print_help()
        safe_print("\nBắt đầu ở đây:  python giong_noi_ai.py giay-phep")


if __name__ == "__main__":
    main()
