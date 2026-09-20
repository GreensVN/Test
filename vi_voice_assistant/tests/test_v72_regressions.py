"""
Test hồi quy cho bản v7.2 - MỖI test gắn với một lỗi CÓ THẬT đã sửa.

Điểm khác biệt so với các file test khác: ở đây không kiểm tra "tính năng mới
chạy được", mà kiểm tra "lỗi cũ KHÔNG quay lại được". Vì vậy mỗi test đều có
chú thích ngắn mô tả triệu chứng trước khi sửa - đọc file này cũng là đọc lại
sổ nhật sử chữa của dự án.

Bao gồm:
  1. model lite: câu vô nghĩa không còn được "tự tin 50%" rồi thực thi bừa
  2. main.py: bảng lệnh điều khiển REPL (không còn chuỗi if/elif 20 nhánh)
  3. tts.py: engine sai tên phải báo, engine chết phải chuyển dự phòng
  4. executor.py: bảng lệnh hệ thống theo nền tảng + escape AppleScript
  5. executor.py: lời nhắc lưu/xoá trên đĩa (không mất khi tắt máy)
  6. nlu_advanced.py: ngưỡng tự tin đọc lại được từ config, giá trị hỏng không
     làm sập lúc import
  7. config.py: thông báo kiểm tra config cụ thể tới từng khoá
"""
import datetime
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import executor
import lite_model
import main
import nlu_advanced
import tts


# ----------------------------------------------------------------------------
# Fixture: model lite huấn luyện trên dataset thật của dự án (chạy ~1 giây)
# ----------------------------------------------------------------------------
def json_loads(path):
    """Đọc reminders.json (dạng list các lời nhắc còn hạn)."""
    return json.loads(path.read_text(encoding="utf-8"))


def json_dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


@pytest.fixture(scope="module")
def lite():
    from dataset import get_dataset_as_lists

    texts, labels = get_dataset_as_lists()
    return lite_model.LiteIntentModel().fit(texts, labels)


# ----------------------------------------------------------------------------
# 1. MODEL LITE: CÂU VÔ NGHĨA KHÔNG ĐƯỢC THỰC THI
# ----------------------------------------------------------------------------
# Trước v7.2, "asdfgh jklzxbv" được model lite chấm tự tin ~0.50 - CAO HƠN
# ngưỡng CONFIDENCE_ACCEPT (0.45) - nên trợ lý lẽ ra đã gọi hàm thật theo một
# câu hoàn toàn vô nghĩa. Nguyên nhân: softmax với temperature nhỏ khuếch đại
# khoảng cách log-prob, nên "không có bằng chứng" vẫn thành "tương đối chắc chắn".


def test_garbage_input_is_below_accept_threshold(lite):
    conf = lite.predict_one("asdfgh jklzxbv")[1]
    assert conf < nlu_advanced.CONFIDENCE_ACCEPT, (
        f"câu vô nghĩa vẫn tự tin {conf:.2f} -> sẽ bị thực thi bừa"
    )


def test_garbage_input_has_almost_no_dictionary_evidence(lite):
    assert lite.evidence_ratio("asdfgh jklzxbv") <= 0.05
    assert lite.evidence_ratio("qqq zzz www") == 0.0
    assert lite.evidence_ratio("") == 0.0


def test_real_command_keeps_full_confidence(lite):
    """Câu tiếng Việt thật không bị ảnh hưởng: bảo chứng = 1.0."""
    for sentence in ("mở chrome lên", "tắt máy tính", "thời tiết hà nội hôm nay"):
        assert lite.evidence_ratio(sentence) == 1.0, sentence
        assert lite.predict_one(sentence)[1] > 0.9, sentence


def test_predict_proba_dict_is_still_a_distribution(lite):
    """`predict_proba_dict` giữ nguyên phân phối softmax (tổng = 1); chỉ
    `predict_proba`/`predict_one` là đã nhân bảo chứng."""
    probs = lite.predict_proba_dict("mở chrome lên")
    assert sum(probs.values()) == pytest.approx(1.0)
    row = lite.predict_proba(["asdfgh jklzxbv"])[0]
    assert max(row) < nlu_advanced.CONFIDENCE_ACCEPT


