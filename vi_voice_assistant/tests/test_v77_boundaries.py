"""Test cho bản v7.7 - biên cuối cùng của model, nhắc nhở và file học.

Vòng này soi những chỗ CHƯA bị audit ở v7.5-v7.6 và tìm được bốn lỗi cùng họ:

  1. `lite_model.predict_proba("mở youtube")` lặp qua TỪNG KÝ TỰ: trả về 11 hàng
     dự đoán trông rất hợp lệ trong khi model đang chấm chữ "ở", "y" như câu nói
     đầy đủ - sai mà không báo gì;
  2. `cancel_reminder(123)` nổ `AttributeError: 'int' object has no attribute
     'strip'`, làm mất luôn cách huỷ một lịch nhắc đặt sai;
  3. `nlu_advanced.teach("a", 123)` nổ cùng kiểu, `confirm_message({})` nổ
     `KeyError: 'intent'` - tức là chính cái câu hỏi "bạn có chắc không?" sập khi
     kết quả đến từ nguồn khác;
  4. `log_feedback(..., confidence=None)` làm hỏng feedback.csv ngay bước
     `round(float(...))`, mà file đó là ĐẦU VÀO của lần huấn luyện sau.

Thêm `config.save_config`: lỗi "không nối được JSON" giờ báo TRƯỚC khi chạm đĩa.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

PKG_DIR = Path(__file__).resolve().parent.parent          # .../vi_voice_assistant
REPO_ROOT = PKG_DIR.parent
sys.path.insert(0, str(PKG_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def model():
    import lite_model

    return lite_model.get_lite_model()


@pytest.fixture
def iso(tmp_path, monkeypatch):
    import executor

    monkeypatch.setattr(executor, "REMINDERS_PATH", str(tmp_path / "reminders.json"))
    monkeypatch.setattr(executor, "ACTIVE_REMINDERS", [])
    return executor


def _later(minutes=5):
    return datetime.now() + timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# 1. lite_model: batch phai la BATCH CAU, khong phai batch KY TU
# ---------------------------------------------------------------------------
def test_chuoi_tran_duoc_hieu_la_mot_cau(model):
    """`predict("mở youtube")` trước đây trả 11 hàng - một cho mỗi KÝ TỰ."""
    single = model.predict("mở youtube")
    assert isinstance(single, list) and len(single) == 1, single
    assert single == model.predict(["mở youtube"])
    assert len(model.predict_proba("mở youtube")) == 1


def test_kieu_khong_lap_duoc_bao_dung_ten_tham_so(model):
    with pytest.raises(TypeError, match="danh sách chuỗi"):
        model.predict(123)
    with pytest.raises(TypeError, match="danh sách chuỗi"):
        model.predict_proba({"k": "v"}.get)          # ham khong phai iterable


def test_danh_sach_rong_va_rong_kieu_khac(model):
    assert model.predict([]) == []
    assert model.predict_proba([]) == []
    assert model.predict_proba(None) == []
    assert isinstance(model.predict_proba_dict(None), dict)   # single-text API chiu duoc None


def test_as_texts_nho_danh_sach_va_generator(model):
    import lite_model

    as_texts = lite_model._as_texts
    assert as_texts("a") == ["a"]
    assert as_texts(["a", "b"]) == ["a", "b"]
    assert as_texts(("a", 123)) == ["a", "123"]      # phan tu lac kieu duoc ep kieu
    assert as_texts(iter(["a", "b"])) == ["a", "b"]
    assert as_texts(None) == [] and as_texts("") == [""]
    with pytest.raises(TypeError):
        as_texts(12345)


def test_score_khong_do_khi_boc_danh_sach(model):
    """Cùng thứ tự -> cùng điểm; độ dài lệch nhau không được IndexError."""
    good = model.score(["mở youtube"], ["play_media"])
    assert good == model.score("mở youtube", "play_media")
    assert model.score([], []) == 0.0 and model.score(None, None) == 0.0
    assert 0.0 <= model.score(["mở youtube", "hôm nay"], ["play_media"]) <= 1.0


def test_ket_qua_batch_khop_voi_tung_cau(model):
    """`predict_proba` không được đổi bản chất khi qua `_as_texts` (parity)."""
    texts = ["mở youtube", "hẹn 7 giờ nhắc tôi", "12 + 34 bằng bao nhiêu"]
    rows = model.predict_proba(texts)
    assert len(rows) == len(texts)
    for row, text in zip(rows, texts):
        assert row == model.predict_proba([text])[0], text
        assert len(row) == len(model.classes_)


def test_from_state_bao_dung_loi_khong_phai_dict(model):
    import lite_model

    for junk in (None, "abc", 123, []):
        with pytest.raises(TypeError, match="from_state cần dict"):
            lite_model.LiteIntentModel.from_state(junk)


def test_from_state_bo_qua_field_sai_kieu(model):
    """File model viet do (mat dien) -> model trang, khong nem AttributeError giua luc khoi dong."""
    import lite_model

    state = model.to_state()
    assert lite_model.LiteIntentModel.from_state({}).classes_ == []
    lac = dict(state, alpha="0.2", classes=123, log_prob=["x"], fingerprint=None)
    rebuilt = lite_model.LiteIntentModel.from_state(lac)
    assert rebuilt.alpha == 0.15 and rebuilt.classes_ == [] and isinstance(rebuilt._log_prob, dict)
    assert rebuilt.predict(["mở youtube"]) == ["chitchat"]
    # trang thai day du thi phai round-trip duoc nguyen ven
    ok = lite_model.LiteIntentModel.from_state(state)
    assert ok.classes_ == model.classes_
    assert ok.predict(["mở youtube"]) == model.predict(["mở youtube"])


# ---------------------------------------------------------------------------
# 2. cancel_reminder: keyword khong nhat thiet la chuoi
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("keyword", [123, None, 3.5, ["nuoc"], {"a": 1}, b"nuoc"])
def test_cancel_reminder_khong_chet_voi_keyword_lac(iso, keyword):
    iso._schedule_reminder("uống nước", _later())
    removed = iso.cancel_reminder(keyword)
    assert isinstance(removed, list)
    assert len(iso.ACTIVE_REMINDERS) in (0, 1)         # hoac con, hoac bi huy het


def test_cancel_reminder_van_dung_chuc_nang(iso):
    iso._schedule_reminder("uống nước", _later())
    iso._schedule_reminder("tắt máy", _later(7))
    removed = iso.cancel_reminder("NƯỚC")             # hoa + dau -> bo dau + lower
    assert [r["task"] for r in removed] == ["uống nước"], removed
    assert [i["task"] for i in iso.ACTIVE_REMINDERS] == ["tắt máy"]
    assert len(iso.cancel_reminder(None)) == 1          # bo trong = huy tat ca
    assert iso.ACTIVE_REMINDERS == []


def test_cancel_reminder_theo_id(iso):
    reminder_id = iso._schedule_reminder("theo id", _later())
    assert iso.cancel_reminder(reminder_id) and iso.ACTIVE_REMINDERS == []


def test_reminders_tren_dia_khong_con_muc_da_huy(iso, tmp_path):
    """Huy xong phai luu lai: mo may lan sau khong thay lich da huy quay lai."""
    iso._schedule_reminder("sẽ bị huỷ", _later())
    iso.cancel_reminder("sẽ bị huỷ")
    text = Path(iso.REMINDERS_PATH).read_text(encoding="utf-8")
    assert "sẽ bị huỷ" not in text, text


# ---------------------------------------------------------------------------
# 3. nlu_advanced: day / hoi lai / file hoc
# ---------------------------------------------------------------------------
def test_teach_intent_kieu_khac_chuoi_bao_loi_le_pha():
    import nlu_advanced

    nlu = nlu_advanced.NLU()
    msg = nlu.teach("một câu", 123)
    assert "không hợp lệ" in msg, msg               # truoc day: AttributeError
    assert "open_app" in msg                        # con liet ke cach dung


def test_teach_van_ghi_duoc_khi_ep_kieu(tmp_path, monkeypatch):
    import nlu_advanced

    monkeypatch.setattr(nlu_advanced, "FEEDBACK_PATH", str(tmp_path / "feedback.csv"))
    nlu = nlu_advanced.NLU()
    msg = nlu.teach(123, "open_app")
    assert "Đã ghi nhớ" in msg, msg
    rows = (tmp_path / "feedback.csv").read_text(encoding="utf-8-sig").splitlines()
    assert rows[0].startswith("time,text,intent"), rows[0]
    assert rows[-1].split(",")[1:3] == ["123", "open_app"], rows[-1]


def test_confirm_message_khong_nem_keyerror():
    import nlu_advanced

    nlu = nlu_advanced.NLU()
    chung = "Bạn muốn tôi làm việc đó phải không? (có/không)"
    assert nlu.confirm_message({}) == chung
    assert nlu.confirm_message({"intent": None}) == chung
    assert nlu.confirm_message({"intent": "open_website"}).startswith("Bạn muốn tôi mở trang")


def test_confirm_message_cau_dung_khong_doi():
    """Chuoi nguoi dung thay phai duoc GIU NGUYEN tung byte (test cu van xanh)."""
    import nlu_advanced

    nlu = nlu_advanced.NLU()
    assert nlu.confirm_message({"intent": "open_website", "target": "youtube"}) == \
        "Bạn muốn tôi mở trang youtube phải không? (có/không)"
    assert nlu.confirm_message({"intent": "set_reminder", "target": "uống nước"}) == \
        "Bạn muốn tôi đặt nhắc nhở uống nước phải không? (có/không)"


@pytest.mark.parametrize(
    "conf, mong",
    [(None, "0.0"), ("abc", "0.0"), ("0.9", "0.9"), (0.123456, "0.1235")],
)
def test_log_feedback_khong_hong_file_hoc(tmp_path, monkeypatch, conf, mong):
    import csv

    import nlu_advanced

    path = tmp_path / "feedback.csv"
    monkeypatch.setattr(nlu_advanced, "FEEDBACK_PATH", str(path))
    nlu_advanced.log_feedback("câu nói", "open_app", conf, correct=True)
    rows = list(csv.reader(path.open(encoding="utf-8-sig")))
    assert rows[0] == ["time", "text", "intent", "confidence", "verified"], rows[0]
    assert rows[-1][1:5] == ["câu nói", "open_app", mong, "1"], rows[-1]


def test_log_feedback_chiu_duoc_không_phai_chuoi(tmp_path, monkeypatch):
    import csv

    import nlu_advanced

    path = tmp_path / "fb.csv"
    monkeypatch.setattr(nlu_advanced, "FEEDBACK_PATH", str(path))
    nlu_advanced.log_feedback(123, 456, None)          # khong duoc nem ngoai le
    row = list(csv.reader(path.open(encoding="utf-8-sig")))[-1]
    assert row[1:5] == ["123", "456", "0.0", "0"], row


# ---------------------------------------------------------------------------
# 4. config.save_config: bao truoc khi cham dia
# ---------------------------------------------------------------------------
def test_save_config_bao_ly_do_khong_tao_file(tmp_path):
    import config

    target = tmp_path / "config.json"
    with pytest.raises(TypeError, match="không ghi thành JSON được"):
        config.save_config({"x": {1, 2}}, target)
    assert not target.exists(), "file tam/that khong duoc phep nam lai"
    assert list(tmp_path.iterdir()) == []


def test_save_config_tu_choi_kieu_sai_cho_dau_vao(tmp_path):
    import config

    with pytest.raises(TypeError, match="cần dict"):
        config.save_config("khong phai dict", tmp_path / "c.json")
    with pytest.raises(TypeError, match="cần dict"):
        config.save_config([("a", 1)], tmp_path / "c.json")


def test_save_config_van_ghi_dung(tmp_path):
    """Ghi mot phan config: doc lai van thay gia tri cua minh + cac key mac dinh."""
    import config

    target = tmp_path / "config.json"
    config.save_config({"confidence_threshold": 0.4, "wake_word": "neo"}, target)
    cfg = config.load_config(target)
    assert cfg["confidence_threshold"] == 0.4 and cfg["wake_word"] == "neo"
    assert set(cfg) >= set(config.DEFAULT_CONFIG), "load_config phai dien key con thieu"


def test_update_config_khong_bao_gi_voi_gia_tri_json_hoa_duoc(tmp_path):
    """Đường hay dùng nhất phải còn nguyên: dict -> merge -> lưu -> đọc lại."""
    import config

    target = tmp_path / "config.json"
    merged = config.update_config({"tts": {"rate": 200}}, target)
    assert merged["tts"]["rate"] == 200
    assert config.load_config(target)["tts"]["rate"] == 200
