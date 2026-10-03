"""Test cho phần STT của bản v7.9 - tải lại model và báo lỗi thật.

Máy CI không có `transformers`/`torch`/`speech_recognition`/`sounddevice`, nên
các test ở đây **không** tải model thật: chúng dựng hậu bối giả cho đúng những
chỗ v7.9 sửa, rồi kiểm hành vi. Đây là điểm yếu thật của bộ test này và được nói
thẳng thay vì giấu: nếu `_load_model` đổi tên biến hay đổi số lần thử, test vẫn
xanh vì hậu bối giả không dính vào mấy chi tiết đó.

Ba lỗi tìm được, cùng họ "lỗi bị nuốt rồi biến thành hành vi sai":

  1. Một lần tải model hỏng thì `_use_google` bị ghim VĨNH VIỄN. Lỗi tải thường
     là lỗi TẠM THỜI (mạng chập chờn lúc tải ~1GB, đĩa bận một lát) - bỏ model
     offline vì một lần thất bại là mất nhầm, và người dùng không hề hay biết
     âm thanh của mình đã nằm trên máy người khác.
  2. `_google_from_array` / `_google_from_file` nuốt MỌI lỗi vào `return ""`.
     Người dùng nghe im, tưởng mình nói không ra, trong khi thật ra là mất mạng
     hoặc hết hạn mức. Hai chuyện đó cần hai cách xử lý khác nhau (nói lại vs
     gõ tay) - và hàm `listen_once` ở tầng trên vốn đã phân biệt được.
  3. Lỗi giải mã ở đường offline nổ thẳng ra ngoài và SẬT cả câu lệnh, trong
     khi đường Google cùng tình huống trả "" êm. Không công bằng.
"""
import sys
import types
from pathlib import Path

import pytest

