# -*- coding: utf-8 -*-
"""
train_tts.py
------------
FILE HUẤN LUYỆN "MÁY HỌC NÓI" (Text-To-Speech)

Có 3 MỨC ĐỘ, bạn chọn theo điều kiện máy:

  MỨC 1 – DÙNG NGAY (0 phút, không cần GPU)
      Tạo sẵn kho giọng cho các câu trợ lý hay nói ("Đang mở Chrome"...)
      -> phản hồi tức thì, không giật, không cần mạng khi chạy.
          python train_tts.py cache

  MỨC 2 – THU GIỌNG CỦA CHÍNH BẠN (30-60 phút thu âm)
      Ghi âm bạn đọc các câu mẫu -> tạo dataset chuẩn LJSpeech
      để sau này huấn luyện giọng giống hệt bạn.
          python train_tts.py record

  MỨC 3 – HUẤN LUYỆN GIỌNG THẬT BẰNG DATASET VietTTS (cần GPU, nhiều giờ)
      Chuẩn bị dataset VietTTS của NTT123 về đúng định dạng để train.
          python train_tts.py prepare --zip infore.zip
      Sau đó train trên Google Colab: mở file train_tts_colab.ipynb

Kiểm tra giọng hiện tại:
          python train_tts.py check
"""

import argparse
import csv
import logging
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VOICE_CACHE_DIR = os.path.join(BASE_DIR, "voice_cache")
MY_VOICE_DIR = os.path.join(BASE_DIR, "my_voice")
TTS_DATA_DIR = os.path.join(BASE_DIR, "tts_data")

VIETTTS_URL = (
    "https://github.com/NTT123/Vietnamese-Text-To-Speech-Dataset"
    "/releases/download/v1/infore.zip"
)


# ============================================================================
# MỨC 1: TẠO KHO GIỌNG SẴN (VOICE CACHE)
# ============================================================================
# Những câu trợ lý nói đi nói lại -> tạo sẵn file mp3 một lần, sau đó phát lại
COMMON_PHRASES = [
    "Xin chào, tôi đã sẵn sàng nhận lệnh",
    "Vâng, tôi làm ngay",
    "Đã xong",
    "Đang mở trình duyệt",
    "Đang mở ứng dụng",
    "Đang mở file",
    "Đang tìm kiếm giúp bạn",
    "Đang phát nhạc",
    "Tôi đã đặt nhắc nhở cho bạn",
    "Đến giờ rồi bạn ơi",
    "Xin lỗi, tôi chưa hiểu ý bạn",
    "Bạn muốn nói lại rõ hơn không",
    "Tôi không tìm thấy ứng dụng này trên máy",
    "Bạn có chắc muốn tắt máy không",
    "Đã huỷ lệnh",
    "Tạm biệt bạn nhé",
]


def build_voice_cache(lang: str = "vi", slow: bool = False):
    """
    Dùng gTTS tạo sẵn file mp3 cho các câu hay dùng (cần internet một lần).
    Sau khi tạo xong, tts.py sẽ ưu tiên phát file có sẵn -> nhanh và offline.
    """
    try:
        from gtts import gTTS
    except ImportError:
        print("Chưa có gTTS. Cài bằng lệnh:  pip install gTTS")
        return

    os.makedirs(VOICE_CACHE_DIR, exist_ok=True)
    index_path = os.path.join(VOICE_CACHE_DIR, "index.csv")

    rows = []
    for i, phrase in enumerate(COMMON_PHRASES, 1):
        filename = f"phrase_{i:03d}.mp3"
        path = os.path.join(VOICE_CACHE_DIR, filename)
        if not os.path.exists(path):
            print(f"  [{i:>2}/{len(COMMON_PHRASES)}] Đang tạo: {phrase}")
            gTTS(text=phrase, lang=lang, slow=slow).save(path)
        rows.append([phrase, filename])

    with open(index_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["text", "file"])
        writer.writerows(rows)

    print(f"\nXong! {len(rows)} câu đã có giọng sẵn trong: {VOICE_CACHE_DIR}")
    print("tts.py sẽ tự động dùng kho này, không cần sửa gì thêm.")


