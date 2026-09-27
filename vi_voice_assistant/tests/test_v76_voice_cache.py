"""Test cho bản v7.6 (1) - kho giọng đọc sẵn phải TẠO ĐƯỢC bằng một lệnh.

Từ v6 tới v7.5, `voice_cache/` chỉ có CHIỀU ĐỌC: `speak()` tìm trong `index.csv`,
tài liệu hướng dẫn người dùng "đặt mp3 vào đó", nhưng KHÔNG có lệnh nào tạo ra
file + chỉ mục (lệnh cũ `train_tts.py cache` đã bị bỏ). Bản này thêm
`paths.atomic_write_text()` (ghi `index.csv` an toàn), các "writer" (gTTS /
espeak-ng / pyttsx3 / piper / `say`) và `tts.prewarm()` + CLI `tts.py --cache`.

Kiểm tra theo hướng "hợp đồng hai chiều": thứ `prewarm` ghi ra thì
`speak()`/`_load_voice_cache()` PHẢI đọc lại được - lệch nhau một bước chuẩn hoá
khoá thôi là cache hỏng im lặng vĩnh viễn, không ai thấy gì sai.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

PKG_DIR = Path(__file__).resolve().parent.parent          # .../vi_voice_assistant
REPO_ROOT = PKG_DIR.parent
sys.path.insert(0, str(PKG_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _env(home: Path) -> dict:
    """Mọi thứ trợ lý ghi phải nằm trong `home`, không phiêu vào repo."""
    return {**os.environ, "VI_ASSISTANT_HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(PKG_DIR)}


def _run_tts(args, home, timeout=180):
    return subprocess.run([sys.executable, str(PKG_DIR / "tts.py"), *args],
                          cwd=str(REPO_ROOT), capture_output=True, text=True,
                          timeout=timeout, env=_env(home))


def _fake_writer():
    """Writer giả: ghi đủ byte để được coi là file có nội dung, không cần audio."""
    calls = []

    def write(text, out):
        calls.append(str(text))
        Path(out).write_bytes(b"RIFF" + b"\0" * 512 + str(text).encode("utf-8"))
        return True

    return write, calls


@pytest.fixture
def tts_mod():
    import tts

    tts._voice_cache_index = None
    yield tts
    tts._voice_cache_index = None


@pytest.fixture
def writers(tts_mod, monkeypatch):
    """Khoá danh sách writer về MỘT writer giả - test không phụ thuộc máy."""
    write, calls = _fake_writer()
    monkeypatch.setattr(tts_mod, "_WRITERS", (("fake", ".wav", write, lambda: True),))
    return calls


# ---------------------------------------------------------------------------
# 1. paths.atomic_write_text - nen tang ghi file
# ---------------------------------------------------------------------------
def test_atomic_write_text_tao_thu_muc_va_ghi_dung_noi_dung(tmp_path):
    import paths

    target = tmp_path / "sub" / "index.csv"
    paths.atomic_write_text(target, "a,b\nc,d\n")
    assert target.read_text(encoding="utf-8") == "a,b\nc,d\n"
    assert [p.name for p in target.parent.iterdir()] == ["index.csv"]


def test_atomic_write_text_khong_de_lai_file_tam_khi_loi(tmp_path, monkeypatch):
    """Lỗi giữa chừng: file cũ còn nguyên, không có rác `.index_tmp_` nằm lại."""
    import paths

    target = tmp_path / "index.csv"
    paths.atomic_write_text(target, "cu\n")

    def boom(fd, mode, **kwargs):
        os.close(fd)
        raise OSError("đĩa hỏng")

    monkeypatch.setattr(paths.os, "fdopen", boom)
    with pytest.raises(OSError, match="đĩa hỏng"):
        paths.atomic_write_text(target, "mới\n")

    assert target.read_text(encoding="utf-8") == "cu\n"
    assert list(tmp_path.glob("*_tmp_*")) == []


def test_atomic_write_text_ghi_de_khong_gi_lai_dong_cu(tmp_path):
    """Mở ``"w"`` trực tiếp là kiểu hay sai: ghi lại PHẢI thay hẳn nội dung."""
    import paths

    target = tmp_path / "x.csv"
    paths.atomic_write_text(target, "dai hon chut\n" * 30)
    paths.atomic_write_text(target, "mot dong\n")
    assert target.read_text(encoding="utf-8") == "mot dong\n"


def test_json_va_text_cung_mot_ghi_nho(tmp_path):
    """`atomic_write_json` đi qua `atomic_write_text` (một chỗ ghi đĩa duy nhất)."""
    import inspect

    import paths

    body = inspect.getsource(paths.atomic_write_json)
    assert "atomic_write_text" in body
    code = body.split('"""')[-1]                          # docstring duoc ke den, loi khong
    assert "os.replace" not in code and "os.fsync" not in code, code
    assert "tempfile.mkstemp" not in code
    target = tmp_path / "c.json"
    paths.atomic_write_json(target, {"a": [1, 2]})
    assert target.read_text(encoding="utf-8").endswith("}\n")


