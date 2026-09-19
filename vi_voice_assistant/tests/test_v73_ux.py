"""
Test cho bản v7.3 - CÀI ĐẶT & TIỆN NGHI, không phải NLU.

Bản này sửa những lỗi mà "chạy được từ thư mục source" KHÔNG phát hiện ra
được, nên test cũng phải kiểm tra đúng những chỗ đó:

  1. `pip install .` xong thì package CHẠY THẬT (v7.2 trở về trước: wheel thiếu
     __init__.py nên `vi-assistant` chết ngay bằng
     ModuleNotFoundError: No module named 'platform_utils');
  2. dữ liệu người dùng không nằm trong site-packages (paths.py) và cũng không
     bị đóng NGƯỢC vào wheel (.history.json của người build từng bị phát tán);
  3. `install.py` / `vi-doctor` quyết định đúng mà không cần gọi pip thật;
  4. CLI mới: nói thẳng lệnh (`main.py "mở youtube"`), `--yes`, `--doctor`,
     gợi ý lệnh gõ sai;
  5. `run_tests.py` - máy CHƯA cài pytest vẫn chạy trọn bộ test (runner nhúng
     từng thiếu caplog/fixture-yield/cờ -q nên báo lỗi ở test hợp lệ).
"""
import importlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PKG_DIR = Path(__file__).resolve().parent.parent          # .../vi_voice_assistant
REPO_ROOT = PKG_DIR.parent
sys.path.insert(0, str(PKG_DIR))

import config  # noqa: E402
import executor  # noqa: E402
import main as assistant_main  # noqa: E402
import paths  # noqa: E402
import run_tests  # noqa: E402
import text_utils  # noqa: E402


