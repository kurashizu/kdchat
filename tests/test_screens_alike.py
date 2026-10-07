"""Every screen's chat looks the same: time labels (+ rules) and dividers follow one setting on the main screen and the
side screens, in the chat and the single layout; the single layout centres the side screens' text like the main one."""
import os

from test_translate_wings import _flush, _mirror_client

SHOTS = os.getenv("KD_SHOTS")                      # a directory: save the previews there (to look at them)


def _shot(k, name):
    if SHOTS:
        with open(os.path.join(SHOTS, name + ".png"), "wb") as f:
            f.write(k.preview_png())


def _shown(k):
    k.d.link.sent[:] = k.d.link.want


def _rules(k, screen):
    return [i for i in range(k.d.cfg.shp_n) if k.d.shapes.data[i] is not None and k.d.shapes.screen[i] == screen
            and i not in (0, 8, 9)]


def test_chat_layout_alike(make_client, monkeypatch):
    c, a, k = _mirror_client(make_client, monkeypatch)
    for t in ("测试", "你好，你是谁", "你可以做什么"):
        c.post("/api/v1/messages", json={"text": t})
    _flush(k)
    _shown(k)
    _shot(k, "chat_time")
    last = k.msgs[-1]
    assert last["deco"] and k.logs[1].lay[last["id"]]["deco"] and k.logs[2].lay[last["id"]]["deco"]
    assert _rules(k, 0) and _rules(k, 1) and _rules(k, 2)          # the rule left of each label, on every screen
    c.put("/api/v1/kd/settings", json={"show_time": False, "divider": True})
    _flush(k)
    _shown(k)
    _shot(k, "chat_divider")
    for log in (1, 2):
        lay = k.logs[log].lay
        assert not any(e["deco"] for e in lay.values())
        assert [e["gap"] for e in lay.values()] == [0, 4, 4]           # as on the main screen
    assert [m["gap"] for m in k.msgs] == [0, 4, 4]
    assert _rules(k, 0) and _rules(k, 1) and _rules(k, 2)          # dividers everywhere
    c.put("/api/v1/kd/settings", json={"divider": False})
    _flush(k)
    assert not _rules(k, 1) and not _rules(k, 2) and not _rules(k, 0)


def test_single_layout_alike(make_client, monkeypatch):
    c, a, k = _mirror_client(make_client, monkeypatch, small=())
    c.put("/api/v1/kd/settings", json={"layout": "single"})
    c.post("/api/v1/messages", json={"text": "你好"})
    _flush(k)
    _shown(k)
    _shot(k, "single_time")
    d = k.d
    assert "msglabel" in d.items and _rules(k, 0)
    for side in (1, 2):
        parts = d.items[f"wing{side}"]
        assert _rules(k, side)
        assert any(r for r in parts)
    # the translation is centred: its first glyph is right of the left edge, like the main screen's text
    xs = lambda item: min(r.x for r in d.items[item] if hasattr(r, "x"))
    assert xs("wing1") > 8 and xs("msg") > 8
    c.put("/api/v1/kd/settings", json={"show_time": False})
    _flush(k)
    _shown(k)
    _shot(k, "single_plain")
    assert "msglabel" not in d.items and not _rules(k, 0) and not _rules(k, 1) and not _rules(k, 2)


def test_old_settings_get_message_time(make_client, tmp_path):
    """settings saved before 1.8.1 (message time off: only the main screen lacked it) switch it on once"""
    import json
    (tmp_path / "state.json").write_text(json.dumps({"kd": {"show_time": False, "scale": 2}}))
    c = make_client()
    k = c.app_module._kd
    assert k.s["show_time"] is True and k.s["scale"] == 2
    c.put("/api/v1/kd/settings", json={"show_time": False})
    st = json.loads((tmp_path / "state.json").read_text())
    assert st["kd_rev"] == 2 and st["kd"]["show_time"] is False      # turned off again: stays off