# ---------------------------------------------------------------------------
# 2. prewarm: ghi file + index ma chinh `speak()` doc lai
# ---------------------------------------------------------------------------
def test_prewarm_ghi_file_va_index_csv(tts_mod, writers, tmp_path):
    result = tts_mod.prewarm(["mở youtube", "tắt máy"], out_dir=tmp_path)
    assert result["written"] == 2 and result["failed"] == 0, result
    rows = tts_mod._read_cache_index(tmp_path)
    assert sorted(k for k, _f in rows) == ["mở youtube", "tắt máy"], rows
    for key, fname in rows:
        assert (tmp_path / fname).is_file(), (key, fname)


def test_prewarm_gop_trung_va_loai_cau_rong(tts_mod, writers, tmp_path):
    result = tts_mod.prewarm(["Mở YouTube", "  mở youtube  ", "mở youtube", "", "   ", None, 12],
                             out_dir=tmp_path)
    texts = [d["text"] for d in result["detail"]]
    assert result["requested"] == 2, result               # "mở youtube" + "12"
    assert texts == ["mở youtube", "12"], texts


def test_cache_hit_sau_khi_prewarm(tts_mod, writers, tmp_path, monkeypatch):
    """Vòng tròn thật: prewarm -> `speak()` phát file cache, không gọi engine.

    Khoá phải khớp SAU chuẩn hoá (hoa/thượng + khoảng trắng kép): đây là chỗ cache
    hỏng im lặng, nên thử bằng chính `speak()` chứ không chỉ bằng bảng tra.
    """
    tts_mod.prewarm(["chúc ngủ ngon"], out_dir=tmp_path)
    monkeypatch.setattr(tts_mod, "VOICE_CACHE_DIR", tmp_path)
    monkeypatch.setattr(tts_mod, "ENABLED", True)   # khong phu thuoc test chay truoc
    tts_mod._voice_cache_index = None
    played = []
    monkeypatch.setattr(tts_mod, "_play_audio",
                        lambda path: played.append(Path(str(path)).name) or True)

    called = []
    monkeypatch.setattr(tts_mod, "_try_engine", lambda *a, **k: called.append(a) or False)

    tts_mod.speak("CHÚC   ngủ NGON")     # `speak()` tra ve None - do la hop dong cua no
    assert len(played) == 1 and played[0].endswith(".wav"), played
    assert called == [], "van con goi engine du cache da co file"


def test_prewarm_lan_hai_bo_qua(tts_mod, writers, tmp_path):
    first = tts_mod.prewarm(["hẹn giờ 7 giờ"], out_dir=tmp_path)
    second = tts_mod.prewarm(["hẹn giờ 7 giờ"], out_dir=tmp_path)
    assert first["written"] == 1 and second["skipped"] == 1 and second["written"] == 0
    assert second["detail"][0]["file"] == first["detail"][0]["file"]


def test_prewarm_force_tao_lai_du_da_co(tts_mod, writers, tmp_path):
    tts_mod.prewarm(["hẹn giờ 7 giờ"], out_dir=tmp_path)
    before = len(writers)
    forced = tts_mod.prewarm(["hẹn giờ 7 giờ"], out_dir=tmp_path, force=True)
    assert forced["written"] == 1 and len(writers) == before + 1


def test_prewarm_cong_vao_khong_xoa_dong_cu(tts_mod, writers, tmp_path):
    """Dòng người dùng đặt tay phải còn: `index.csv` là file HỌ sửa được."""
    import paths

    paths.atomic_write_text(tmp_path / "index.csv", "cau cu, cu.wav\n")
    (tmp_path / "cu.wav").write_bytes(b"\0" * 200)
    tts_mod.prewarm(["cau moi"], out_dir=tmp_path)
    rows = tts_mod._read_cache_index(tmp_path)
    assert rows[0] == ("cau cu", "cu.wav"), rows
    assert rows[-1][0] == "cau moi", rows