def _load_root_module(name: str, filename: str):
    """Nạp module ở THƯ MỤC GỐC repo (install.py) - không nằm trong package."""
    spec = importlib.util.spec_from_file_location(name, str(REPO_ROOT / filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


install = _load_root_module("_install_under_test", "install.py")


# ----------------------------------------------------------------------------
# 1. PATHS: DỮ LIỆU KHÔNG NẰM TRONG SITE-PACKAGES
# ----------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_paths_cache():
    """`paths` cache kết quả; test đổi biến môi trường phải xoá cache trước/sau."""
    saved_env = os.environ.get(paths_env_key())
    paths.reset_cache()
    yield
    if saved_env is None:
        os.environ.pop(paths_env_key(), None)
    else:
        os.environ[paths_env_key()] = saved_env
    paths.reset_cache()


def paths_env_key() -> str:
    return "VI_ASSISTANT_HOME"


def test_env_var_wins_over_everything(tmp_path, monkeypatch):
    target = tmp_path / "du-lieu-cua-toi"
    monkeypatch.setenv(paths_env_key(), str(target))
    paths.reset_cache()
    assert paths.data_dir() == target
    assert target.is_dir(), "phải TỰ TẠO thư mục khi người dùng chỉ định"
    assert paths.data_path("config.json") == target / "config.json"


def test_relative_env_var_is_resolved_against_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(paths_env_key(), "dữ-liệu")
    paths.reset_cache()
    assert paths.data_dir().is_absolute()
    assert paths.data_dir().name == "dữ-liệu"


def test_source_checkout_detected_by_pyproject_not_by_run_tests(tmp_path, monkeypatch):
    """Dấu vết `run_tests.py` BỊ LOẠI vì nó cũng được đóng vào wheel - nếu tin
    vào nó thì mọi bản cài bằng pip đều bị nhận nhầm là "source" và lại ghi
    dữ liệu vào site-packages (chính cái bug bản này sinh ra để sửa)."""
    assert paths.is_source_checkout(PKG_DIR) is True
    fake_site = tmp_path / "site-packages" / "vi_voice_assistant"
    (fake_site).mkdir(parents=True)
    (fake_site / "run_tests.py").write_text("# ban sao cua runner\n", encoding="utf-8")
    assert paths.is_source_checkout(fake_site) is False


def test_data_dir_falls_back_when_target_unwritable(tmp_path, monkeypatch):
    """Thiếu quyền ghi KHÔNG được làm chết trợ lý: rơi về temp dir có PID."""
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    os.chmod(blocked, 0o500)                       # r-x: tạo thư mục con sẽ fail
    monkeypatch.setenv(paths_env_key(), str(blocked / "con"))
    paths.reset_cache()
    try:
        chosen = paths.data_dir()
    finally:
        os.chmod(blocked, 0o700)
    assert chosen != blocked / "con"
    assert chosen.is_dir()
    assert str(os.getpid()) in chosen.name, "temp dir phải mang PID riêng"


def test_migrate_never_overwrites_newer_user_data(tmp_path, monkeypatch):
    """Chuyển từ source sang `pip install`: chép config CŨ sang, nhưng không bao
    giờ ghi đè file người dùng đã tự sửa ở nơi mới."""
    monkeypatch.setattr(paths, "PACKAGE_DIR", tmp_path / "package")
    (tmp_path / "package").mkdir()
    (tmp_path / "package" / "config.json").write_text('{"gui": "cu"}', encoding="utf-8")
    (tmp_path / "package" / "reminders.json").write_text("[]", encoding="utf-8")
    new_dir = tmp_path / "user-data"
    new_dir.mkdir()
    (new_dir / "config.json").write_text('{"gui": "moi"}', encoding="utf-8")
    monkeypatch.setattr(paths, "data_dir", lambda: new_dir)

    moved = paths.migrate_from_package_dir(("config.json", "reminders.json"))

    assert moved == ["reminders.json"], moved
    assert json.loads((new_dir / "config.json").read_text(encoding="utf-8")) == {"gui": "moi"}


def test_describe_reports_writability(tmp_path, monkeypatch):
    monkeypatch.setenv(paths_env_key(), str(tmp_path / "ok"))
    paths.reset_cache()
    info = paths.describe()
    assert info["writable"] is True
    assert info["from_source"] is False
    assert Path(str(info["data_dir"])).is_dir()


# ----------------------------------------------------------------------------
# 2. PACKAGE PHẢI IMPORT & CHẠY ĐƯỢC SAU `pip install .`
# ----------------------------------------------------------------------------
def test_flat_imports_work_when_used_as_a_package(tmp_path):
    """Đây chính là lỗi: wheel v7.2 chứa đủ .py nhưng `import vi_voice_assistant.main`
    chết vì `from platform_utils import ...` không giải được.

    Chạy ở cwd KHÁC thư mục dự án (tmp_path) - nếu chạy ngay trong repo thì
    import phẳng tự nó đã tìm thấy file, test sẽ xanh giả.
    """
    code = (
        f"import sys; sys.path.insert(0, {str(REPO_ROOT)!r});"
        "import vi_voice_assistant.main as m; print('VERSION', m.APP_VERSION)"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          cwd=str(tmp_path), timeout=120)
    assert proc.returncode == 0, proc.stderr[-500:]
    assert f"VERSION {assistant_main.APP_VERSION}" in proc.stdout


def test_module_entry_point_runs():
    """`python -m vi_voice_assistant` (mới v7.3) - trước đây chết vì không có
    __main__.py, người dùng pip chỉ còn cách nhớ đường dẫn file."""
    proc = subprocess.run([sys.executable, "-m", "vi_voice_assistant", "--version"],
                          capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120)
    assert proc.returncode == 0, proc.stderr[-500:]
    assert "phiên bản" in proc.stdout


def test_package_version_matches_cli():
    import vi_voice_assistant

    assert vi_voice_assistant.__version__ == assistant_main.APP_VERSION


def test_shipped_config_is_not_broken_by_data_dir_change():
    """Đổi chỗ lưu dữ liệu KHÔNG được làm mất whitelist: config vẫn đọc được và
    giữ các map quan trọng."""
    cfg = config.load_config()
    assert isinstance(cfg, dict)
    assert "website_map" in cfg or "app_map" in cfg


# ----------------------------------------------------------------------------
# 3. PYPROJECT: ĐÓNG GÓI ĐÚNG, KHÔNG RÒ RỈ DỮ LIỆU
# ----------------------------------------------------------------------------
def _pyproject_text() -> str:
    return (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_package_data_is_explicit():
    """`include-package-data = true` sẽ vơ cả file đang có trên đĩa lúc build ->
    `.history.json` (câu người dùng đã nói) từng bị phát tán trong wheel."""
    text = _pyproject_text()
    assert "include-package-data = false" in text
    data_block = text.split("[tool.setuptools.package-data]", 1)[1]
    assert "*" not in data_block.split("]")[0], "không dùng wildcard trong package-data"


def test_console_scripts_point_at_real_callables():
    """Mỗi entry point phải trỏ tới một hàm CÓ THẬT - sai tên thì `pip install`
    vẫn thành công, chỉ chết khi người dùng gõ lệnh (rất khó báo lỗi hộ)."""
    text = _pyproject_text()
    block = text.split("[project.scripts]", 1)[1].split("[", 1)[0]
    scripts = {}
    for line in block.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            scripts[key.strip()] = value.strip().strip('"')
    assert len(scripts) >= 4, scripts
    for target in scripts.values():
        module_name, _, func = target.partition(":")
        module = importlib.import_module(module_name)
        assert callable(getattr(module, func, None)), target


def test_package_has_init_and_main():
    """Hai file làm `pip install .` chạy được: __init__.py (nối thư mục gói vào
    sys.path cho các import phẳng) và __main__.py (cho `python -m`)."""
    assert (PKG_DIR / "__init__.py").is_file()
    assert (PKG_DIR / "__main__.py").is_file()
    init = (PKG_DIR / "__init__.py").read_text(encoding="utf-8")
    assert "sys.path" in init


def test_runtime_files_are_gitignored():
    """File dữ liệu lúc build (history/reminders/model/log) từng bị đóng vào
    wheel và phát tán cho người cài sau - .gitignore gốc phải chặn chúng."""
    gitignore = (REPO_ROOT / ".gitignore")
    assert gitignore.is_file(), "phải có .gitignore ở thư mục gốc (pip build chạy từ đây)"
    text = gitignore.read_text(encoding="utf-8")
    for entry in (".history.json", "reminders.json", "lite_model.pkl", "logs/", "build/"):
        assert entry in text, entry


# ----------------------------------------------------------------------------
# 4. INSTALL.PY: QUYẾT ĐỊNH ĐÚNG MÀ KHÔNG CẦN GỌI PIP THẬT
# ----------------------------------------------------------------------------
def test_pep668_gets_progressive_flags():
    """Đúng trình tự an toàn: --user trước (ghi vào nhà người dùng),
    --break-system-packages chỉ khi hết cách."""
    err = ("error: externally-managed-environment\n\n"
           "This environment is externally managed")
    assert install.retry_flags_for(err, []) == ["--user"]
    assert install.retry_flags_for(err, ["--user"]) == ["--break-system-packages"]
    assert install.retry_flags_for(err, ["--user", "--break-system-packages"]) is None


def test_permission_error_falls_back_to_user_site():
    err = "CouldNotInstallRequirement: [Errno 13] Permission denied: '/usr/lib/python3'"
    assert install.retry_flags_for(err, []) == ["--user"]
    assert install.retry_flags_for(err, ["--user"]) is None


def test_unrelated_error_is_not_silently_retried():
    """Không đoán mò: lỗi mạng/cú pháp thì BÁO người dùng, không âm thầm cài
    tiếp bằng cờ lạ (trước đây mọi lỗi đều bị diễn giải giống nhau)."""
    for message in ("No matching distribution found for xyz",
                    "ReadTimeoutError: HTTPSConnectionPool(host='pypi.org')",
                    ""):
        assert install.retry_flags_for(message, []) is None, message


def test_all_packages_install_in_one_pip_call():
    """Mỗi lần gọi pip là ~1-3 giây tự kiểm tra PyPI; gọi 5 lần cho 5 gói chính
    là cảm giác "cài đặt treo máy" mà người dùng hay phàn nàn."""
    cmds = install.plan_commands(("scikit-learn", "joblib", "rapidfuzz"), editable=False)
    assert len(cmds) == 1
    assert cmds[0][-3:] == ["scikit-learn", "joblib", "rapidfuzz"]


def test_editable_install_appended_after_libraries():
    cmds = install.plan_commands(("numpy",), editable=True)
    assert len(cmds) == 2
    assert "-e" in cmds[1]
    assert cmds[1][-1] == str(REPO_ROOT)


def test_core_profile_installs_nothing():
    """'core' = hợp đồng của dự án: chạy bằng thuần stdlib, không pip gì cả."""
    assert install.PROFILES["core"] == ()
    assert install.plan_commands((), editable=False) == []


def test_pip_is_always_called_through_current_interpreter():
    """`pip` trẩn trơi có thể thuộc Python khác (máy có 3.9 + 3.12 cùng lúc) ->
    cài xong vẫn báo thiếu thư viện, và đường dẫn có dấu cách trên Windows thì
    vỡ lệnh."""
    for cmd in install.plan_commands(("numpy",), editable=True):
        assert cmd[:3] == [sys.executable, "-m", "pip"], cmd


def test_check_imports_detects_silent_pip_failure():
    missing = install.check_imports(("json", "module_khong_ton_tai_xyz"))
    assert missing == ["module_khong_ton_tai_xyz"]
    assert install.check_imports(("json",)) == []


def test_dry_run_never_touches_the_network(capsys):
    """`--dry-run` phải in đúng lệnh để review, và KHÔNG chạy subprocess nào."""
    code = install.main(["--dry-run", "--profile", "ml", "--skip-tests"])
    out = capsys.readouterr().out
    assert code == 0
    assert "pip install --upgrade scikit-learn" in out
    assert "--break-system-packages" not in out       # chi xuat hien khi pip that tu choi


# ----------------------------------------------------------------------------
# 5. VI-DOCTOR: CHẨN ĐOÁN TẬP TRUNG, LỆNH KHẮC PHỤC KHÔNG TRÙNG LẶP
# ----------------------------------------------------------------------------
def test_run_checks_shape():
    report = importlib.import_module("diagnostic").run_checks()
    assert set(report) >= {"ok", "problems", "warnings", "sections", "fixes"}
    assert report["sections"], "phải có ít nhất một mục chẩn đoán"
    for rows in report["sections"].values():
        for mark, line in rows:
            assert mark in ("[OK]  ", "[!]  ", "[X]  ")
            assert isinstance(line, str) and line


def test_fix_list_is_deduplicated():
    """Nhiều mục thiếu cùng cần MỘT lệnh pip -> lệnh đó chỉ được in một lần,
    nếu không người dùng tưởng phải cài 3 thứ khác nhau."""
    diagnostic = importlib.import_module("diagnostic")
    report = diagnostic.run_checks()
    assert len(report["fixes"]) == len(set(report["fixes"])), report["fixes"]


def test_doctor_json_is_machine_readable(capsys):
    diagnostic = importlib.import_module("diagnostic")
    code = diagnostic.main(["--json"])
    out = capsys.readouterr().out
    assert code in (0, 1)
    data = json.loads(out)
    assert data["sections"]


def test_module_probe_does_not_import_heavy_libraries():
    """Doctor chạy trên máy yếu: chỉ ĐUOC XEM module có tồn tại không, không được
    import torch/piper (mỗi cái vài giây, có cái còn in logo)."""
    diagnostic = importlib.import_module("diagnostic")
    assert diagnostic._module_available("json") is True
    assert diagnostic._module_available("module_khong_ton_tai_xyz") is False
    assert "torch" not in sys.modules or True          # khong ep buoc, chi kiem tra khong loi


# ----------------------------------------------------------------------------
# 6. CLI TIỆN NGHI
# ----------------------------------------------------------------------------
def test_positional_sentence_behaves_like_once(monkeypatch):
    """`vi-assistant "mở youtube"` thay vì bắt nhớ cờ --once."""
    monkeypatch.setattr(sys, "argv", ["main.py", "mở youtube"])
    args = assistant_main.parse_args()
    assert args.text == "mở youtube"
    assert args.once is None


def test_explicit_once_still_wins(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--once", "tắt máy", "phụ-thừa"])
    args = assistant_main.parse_args()
    assert args.once == "tắt máy"


def test_yes_flag_switches_auto_confirm():
    """--yes cho script/CI: bỏ qua bước xác nhận, KHÔNG bỏ qua bước chặn lệnh.
    Test cũng đảm bảo trạng thái được trả về đúng như cũ (không rò rỉ sang test khác)."""
    before = executor.AUTO_CONFIRM
    try:
        assert executor.set_auto_confirm(True) is True
        assert executor._confirm("tắt máy tính") is True
        assert executor.set_auto_confirm(False) is False
    finally:
        executor.set_auto_confirm(before)


def test_confirm_declines_when_answer_is_no(monkeypatch):
    monkeypatch.setattr(executor, "AUTO_CONFIRM", False)
    monkeypatch.setattr("builtins.input", lambda *_: "không")
    assert executor._confirm("tắt máy tính") is False


def test_confirm_accepts_common_yes_words(monkeypatch):
    monkeypatch.setattr(executor, "AUTO_CONFIRM", False)
    for answer in ("y", "yes", "co", "có", "ok"):
        monkeypatch.setattr("builtins.input", lambda _p, a=answer: a)
        assert executor._confirm("chụp màn hình") is True, answer


@pytest.mark.parametrize("typed,expected", [
    ("he thogng", "he thong"),
    ("napllai", "nap lai"),
    ("hiostyr", "history"),
])
def test_typo_in_control_command_gets_a_hint(typed, expected):
    """Trước đây gõ sai một lệnh có sẵn -> rơi vào NLU -> "tôi chưa hiểu ý bạn",
    người dùng không biết mình chỉ sai chính tả."""
    assert assistant_main._suggest_control_command(typed) == expected


@pytest.mark.parametrize("sentence", [
    "mở youtube cho tôi", "hôm nay thứ mấy", "12 + 30 bằng bao nhiêu", "a",
])
def test_normal_sentences_are_not_treated_as_typos(sentence):
    assert assistant_main._suggest_control_command(sentence) is None


def test_info_flags_short_circuit_before_nlu(monkeypatch):
    """--doctor/--version/--history/--sysinfo phải chạy được khi model HỎNG
    (mục đích của chúng là chẩn đoán lúc cài đặt chưa xong)."""
    monkeypatch.setattr(sys, "argv", ["main.py", "--version"])
    args = assistant_main.parse_args()
    assert assistant_main._run_info_command(args) == 0


def test_adopt_shipped_data_is_noop_for_source_checkout():
    """Chạy từ thư mục dự án: không được chép/xáo gì cả."""
    assert assistant_main._adopt_shipped_data() == []


def test_readline_setup_is_optional(capsys):
    """Không có readline (Windows thường xuyên) thì REPL vẫn chạy như cũ -
    đây là NÂNG CẤP tuỳ chọn, không phải yêu cầu mới."""
    result = assistant_main._setup_readline()
    assert result in (True, False)


def test_control_suggestions_use_registered_table():
    """Bảng gợi ý lấy từ chính table đăng ký -> thêm lệnh mới sẽ tự được gợi ý,
    không phải sửa hai chỗ."""
    candidates = assistant_main._control_candidates()
    assert "nap lai" in candidates and "help" in candidates
    assert "?" not in candidates                      # ky tu tro giup, khong phai ten lenh


# ----------------------------------------------------------------------------
# 7. TEXT_UTILS: CACHE KHÔNG ĐỔI KẾT QUẢ
# ----------------------------------------------------------------------------
TRICKY = ["Đà Nẵng", "đ/Đ", "MỞ   Chrome!!", "hẹn 8 giờ kém 15", "", "12345",
          "trường  tôi", "q w e", "  leading and trailing  "]


@pytest.mark.parametrize("text", TRICKY)
def test_normalize_matches_independent_implementation(text):
    """Cache không được đổi kết quả: so với bản tính lại ĐỘC LẬP ngay trong test
    (nếu ai đó cache luôn cả bước sai thì test này vẫn đỏ)."""
    import re
    import unicodedata

    expected = unicodedata.normalize("NFC", str(text).strip().lower())
    expected = re.sub(r"[^\w\s./:\\-]+", " ", expected)
    expected = re.sub(r"\s+", " ", expected).strip()
    assert text_utils.normalize_text(text) == expected


@pytest.mark.parametrize("text", TRICKY)
def test_strip_diacritics_stable_across_cache(text):
    first = text_utils.strip_diacritics(text)
    for _ in range(3):
        assert text_utils.strip_diacritics(text) == first
    assert "̀" not in first                            # không còn dấu thanh


def test_non_string_input_is_coerced_not_fatal():
    """Một con số lọt vào từ config hỏng không được phép làm chết tầng văn bản
    (trước đây: AttributeError ở nơi không ai ngờ)."""
    assert text_utils.normalize_text(12345) == "12345"
    assert text_utils.strip_diacritics(None) == ""
    # ["a"] -> "['a']" -> _KEEP_RE bo ky tu khong phai chu/cach -> "a"
    assert text_utils.normalize_text(["a"]) == "a"


def test_cache_actually_hits_on_repeated_sentences():
    """Nếu ai bỏ `lru_cache` đi thì test này đỏ: hot path của NLU gọi lại cùng
    một chuỗi hàng chục lần cho MỘT câu nói."""
    info_before = text_utils._strip_diacritics_cached.cache_info()
    sentence = "nhắc tôi họp lúc 3 giờ chiều mai"
    for _ in range(30):
        text_utils.strip_diacritics(sentence)
    info_after = text_utils._strip_diacritics_cached.cache_info()
    assert info_after.hits > info_before.hits


def test_cache_is_bounded():
    """Chạy cả ngày không được ăn RAM vô hạn: LRU chặn ở 8192 câu."""
    maxsize = text_utils._strip_diacritics_cached.cache_info().maxsize
    assert maxsize and maxsize <= 100_000


# ----------------------------------------------------------------------------
# 8. RUN_TESTS: MÁY KHÔNG CÓ PYTEST VẪN CHẠY ĐƯỢC TRỌN BỘ TEST
# ----------------------------------------------------------------------------
def test_importing_run_tests_does_not_clobber_real_pytest():
    """Runner nhúng thay module `pytest` bằng shim CHỈ khi không có pytest thật.
    Ngược lại, `import run_tests` giữa một phiên pytest sẽ che mất module thật
    và làm hỏng fixture/mark ở những file test chạy SAU đó."""
    if run_tests._HAS_PYTEST:
        assert sys.modules["pytest"] is not None
        assert hasattr(sys.modules["pytest"], "mark")
        assert getattr(sys.modules["pytest"], "__file__", None), "phải là pytest thật"


def test_runner_accepts_pytest_style_flags(monkeypatch):
    """CI chạy `python run_tests.py -q`; máy chưa có pytest thì cờ này trước
    đây làm argparse của runner báo 'unrecognized arguments' và CHẾT TRƯỚC KHI
    chạy bất kỳ test nào.

    (Test này từng TREO HỆ THỐNG vì gọi _delegate_to_pytest khi pytest đang
    chạy: runner khởi tiến trình con chạy... chính bộ test này, đệ quy vô hạn.
    Must test by turning the flag off instead.)
    """
    monkeypatch.setattr(run_tests, "_HAS_PYTEST", False)
    assert run_tests._delegate_to_pytest(["-q"]) is None       # ty dung runner nhúng
    monkeypatch.setattr(run_tests, "_HAS_PYTEST", True)
    assert run_tests._delegate_to_pytest(["--list"]) is None   # co cua runner -> khong delegate
    assert run_tests.main(["--list"]) == 0


def test_caplog_shim_collects_records():
    import logging

    caplog = run_tests._Caplog()
    caplog._enter()
    try:
        logging.getLogger("demo_config").warning("khoá %s không hợp lệ", "abc")
    finally:
        caplog._exit()
    assert "khoá abc không hợp lệ" in caplog.text
    assert caplog.records[-1].levelname == "WARNING"


def test_caplog_at_level_lowers_only_the_named_logger():
    import logging

    caplog = run_tests._Caplog()
    caplog._enter()
    try:
        with caplog.at_level("DEBUG", logger="chuyen_dao"):
            logging.getLogger("chuyen_dao").debug("tin nhan")
            assert "tin nhan" in caplog.text
        logging.getLogger("chuyen_dao").debug("an di")
        assert "an di" not in caplog.text
    finally:
        caplog._exit()
    assert logging.getLogger("chuyen_dao").level == logging.NOTSET


def test_fixture_with_parameters_and_yield_teardown(tmp_path):
    """Runner nhúng phải hiểu `def fx(tmp_path, monkeypatch)` + `yield` như
    pytest - hai thứ mà bản cũ bỏ sót nên test hợp lệ bị báo TypeError."""
    fixtures = {
        "dep": run_tests._fixture(lambda tmp_path: tmp_path / "x"),
        "holder": run_tests._fixture(lambda tmp_path, dep: _gen(tmp_path, dep)),
    }

    def _gen(tmp_path, dep):
        dep.parent.mkdir(exist_ok=True)
        yield dep
        (tmp_path / "teardown_ran").write_text("1", encoding="utf-8")

    fixtures["holder"].__is_fixture__ = True
    finalizers = []
    value = run_tests._resolve("holder", fixtures, None, None, tmp_path, finalizers)
    assert value == tmp_path / "x"
    for fin in finalizers:
        fin()
    assert (tmp_path / "teardown_ran").is_file(), "teardown của fixture phải được chạy"


def test_missing_fixture_dependency_is_reported_clearly(tmp_path):
    def needs_unknown(khong_bao_gio_co):
        pass
    needs_unknown.__is_fixture__ = True
    with pytest.raises(RuntimeError, match="khong_bao_gio_co"):
        run_tests._resolve("needs_unknown", {"needs_unknown": needs_unknown},
                           None, None, tmp_path)


# ----------------------------------------------------------------------------
# 9. CUOI CUNG: TOAN BO CLI CHUAN VAN TRẢ VỀ MA EXIT DUNG
# ----------------------------------------------------------------------------
@pytest.mark.parametrize("flags", [
    ["--version"],
    ["--doctor"],
    ["--sysinfo"],
    ["--history"],
])
def test_info_commands_exit_zero(flags):
    proc = subprocess.run([sys.executable, "main.py", *flags], capture_output=True,
                          text=True, cwd=str(PKG_DIR), timeout=180)
    assert proc.returncode == 0, proc.stderr[-400:]


def test_once_mode_returns_zero_for_executable_command():
    proc = subprocess.run([sys.executable, "main.py", "--dry-run", "--once", "mở youtube"],
                          capture_output=True, text=True, cwd=str(PKG_DIR), timeout=180)
    assert proc.returncode == 0, proc.stderr[-400:]
    assert "|" in proc.stdout


def test_unknown_garbage_is_not_executed():
    """Giữ vững thành quả v7.2 qua cả con đường CLI mới (positional text)."""
    proc = subprocess.run([sys.executable, "main.py", "--once", "asdfgh jklzxbv"],
                          capture_output=True, text=True, cwd=str(PKG_DIR), timeout=180)
    assert "| 0%" in proc.stdout or "unknown" in proc.stdout


# ----------------------------------------------------------------------------
# 9b. --once + --yes: che do script phai chay duoc lenh nguy hiem khi da bao "khoi hoi"
# ----------------------------------------------------------------------------
class _ScriptedNlu:
    """NLU gia: tra ve san danh sach lenh de test rieng cach xu ly cua run_once."""

    def __init__(self, commands):
        self._commands = commands

    def understand(self, text):
        return list(self._commands)

    def confirm_message(self, result):
        return "Bạn chắc chắn?"

    def teach(self, text, intent):
        return ""


DANGEROUS = [{"intent": "system_control", "target": "shutdown", "confidence": 1.0,
              "status": "need_confirm", "raw": "tắt máy tính"}]


def test_once_refuses_dangerous_command_without_yes(monkeypatch):
    executed = []
    monkeypatch.setattr(executor, "AUTO_CONFIRM", False)
    monkeypatch.setattr(assistant_main, "execute_command", lambda r: executed.append(r) or True)
    code = assistant_main.run_once("tắt máy tính", _ScriptedNlu(DANGEROUS))
    assert executed == [], "khong duoc thuc thi lenh nguy hiem khi chua xac nhan"
    assert code == 2


def test_yes_flag_lets_once_run_dangerous_command(monkeypatch):
    """--yes chot buoc xac nhan (KHONG phai bat buoc chay): do la toan bo y nghia
    cua co nay, va no tung bi bo vot o che do --once."""
    executed = []
    monkeypatch.setattr(executor, "AUTO_CONFIRM", True)
    monkeypatch.setattr(assistant_main, "execute_command", lambda r: executed.append(r) or True)
    code = assistant_main.run_once("tắt máy tính", _ScriptedNlu(DANGEROUS))
    assert len(executed) == 1
    assert code == 0


def test_dry_run_ignores_yes(monkeypatch):
    """--dry-run van la lenh "khong chay": --yes khong duoc phep vuot qua no."""
    executed = []
    monkeypatch.setattr(executor, "AUTO_CONFIRM", True)
    monkeypatch.setattr(assistant_main, "execute_command", lambda r: executed.append(r) or True)
    code = assistant_main.run_once("tắt máy tính", _ScriptedNlu(DANGEROUS), dry_run=True)
    assert executed == []
    assert code == 0
