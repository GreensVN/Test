"""Test cho bản v7.5 - điểm vào công cộng phải chịu được đầu vào thật.

Bản này sửa năm nhóm lỗi cùng một kiểu: hàm ký mong `str` nhưng giá trị đến từ file
JSON / người gọi khác lại là số, `None`, danh sách.

  1. `intent_model.predict_intent(123)` -> AttributeError ở `extract_entity`
     (`(text or "").strip()`), trong khi chính nó đã ép kiểu ở `normalize_text`;
  2. `tts.speak(123)` crash, còn `speak(None)`/`speak("")` in ra
     "[TRỢ LÝ] None" - màn hình báo trợ lý nói "None" trong khi nó nói gì cả;
  3. `nlu_advanced.split_commands(123)` / `understand(123)` -> TypeError của `re`
     ("expected string or bytes-like object, got 'int'") - không nói gì về cách
     sửa; `understand("")` thì TRẢ VỀ MỘT LỆNH BỊA (open_website/unknown);
  4. `config.json` hỏng (danh sách, thiếu dấu phẩy) giết `executor` ngay lúc import
     -> MỌI lệnh của trợ lý chết bằng traceback, kể cả `--doctor`;
  5. `--once ""` bị lặng lẽ chuyển qua REPL (script/CI treo), vì `args.once or
     args.text` không phân biệt được "rỗng" với "không có".

Kiểm tra cuối: `sanitize_filename` (tên dành riêng của Windows + giới hạn byte).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent.parent          # .../vi_voice_assistant
REPO_ROOT = PKG_DIR.parent
sys.path.insert(0, str(PKG_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _env(home: Path) -> dict:
    """Moi thu Nghiep vu phai ghi vao `home`, khong phiet vao repo."""
    return {**os.environ, "VI_ASSISTANT_HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(PKG_DIR)}


def _run_main(args, home, stdin="", timeout=180):
    return subprocess.run([sys.executable, str(PKG_DIR / "main.py"), *args],
                          cwd=str(REPO_ROOT), capture_output=True, text=True,
                          input=stdin, timeout=timeout, env=_env(home))


# ---------------------------------------------------------------------------
# 1. tang hieu y: khong chet vi kieu, khong bia lenh khi cau rong
# ---------------------------------------------------------------------------
def test_predict_intent_chiu_duoc_gia_tri_khong_phai_chuoi():
    import intent_model

    for value in (123, None, 1.5, ["a"], {"k": "v"}, True, b"x"):
        result = intent_model.predict_intent(value)
        assert isinstance(result, dict), value
        assert set(result) >= {"intent", "target", "confidence"}, result


def test_extract_entity_khong_bao_gi_ca_khong_chet():
    import intent_model

    assert intent_model.extract_entity(123, "app") == "123"
    # `None` -> chuoi rong: intent "app" khong tim thay ung dung nao -> "unknown",
    # do la duong ve cua chuc nang (khong phai crash), test git lai de no khong doi.
    assert intent_model.extract_entity(None, "app") == "unknown"
    assert intent_model.extract_entity("mở youtube", "app") == "youtube"


def test_replace_number_words_va_split_commands_ep_kieu_truoc_regex():
    import intent_model
    import nlu_advanced

    assert intent_model.replace_number_words(123) == "123"
    assert intent_model.replace_number_words(None) == ""
    assert nlu_advanced.split_commands(123) == ["123"]
    # cau lenh that van cat dung - ep kieu khong duoc thay doi hanh vi cu
    assert nlu_advanced.split_commands("mở chrome rồi tắt máy") == ["mở chrome", "tắt máy"]


def test_understand_cau_rong_tra_ve_danh_sach_rong_khong_bia_lenh():
    """`understand("")` tung tra ve {'intent':'open_website','target':'unknown'}.

    Ai lap qua ket qua roi thuc thi (script, `--json`) se mo that mot website ten
    la "unknown". Khong co noi dung thi khong co lenh.
    """
    import nlu_advanced

    nlu = nlu_advanced.NLU()
    for blank in ("", "   ", "\n\t ", None):
        assert nlu.understand(blank) == [], blank
    got = nlu.understand(123)
    assert isinstance(got, list) and len(got) == 1
    assert "intent" in got[0]


# ---------------------------------------------------------------------------
# 2. tts: khong crash, va khong in "None" nhu the tro ly vua noi
# ---------------------------------------------------------------------------
def test_speak_khong_chet_voi_dau_vao_khong_phai_chuoi(capsys):
    import tts

    tts.set_enabled(True)
    try:
        for value in (123, None, "", "   ", ["a", "b"], 0):
            assert tts.speak(value) is None, value
    finally:
        tts.set_enabled(False)


def test_speak_khong_in_gi_khi_cau_rong(capsys):
    import tts

    for blank in ("", "   ", "\n", None):
        capsys.readouterr()
        tts.speak(blank)
        out = capsys.readouterr().out
        assert out == "", f"cau rong khong duoc in gi ca, duoc: {out!r}"


def test_speak_in_cau_da_cat_khoang_trang(capsys):
    import tts

    capsys.readouterr()
    tts.speak("  xin chào  ", show=True)
    assert capsys.readouterr().out.strip() == "[TRỢ LÝ] xin chào"


def test_speech_text_dung_dan_duoc_renhan_duoc():
    import tts

    assert tts._speech_text("  a  ") == "a"
    assert tts._speech_text(None) == ""
    assert tts._speech_text(45) == "45"


# ---------------------------------------------------------------------------
# 3. config hong: bao cho ro, nhung van PHAI con chay duoc lenh khac
# ---------------------------------------------------------------------------
def test_load_config_safe_tra_ve_mac_dinh_kem_loi(tmp_path):
    import config

    bad = tmp_path / "config.json"
    bad.write_text("[1, 2, 3]", encoding="utf-8")
    cfg, error = config.load_config_safe(bad)
    assert error, "phai tra ve mo loi de in ra"
    assert cfg == config.DEFAULT_CONFIG
    assert "list" in error

    good = tmp_path / "ok.json"
    good.write_text(json.dumps({"wake_words": ["này"]}), encoding="utf-8")
    cfg2, error2 = config.load_config_safe(good)
    assert error2 is None
    assert cfg2["wake_words"] == ["này"]


def test_config_hong_khong_giet_moi_lenh(tmp_path):
    """Vu that: file sai kieu -> `import executor` RuntimeErrors, CLI chet.

    Sau v7.5: dung gia tri mac dinh, IN canh bao ro (de nguoi dung biet file cua
    ho dang bi bo qua), va lenh van chay.
    """
    (tmp_path / "config.json").write_text('{"volume": 0.5,}', encoding="utf-8")
    proc = _run_main(["--once", "mở youtube", "--dry-run", "--no-banner"], tmp_path)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, (proc.returncode, out[-500:])
    assert "config.json không dùng được" in out, out[-500:]
    assert "youtube" in out, "lenh phai duoc thuc hien duoc duoi config mac dinh"
    assert "Traceback" not in out, out[-400:]


def test_executor_tu_chap_nhan_config_hong(tmp_path, monkeypatch):
    monkeypatch.setenv("VI_ASSISTANT_HOME", str(tmp_path))
    (tmp_path / "config.json").write_text('"khong phai object"', encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(PKG_DIR))
    code = (
        "import json, executor, config\n"
        "print(json.dumps({"
        "'co_loi': bool(executor.CONFIG_ERROR),"
        "'day_du_khoa': set(config.DEFAULT_CONFIG) <= set(executor.CONFIG)}))"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(tmp_path),
                          capture_output=True, text=True, timeout=120,
                          env=_env(tmp_path))
    assert proc.returncode == 0, proc.stderr[-400:]
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    assert data == {"co_loi": True, "day_du_khoa": True}, proc.stdout[-300:]
    assert "Traceback" not in proc.stdout + proc.stderr, proc.stderr[-300:]


# ---------------------------------------------------------------------------
# 4. CLI: `--once ""` phai thoat, khong im lang roi roi vao hoi thoai
# ---------------------------------------------------------------------------
def test_once_voi_cau_rong_thoat_ngay_khong_vao_repl(tmp_path):
    for blank in ("", "   ", "\t"):
        proc = _run_main(["--once", blank, "--dry-run"], tmp_path, stdin="")
        out = proc.stdout + proc.stderr
        assert proc.returncode == 0, (blank, proc.returncode, out[-300:])
        assert "Câu rỗng" in out, (blank, out[-300:])
        assert "Bạn nói" not in out, "khong duoc roi vao REPL"
        assert "Traceback" not in out


def test_once_voi_cau_that_van_chay(tmp_path):
    proc = _run_main(["--once", "mở youtube", "--dry-run", "--no-banner"], tmp_path)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, (proc.returncode, out[-400:])
    assert "youtube" in out
    assert "Câu rỗng" not in out


def test_one_shot_helper_phan_biet_khong_co_va_rong():
    import argparse

    import main as assistant_main

    f = assistant_main._one_shot_text
    assert f(argparse.Namespace(once=None, text=None)) == (None, False)
    assert f(argparse.Namespace(once="", text=None)) == ("", True)
    assert f(argparse.Namespace(once="   ", text=None)) == ("", True)
    assert f(argparse.Namespace(once=None, text="mở youtube")) == ("mở youtube", False)
    assert f(argparse.Namespace(once="", text="mở youtube")) == ("", True)


# ---------------------------------------------------------------------------
# 5. ten file: Windows reserved names + gioi han byte + duong dan
# ---------------------------------------------------------------------------
def test_sanitize_filename_chan_ten_windows_danh_rieng():
    from text_utils import sanitize_filename

    for reserved in ("CON", "PRN", "AUX", "NUL", "com1", "LPT9", "CON.txt", "aux.json"):
        out = sanitize_filename(reserved)
        assert out.startswith("_"), (reserved, out)
        assert out.lower().lstrip("_") == reserved.lower(), (reserved, out)
    # ten binh thuong khong bi cham
    assert sanitize_filename("ghi chu") == "ghi chu"
    assert sanitize_filename("contest") == "contest"       # 'con' nam trong tu khac
    assert sanitize_filename("my_aux_file") == "my_aux_file"


def test_sanitize_filename_khong_vuot_gioi_han_byte():
    from text_utils import sanitize_filename

    ascii_long = sanitize_filename("a" * 400)
    assert len(ascii_long.encode("utf-8")) <= 255
    vn = sanitize_filename("Hà Nội " * 80)
    raw = vn.encode("utf-8")
    assert len(raw) <= 255
    assert raw.decode("utf-8") == vn, "khong duoc cat giua ky tu"
    assert not vn.endswith((" ", ".")), vn[-4:]


def test_sanitize_filename_chiu_duoc_kieu_va_khong_di_ra_thu_muc():
    from text_utils import sanitize_filename

    assert sanitize_filename(123) == "123"
    assert sanitize_filename(None) == "untitled"
    assert sanitize_filename(["x"]) == "['_x_']" or sanitize_filename(["x"])   # chi can khong crash
    assert not isinstance(sanitize_filename(["x"]), list)
    # Khong di ra ngoai thu muc: `..` con lai trong MOT thanh phan thi vo hai
    # (khong phai duong dan), dieu can kiem tra la khong con `sep` nao.
    esc = sanitize_filename("../../etc/passwd")
    assert "/" not in esc and "\\" not in esc, esc
    assert Path(esc).name == esc, esc
    assert sanitize_filename("ab\x00cd") == "ab_cd"


def test_get_dataframe_khong_im_lang_bao_thieu_pandas(tmp_path):
    """Loi phai kem cach khac phuc hoac loi gioi thieu duong thay the."""
    import pytest

    dataset = pytest.importorskip("dataset")
    try:
        import pandas  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="pandas"):
            dataset.get_dataframe()
    else:
        df = dataset.get_dataframe()
        assert len(df) > 0