def test_vocab_rebuilt_from_log_prob_for_old_model_files(lite):
    """File model cũ (không lưu từ điển) vẫn tính được bảo chứng."""
    state = lite.to_state()
    assert "vocab" not in state               # định dạng file không đổi
    revived = lite_model.LiteIntentModel.from_state(state)
    revived._vocab = set()                     # giả lập model vừa nạp từ đĩa
    assert revived.vocabulary_size() > 0
    assert revived.evidence_ratio("mở chrome lên") == 1.0


# ----------------------------------------------------------------------------
# 2. MAIN.PY: BẢNG LỆNH ĐIỀU KHIỂN REPL
# ----------------------------------------------------------------------------
# main() trước đây là một chuỗi ~20 nhánh if/elif nằm thẳng trong vòng lặp:
# thêm một lệnh là phải sửa vòng lặp, và hai lệnh "na ná" (vd "nhac" và
# "nhac lai") rất dễ che khuất nhau. Nay mỗi lệnh là một hàm đăng ký trong bảng.


class _FakeNlu:
    """Thế chỗ NLU thật: các lệnh điều khiển chỉ gọi vài method đơn giản."""

    def __init__(self):
        self.taught = []

    def teach(self, text, intent):
        self.taught.append((text, intent))
        return f"Đã học: {text!r} -> {intent}"


def test_exit_words_stop_the_loop(capsys):
    state = main.ReplState()
    for word in ("thoat", "thoát", "exit", "quit", "q"):
        state.stop = False
        assert main.handle_control_command(word, _FakeNlu(), state) is True
        assert state.stop is True, word
    assert "Tạm biệt!" in capsys.readouterr().out


def test_unknown_command_is_not_swallowed():
    """Câu nói bình thường phải TRẢ VỀ False để REPL đem đi phân tích intent.

    "giup" là lệnh có thật (bảng đăng ký từ khoá), nên câu chứa chữ "giúp" ở
    giữa vẫn phải lọt qua - đây chính là chỗ chuỗi if/elif cũ hay sai vì chỉ
    kiểm tra `in` thay vì so khớp nguyên câu.
    """
    state = main.ReplState()
    for sentence in ("mở chrome giup toi", "cho tôi xin trà sữa", "giúp tôi với"):
        assert main.handle_control_command(sentence, _FakeNlu(), state) is False, sentence
    assert main.handle_control_command("giup", _FakeNlu(), state) is True


def test_control_tables_cover_documented_commands():
    """Mọi lệnh ghi trong `help` đều phải có trong bảng (chống "lệnh in ra mà
    không tồn tại hàm xử lý")."""
    registered = set(main._CONTROL_COMMANDS)
    registered.update(prefix for pair in main._CONTROL_PREFIXES for prefix in pair[0])
    for word in ("help", "lich su", "nap lai", "he thong", "quen", "voice", "mic",
                 "nhac nho", "huy nhac", "test"):
        assert word in registered, word


def test_help_lists_the_reload_command(capsys):
    main.handle_control_command("help", _FakeNlu(), main.ReplState())
    out = capsys.readouterr().out
    assert "nap lai" in out and "day" in out


def test_teach_prefix_reaches_nlu(capsys):
    nlu = _FakeNlu()
    assert main.handle_control_command("day mo zinc = open_app", nlu, main.ReplState()) is True
    assert nlu.taught, "lệnh `day <cau> = <intent>` phải gọi nlu.teach()"
    taught_text, taught_intent = nlu.taught[-1]
    assert taught_intent == "open_app"
    assert "zinc" in taught_text
    assert "đã học" in capsys.readouterr().out.lower() or capsys.readouterr().out


# ----------------------------------------------------------------------------
# 3. TTS: ENGINE INHỈNG PHẢI ĐƯỢC BÁO, ENGINE CHẾT PHẢI CHUYỂN DỰ PHÒNG
# ----------------------------------------------------------------------------


def test_print_engine_means_silence(monkeypatch):
    monkeypatch.setattr(tts, "ENGINE", "print")
    assert tts._engine_order() == []


def test_unknown_engine_name_is_reported(monkeypatch, caplog):
    """`--engine pipper` trước đây bị hiểu nhầm là auto HOÀN TOÀN ÂM THẦM."""
    with caplog.at_level("WARNING", logger="tts"):
        monkeypatch.setattr(tts, "ENGINE", "pipper")
        order = tts._engine_order()
    assert len(order) > 1                      # vẫn rơi về auto để không mất tiếng
    assert "pipper" in caplog.text, "phải cảnh báo tên engine không hợp lệ"


