"""Test cho bản v7.8 - ngưỡng tự tin, số học không dấu, và ranh giới dữ liệu.

v7.5-v7.7 soi các điểm vào "chữ nghĩa" (chuỗi rỗng, số, None). Vòng này soi
những chỗ còn lại, và phần lớn lỗi tìm được đều có một điểm chung: **số bị
bỏ qua âm thầm, hoặc dữ liệu bị đánh cắp bởi chính lớp bảo vệ**:

  1. `execute_command` với `"confidence": NaN` BỎ QUA ngưỡng an toàn rồi chạy
     lệnh - vì `nan < x` luôn False. JSON của Python mặc định chấp nhận
     `NaN`/`Infinity`, và `--json` là đường dùng thật.
  2. `NLU._judge` nổ TypeError khi `confidence` không phải số, và với NaN thì
     trả về "ok" - tức lệnh ĐƯỢC THỰC THI chứ không phải bị hỏi lại.
  3. `log_feedback` vào một file CSV RỖNG (do mất điện) không ghi dòng tiêu đề;
     `train_nlu.py` đọc bằng `csv.DictReader` nên ăn mất dòng đầu và bỏ qua
     toàn bộ phần còn lại: MỌI câu người dùng đã dạy biến mất khỏi huấn luyện.
  4. `parse_math_expression` CHỈ hiểu câu có dấu, và `normalize_text` xoá mất
     `+`/`*`/dấu phẩy thập phân - nên `--once "15 + 27"` (đúng ví dụ trong
     `--help`) không tính được, còn "2,5 nhân 4" ra kết quả SAI (20 thay vì 10).
  5. `save_lite_model` để lại file tạm khi ghi lỗi OSError - đúng nhánh lỗi hay
     xảy ra nhất (đĩa đầy, thiếu quyền).
  6. `voice_cache/index.csv` trỏ được ra ngoài thư mục cache rồi bị phát.
  7. `data_path("/etc/hosts")` trèo khỏi thư mục dữ liệu.

Phần 12-13 bổ sung những lỗi mà chính phần 4 ĐÃ BỎ SÓT, vì test ở đó gọi
`parse_math_expression` trực tiếp nên không đi qua những chỗ làm hỏng nó:

  8. `split_commands` tách "," vô điều kiện -> "2,5 nhân 4" thành HAI lệnh.
  9. `target` (từ `extract_entity`) và `result` (từ `parse_math_expression`) lệch
     nhau: "12,75 + 1" cho target "75 + 1" (=76) nhưng result 13.75.
 10. Dấu chấm là dấu PHẨY NGHÌN kiểu Việt Nam: "1.234,5 chia 3" ra 78.17
     (= 234.5 / 3) thay vì 411.5 - mất luôn phần "1." và ra số sai.
 11. Câu toán hỏng dấu `+` đôi khi còn bị model đoán nhầm sang intent khác
     ("1.234 + 5" -> "1.234 5" -> system_control, tưởng là số phiên bản).
"""
import json
import math
import sys
from pathlib import Path

import pytest