def test_prewarm_dry_run_khong_cham_vao_dia(tts_mod, writers, tmp_path):
    target = tmp_path / "cache"
    result = tts_mod.prewarm(["một câu"], out_dir=target, dry_run=True)
    assert result["written"] == 1 and result["detail"][0]["status"] == "plan"
    assert result["detail"][0]["file"].endswith(".wav")
    assert not target.exists()
    assert writers == []


def test_prewarm_dau_vao_trong_khong_lam_gi(tts_mod, writers, tmp_path):
    for empty in ([], ["", "  "], None, (), ["\n"]):
        result = tts_mod.prewarm(empty, out_dir=tmp_path)
        assert result["requested"] == 0 and result["written"] == 0, empty
    assert writers == []


def test_prewarm_that_bai_khong_im_lang_cung_ly_do(tts_mod, monkeypatch, tmp_path):
    """Writer ném lỗi -> `detail` phải nói VÌ SAO (để CLI in ra, không đoán)."""
    def broken(text, out):
        raise tts_mod.TTSWriteError("chưa cài gTTS (pip install gTTS)")

    monkeypatch.setattr(tts_mod, "_WRITERS", (("gtts", ".mp3", broken, lambda: True),))
    result = tts_mod.prewarm("một câu", out_dir=tmp_path)
    assert result["failed"] == 1 and result["written"] == 0
    assert "chưa cài gTTS" in result["detail"][0]["reason"], result["detail"]


def test_prewarm_tu_choi_file_chi_co_header(tts_mod, monkeypatch, tmp_path):
    """File 44 byte (chỉ WAV header) KHÔNG được tính là cache hợp lệ.

    Đây là kiểu "thành công giả" của espeak/pyttsx3: exit 0, file có thật, không
    phát ra tiếng. Chặn ở tầng gọi để writer mới thêm sau này không lọt lưới.
    """
    def empty_wav(text, out):
        Path(out).write_bytes(b"RIFF" + b"\0" * 40)
        return True

    monkeypatch.setattr(tts_mod, "_WRITERS", (("rong", ".wav", empty_wav, lambda: True),))
    result = tts_mod.prewarm("câu này", out_dir=tmp_path)
    assert result["failed"] == 1, result
    assert list(tmp_path.glob("*.wav")) == [], "file rác bị bỏ lại trong kho"


def test_prewarm_thu_writer_kiep_theo_khi_mot_writer_hoang(tts_mod, monkeypatch, tmp_path):
    def first(text, out):
        raise OSError("backend chết")

    write, _calls = _fake_writer()
    monkeypatch.setattr(tts_mod, "_WRITERS", (
        ("hong", ".wav", first, lambda: True),
        ("fake", ".wav", write, lambda: True),
    ))
    result = tts_mod.prewarm("cần dự phòng", out_dir=tmp_path)
    assert result["written"] == 1 and result["detail"][0]["writer"] == "fake", result


def test_prewarm_dinh_engine_chi_goi_writer_do(tts_mod, monkeypatch, tmp_path):
    called = []

    def a(text, out):
        called.append("a")
        raise tts_mod.TTSWriteError("a khong chay duoc")

    def b(text, out):
        called.append("b")
        Path(out).write_bytes(b"\0" * 300)
        return True

    monkeypatch.setattr(tts_mod, "_WRITERS", (
        ("aaa", ".wav", a, lambda: True),
        ("bbb", ".wav", b, lambda: True),
    ))
    result = tts_mod.prewarm("một câu", out_dir=tmp_path, engine="bbb")
    assert result["written"] == 1 and called == ["b"], called


def test_prewarm_khoa_engine_khong_ton_tai_thi_raise(tts_mod, writers, tmp_path):
    with pytest.raises(ValueError, match="Không có writer"):
        tts_mod.prewarm("câu", out_dir=tmp_path, engine="khong_co_that")
    assert writers == []


