"""
v7.9 (bổ sung 9e) - Lệnh DỪNG không được thành lệnh PHÁT.

`play_media` mở YouTube tìm từ khoá lấy từ câu. Nên khi câu là lệnh DỪNG mà
vẫn rơi vào `play_media`, máy mở trình duyệt tìm CHÍNH NHỮNG TỪ DỪNG đó:

    "tắt nhạc"      -> "Đang phát tắt nhạc"      + mở YouTube
    "dừng nhạc"     -> "Đang phát dừng nhạc"     + mở YouTube
    "bật đèn"       -> "Đang phát đèn"           + mở YouTube
    "mở đèn"        -> mở FILE tên "đèn"

Đây là cùng lớp lỗi với `"alarm clock"` khoá nhầm máy: **làm việc KHÁC hẳn
với điều người dùng nói, và không có tín hiệu nào cho người dùng nghi ngờ.**

Máy này không điều khiển được đèn, cũng không dừng được phát (nó chỉ mở URL),
nên kết quả ĐÚNG là thừa nhận không hỗ trợ - đã có sẵn ở `action_system_control`.
Việc cần sửa là cho các lệnh này rơi đúng chỗ đó.
"""

import pytest
from intent_model import predict_intent


# ---------------------------------------------------------------------------
# 1. Lệnh dừng/bật thiết bị -> system_control, KHÔNG phải play_media
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,action", [
    ("bật đèn", "lights_on"),
    ("mở đèn", "lights_on"),
    ("bật hết đèn", "lights_on"),
    ("tắt đèn", "lights_off"),
    ("tắt nhạc", "stop_media"),
    ("dừng nhạc", "stop_media"),
    ("ngừng phát nhạc", "stop_media"),
    ("tạm dừng nhạc", "stop_media"),
    ("stop music", "stop_media"),
    ("tắt youtube", "close_app"),
])
def test_lenh_dung_khong_bien_thanh_lenh_phat(text, action):
    r = predict_intent(text)
    assert r["intent"] == "system_control", (
        f"{text!r} -> {r['intent']} ({r['confidence']}): "
        f"sẽ mở trình duyệt tìm chính chữ người dùng vừa nói")
    assert r["target"] == action


# ---------------------------------------------------------------------------
# 2. Lệnh PHÁT thật thì không được đụng vào
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,target", [
    ("phát nhạc", "nhạc"),
    ("bật nhạc", "nhạc"),
    ("mở nhạc", "nhạc"),
    ("nghe nhạc nhẹ", "nhạc nhẹ"),
    ("mở youtube", "youtube"),
    ("phát podcast về công nghệ", "podcast về công nghệ"),
])
def test_lenh_phat_that_van_phat(text, target):
    """`bật nhạc` và `bật đèn` chỉ khác nhau ở TỪ CUỐI."""
    r = predict_intent(text)
    assert r["intent"] == "play_media"
    assert r["target"] == target


# ---------------------------------------------------------------------------
# 3. Lệnh hệ thống có thật thì không được đụng vào
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,action", [
    ("tắt máy", "shutdown"),
    ("khoá máy", "lock"),
    ("chụp màn hình", "screenshot"),
    ("khởi động lại", "restart"),
])
def test_lenh_he_thong_co_that_khong_bi_dong_vao(text, action):
    from intent_model import _system_action
    from text_utils import strip_diacritics

    u = strip_diacritics(text)
    assert _system_action(text, u) == action


# ---------------------------------------------------------------------------
# 4. Bằng chứng tầng executor: KHÔNG được mở trình duyệt
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("action", ["lights_on", "lights_off", "stop_media"])
def test_lenh_khong_ho_tro_thi_khong_mo_trinh_duyet(action, monkeypatch):
    import executor

    opened: list[str] = []
    monkeypatch.setattr(executor, "_open_url", opened.append)
    assert executor.action_system_control(action) is False
    assert not opened


def test_may_that_bao_khong_ho_tro_thay_vi_bia_ra_hanh_dong(monkeypatch):
    """Hành vi đúng là thừa nhận, và câu thừa nhận phải nói đúng sự thật."""
    import executor

    said: list[str] = []
    monkeypatch.setattr(executor, "safe_print", said.append)
    monkeypatch.setattr(executor, "_open_url", lambda _u: pytest.fail("mở trình duyệt"))
    assert executor.action_system_control("stop_media") is False
    assert any("stop_media" in line for line in said), said