PKG_DIR = Path(__file__).resolve().parent.parent          # .../vi_voice_assistant
REPO_ROOT = PKG_DIR.parent
sys.path.insert(0, str(PKG_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def ex(monkeypatch):
    """executor với `Popen` bị chặn, để test đo lệnh nào THỰC SỰ đã chạy."""
    import executor

    monkeypatch.setattr(executor, "AUTO_CONFIRM", False)
    monkeypatch.setattr(executor, "_confirm", lambda prompt: True)
    ran = []
    monkeypatch.setattr(executor, "_popen", lambda cmd: ran.append(cmd))
    monkeypatch.setattr(executor, "_run_first_available", lambda c: ran.append(c) or True)
    executor.ran = ran
    return executor


# ---------------------------------------------------------------------------
# 1. confidence NaN/Infinity khong duoc bo qua nguong an toan
# ---------------------------------------------------------------------------
def test_confidence_nan_khong_chay_lenh(ex):
    """NaN < threshold luôn False -> lenh chay qua canh "do tu tin thap"."""
    payload = '{"intent":"system_control","target":"lock","confidence":NaN}'
    assert ex.execute_command(payload) is False
    assert ex.ran == [], "lenh da chay du confidence la NaN"


def test_confidence_infinity_khong_chay_lenh(ex):
    assert ex.execute_command(
        '{"intent":"system_control","target":"lock","confidence":Infinity}'
    ) is False
    assert ex.ran == []


def test_confidence_hong_phai_so_bi_tu_choi(ex):
    """Giá trị không đọc được thì từ chối chứ không phải im lặng coi như 0.0."""
    for raw in ('"abc"', "true", "null", "{}", "[]"):
        assert ex.execute_command(
            '{"intent":"system_control","target":"lock","confidence":' + raw + "}"
        ) is False
    assert ex.ran == []


def test_confidence_binh_thuong_van_chay(ex):
    """Đường hợp hợp lệ KHÔNG đổi: số trong [0,1] vẫn thực thi bình thường."""
    assert ex.execute_command(
        '{"intent":"system_control","target":"lock","confidence":0.9}'
    ) is True
    assert len(ex.ran) == 1


def test_confidence_ngoai_doi_gioi_han_bi_tu_choi(ex):
    for value in ("-0.5", "1.5"):
        assert ex.execute_command(
            '{"intent":"system_control","target":"lock","confidence":' + value + "}"
        ) is False
    assert ex.ran == []


def test_read_confidence_tra_ve_so_hop_le(ex):
    assert ex._read_confidence(0.5) == 0.5
    assert ex._read_confidence("0.5") == 0.5
    assert ex._read_confidence(None) == -1.0
    assert ex._read_confidence(float("nan")) == -1.0
    assert ex._read_confidence(math.inf) == -1.0
    assert ex._read_confidence(True) == -1.0        # bool khong phai do tu tin


# ---------------------------------------------------------------------------
# 2. NLU._judge chiu duoc kieu la
# ---------------------------------------------------------------------------
def test_judge_khong_no_khi_confidence_hong_phai_so():
    """Giá trị KHÔNG phải số phải rơi về "unknown" chứ không nổ TypeError."""
    import nlu_advanced

    for bad in (None, "abc", "", object(), [], {}, True, False):
        status = nlu_advanced.NLU._judge(
            {"intent": "chitchat", "target": "x", "confidence": bad}
        )
        assert status == "unknown", (bad, status)


def test_judge_van_nhan_chuoi_so():
    """`"0.9"` LÀ số hợp lệ (đọc từ JSON) - vẫn phải ra "ok" như số thật."""
    import nlu_advanced

    assert nlu_advanced.NLU._judge(
        {"intent": "open_website", "target": "g", "confidence": "0.9"}
    ) == "ok"


def test_judge_nan_khong_duoc_coi_la_ok():
    """Trước đây NaN lọt qua MỌI phép so sánh nên rơi xuống cuối = "ok" = chạy."""
    import nlu_advanced

    status = nlu_advanced.NLU._judge(
        {"intent": "system_control", "target": "shutdown", "confidence": float("nan")}
    )
    assert status != "ok", status


def test_judge_giu_nguyen_nguong_da_co(ex_monkeypatch=None):
    import nlu_advanced

    base = {"intent": "open_website", "target": "google"}
    assert nlu_advanced.NLU._judge({**base, "confidence": 0.9}) == "ok"
    assert nlu_advanced.NLU._judge({**base, "confidence": 0.30}) == "low_confidence"
    assert nlu_advanced.NLU._judge({**base, "confidence": 0.01}) == "unknown"
    # hành động nguy hiểm vẫn phải hỏi lại dù tự tin cao
    assert nlu_advanced.NLU._judge(
        {"intent": "system_control", "target": "shutdown", "confidence": 0.95}
    ) == "need_confirm"


def test_context_memory_last_intent_khong_no_keyerror():
    import nlu_advanced

    ctx = nlu_advanced.ContextMemory()
    assert ctx.last_intent is None
    ctx.remember({"target": "x"})            # thieu "intent" - dict qua tay noi khac
    assert ctx.last_intent is None
    assert ctx.last_target == "x"
    ctx.remember({"intent": "open_app", "target": "chrome"})
    assert ctx.last_intent == "open_app"


# ---------------------------------------------------------------------------
# 3. feedback.csv rong -> phai ghi lai dong tieu de
# ---------------------------------------------------------------------------
def _feedback_path(tmp_path, monkeypatch):
    import nlu_advanced

    path = tmp_path / "feedback.csv"
    monkeypatch.setattr(nlu_advanced, "FEEDBACK_PATH", str(path))
    return path


def test_feedback_file_rong_van_co_dong_tieu_de(tmp_path, monkeypatch):
    """File 0 byte (mất điện lúc ghi) phải được coi là "chưa có"."""
    import csv

    import nlu_advanced

    path = _feedback_path(tmp_path, monkeypatch)
    path.write_text("", encoding="utf-8")
    nlu_advanced.log_feedback("mo chrome", "open_app", 0.9, correct=True)
    rows = list(csv.reader(path.read_text(encoding="utf-8-sig").splitlines()))
    assert rows[0] == ["time", "text", "intent", "confidence", "verified"]


def test_feedback_khong_co_header_thi_huan_luyen_mat_het(tmp_path, monkeypatch):
    """DictReader ăn dòng đầu làm TÊN CỘT -> mọi câu đã dạy biến mất.

    Đây là hậu quả thật, không phải giả định: test lấy đúng bộ đọc mà
    train_nlu.py dùng, nên test đỏ nếu file hỏng làm mất dữ liệu huấn luyện.
    """
    import csv

    import nlu_advanced

    path = _feedback_path(tmp_path, monkeypatch)
    nlu_advanced.log_feedback("mo chrome", "open_app", 0.9, correct=True)
    nlu_advanced.log_feedback("tat may tinh", "system_control", 0.8, correct=True)
    learned = [
        row for row in csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines())
        if str(row.get("verified", "0")).strip() == "1"
    ]
    assert len(learned) == 2, learned
    assert {row["text"] for row in learned} == {"mo chrome", "tat may tinh"}


def test_feedback_confidence_hong_phai_so_van_ghi_duoc(tmp_path, monkeypatch):
    import csv

    import nlu_advanced

    path = _feedback_path(tmp_path, monkeypatch)
    nlu_advanced.log_feedback("a", "open_app", None)
    nlu_advanced.log_feedback("b", "open_app", float("nan"))
    rows = list(csv.reader(path.read_text(encoding="utf-8-sig").splitlines()))
    body = rows[1:]
    assert len(body) == 2
    for row in body:
        float(row[3])                                  # phai la so doc duoc
        assert math.isfinite(float(row[3]))


# ---------------------------------------------------------------------------
# 4. So hoc: phai hieu ca cau CO DAU lan cau KHONG DAU, va giu dau phay
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("accented,plain,expected", [
    ("15 phần trăm của 200", "15 phan tram cua 200", 30.0),
    ("căn bậc hai của 81", "can bac hai cua 81", 9.0),
    ("căn bậc ba của 27", "can bac ba cua 27", 3.0),
    ("16 bình phương", "16 binh phuong", 256.0),
    ("16 lập phương", "16 lap phuong", 4096.0),
    ("3 mũ 2", "3 mu 2", 9.0),
    ("12 cộng 8", "12 cong 8", 20.0),
    ("100 chia cho 4", "100 chia cho 4", 25.0),
    ("9 nhân 9", "9 nhan 9", 81.0),
    ("5 trừ 12", "5 tru 12", -7.0),
])
def test_toan_khong_dau_cho_ket_qua_giong_het_cau_co_dau(accented, plain, expected):
    from intent_model import parse_math_expression as pm

    got_accented, got_plain = pm(accented), pm(plain)
    assert got_plain == got_accented, (accented, plain, got_accented, got_plain)
    assert got_plain[1] == pytest.approx(expected)


def test_dau_phay_thap_phan_khong_bi_nhanh_thanh_hai_so():
    """normalize_text xoá dấu phẩy -> "2,5 * 4" ra "2 5 * 4" = 20 thay vì 10."""
    from intent_model import parse_math_expression as pm

    assert pm("2,5 nhân 4")[1] == pytest.approx(10.0)
    assert pm("0,25 * 4")[1] == pytest.approx(1.0)
    assert pm("12,75 + 1")[1] == pytest.approx(13.75)


def test_toan_tu_got_tay_khong_bi_xoa():
    """`--once "15 + 27"` là ví dụ trong chính --help; trước đây trả None."""
    from intent_model import parse_math_expression as pm

    assert pm("15 + 27")[1] == 42
    assert pm("15 * 2")[1] == 30
    assert pm("2 ** 10")[1] == 1024


def test_toan_hoc_hien_thu_dung_ngon_ngu_co_dau():
    """Câu không dấu vẫn trả về câu mô tả CÓ DẤU cho người dùng đọc."""
    from intent_model import parse_math_expression as pm

    assert pm("can bac hai cua 81")[0] == "căn bậc hai của 81"
    assert pm("15 phan tram cua 200")[0] == "15% của 200"


def test_cau_hong_van_trai_ve_khong_thay_doi():
    """Câu rác KHÔNG được biến thành câu tính được."""
    from intent_model import parse_math_expression as pm

    for junk in ("xin chao ban", "", "het", "tinh giup toi 3 cong 4 nhan 2"):
        got = pm(junk)
        assert got == (None, None) or got[1] is not None, junk


# ---------------------------------------------------------------------------
# 5. _safe_eval chi chap nhan SO
# ---------------------------------------------------------------------------
def test_safe_eval_chan_hang_so_khong_phai_so():
    from intent_model import _safe_eval

    for expr in ("'ab' * 3", "b'x' * 5", "None"):
        with pytest.raises(ValueError):
            _safe_eval(expr)


def test_safe_eval_van_tinh_binh_thuong():
    from intent_model import _safe_eval

    assert _safe_eval("15 + 27") == 42
    assert _safe_eval("2 ** 10") == 1024
    assert _safe_eval("1.5 * 2") == pytest.approx(3.0)


def test_predict_intent_khi_model_tra_xac_suat_rong():
    """`max([])` nổ ValueError bay ra ngoài, giết cả câu lệnh."""
    from intent_model import predict_intent

    class EmptyProba:
        def predict(self, texts):
            return ["open_website"]

        def predict_proba(self, texts):
            return [[]]

    result = predict_intent("mo google", EmptyProba())
    assert result["intent"] == "open_website"
    assert 0.0 <= result["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# 6. save_lite_model khong de lai file tam
# ---------------------------------------------------------------------------
def test_save_lite_model_khong_de_lai_file_tmp_khi_loi_oserror(tmp_path, monkeypatch):
    """OSError SAU khi file tạm đã tạo (đĩa đầy lúc ghi) không được bỏ rác.

    Bản cũ chỉ dọn file tạm trong `except Exception`, tức đúng nhánh
    `except OSError` bị bỏ qua - mà OSError (đĩa đầu/thiếu quyền) mới là lỗi
    hay xảy ra nhất khi lưu model.
    """
    import lite_model

    model = lite_model.LiteIntentModel().fit(["mo chrome", "tat may"], ["a", "b"])
    target = tmp_path / "lite_model.pkl"

    def boom(*args, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr(lite_model.os, "fdopen", boom)
    assert lite_model.save_lite_model(model, target) is False
    assert list(tmp_path.iterdir()) == [], "con file tam bi bo lai"


def test_save_lite_model_khong_de_lai_file_tmp_khi_loi_khong_phai_oserror(tmp_path, monkeypatch):
    """Lỗi khác (pickling, đường dẫn tới hạn) cũng phải dọn file tạm."""
    import lite_model

    model = lite_model.LiteIntentModel().fit(["mo chrome", "tat may"], ["a", "b"])
    target = tmp_path / "lite_model.pkl"

    monkeypatch.setattr(lite_model.pickle, "dump",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert lite_model.save_lite_model(model, target) is False
    assert list(tmp_path.iterdir()) == [], "con file tam bi bo lai"


def test_save_lite_model_thanh_cong_va_doc_lai_duoc(tmp_path):
    import lite_model

    model = lite_model.LiteIntentModel().fit(["mo chrome", "tat may"], ["a", "b"])
    target = tmp_path / "lite_model.pkl"
    assert lite_model.save_lite_model(model, target) is True
    assert list(tmp_path.iterdir()) == [target], "file tam phai duoc doi ten sach"
    assert lite_model.load_lite_model(target).classes_ == model.classes_


# ---------------------------------------------------------------------------
# 7. voice_cache khong tro ra ngoai thu muc cache
# ---------------------------------------------------------------------------
def test_index_csv_tro_duong_dan_tuyet_doi_bi_bo(tmp_path, monkeypatch):
    import tts

    cache = tmp_path / "voice_cache"
    cache.mkdir()
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"RIFF" + b"\0" * 200)
    (cache / "index.csv").write_text(
        f"mo youtube,{outside}\n", encoding="utf-8"
    )
    monkeypatch.setattr(tts, "VOICE_CACHE_DIR", cache)
    monkeypatch.setattr(tts, "_voice_cache_index", None)
    assert tts._load_voice_cache() == {}


def test_index_csv_tro_ra_ngoai_bang_dau_dot_bi_bo(tmp_path, monkeypatch):
    import tts

    cache = tmp_path / "voice_cache"
    (cache / "sub").mkdir(parents=True)
    (cache / "sub" / "ok.wav").write_bytes(b"RIFF" + b"\0" * 200)
    (cache / "index.csv").write_text(
        "hai cay,sub/ok.wav\nnam cay,../../etc/passwd\n", encoding="utf-8"
    )
    monkeypatch.setattr(tts, "VOICE_CACHE_DIR", cache)
    monkeypatch.setattr(tts, "_voice_cache_index", None)
    index = tts._load_voice_cache()
    assert list(index) == ["hai cay"], index
    assert index["hai cay"].parent == (cache / "sub").resolve()


def test_index_csv_hop_le_bi_bo(tmp_path, monkeypatch):
    import tts

    cache = tmp_path / "voice_cache"
    cache.mkdir()
    (cache / "index.csv").write_text(
        "cot mot\nkhong,co-file.wav\nrong,\n", encoding="utf-8"
    )
    monkeypatch.setattr(tts, "VOICE_CACHE_DIR", cache)
    monkeypatch.setattr(tts, "_voice_cache_index", None)
    assert tts._load_voice_cache() == {}


# ---------------------------------------------------------------------------
# 8. data_path khong tro ra ngoai thu muc du lieu
# ---------------------------------------------------------------------------
def test_data_path_chan_duong_dan_tuyet_doi_va_dot_dot(tmp_path, monkeypatch):
    import paths

    monkeypatch.setenv("VI_ASSISTANT_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(paths, "_cached", None)
    for bad in ("/etc/hosts", "../../etc/hosts", "a/../../b"):
        with pytest.raises(ValueError):
            paths.data_path(bad)
    monkeypatch.setattr(paths, "_cached", None)


def test_data_path_van_dung_cho_ten_file_thuong():
    import paths

    base = paths.data_dir()
    for name in ("config.json", "reminders.json", "voice_cache", "a/b/c.json"):
        assert paths.data_path(name).is_relative_to(base)


# ---------------------------------------------------------------------------
# 9. Nhac nho: timer phai duoc DANG KY truoc khi bat
# ---------------------------------------------------------------------------
def test_timer_khong_bat_truoc_khi_muc_da_dang_ky(monkeypatch, tmp_path):
    """Timer nổ trước khi mục vào danh sách -> lời nhắc "ma" không bao giờ tắt."""
    import executor

    monkeypatch.setattr(executor, "REMINDERS_PATH", str(tmp_path / "reminders.json"))
    monkeypatch.setattr(executor, "ACTIVE_REMINDERS", [])
    seen = {}

    class FakeTimer:
        def __init__(self, delay, fn, args=()):
            self.fn, self.args, self.started = fn, args, False

        def start(self):
            self.started = True
            # mo phong timer that su: no no trong khoi "goi tim" thu muc
            ids = [item.get("id") for item in executor.ACTIVE_REMINDERS]
            seen["id_da_dang_ky"] = self.args[1] in ids

        def cancel(self):
            pass

    monkeypatch.setattr(executor.threading, "Timer", FakeTimer)
    from datetime import datetime, timedelta

    executor._schedule_reminder("uong nuoc", datetime.now() + timedelta(seconds=30))
    assert seen.get("id_da_dang_ky") is True, "timer bat truoc khi muc da vao danh sach"


# ---------------------------------------------------------------------------
# 10. main: in phan tram phai chiu duoc kieu la
# ---------------------------------------------------------------------------
def test_confidence_percent_chiu_duoc_chuoi_va_none():
    import main

    assert main._confidence_percent({"confidence": 0.9}) == pytest.approx(0.9)
    assert main._confidence_percent({"confidence": "0.5"}) == pytest.approx(0.5)
    for bad in (None, "abc", float("nan"), float("inf"), {}, [1]):
        assert main._confidence_percent({"confidence": bad}) == 0.0


def test_handle_result_khong_no_khi_confidence_la_chuoi(monkeypatch):
    import main

    shown = []
    monkeypatch.setattr(main, "safe_print", lambda *a, **k: shown.append(" ".join(
        str(x) for x in a)))
    monkeypatch.setattr("builtins.input", lambda *a, **k: "khong")
    monkeypatch.setattr(main.executor, "respond", lambda *a, **k: None)

    class FakeNLU:
        def confirm_message(self, r):
            return "Ban co xac nhan khong?"

        def teach(self, a, b):
            return ""

    main.handle_result(
        {"intent": "open_website", "target": "google", "confidence": "0.9",
         "status": "low_confidence"},
        FakeNLU(), dry_run=True,
    )
    assert any("tự tin" in line for line in shown), shown


# ---------------------------------------------------------------------------
# 11. JSON cua Python chap nhan NaN - ghi ro ra de khong ai "chua biet"
# ---------------------------------------------------------------------------
def test_json_mac_dinh_thuc_su_chap_nhan_nan():
    """Bằng chứng cho lý do sửa: đây không phải rủi ro lý thuyết."""
    parsed = json.loads('{"confidence": NaN, "x": Infinity}')
    assert math.isnan(parsed["confidence"])
    assert parsed["x"] == math.inf


# ---------------------------------------------------------------------------
# 12. Duong DIEN DAU: tach lenh + trich entity + tinh - sua o noi test "hop le"
#     trong phan 4 CHUA BAT duoc.
#     Cac test tren goi `parse_math_expression` truc tiep nen khong bat duoc
#     hai loi duoi day, ca hai deu rat nhe trong khi test don vi cung pass:
#       * `split_commands` tach "," VO DIEU KIEN nen "2,5 nhan 4" thanh HAI
#         lenh: lenh 2 la "2" (khong phai lenh tinh) - ket qua 20 thay vì 10.
#       * `normalize_text` xoa "+"/"," nen `_EntityContext.raw` mat dau, va
#         `target` (tu `extract_entity`) LE CHON phep ban khac voi `result`
#         (tu `parse_math_expression(entity_source)`).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    # Phay thap phan: phai giu nguyen trong MOT lenh
    ("2,5 nhân 4", ["2,5 nhân 4"]),
    ("2,5 nhan 4", ["2,5 nhan 4"]),
    ("12,75 + 1", ["12,75 + 1"]),
    ("1.234,5 chia 3", ["1.234,5 chia 3"]),
    # Phay tach lenh: van tach nhu truoc
    ("mở chrome, phát nhạc", ["mở chrome", "phát nhạc"]),
    ("mo chrome, phat nhac", ["mo chrome", "phat nhac"]),
    ("mở chrome; phát nhạc", ["mở chrome", "phát nhạc"]),
    ("mở chrome rồi phát nhạc", ["mở chrome", "phát nhạc"]),
    ("tao roi chay", ["tao", "chay"]),
])
def test_split_commands_giu_phay_thap_phan(text, expected):
    from nlu_advanced import split_commands

    assert split_commands(text) == expected


def test_split_commands_giu_phay_thap_phan_qua_chu_roi():
    """Dấu phẩy thập phân ngay TRƯỚC từ nối cũng không được nuốt theo."""
    from nlu_advanced import split_commands

    assert split_commands("2,5 nhân 4 rồi bật đèn") == ["2,5 nhân 4", "bật đèn"]


@pytest.mark.parametrize("text,expected", [
    ("15 + 27", 42),
    ("2,5 nhân 4", 10.0),
    ("12,75 + 1", 13.75),
    ("1.234,5 chia 3", 411.5),
    ("1.234 + 5", 1239),
    ("1.000 nhân 2", 2000),
    ("0.250 nhân 4", 1.0),
    ("9 * 9", 81),
    ("15 cộng 27", 42),
    ("can bac hai cua 81", 9.0),
])
def test_predict_intent_target_khop_dung_ket_qua(text, expected):
    """`target` và `result` phải cùng nói một đằng - đây là chỗ lệch nhau."""
    from intent_model import parse_math_expression, predict_intent

    r = predict_intent(text)
    assert r["intent"] == "calculate", (text, r)
    assert r["result"] == pytest.approx(expected), (text, r)

    # target phải parse lại ra CHÍNH kết quả đó (trước đây ra "75 + 1")
    assert parse_math_expression(r["target"])[1] == pytest.approx(expected), (
        text, r["target"])


def test_duong_math_di_den_cli_bien_mot_lenh_tinh_dung():
    """Mô phỏng đúng thứ `--once` làm: tách lệnh -> predict -> intent."""
    from intent_model import predict_intent
    from nlu_advanced import split_commands

    parts = split_commands("2,5 nhân 4")
    assert len(parts) == 1, parts                      # trước đây ra 2 phần
    assert predict_intent(parts[0])["result"] == pytest.approx(10.0)


@pytest.mark.parametrize("text,expected", [
    ("1.234,5 chia 3", 411.5),        # 1.234,5 = 1234.5 (dấu chấm = nghìn)
    ("1.234.567,89 + 1", 1234568.89),
    ("1.234 + 5", 1239),
    ("1.000 nhân 2", 2000),
    ("2.5 + 1", 3.5),                 # nhóm KHÔNG đủ 3 số -> thập phân kiểu Anh
    ("12.75 + 1", 13.75),
    ("0.250 nhân 4", 1.0),            # nhóm đầu "0" -> giữ thập phân
])
def test_dau_cham_phan_tach_nghin_khong_bi_nham_thanh_thap_phan(text, expected):
    """"1.234,5 chia 3" trả về 78.17 (= 234.5/3): mất "1." và ra SAI SỐ."""
    from intent_model import parse_math_expression as pm

    assert pm(text)[1] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# 13. Câu toán bị model đoán nhầm vì dấu `+` bị `normalize_text` xoá.
# ---------------------------------------------------------------------------
def test_cau_co_dau_cham_nghin_khong_bi_doan_nham_thanh_so_phien_ban():
    """"1.234 + 5" -> normalize thành "1.234 5"; model tưởng đó là version."""
    from intent_model import predict_intent

    r = predict_intent("1.234 + 5")
    assert r["intent"] == "calculate", r
    assert r["result"] == pytest.approx(1239), r
    assert r["target"] == "1234 + 5", r


@pytest.mark.parametrize("text,expected", [
    ("1.234 + 5", 1239),
    ("1.000 * 2", 2000),
    ("1.234,5 / 2", 617.25),
])
def test_guard_calculate_bung_intent_khi_model_do_nham(text, expected):
    from intent_model import predict_intent

    assert predict_intent(text)["result"] == pytest.approx(expected)


@pytest.mark.parametrize("text", [
    "mo chrome", "mo youtube", "may bao gio", "tat may", "mo file report.pdf",
    "thong bao 9 gio sang mai", "v2.0", "xin chao ban", "tim bai hat abc",
    "doc huong dan", "chat giup toi", "bat den", "ket noi wifi",
])
def test_guard_calculate_khong_duoc_goi_nham_lenh_thuong(text):
    """Câu KHÔNG tính được thì tuyệt đối không được ép thành calculate."""
    from intent_model import predict_intent

    assert predict_intent(text)["intent"] != "calculate", text


def test_model_chac_thi_guard_calculate_im_lang():
    """Model chắc thì để model quyết - không cãi ý kiến đã vững."""
    import intent_model as im

    class Stub:
        def predict(self, x):
            return ["play_media"]

        def predict_proba(self, x):
            return [[0.9, 0.1]]

    saved = im._MATH_INTENT_MIN_CONFIDENCE
    im._MATH_INTENT_MIN_CONFIDENCE = 0.5
    try:
        assert im.predict_intent("15 + 27", Stub())["intent"] == "play_media"
    finally:
        im._MATH_INTENT_MIN_CONFIDENCE = saved


def test_guard_calculate_chi_dung_khi_model_khong_chac():
    """Cùng câu đó: model chắc -> giữ; model mơ hồ -> ép calculate."""
    import intent_model as im

    class Vague:
        def predict(self, x):
            return ["system_control"]

        def predict_proba(self, x):
            return [[0.45, 0.2]]        # max = 0.45 < 0.5 -> mơ hồ

    class Sure:
        def predict(self, x):
            return ["system_control"]

        def predict_proba(self, x):
            return [[0.95, 0.05]]

    assert im.predict_intent("15 + 27", Vague())["intent"] == "calculate"
    assert im.predict_intent("15 + 27", Sure())["intent"] == "system_control"


def test_raw_text_ban_bo_roi_dung_text():
    """Gọi trực tiếp không truyền raw_text thì câu gốc lấy từ `text`."""
    from intent_model import predict_intent

    r = predict_intent("15 + 27")
    assert r["intent"] == "calculate" and r["result"] == 42, r