def test_prewarm_lam_moi_bang_tra_khong_can_khoi_dong_lai(tts_mod, writers, tmp_path, monkeypatch):
    """Ghi cache xong thì `speak()` lần sau thấy ngay (cache index phải được reset)."""
    monkeypatch.setattr(tts_mod, "VOICE_CACHE_DIR", tmp_path)
    tts_mod._voice_cache_index = None
    assert tts_mod._load_voice_cache() == {}
    tts_mod.prewarm(["câu vừa tạo xong"], out_dir=tmp_path)
    assert "câu vừa tạo xong" in tts_mod._load_voice_cache(), tts_mod._load_voice_cache()


# ---------------------------------------------------------------------------
# 3. khoa & ten file: hai ben phai khop, va ten phai an toan tren Windows
# ---------------------------------------------------------------------------
def test_cache_key_chuan_hoa_giong_het_choi_doc(tts_mod):
    key = tts_mod._cache_key
    assert key("  Mở   YouTube ") == "mở youtube"
    assert key("a\t\nb") == "a b"
    assert key(12) == "12" and key(None) == ""
    # khoa sinh ra tu prewarm va khoa `speak()` tim PHAI giong het
    assert key("CHÚC   ngủ NGON") == "chúc ngủ ngon"


def test_cache_name_khong_va_cham_ma_doc_duoc(tts_mod):
    name_a = tts_mod._cache_name("mo youtube", ".wav")
    name_b = tts_mod._cache_name("mo  youtube", ".wav")
    assert name_a != name_b, (name_a, name_b)
    assert name_a.startswith("mo_youtube-") and name_a.endswith(".wav")
    assert len(name_a) <= 48 + 1 + 8 + 4, name_a
    # Windows: ten danh riêng + ky tu cam khong duoc xuyen qua ten file
    risky = tts_mod._cache_name('con.txt <a>/b\\c:d"e|f*g?h', ".mp3")
    assert "<" not in risky and ":" not in risky and "/" not in risky
    assert not risky.lower().startswith("con."), risky


def test_writer_for_va_available_writers(tts_mod, monkeypatch):
    assert tts_mod.writer_for("GTTS")[0] == "gtts"          # khong phan biet hoa/thuong
    assert tts_mod.writer_for(None) is None                   # kieu rac -> None, khong crash
    assert tts_mod.writer_for("khong_co_that") is None

    def unavailable():
        return False

    monkeypatch.setattr(tts_mod, "_WRITERS", (
        ("aaa", ".wav", lambda t, o: True, unavailable),
        ("bbb", ".wav", lambda t, o: True, lambda: True),
    ))
    assert tts_mod.available_writers() == ["bbb"]


def test_module_present_khong_chay_code_cua_thu_vien(tts_mod):
    assert tts_mod._module_present("json") is True
    assert tts_mod._module_present("module_khong_bao_gio_co_xyz") is False
    assert tts_mod._binary_present("khong_lenh_nay_khong_ton_tai_xyz") is False


# ---------------------------------------------------------------------------
# 4. chuan hoa dau vao: danh sach / file moi dong mot cau
# ---------------------------------------------------------------------------
def test_cache_texts_tu_file_moi_dong_mot_cau(tts_mod, tmp_path):
    listing = tmp_path / "cau.txt"
    listing.write_bytes("\ufeffmở youtube\r\nhôm nay thứ mấy\r\n\r\n   \n".encode("utf-8"))
    assert tts_mod._cache_texts([listing]) == ["mở youtube", "hôm nay thứ mấy"]


def test_cache_texts_chiu_duoc_generator_va_nhieu_dong(tts_mod):
    assert tts_mod._cache_texts(iter(["x", "y", "x"])) == ["x", "y"]
    assert tts_mod._cache_texts("a\nb\n  \nc") == ["a", "b", "c"]
    assert tts_mod._cache_texts(123) == ["123"]
    assert tts_mod._cache_texts(None) == []


def test_cache_texts_file_khong_ton_tai_bao_dung_duong_dan(tts_mod, tmp_path):
    missing = tmp_path / "khong_co.txt"
    with pytest.raises(FileNotFoundError, match="danh sách câu"):
        tts_mod._cache_texts([missing])


def test_prewarm_doc_file_danh_sach_va_ghi_du(tts_mod, writers, tmp_path):
    listing = tmp_path / "cau.txt"
    listing.write_text("mở youtube\nhẹn 7 giờ\n", encoding="utf-8")
    out = tmp_path / "cache"
    result = tts_mod.prewarm([listing], out_dir=out)
    assert result["written"] == 2, result
    assert [d["text"] for d in result["detail"]] == ["mở youtube", "hẹn 7 giờ"]


