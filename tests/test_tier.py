"""The avatar's version (KuraDot full / standard / lite; Klaude = full): chosen by the user (first-run setup or the
settings); the lite tier sends pictures in low resolution and opens one side screen (a second translation: game chatbox
only)."""
import json

from test_engine_images import _raw
from test_translate_wings import _flush, _mirror_client


def test_setting(make_client):
    c = make_client()
    k = c.app_module._kd
    assert k.d.cfg.tier == "full" and c.get("/api/v1/kd/status").json()["tier"] == "full"
    assert c.get("/api/v1/kd/settings").json()["choices"]["tier"] == ["full", "standard", "lite"]
    for bad in ("huge", "auto"):
        assert c.put("/api/v1/kd/settings", json={"tier": bad}).status_code == 400
    c.put("/api/v1/kd/settings", json={"tier": "standard"})
    assert k.d.cfg.tier == "standard" and k.d.cfg.params()[:2] == ["KD_P", "KD_S0"]
    c.put("/api/v1/kd/settings", json={"tier": "lite"})
    st = c.get("/api/v1/kd/status").json()
    assert st["tier"] == "lite" and st["max_wings"] == 1 and not st["hires"] and "tier_detected" not in st


def test_old_auto_setting_is_full(make_client, tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"kd": {"tier": "auto"}, "kd_rev": 2}))
    c = make_client()
    assert c.app_module._kd.s["tier"] == "full" and c.app_module._kd.d.cfg.tier == "full"


def test_first_run_setup(make_client, tmp_path):
    c = make_client()
    assert c.get("/api/v1/settings").json()["setup_done"] is False          # a new install: the console offers it
    assert c.put("/api/v1/setup", json={"done": True}).json() == {"done": True}
    assert json.loads((tmp_path / "state.json").read_text())["setup_done"] is True
    c2 = make_client()
    assert c2.get("/api/v1/settings").json()["setup_done"] is True


def test_setup_done_for_old_installs(make_client, tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"outputs": {"chatbox": True, "kd": True}, "kd_rev": 2}))
    assert make_client().get("/api/v1/settings").json()["setup_done"] is True


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