PKG_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = PKG_DIR.parent
sys.path.insert(0, str(PKG_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class FakeRequestError(Exception):
    """Giả lỗi mạng của `speech_recognition.RequestError`."""


@pytest.fixture
def fake_sr(monkeypatch):
    """Cài `speech_recognition` giả: đủ cho import, và báo lỗi theo kịch bản."""
    calls = {"recognize": 0, "mode": "ok"}

    class UnknownValueError(Exception):
        pass

    class Recognizer:
        def recognize_google(self, audio, language=None):
            calls["recognize"] += 1
            if calls["mode"] == "unknown":
                raise UnknownValueError("không nghe rõ")
            if calls["mode"] == "error":
                raise FakeRequestError("mất mạng")
            return "mở nhạc"

    class AudioFile:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def record(self, source):
            return b"audio"

    mod = types.ModuleType("speech_recognition")
    mod.Recognizer = Recognizer
    mod.AudioFile = AudioFile
    mod.UnknownValueError = UnknownValueError
    mod.RequestError = FakeRequestError
    monkeypatch.setitem(sys.modules, "speech_recognition", mod)
    return calls


@pytest.fixture
def broken_transformers(monkeypatch):
    """Cài `transformers`/`torch` giả, cố tình làm `pipeline()` nổ."""
    attempts = {"n": 0}

    def fake_pipeline(*a, **k):
        attempts["n"] += 1
        raise OSError("hết mạng lúc tải model")

    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    tf = types.ModuleType("transformers")
    tf.pipeline = fake_pipeline
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", tf)
    return attempts


@pytest.fixture
def fake_numpy(monkeypatch):
    """`numpy` giả: máy CI không cài, mà `transcribe_array` cần `np.float32`."""
    np = types.ModuleType("numpy")
    np.float32 = "float32"
    monkeypatch.setitem(sys.modules, "numpy", np)
    return np


# ---------------------------------------------------------------------------
# 1. Tải lại thay vì ghim vĩnh viễn.
# ---------------------------------------------------------------------------
def test_tai_lai_truoc_khi_bo_model_offline(broken_transformers, fake_sr):
    """Lần tải đầu hỏng KHÔNG được kết luận là hỏng vĩnh viễn."""
    import stt

    st = stt.STT()
    st._load_model()
    assert broken_transformers["n"] == stt._MAX_MODEL_LOAD_ATTEMPTS, \
        "phải thử lại trước khi bỏ model offline"
    assert broken_transformers["n"] > 1, \
        "một lỗi tạm thời không được phải đổi cả phiên sang STT đám mây"
    assert st._use_google is True


def test_het_ca_hai_duong_thi_bao_ro(monkeypatch, broken_transformers):
    """Không còn đường nào thì phải nói TO, không được im lặng."""
    import stt

    monkeypatch.setitem(sys.modules, "speech_recognition", None)
    st = stt.STT()
    with pytest.raises(RuntimeError):
        st._load_model()


def test_tai_lai_vao_thanh_cong_thi_khong_bo_sang_google(monkeypatch, fake_sr):
    """Lần thứ hai thành công thì giữ model offline - đừng hạ cấp."""
    import stt

    attempts = {"n": 0}

    def fake_pipeline(*a, **k):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise OSError("hết mạng lúc tải model")
        return lambda audio: {"text": "mở nhạc"}

    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    tf = types.ModuleType("transformers")
    tf.pipeline = fake_pipeline
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", tf)

    st = stt.STT()
    st._load_model()
    assert attempts["n"] == 2
    assert st._use_google is False, "tải lại được thì không có lý do bỏ model"
    assert st._pipe is not None


def test_da_co_model_thi_khong_tai_lai(broken_transformers):
    """Không tải lại ở mỗi câu nói (tải 1GB mỗi lần thì vô dụng)."""
    import stt

    st = stt.STT()
    st._pipe = lambda audio: {"text": "x"}
    st._load_model()
    st._load_model()
    assert broken_transformers["n"] == 0


# ---------------------------------------------------------------------------
# 2. Phân biệt "nói không rõ" với "mất mạng".
# ---------------------------------------------------------------------------
def test_mat_mang_thi_bao_cho_nguoi_dung(fake_sr, capsys):
    """Bản cũ nuốt lỗi thành "" - người dùng tưởng mình nói không ra."""
    import stt

    st = stt.STT()
    st._use_google = True
    fake_sr["mode"] = "error"
    assert st._google_transcribe(b"audio") == ""
    out = capsys.readouterr().out
    assert "kết nối" in out and "mạng" in out


def test_noi_khong_roi_thi_bao_rieng(fake_sr, capsys):
    """Nói không rõ và mất mạng là hai chuyện: một cái thì nói lại, cái kia
    thì gõ tay. Gộp chung thì người dùng nói lại mãi mà không bao giờ được."""
    import stt

    st = stt.STT()
    st._use_google = True
    fake_sr["mode"] = "unknown"
    assert st._google_transcribe(b"audio") == ""
    out = capsys.readouterr().out
    assert "nói lại" in out
    assert "mạng" not in out


def test_google_hong_lien_tiep_khong_in_spam(fake_sr, capsys):
    """Chỉ cảnh báo lần đầu và mỗi 10 lần - in mỗi câu là spam trong lúc dùng."""
    import stt

    st = stt.STT()
    st._use_google = True
    fake_sr["mode"] = "error"
    for _ in range(12):
        st._google_transcribe(b"audio")
    assert st._google_failures == 12
    out = capsys.readouterr().out
    assert out.count("Lỗi kết nối dịch vụ STT") == 2, \
        "12 lần hỏng liên tiếp mà in 12 dòng là spam, không phải thông tin"


def test_nghe_lai_duoc_thi_bien_so_hoi_reset(fake_sr, capsys):
    import stt

    st = stt.STT()
    st._use_google = True
    fake_sr["mode"] = "error"
    st._google_transcribe(b"audio")
    assert st._google_failures == 1
    fake_sr["mode"] = "ok"
    assert st._google_transcribe(b"audio") == "mở nhạc"
    assert st._google_failures == 0


# ---------------------------------------------------------------------------
# 3. Lỗi giải mã không được sập cả câu lệnh.
# ---------------------------------------------------------------------------
def test_loi_giai_ma_offline_khong_lam_sap_cau_lenh(fake_numpy, tmp_path, capsys):
    """Đường Google lỗi thì trả "" êm; đường offline phải công bằng."""
    import stt

    class Boom:
        def __call__(self, audio):
            raise RuntimeError("GPU tràn bộ nhớ")

    st = stt.STT()
    st._pipe = Boom()

    class FakeArray:
        def astype(self, _t):
            return self

        def __truediv__(self, _o):
            return self

    assert st.transcribe_array(FakeArray()) == ""
    assert "Lỗi" in capsys.readouterr().out
    assert st.transcribe_file(tmp_path / "audio.wav") == ""


def test_duong_offline_that_thi_van_tra_ve_chuoi(fake_numpy, tmp_path):
    import stt

    st = stt.STT()
    st._pipe = lambda audio: {"text": "  mở nhạc  "}
    assert st.transcribe_file(tmp_path / "audio.wav") == "mở nhạc"
