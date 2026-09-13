"""
giong_nc.py
-----------
TẦNG 2: GIỌNG AI TIẾNG VIỆT — PHI THƯƠNG MẠI NHƯNG ĐƯỢC MỞ MÃ NGUỒN

Dùng file này khi bạn CHẤP NHẬN không kiếm tiền từ sản phẩm, đổi lại
được dùng mô hình tiếng Việt chất lượng cao hơn hẳn Piper.

QUY TẮC VÀNG — đọc kỹ, đây là toàn bộ lý do file này tồn tại:

    Mã nguồn CỦA BẠN  ->  vẫn là MIT/Apache thật sự (open source đúng nghĩa)
    Trọng số MÔ HÌNH  ->  phi thương mại, TUYỆT ĐỐI KHÔNG nhét vào repo
    Người dùng cuối   ->  tự tải weights, tự chấp nhận giấy phép của weights

Làm đúng 3 dòng trên thì repo của bạn VẪN là open source hợp lệ, và bạn
không vi phạm giấy phép phi thương mại của mô hình.

VÌ SAO KHÔNG ĐƯỢC NHÉT WEIGHTS VÀO REPO:
    Định nghĩa Open Source của OSI, điều 6 "No Discrimination Against Fields
    of Endeavor", cấm giấy phép chặn việc dùng thương mại. Nghĩa là CC BY-NC
    KHÔNG PHẢI open source. Nếu bạn đóng gói weights NC vào repo rồi gắn nhãn
    MIT, bạn đang phát hành sai giấy phép. Tách ra thì mọi thứ hợp lệ.

Dùng nhanh:
    python giong_nc.py giay-phep              # bảng giấy phép tầng NC
    python giong_nc.py so-sanh                # tầng thương mại vs tầng NC
    python giong_nc.py dong-y viet-tts        # xác nhận đã đọc giấy phép
    python giong_nc.py cai viet-tts           # in lệnh cài
    python giong_nc.py thu "Xin chào" --mo-hinh mms-vie
    python giong_nc.py notice                 # sinh GIAY_PHEP_MODEL.md cho repo
    python giong_nc.py kiem-tra

Dùng trong code:
    import giong_nc
    giong_nc.speak("Xin chào", mo_hinh="mms-vie")
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile

from platform_utils import safe_print, setup_console

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NC_DIR = os.path.join(BASE_DIR, "giong_nc_model")
CONSENT_FILE = os.path.join(NC_DIR, "DA_DONG_Y.json")


# ============================================================================
# KHO MÔ HÌNH TẦNG NC
#   thuong_mai   = False cho tất cả (đó là điều kiện của tầng này)
#   phat_hanh_lai= có được redistribute / fork / mở mã nguồn không
#   sharealike   = giấy phép có ép lây sang bản phái sinh không
# ============================================================================
NC_MODELS = {
    "viet-tts": {
        "ten": "VietTTS — dangvansam/viet-tts",
        "gp_code": "Apache-2.0",
        "gp_model": "CC BY-NC 4.0",
        "sharealike": False,
        "phat_hanh_lai": True,
        "clone_giong": True,
        "nang": "~1 GB + PyTorch",
        "chat_luong": 4,
        "repo": "https://github.com/dangvansam/viet-tts",
        "hf": "https://huggingface.co/dangvansam/viet-tts",
        "cai": ["pip install viet-tts"],
        "uu": "Cân bằng tốt nhất của tầng này. Code Apache-2.0 nên phần bạn "
              "tích hợp sạch hoàn toàn. Weights CC BY-NC KHÔNG kèm ShareAlike "
              "nên KHÔNG lây sang code của bạn. Có server API kiểu OpenAI.",
        "nhuoc": "Weights train trên dữ liệu in-the-wild (tác giả nói rõ), "
                 "nên vĩnh viễn không thể chuyển sang thương mại.",
        "khuyen": True,
    },
    "vixtts": {
        "ten": "viXTTS — capleaf/viXTTS",
        "gp_code": "MPL-2.0 (repo demo thinhlpg/vixtts-demo)",
        "gp_model": "CPML (Coqui Public Model License)",
        "sharealike": False,
        "phat_hanh_lai": True,
        "clone_giong": True,
        "nang": "1.88 GB + PyTorch",
        "chat_luong": 5,
        "repo": "https://github.com/thinhlpg/vixtts-demo",
        "hf": "https://huggingface.co/capleaf/viXTTS",
        "cai": ["git clone https://github.com/thinhlpg/vixtts-demo",
                "pip install coqui-tts  # bản fork còn bảo trì của idiap"],
        "uu": "Clone giọng tiếng Việt chỉ với 6 giây mẫu. Chất lượng cao nhất "
              "trong nhóm này. Fine-tune từ XTTS-v2.0.3 trên bộ viVoice.",
        "nhuoc": "CPML siết cả ÂM THANH ĐẦU RA, không chỉ weights — audio sinh ra "
                 "cũng phi thương mại. CPML là giấy phép tự chế, không phải CC, "
                 "nên ít án lệ và khó diễn giải hơn. Coqui đóng cửa 01/2024.",
        "khuyen": False,
    },
    "f5-vi": {
        "ten": "F5-TTS-Vietnamese-ViVoice — hynt",
        "gp_code": "MIT (SWivid/F5-TTS)",
        "gp_model": "CC BY-NC-SA 4.0",
        "sharealike": True,
        "phat_hanh_lai": True,
        "clone_giong": True,
        "nang": "~1.4 GB + PyTorch",
        "chat_luong": 5,
        "repo": "https://github.com/nguyenthienhy/F5-TTS-Vietnamese",
        "hf": "https://huggingface.co/hynt/F5-TTS-Vietnamese-ViVoice",
        "cai": ["pip install f5-tts"],
        "uu": "Train trên 1000 giờ tiếng Việt (viVoice + VLSP 2021/2022/2023). "
              "Phát âm tự nhiên, ngắt nghỉ tốt.",
        "nhuoc": "CÓ ShareAlike. Nếu bạn fine-tune tiếp thì mô hình mới BẮT BUỘC "
                 "cũng phải CC BY-NC-SA 4.0. Model card ghi rõ 'non-commercial "
                 "research use only'.",
        "khuyen": False,
    },
    "mms-vie": {
        "ten": "facebook/mms-tts-vie",
        "gp_code": "CC BY-NC 4.0",
        "gp_model": "CC BY-NC 4.0",
        "sharealike": False,
        "phat_hanh_lai": True,
        "clone_giong": False,
        "nang": "~145 MB + PyTorch",
        "chat_luong": 3,
        "repo": "https://github.com/facebookresearch/fairseq/tree/main/examples/mms",
        "hf": "https://huggingface.co/facebook/mms-tts-vie",
        "cai": ["pip install transformers torch"],
        "uu": "Nhẹ nhất tầng NC, chạy CPU được, cài 1 lệnh, không ShareAlike. "
              "File này CHẠY THẲNG ĐƯỢC mô hình đó — xem lệnh 'thu'.",
        "nhuoc": "Giọng máy hơn viet-tts. Không clone giọng. Không đọc số/ngày "
                 "tháng thông minh, nên tự chuẩn hoá văn bản trước.",
        "khuyen": True,
    },
    "vivos-piper": {
        "ten": "Piper + vi_VN-vivos-x_low",
        "gp_code": "MIT (piper-tts 1.2.0)",
        "gp_model": "CC BY-NC-SA 4.0 (bộ VIVOS, ĐH KHTN TP.HCM)",
        "sharealike": True,
        "phat_hanh_lai": True,
        "clone_giong": False,
        "nang": "~20 MB, không cần torch",
        "chat_luong": 2,
        "repo": "https://github.com/rhasspy/piper",
        "hf": "https://huggingface.co/rhasspy/piper-voices/tree/v1.0.0/vi/vi_VN/vivos/x_low",
        "cai": ["python giong_noi_ai.py tai --giong vivos"],
        "uu": "Siêu nhẹ, chạy được trên máy yếu và Raspberry Pi. Cùng engine "
              "Piper nên không phải cài thêm gì nếu bạn đã theo tầng 1.",
        "nhuoc": "Chất lượng x_low nghe rõ là giọng máy. Có ShareAlike.",
        "khuyen": False,
    },
}

DEFAULT_NC = "mms-vie"

# Những thứ VẪN PHẢI TRÁNH kể cả khi đã chấp nhận phi thương mại.
# Lý do: "không rõ giấy phép" TỆ HƠN "phi thương mại".
# NC cho bạn quyền dùng + phát hành lại có điều kiện.
# Không rõ = KHÔNG cấp quyền gì cả = bạn không được phát hành lại, chấm hết.
VAN_PHAI_TRANH = {
    "25hours": (
        "Piper vi_VN-25hours_single-low",
        "Model card ghi giấy phép 'Unknown'. Không có giấy phép nghĩa là KHÔNG "
        "được cấp quyền nào — kể cả phi thương mại. Bạn không thể mở mã nguồn "
        "một dự án phụ thuộc vào nó.",
    ),
    "license-laundering": (
        "Bản fine-tune trên HF tự gắn nhãn 'mit' / 'apache-2.0'",
        "Ví dụ vài bản f5tts-vietnamese-finetuned gắn nhãn MIT trong khi "
        "checkpoint gốc F5-TTS là CC BY-NC. Người upload KHÔNG có quyền nới "
        "lỏng giấy phép của người khác. Nhãn đó vô hiệu — luôn truy ngược lên "
        "mô hình gốc và bộ dữ liệu gốc.",
    ),
    "scraped": (
        "Weights train từ YouTube / sách nói cào về",
        "Không có giấy phép nào ở đầu nguồn. Rủi ro bản quyền thuộc về BẠN, "
        "kể cả khi dự án phi thương mại.",
    ),
}


# ============================================================================
# CỔNG XÁC NHẬN GIẤY PHÉP
# ============================================================================
def _load_consent() -> dict:
    if not os.path.exists(CONSENT_FILE):
        return {}
    try:
        with open(CONSENT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def da_dong_y(mo_hinh: str) -> bool:
    """Người dùng đã xác nhận đọc giấy phép phi thương mại của mô hình chưa."""
    return bool(_load_consent().get(mo_hinh))


def dong_y(mo_hinh: str) -> bool:
    """Ghi nhận việc chấp nhận giấy phép phi thương mại."""
    if mo_hinh not in NC_MODELS:
        safe_print(f"[LỖI] Không có mô hình '{mo_hinh}'. Có: {', '.join(NC_MODELS)}")
        return False

    m = NC_MODELS[mo_hinh]
    safe_print("")
    safe_print("=" * 74)
    safe_print(f"  XÁC NHẬN GIẤY PHÉP — {m['ten']}")
    safe_print("=" * 74)
    safe_print(f"  Giấy phép code   : {m['gp_code']}")
    safe_print(f"  Giấy phép weights: {m['gp_model']}")
    safe_print("")
    safe_print("  Khi bấm đồng ý, bạn xác nhận HIỂU RẰNG:")
    safe_print("    1. KHÔNG được dùng mô hình này để tạo doanh thu dưới mọi hình")
    safe_print("       thức: bán app, SaaS, quảng cáo, làm thuê cho khách.")
    safe_print("    2. Repo của bạn vẫn mở mã nguồn được, NHƯNG không được đóng gói")
    safe_print("       file weights vào repo. Để người dùng tự tải.")
    safe_print("    3. Phải ghi công tác giả mô hình trong README/NOTICE.")
    if m["sharealike"]:
        safe_print("    4. CÓ ShareAlike: mọi bản fine-tune của bạn cũng phải mang")
        safe_print("       đúng giấy phép này.")
    safe_print("")
    safe_print(f"  Đọc bản gốc: {m['hf']}")
    safe_print("=" * 74)

    try:
        tra_loi = input("  Bạn đã đọc và đồng ý? (go/K): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        safe_print("\n[HUỶ]")
        return False

    if tra_loi not in ("go", "g", "y", "yes", "co", "có"):
        safe_print("[HUỶ] Chưa ghi nhận đồng ý.")
        return False

    os.makedirs(NC_DIR, exist_ok=True)
    data = _load_consent()
    data[mo_hinh] = {
        "giay_phep": m["gp_model"],
        "nguon": m["hf"],
        "phi_thuong_mai": True,
    }
    with open(CONSENT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    safe_print(f"[OK] Đã ghi nhận. Chạy tiếp: python giong_nc.py cai {mo_hinh}")
    return True


# ============================================================================
# CHẠY THẬT: facebook/mms-tts-vie (mô hình NC nhẹ nhất, cài 1 lệnh)
# ============================================================================
def _write_wav(path: str, sound, sample_rate: int) -> bool:
    """Ghi mảng float32 [-1, 1] ra file WAV 16-bit mono."""
    try:
        import wave as _wave

        import numpy as np
    except ImportError:
        safe_print("[LỖI] Thiếu numpy. Cài: pip install numpy")
        return False

    data = np.clip(np.asarray(sound, dtype="float32").reshape(-1), -1.0, 1.0)
    pcm = (data * 32767.0).astype("<i2")
    with _wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return True


_mms_cache = {}


def _load_mms():
    """Nạp facebook/mms-tts-vie. Tải ~145MB ở lần chạy đầu."""
    if _mms_cache:
        return _mms_cache.get("model"), _mms_cache.get("tok")

    try:
        from transformers import AutoTokenizer, VitsModel
    except ImportError:
        safe_print("[LỖI] Chưa cài transformers. Cài: pip install transformers torch")
        return None, None

    try:
        model = VitsModel.from_pretrained("facebook/mms-tts-vie")
        tok = AutoTokenizer.from_pretrained("facebook/mms-tts-vie")
    except Exception as e:
        safe_print(f"[LỖI] Không nạp được mms-tts-vie: {e}")
        return None, None

    _mms_cache["model"] = model
    _mms_cache["tok"] = tok
    return model, tok


def synth_mms(text: str, out_path: str) -> bool:
    """Tổng hợp giọng bằng facebook/mms-tts-vie, ghi ra file WAV. v7.0: tự tạo thư mục cha."""
    if not text or not text.strip():
        return False
    from pathlib import Path

    try:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.debug("Không tạo được thư mục cha cho %s: %s", out_path, e)
    if not da_dong_y("mms-vie"):
        safe_print("[CHẶN] Chưa xác nhận giấy phép phi thương mại.")
        safe_print("       Chạy: python giong_nc.py dong-y mms-vie")
        return False

    model, tok = _load_mms()
    if model is None:
        return False

    try:
        import torch
    except ImportError:
        safe_print("[LỖI] Chưa cài torch. Cài: pip install torch")
        return False

    try:
        inputs = tok(text, return_tensors="pt")
        with torch.no_grad():
            out = model(**inputs).waveform
        return _write_wav(out_path, out.cpu().numpy(), model.config.sampling_rate)
    except Exception as e:
        safe_print(f"[LỖI] Tổng hợp thất bại: {e}")
        return False


def speak(text: str, mo_hinh: str = DEFAULT_NC) -> bool:
    """Đọc to một câu bằng mô hình tầng NC. Hiện chạy thẳng được 'mms-vie'."""
    if not text or not text.strip():
        return False

    if mo_hinh != "mms-vie":
        safe_print(f"[!] '{mo_hinh}' cần cài riêng, file này không gọi trực tiếp.")
        safe_print(f"    Xem hướng dẫn: python giong_nc.py cai {mo_hinh}")
        return False

    tmp = os.path.join(tempfile.gettempdir(), "vi_nc_tts.wav")
    if not synth_mms(text, tmp):
        return False

    try:
        import tts as _tts

        _tts._play_audio(tmp)
        return True
    except Exception as e:
        safe_print(f"[LỖI] Không phát được âm thanh: {e}")
        return False


def is_available(mo_hinh: str = DEFAULT_NC) -> bool:
    """Mô hình NC này đã sẵn sàng dùng chưa."""
    if not da_dong_y(mo_hinh):
        return False
    if mo_hinh != "mms-vie":
        return False
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401

        return True
    except ImportError:
        return False


# ============================================================================
# SINH FILE GIẤY PHÉP CHO REPO CỦA BẠN
# ============================================================================
def tao_notice(mo_hinh: str | None = None, out_path: str | None = None) -> str:
    """Sinh GIAY_PHEP_MODEL.md — file bạn PHẢI có khi mở mã nguồn dự án."""
    chon = [mo_hinh] if mo_hinh else sorted(_load_consent().keys())
    chon = [m for m in chon if m in NC_MODELS]
    if not chon:
        chon = [DEFAULT_NC]

    d = []
    d.append("# Giấy phép mô hình AI được sử dụng")
    d.append("")
    d.append("> **Đọc trước khi dùng dự án này.**")
    d.append(">")
    d.append("> Mã nguồn trong repo này là mã nguồn mở. Các **mô hình giọng nói**")
    d.append("> mà nó gọi tới thì **không**. Đó là hai giấy phép tách rời nhau.")
    d.append("")
    d.append("## Mã nguồn")
    d.append("")
    d.append("Toàn bộ code trong repo: giấy phép MIT. Xem `LICENSE`.")
    d.append("")
    d.append("## Mô hình giọng nói")
    d.append("")
    d.append("Repo này **không chứa** file trọng số mô hình. Script sẽ tải về khi")
    d.append("bạn chạy lần đầu. Khi tải, bạn chấp nhận giấy phép của mô hình đó:")
    d.append("")

    for key in chon:
        m = NC_MODELS[key]
        d.append(f"### {m['ten']}")
        d.append("")
        d.append(f"- Nguồn: {m['hf']}")
        d.append(f"- Giấy phép code: `{m['gp_code']}`")
        d.append(f"- Giấy phép trọng số: `{m['gp_model']}`")
        d.append("- **Phi thương mại.** Không được dùng để tạo doanh thu.")
        if m["sharealike"]:
            d.append("- **ShareAlike.** Bản fine-tune phải giữ nguyên giấy phép này.")
        d.append("")

    d.append("## Điều này nghĩa là gì với bạn")
    d.append("")
    d.append("| Bạn muốn | Được phép |")
    d.append("| --- | --- |")
    d.append("| Đọc, sửa, fork mã nguồn | Có |")
    d.append("| Dùng cho cá nhân, học tập, nghiên cứu | Có |")
    d.append("| Đăng bản sửa đổi lên GitHub | Có |")
    d.append("| Bán app, chạy SaaS, gắn quảng cáo | **Không** |")
    d.append("| Dùng audio sinh ra trong video kiếm tiền | **Không** |")
    d.append("")
    d.append("Muốn thương mại: thay bằng Piper + `vi_VN-vais1000-medium` (CC BY 4.0),")
    d.append("hoặc tự thu giọng rồi fine-tune. Xem `giong_noi_ai.py`.")
    d.append("")
    d.append("## Ghi công")
    d.append("")
    for key in chon:
        m = NC_MODELS[key]
        d.append(f"- {m['ten']} — {m['gp_model']} — {m['hf']}")
    d.append("")
    d.append("---")
    d.append("")
    d.append("*Đây là tóm tắt kỹ thuật, không phải tư vấn pháp lý. Hãy đọc bản")
    d.append("giấy phép gốc tại link ở trên trước khi phát hành.*")
    d.append("")

    noi_dung = "\n".join(d)
    out_path = out_path or os.path.join(BASE_DIR, "GIAY_PHEP_MODEL.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(noi_dung)
    safe_print(f"[OK] Đã ghi {out_path}")
    safe_print("     Commit file này kèm repo khi bạn public lên GitHub.")
    return out_path


# ============================================================================
# IN BẢNG
# ============================================================================
def in_giay_phep():
    safe_print("")
    safe_print("=" * 78)
    safe_print("  TẦNG NC — PHI THƯƠNG MẠI, NHƯNG ĐƯỢC MỞ MÃ NGUỒN")
    safe_print("=" * 78)
    safe_print("")
    safe_print("  Nguyên tắc: code của bạn MIT thật, weights để người dùng tự tải.")
    safe_print("  Đừng bao giờ commit file .onnx/.pt/.safetensors phi thương mại.")
    safe_print("")

    khuyen = [k for k, v in NC_MODELS.items() if v["khuyen"]]
    khac = [k for k, v in NC_MODELS.items() if not v["khuyen"]]

    safe_print("### NÊN DÙNG ###")
    safe_print("")
    for key in khuyen:
        _in_mo_hinh(key)

    safe_print("### DÙNG ĐƯỢC, NHƯNG CÂN NHẮC ###")
    safe_print("")
    for key in khac:
        _in_mo_hinh(key)

    safe_print("### VẪN PHẢI TRÁNH (kể cả khi chấp nhận phi thương mại) ###")
    safe_print("")
    for _, (ten, ly_do) in VAN_PHAI_TRANH.items():
        safe_print(f"  [X] {ten}")
        for dong in _wrap(ly_do, 68):
            safe_print(f"      {dong}")
        safe_print("")

    safe_print("=" * 78)
    safe_print("  Bước tiếp: python giong_nc.py dong-y <mô hình>")
    safe_print("=" * 78)
    safe_print("")


def _in_mo_hinh(key: str):
    m = NC_MODELS[key]
    sao = "*" * m["chat_luong"] + "." * (5 - m["chat_luong"])
    safe_print(f"  [{key}]  {m['ten']}")
    safe_print(f"       Chất lượng : {sao}")
    safe_print(f"       Code       : {m['gp_code']}")
    safe_print(f"       Weights    : {m['gp_model']}")
    safe_print(f"       ShareAlike : {'CÓ — cẩn thận' if m['sharealike'] else 'không'}")
    safe_print(f"       Clone giọng: {'có' if m['clone_giong'] else 'không'}")
    safe_print(f"       Dung lượng : {m['nang']}")
    for dong in _wrap("Ưu: " + m["uu"], 66):
        safe_print(f"       {dong}")
    for dong in _wrap("Nhược: " + m["nhuoc"], 66):
        safe_print(f"       {dong}")
    safe_print("")


def _wrap(text: str, width: int):
    tu = text.split()
    dong, cur = [], ""
    for t in tu:
        if len(cur) + len(t) + 1 > width:
            dong.append(cur)
            cur = t
        else:
            cur = f"{cur} {t}".strip()
    if cur:
        dong.append(cur)
    return dong


def so_sanh():
    safe_print("")
    safe_print("=" * 78)
    safe_print("  CHỌN TẦNG NÀO?")
    safe_print("=" * 78)
    safe_print("")
    safe_print("  TẦNG 1 — giong_noi_ai.py   (thương mại + mã nguồn mở)")
    safe_print("     Piper + vais1000, CC BY 4.0")
    safe_print("     + Bán được, mở mã nguồn được, 63MB, chạy CPU")
    safe_print("     + Là open source ĐÚNG NGHĨA theo định nghĩa OSI")
    safe_print("     - Giọng ở mức khá, không clone được giọng")
    safe_print("")
    safe_print("  TẦNG 2 — giong_nc.py       (phi thương mại + mã nguồn mở)")
    safe_print("     viet-tts / viXTTS / F5-TTS-vi / mms-tts-vie")
    safe_print("     + Giọng tự nhiên hơn hẳn, có clone giọng")
    safe_print("     + Code của bạn VẪN là MIT thật sự")
    safe_print("     - Vĩnh viễn không bán được")
    safe_print("     - Người fork repo của bạn cũng không bán được")
    safe_print("")
    safe_print("  DÙNG CẢ HAI — cách nhiều dự án thật đang làm:")
    safe_print("     Mặc định tầng 1 (ai cũng dùng thoải mái).")
    safe_print("     Tầng 2 là tuỳ chọn, bật bằng cờ, kèm cảnh báo giấy phép.")
    safe_print("     -> Repo mở, người dùng tự chọn mức rủi ro của họ.")
    safe_print("")
    safe_print("=" * 78)
    safe_print("")


def in_cai(mo_hinh: str):
    if mo_hinh not in NC_MODELS:
        safe_print(f"[LỖI] Không có '{mo_hinh}'. Có: {', '.join(NC_MODELS)}")
        return
    m = NC_MODELS[mo_hinh]
    safe_print("")
    safe_print("=" * 74)
    safe_print(f"  CÀI {m['ten']}")
    safe_print("=" * 74)
    if not da_dong_y(mo_hinh):
        safe_print("")
        safe_print("  [!] Bạn chưa xác nhận giấy phép.")
        safe_print(f"      Chạy trước: python giong_nc.py dong-y {mo_hinh}")
    safe_print("")
    safe_print("  Lệnh cài:")
    for c in m["cai"]:
        safe_print(f"      {c}")
    safe_print("")
    safe_print(f"  Repo    : {m['repo']}")
    safe_print(f"  Weights : {m['hf']}")
    safe_print("")
    safe_print("  Sau khi cài, thêm vào .gitignore của bạn:")
    safe_print("      giong_nc_model/")
    safe_print("      *.onnx")
    safe_print("      *.pt")
    safe_print("      *.safetensors")
    safe_print("  Rồi sinh file giấy phép: python giong_nc.py notice")
    safe_print("=" * 74)
    safe_print("")


def kiem_tra():
    safe_print("")
    safe_print("=" * 74)
    safe_print("  KIỂM TRA TẦNG NC")
    safe_print("=" * 74)

    for ten, mod in (("torch", "torch"), ("transformers", "transformers"),
                     ("numpy", "numpy")):
        try:
            __import__(mod)
            safe_print(f"  [OK]     {ten}")
        except ImportError:
            safe_print(f"  [THIẾU]  {ten}")

    safe_print("")
    consent = _load_consent()
    for key in NC_MODELS:
        dau = "đã đồng ý" if key in consent else "chưa đồng ý"
        safe_print(f"  {key:<14} {dau}")

    safe_print("")
    if is_available("mms-vie"):
        safe_print('  Sẵn sàng: python giong_nc.py thu "Xin chào"')
    else:
        safe_print("  Chưa chạy được. Làm theo thứ tự:")
        safe_print("      python giong_nc.py giay-phep")
        safe_print("      python giong_nc.py dong-y mms-vie")
        safe_print("      pip install transformers torch numpy")
    safe_print("=" * 74)
    safe_print("")


# ============================================================================
# CLI
# ============================================================================
def main():
    setup_console()
    p = argparse.ArgumentParser(
        description="Giọng AI tiếng Việt — tầng phi thương mại, mở mã nguồn"
    )
    sub = p.add_subparsers(dest="lenh")

    sub.add_parser("giay-phep", help="bảng giấy phép tầng NC")
    sub.add_parser("so-sanh", help="so tầng thương mại vs tầng NC")
    sub.add_parser("kiem-tra", help="kiểm tra đã cài xong chưa")

    p_dy = sub.add_parser("dong-y", help="xác nhận đã đọc giấy phép")
    p_dy.add_argument("mo_hinh")

    p_cai = sub.add_parser("cai", help="in lệnh cài mô hình")
    p_cai.add_argument("mo_hinh")

    p_thu = sub.add_parser("thu", help="đọc thử một câu")
    p_thu.add_argument("text", nargs="?", default="Xin chào, đây là giọng AI tiếng Việt.")
    p_thu.add_argument("--mo-hinh", dest="mo_hinh", default=DEFAULT_NC)
    p_thu.add_argument("--luu", default=None, help="lưu ra file WAV thay vì phát")

    p_nt = sub.add_parser("notice", help="sinh GIAY_PHEP_MODEL.md cho repo")
    p_nt.add_argument("--mo-hinh", dest="mo_hinh", default=None)

    args = p.parse_args()

    if args.lenh == "giay-phep" or args.lenh is None:
        in_giay_phep()
    elif args.lenh == "so-sanh":
        so_sanh()
    elif args.lenh == "kiem-tra":
        kiem_tra()
    elif args.lenh == "dong-y":
        dong_y(args.mo_hinh)
    elif args.lenh == "cai":
        in_cai(args.mo_hinh)
    elif args.lenh == "notice":
        tao_notice(args.mo_hinh)
    elif args.lenh == "thu":
        if args.luu:
            ok = synth_mms(args.text, args.luu)
            if ok:
                safe_print(f"[OK] Đã lưu {args.luu}")
        else:
            speak(args.text, args.mo_hinh)


if __name__ == "__main__":
    main()