def test_dead_engine_falls_over_to_next_one(monkeypatch):
    """Engine đầu tiên ném lỗi -> phải thử engine kế tiếp, không chết cả câu."""
    calls = []

    def broken(text):
        calls.append("broken")
        raise RuntimeError("pyttsx3 không có driver tiếng Việt")

    def working(text):
        calls.append("working")
        return True

    monkeypatch.setattr(tts, "ENGINE", "auto")
    monkeypatch.setattr(tts, "ENABLED", True)
    monkeypatch.setattr(tts, "_resolved_engine", None)
    monkeypatch.setattr(tts, "_speak_pyttsx3", broken, raising=False)
    monkeypatch.setattr(tts, "_speak_sapi", working, raising=False)
    monkeypatch.setattr(tts, "_speak_gtts", lambda text: False, raising=False)
    monkeypatch.setattr(tts, "_speak_piper", lambda text: False, raising=False)
    monkeypatch.setattr(tts, "_speak_macos", lambda text: False, raising=False)

    tts.speak("câu kiểm tra engine dự phòng")
    assert "working" in calls, "engine sau phải được gọi khi engine trước ném lỗi"
    assert tts._resolved_engine is working, "phải chốt lại engine sống được"


# ----------------------------------------------------------------------------
# 4. EXECUTOR: BẢNG LỆNH HỆ THỐNG + ESCAPE CHUỖI
# ----------------------------------------------------------------------------


def _assert_argv_table(table, *, nested, label):
    """Mọi lệnh trong bảng phải là argv (list[str]) - truyền chuỗi nguyên văn
    có dấu cách cho Popen không qua shell là lỗi chạy-lệnh-im-lặng."""
    assert table, f"{label}: bảng rỗng = mất chức năng"
    for target, commands in table.items():
        assert isinstance(target, str) and target
        candidates = commands if nested else [commands]
        for cmd in candidates:
            assert isinstance(cmd, list) and cmd, f"{label}/{target}: {cmd!r}"
            assert all(isinstance(a, str) for a in cmd), f"{label}/{target}: {cmd!r}"


def test_platform_tables_have_consistent_shape():
    """+ Windows/macOS: một mục tiêu = MỘT lệnh (dùng thẳng, không cần thử lại).
    + Linux: một mục tiêu = NHIỀU lệnh dự phòng (wpctl -> pactl -> amixer),
      vì DE nào có lệnh nào; handler chạy lệnh đầu tiên tồn tại trên máy.
    """
    _assert_argv_table(executor.COMMANDS_WINDOWS, nested=False, label="win")
    _assert_argv_table(executor.COMMANDS_MACOS, nested=False, label="mac")
    _assert_argv_table(executor.VOLUME_MACOS, nested=False, label="mac-vol")
    _assert_argv_table(executor.COMMANDS_LINUX, nested=True, label="linux")
    _assert_argv_table(executor.VOLUME_LINUX, nested=True, label="linux-vol")
    assert set(executor._SYSTEM_HANDLERS) == {"Windows", "Darwin", "Linux"}
    assert all(callable(fn) for fn in executor._SYSTEM_HANDLERS.values())


def test_unsupported_target_returns_none_not_true():
    assert executor._system_control_macos("khong_ton_tai") is None
    assert executor._system_control_linux("khong_ton_tai") is None


def test_handlers_return_none_when_platform_cannot_do_it():
    """None = "nền tảng này không làm được" -> tầng trên in [BỎ QUA] thay vì
    nói dối "đã thực thi" như bản cũ (mọi nhánh lạ đều return True)."""
    for handler in executor._SYSTEM_HANDLERS.values():
        assert handler("mot_lenh_khong_co_trong_bang") is None


def test_screenshot_path_is_timestamped(tmp_path, monkeypatch):
    """Không ghi đè ảnh cũ: mỗi tấm một tên theo timestamp (đề tên file là
    trách nhiệm của executor, trước đây hard-code "screenshot.png")."""
    monkeypatch.setattr(executor, "HOME", str(tmp_path))
    first = executor._screenshot_path()
    assert first.parent == tmp_path / "Pictures"
    assert re.fullmatch(r"screenshot_\d{8}_\d{6}\.png", first.name)
    assert first.parent.is_dir()