# ============================================================================
# MỨC 2: THU GIỌNG CỦA CHÍNH BẠN
# ============================================================================
def _recording_sentences(n: int = 100):
    """Lấy câu để bạn đọc: gồm câu trợ lý + câu trong dataset (đủ âm tiết)."""
    sentences = list(COMMON_PHRASES)
    try:
        from dataset import get_dataset_as_lists
        texts, _ = get_dataset_as_lists()
        step = max(1, len(texts) // max(1, n - len(sentences)))
        sentences += list(texts)[::step]
    except Exception:
        logging.getLogger(__name__).warning(
            "Khong doc duoc dataset de bo sung cau mau", exc_info=True)
    return sentences[:n]


def record_my_voice(count: int = 50, samplerate: int = 22050):
    """
    Thu âm bạn đọc từng câu -> tạo dataset chuẩn LJSpeech:
        my_voice/wavs/0001.wav ...
        my_voice/metadata.csv   (định dạng: id|câu|câu)

    Cần:  pip install sounddevice scipy
    Mẹo thu cho hay: phòng yên tĩnh, mic cách miệng 15-20cm, đọc đều giọng.
    """
    try:
        import sounddevice as sd
        from scipy.io.wavfile import write as wav_write
    except ImportError:
        print("Thiếu thư viện. Cài bằng lệnh:  pip install sounddevice scipy")
        return

    wav_dir = os.path.join(MY_VOICE_DIR, "wavs")
    os.makedirs(wav_dir, exist_ok=True)
    meta_path = os.path.join(MY_VOICE_DIR, "metadata.csv")

    sentences = _recording_sentences(count)
    print("=" * 66)
    print(f"THU GIỌNG CỦA BẠN – {len(sentences)} câu")
    print("=" * 66)
    print("Enter để bắt đầu thu, Enter lần nữa để dừng. Gõ 's' để bỏ qua câu.")
    print("Gõ 'q' để dừng hẳn (dữ liệu đã thu vẫn được giữ).\n")

    rows = []
    for i, sentence in enumerate(sentences, 1):
        print(f"[{i}/{len(sentences)}] Đọc câu: \"{sentence}\"")
        cmd = input("   > ").strip().lower()
        if cmd == "q":
            break
        if cmd == "s":
            continue

        print("   Đang thu... (Enter để dừng)")
        frames = sd.rec(int(20 * samplerate), samplerate=samplerate,
                        channels=1, dtype="int16")
        input()
        sd.stop()

        file_id = f"{i:04d}"
        wav_write(os.path.join(wav_dir, f"{file_id}.wav"), samplerate, frames)
        rows.append([file_id, sentence, sentence])
        print("   Đã lưu.\n")

    with open(meta_path, "w", newline="", encoding="utf-8") as f:
        for row in rows:
            f.write("|".join(row) + "\n")

    print(f"\nXong! {len(rows)} câu đã thu tại: {MY_VOICE_DIR}")
    print("Bước tiếp: nén thư mục my_voice, tải lên Colab và finetune theo")
    print("hướng dẫn trong train_tts_colab.ipynb (cần GPU).")


# ============================================================================
# MỨC 3: CHUẨN BỊ DATASET VietTTS
# ============================================================================
def prepare_viettts(zip_path: str = None):
    """
    Giải nén và kiểm tra dataset VietTTS (NTT123), tạo metadata.csv chuẩn.

    Dataset: https://github.com/NTT123/Vietnamese-Text-To-Speech-Dataset
    Giấy phép: chỉ dùng cho mục đích THỬ NGHIỆM và GIÁO DỤC.
    """
    import zipfile

    os.makedirs(TTS_DATA_DIR, exist_ok=True)

    if zip_path and os.path.exists(zip_path):
        print(f"Đang giải nén {zip_path} ...")
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(TTS_DATA_DIR)
        print("Giải nén xong.")
    else:
        print("Chưa có file zip. Tải dataset về trước bằng một trong hai cách:")
        print(f"   1. Mở trình duyệt: {VIETTTS_URL}")
        print(f"   2. Hoặc dòng lệnh:  curl -L -o infore.zip {VIETTTS_URL}")
        print("Sau đó chạy lại: python train_tts.py prepare --zip infore.zip")
        return

    # Thống kê nhanh
    wavs, texts = [], []
    for dirpath, _, filenames in os.walk(TTS_DATA_DIR):
        for name in filenames:
            if name.lower().endswith(".wav"):
                wavs.append(os.path.join(dirpath, name))
            elif name.lower().endswith((".txt", ".csv")):
                texts.append(os.path.join(dirpath, name))

    print(f"\nTìm thấy {len(wavs)} file audio, {len(texts)} file văn bản.")
    if texts:
        print("File văn bản mẫu:", texts[0])
    print("\nBƯỚC TIẾP THEO (cần GPU – nên làm trên Google Colab):")
    print("   1. Mở file train_tts_colab.ipynb bằng Google Colab")
    print("   2. Runtime > Change runtime type > T4 GPU")
    print("   3. Chạy lần lượt các cell")
    print("   4. Tải model về, đặt vào thư mục này rồi sửa tts.py")


# ============================================================================
# KIỂM TRA GIỌNG HIỆN TẠI
# ============================================================================
def check_voice():
    try:
        import tts
    except ImportError:
        print("Không tìm thấy tts.py trong thư mục này.")
        return

    print("Engine khả dụng:", ", ".join(tts.available_engines()))
    has_cache = os.path.isdir(VOICE_CACHE_DIR)
    print("Kho giọng sẵn :", "có" if has_cache else "chưa tạo (python train_tts.py cache)")
    print("Giọng thu riêng:", "có" if os.path.isdir(MY_VOICE_DIR) else "chưa thu")
    print("\nĐang thử nói một câu...")
    tts.speak("Xin chào, đây là giọng nói hiện tại của trợ lý")


# ============================================================================
# CLI
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description="Cho máy học nói tiếng Việt")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("check", help="kiểm tra giọng nói hiện tại")
    sub.add_parser("cache", help="tạo sẵn kho giọng cho câu hay dùng")

    p_rec = sub.add_parser("record", help="thu giọng của chính bạn")
    p_rec.add_argument("--count", type=int, default=50, help="số câu cần đọc")

    p_prep = sub.add_parser("prepare", help="chuẩn bị dataset VietTTS để train")
    p_prep.add_argument("--zip", dest="zip_path", default=None, help="đường dẫn infore.zip")

    args = parser.parse_args()

    if args.command == "cache":
        build_voice_cache()
    elif args.command == "record":
        record_my_voice(count=args.count)
    elif args.command == "prepare":
        prepare_viettts(args.zip_path)
    elif args.command == "check":
        check_voice()
    else:
        parser.print_help()
        print("\nGỢI Ý: bắt đầu bằng  python train_tts.py check")


if __name__ == "__main__":
    main()
