"""The avatar's sync tier (KuraDot full / standard / lite): detected from VRChat's OSC files, chosen in the settings; the
lite tier sends pictures in low resolution and opens one side screen (a second translation: game chatbox only)."""
import json
import os

import tier_detect
from test_engine_images import _raw
from test_translate_wings import _flush, _mirror_client


def _avatar(d, user, avatar, names, name="Test", age=0):
    p = os.path.join(d, user, "Avatars", avatar + ".json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8-sig") as f:              # (VRChat writes a BOM)
        json.dump({"id": avatar, "name": name, "parameters": [{"name": n} for n in names]}, f)
    t = 1_700_000_000 + age
    os.utime(p, (t, t))


def test_detect(tmp_path, monkeypatch):
    monkeypatch.setenv("KDCHAT_VRC_OSC_DIR", str(tmp_path))
    assert tier_detect.detect() is None
    _avatar(tmp_path, "usr_a", "avtr_plain", ["VRCEmote"], age=50)
    assert tier_detect.detect() is None
    _avatar(tmp_path, "usr_a", "avtr_full", ["KD_P", "KD_B0"], "Klaude", age=10)
    _avatar(tmp_path, "usr_a", "avtr_lite", ["KD_P", "KD_S0", "KD_S1", "KD_B0"], "Stick", age=20)
    assert tier_detect.detect() == {"tier": "lite", "avatar": "avtr_lite", "name": "Stick"}   # the newest with KD_*
    _avatar(tmp_path, "usr_b", "avtr_std", ["KD_P", "KD_S0"], "Std", age=30)
    assert tier_detect.detect()["tier"] == "standard"


def test_setting_and_auto(make_client, tmp_path, monkeypatch):
    monkeypatch.setenv("KDCHAT_VRC_OSC_DIR", str(tmp_path))
    c = make_client()
    a = c.app_module
    k = a._kd
    assert k.d.cfg.tier == "full" and c.get("/api/v1/kd/status").json()["tier"] == "full"
    assert c.put("/api/v1/kd/settings", json={"tier": "huge"}).status_code == 400
    c.put("/api/v1/kd/settings", json={"tier": "standard"})
    assert k.d.cfg.tier == "standard" and k.d.cfg.params()[:2] == ["KD_P", "KD_S0"]
    _avatar(tmp_path, "usr_a", "avtr_x", ["KD_P", "KD_S0", "KD_S1"], "Stick")
    c.put("/api/v1/kd/settings", json={"tier": "auto"})
    st = c.get("/api/v1/kd/status").json()
    assert st["tier"] == "lite" and st["tier_detected"]["name"] == "Stick" and st["max_wings"] == 1 and not st["hires"]


def test_lite_one_side_screen(make_client, monkeypatch):
    c, a, k = _mirror_client(make_client, monkeypatch)              # two languages: left + right
    c.post("/api/v1/messages", json={"text": "你好"})
    _flush(k)
    assert k.wings_open() == {1, 2}
    c.put("/api/v1/kd/settings", json={"tier": "lite"})
    assert k.wing_lang == [None, "ja"]                             # the first language on the right, the second: chatbox
    c.post("/api/v1/messages", json={"text": "再见"})
    _flush(k)
    assert k.wings_open() == {2}
    c.put("/api/v1/kd/settings", json={"wings": "on"})
    assert k.wings_open() == {2}
    m = c.post("/api/v1/messages", json={"text": "谢谢"}).json()
    assert set(m["translations"]) == {"ja", "en"}                 # (the chatbox still gets both)


def test_lite_pictures_low_resolution(make_client):
    c = make_client()
    c.put("/api/v1/outputs", json={"chatbox": False, "kd": True})
    c.put("/api/v1/kd/settings", json={"tier": "lite", "image_res": "high"})
    assert c.post("/api/v1/kd/image", content=_raw(64, 48, bytes(range(256)) * 36)).status_code == 200
    k = c.app_module._kd
    k._prepare_images()
    assert k.d.cfg.gscale == 2 and c.get("/api/v1/kd/status").json()["lowres"]


def test_mixed_message_not_in_the_small_font(make_client, monkeypatch):
    """a mostly-Latin message with Chinese in it is detected as English (small font on the main log): the small font
    has no Chinese, so that message keeps the normal font"""
    c, a, k = _mirror_client(make_client, monkeypatch)
    c.put("/api/v1/translate", json={"small": ["en"]})
    assert k.msc({"lang": "en", "text": "这是 KuraDot Lite 版"}) != "small"
    assert k.msc({"lang": "en", "text": "Hello there"}) == "small"