def test_osascript_escape_orders_backslash_first():
    """LỖI BẢO MẬT v7.0: escape ``"`` TRƯỚC ``\\`` khiến ``\\"`` bị nhân đôi ->
    chuỗi đóng sớm và nội dung do người dùng gõ chạy thành mã AppleScript."""
    evil = 'a\\" with title \\"PWNED\\"'
    escaped = executor._escape_osascript(evil)
    assert "\\\\" in escaped
    # sau khi escape, không còn dấu nháy kép "trần" nào có thể đóng chuỗi
    bare_quotes = re.findall(r'(?<!\\)"', escaped)
    assert not bare_quotes, escaped


def test_powershell_single_quote_escape_doubles_quotes():
    assert executor._escape_powershell_single_quoted("it's") == "it''s"


# ----------------------------------------------------------------------------
# 5. LỜI NHẮC: LƯU / XOÁ TRÊN ĐĨA
# ----------------------------------------------------------------------------


@pytest.fixture
def isolated_reminders(tmp_path, monkeypatch):
    """Chuyển file lời nhắc + danh sách đang chạy sang vùng test, trả về path."""
    path = tmp_path / "reminders.json"
    monkeypatch.setattr(executor, "REMINDERS_PATH", path)
    with executor.ACTIVE_REMINDERS_LOCK:
        saved = list(executor.ACTIVE_REMINDERS)
        for item in saved:
            timer = item.get("timer")
            if timer is not None:
                timer.cancel()
        executor.ACTIVE_REMINDERS.clear()
    yield path
    with executor.ACTIVE_REMINDERS_LOCK:
        for item in list(executor.ACTIVE_REMINDERS):
            timer = item.get("timer")
            if timer is not None:
                timer.cancel()
        executor.ACTIVE_REMINDERS[:] = saved


def test_reminders_survive_a_restart(isolated_reminders):
    """Trước v7.2, `huy nhac` chỉ xoá trong bộ nhớ: lần sau bật lên lời nhắc
    "quay lại như chưa từng bị huỷ", và ngược lại lời nhắc đang chờ biến mất
    khi tắt máy."""
    run_at = datetime.datetime.now() + datetime.timedelta(hours=3)
    executor._schedule_reminder("uống thuốc", run_at, persist=True)
    assert "uống thuốc" in isolated_reminders.read_text(encoding="utf-8")

    with executor.ACTIVE_REMINDERS_LOCK:
        executor.ACTIVE_REMINDERS.clear()
    assert executor.restore_reminders() >= 1
    assert any("uống thuốc" in item.get("task", "") for item in executor.ACTIVE_REMINDERS)


def test_cancel_reminder_persists_the_deletion(isolated_reminders):
    run_at = datetime.datetime.now() + datetime.timedelta(hours=2)
    executor._schedule_reminder("nộp báo cáo", run_at, persist=True)
    assert json_loads(isolated_reminders), "phải có lời nhắc trên đĩa trước đã"

    cancelled = executor.cancel_reminder("báo cáo")
    assert cancelled, "cancel_reminder phải trả về lời nhắc đã huỷ"
    assert json_loads(isolated_reminders) == [], "file phải được ghi lại sau khi huỷ"


def test_expired_reminders_are_dropped_on_restore(isolated_reminders):
    """Lời nhắc quá hạn từ lần chạy trước không được "nổ" dồn dập khi bật máy."""
    now = datetime.datetime.now()
    isolated_reminders.write_text(json_dumps([
        {"task": "cũ", "at": (now - datetime.timedelta(days=1)).isoformat()},
        {"task": "mới", "at": (now + datetime.timedelta(hours=1)).isoformat()},
        "khong phai object",
        {"task": "thieu gio"},
    ]), encoding="utf-8")
    assert executor.restore_reminders() == 1
    assert [it["task"] for it in executor.ACTIVE_REMINDERS] == ["mới"]


# ----------------------------------------------------------------------------
# 6. NGƯỠNG TỰ TIN: GIÁ TRỊ HỎNG KHÔNG ĐƯỢC LÀM SẬP CHƯƠNG TRÌNH
# ----------------------------------------------------------------------------
# Trước v7.2, `float(_CONFIG_ACCEPT)` chạy ngào ngày lúc import module và nằm
# NGOÀI try/except -> một giá trị sửa tay sai trong config.json ném
# ValueError/TypeError ngay `import nlu_advanced`, chết cả main.py.


def test_broken_threshold_falls_back_to_default():
    accept, ask = nlu_advanced._read_thresholds({"confidence_accept": "0.45 phan tram",
                                                 "confidence_ask": None})
    assert accept == pytest.approx(nlu_advanced._DEFAULT_ACCEPT)
    assert ask == pytest.approx(nlu_advanced._DEFAULT_ASK)