# ---------------------------------------------------------------------------
# 5. CLI (subprocess that) - lenh phai ho tro du cho nguoi dung dung mot minh
# ---------------------------------------------------------------------------
def test_cli_list_tren_kho_trong(tmp_path):
    proc = _run_tts(["--list"], tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Kho giọng: 0 mục" in proc.stdout, proc.stdout


def test_cli_cache_thieu_noi_dung_bao_cach_dung(tmp_path):
    proc = _run_tts(["--cache"], tmp_path)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "--text" in proc.stdout and "--file" in proc.stdout, proc.stdout


def test_cli_cache_dry_run_in_ke_hoach(tmp_path):
    proc = _run_tts(["--cache", "--text", "xin chào bạn", "--out", str(tmp_path / "c"),
                     "--dry-run"], tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Sẽ tạo 1 mục" in proc.stdout, proc.stdout
    assert not (tmp_path / "c").exists()


def test_cli_engines_liet_ke_ca_writer(tmp_path):
    proc = _run_tts(["--engines"], tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Writer ghi ra file" in proc.stdout, proc.stdout
    assert "Engine khả dụng" in proc.stdout


def test_cli_engine_khong_hop_le_bi_argparse_chan(tmp_path):
    proc = _run_tts(["--cache", "--text", "a", "--engine", "piper_gia"], tmp_path)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "invalid choice" in (proc.stdout + proc.stderr).lower()


# ---------------------------------------------------------------------------
# 6. vi-doctor phai noi ve kho giong (truoc day im lang hoan toan)
# ---------------------------------------------------------------------------
def test_doctor_bao_dieu_kho_giong_trong(tts_mod, monkeypatch):
    import diagnostic

    monkeypatch.setattr(tts_mod, "_load_voice_cache", lambda: {})
    monkeypatch.setattr(tts_mod, "available_writers", lambda: [])
    rows = diagnostic._voice_cache_rows()
    assert rows and all(mark == diagnostic.INFO for mark, _ in rows), rows
    assert any("gTTS" in line for _m, line in rows), rows


def test_doctor_huong_dan_lenh_khi_may_tao_duoc(tts_mod, monkeypatch):
    import diagnostic

    monkeypatch.setattr(tts_mod, "_load_voice_cache", lambda: {})
    monkeypatch.setattr(tts_mod, "available_writers", lambda: ["espeak"])
    rows = diagnostic._voice_cache_rows()
    text = " ".join(line for _m, line in rows)
    assert "espeak" in text and diagnostic.PREWARM_CMD in text, rows


def test_doctor_dem_muc_khi_kho_da_co(tts_mod, monkeypatch, tmp_path):
    import diagnostic

    monkeypatch.setattr(tts_mod, "_load_voice_cache",
                        lambda: {"a": tmp_path / "a.wav", "b": tmp_path / "b.wav"})
    monkeypatch.setattr(tts_mod, "VOICE_CACHE_DIR", tmp_path)
    rows = diagnostic._voice_cache_rows()
    assert rows[0][0] == diagnostic.OK and "2 mục" in rows[0][1], rows


def test_dong_thong_tin_khong_dem_vao_canh_bao(tmp_path):
    """[i] là thông tin thuần: không được thành [!] (đỏ mắt) hay [X]."""
    import diagnostic

    report = diagnostic.run_checks()
    marks = [mark for rows in report["sections"].values() for mark, _line in rows]
    assert marks.count(diagnostic.BAD) == report["problems"]
    assert marks.count(diagnostic.WARN) == report["warnings"]
    assert diagnostic.INFO not in (diagnostic.WARN, diagnostic.BAD)


def test_doctor_khong_chet_khi_tts_lam_lenh(tts_mod, monkeypatch):
    """Bộ kiểm tra giọng nói mà nổ thì `vi-doctor` vẫn phải in được phần còn lại."""
    import diagnostic

    def boom():
        raise RuntimeError("tts hong")

    monkeypatch.setattr(tts_mod, "_load_voice_cache", boom)
    rows = diagnostic._voice_cache_rows()
    assert rows and rows[0][0] == diagnostic.WARN and "tts hong" in rows[0][1], rows