def test_thresholds_are_swapped_if_inverted():
    """Cấu hình ngược (accept < ask) phải được hiệu chỉnh lại, không giữ nguyên."""
    accept, ask = nlu_advanced._read_thresholds({"confidence_accept": 0.2, "confidence_ask": 0.8})
    assert accept >= ask or accept == pytest.approx(nlu_advanced._DEFAULT_ACCEPT)


def test_refresh_thresholds_syncs_the_module():
    """Lệnh `nap lai` phải đổi được ngưỡng của tầng NLU (trước đây chỉ executor
    được cập nhật, người dùng sửa config rồi nạp lại vẫn thấy hành vi cũ)."""
    old_accept, old_ask = nlu_advanced.CONFIDENCE_ACCEPT, nlu_advanced.CONFIDENCE_ASK
    try:
        nlu_advanced.refresh_thresholds({"confidence_accept": 0.91, "confidence_ask": 0.55})
        assert nlu_advanced.CONFIDENCE_ACCEPT == pytest.approx(0.91)
        assert nlu_advanced.CONFIDENCE_ASK == pytest.approx(0.55)
    finally:
        nlu_advanced.CONFIDENCE_ACCEPT, nlu_advanced.CONFIDENCE_ASK = old_accept, old_ask


def test_refresh_thresholds_accepts_dangerous_actions():
    old = nlu_advanced.DANGEROUS_TARGETS
    try:
        nlu_advanced.refresh_thresholds({"dangerous_actions": ["shutdown", "format_disk"]})
        assert "format_disk" in nlu_advanced.DANGEROUS_TARGETS
    finally:
        nlu_advanced.DANGEROUS_TARGETS = old


# ----------------------------------------------------------------------------
# 7. CONFIG: THÔNG BÁO CỤ THỂ TỚI TỪNG KHOÁ
# ----------------------------------------------------------------------------


def test_validation_names_the_bad_key(caplog):
    """Trước đây mọi lỗi config chỉ ra một câu "config không hợp lệ" chung ->
    người dùng phải mở file dò từng dòng. Nay mỗi lỗi nêu ĐÚNG tên khoá."""
    with caplog.at_level("WARNING", logger="config"):
        with pytest.raises(RuntimeError, match="confidence_accept"):
            config._validate_config({"confidence_accept": "abc", "app_map_window": {}})
    # tên khoá gõ sai (thiếu "s" cuối) phải bị gọi tên TRƯỚC khi chương trình chết
    assert "app_map_window" in caplog.text, caplog.text


def test_validation_raises_on_non_dict(caplog):
    with pytest.raises(RuntimeError):
        config._validate_config(["khong", "phai", "dict"])


def test_validation_accepts_the_default_config(caplog):
    with caplog.at_level("WARNING", logger="config"):
        config._validate_config(config.DEFAULT_CONFIG)
    assert caplog.text.strip() == "", caplog.text


def test_validation_rejects_wrong_container_types():
    """website_map là list thì phải bị chặn tại config, không để lọt tới
    executor rồi nổ AttributeError giữa lúc đang chạy lệnh."""
    with pytest.raises(RuntimeError, match="website_map"):
        config._validate_config({**config.DEFAULT_CONFIG, "website_map": ["not", "a", "dict"]})
    with pytest.raises(RuntimeError, match="KHÔNG phải chuỗi"):
        config._validate_config({**config.DEFAULT_CONFIG,
                                 "website_map": {"url": ["khong", "phai", "chuoi"]}})


# ----------------------------------------------------------------------------
# 8. DATASET: DANH SÁCH MẪU CÂU RỖNG KHÔNG GIẾT LÚC IMPORT
# ----------------------------------------------------------------------------


def test_empty_template_list_does_not_crash():
    """`% n` với n = len(templates) = 0 -> ZeroDivisionError ngay lúc import
    `dataset`, kéo chết cả trợ lý lẫn toàn bộ test."""
    import dataset

    assert dataset._generate([], ["hà nội"]) == []
    assert dataset._generate(["thời tiết {object}"], []) == []
    # khong co mau -> khong co cau; co mau -> moi doi tuong `per_object` mau
    assert dataset._generate(["thời tiết {} thế nào"], []) == []
    assert len(dataset._generate(["a {}", "b {}"], ["hà nội", "sapa"], per_object=2)) == 4
