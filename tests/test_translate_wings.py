"""Translation (language detection, chatbox text, settings / API with a fake engine) and the side screens."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "kd_display"))

import translate as tr                      # noqa: E402
from kd.display import Display              # noqa: E402
from kd.sim import render, wings_open       # noqa: E402


def test_detect():
    assert tr.detect("こんにちは世界") == "ja"
    assert tr.detect("今天天气不错") == "zh"
    assert tr.detect("今天天氣不錯", latin="zh_hant") == "zh_hant"
    assert tr.detect("안녕하세요") == "ko"
    assert tr.detect("Привет") == "ru"
    assert tr.detect("Привіт", latin="uk") == "uk"
    assert tr.detect("Hola amigos", latin="es") == "es"
    assert tr.detect("hello") == "en"
    assert tr.detect("hello", hint="fr") == "fr"
    assert tr.detect("123 :)") == "en"


def test_tidy_full_width():
    assert tr._tidy("你好,世界!", "zh") == "你好，世界！"
    assert tr._tidy("A, B", "en") == "A, B"
    assert tr._tidy("v1.4, ok", "ja").startswith("v1.4")


def _wing_regs(d):
    c = d.cfg
    return {n: d.mem.buf[c.regs[n]] for n in ("show", "wing_tl", "wing_tr", "wing_gl", "wing_gr", "wing_shp", "wing_spr")}


def test_wing_text_regions_with_page_items():
    """wing regions sit at the end of the text area, also after page items (a chat log); registers stay intact"""
    d = Display(dry=True)
    for k in range(7):
        d.compose([{"s": f"line {k}", "x": 0, "y": 20 + 14 * k}], id=f"s{k}", move=True, page=True, pages=2)
    d.compose([], id="hdr", page=True, pages=1)
    d.text("左翼", 4, 4, screen="left")
    d.text("right", 4, 4, screen="right")
    d.set(wings=True, wing_pages=(3, 3), size_m=0.4)
    before = len(d.mem.buf)
    r = d.present()
    assert len(d.mem.buf) == before and r["dropped"] == 0
    regs = _wing_regs(d)
    assert regs["show"] == 3 and regs["wing_tl"] == 15 and regs["wing_tr"] == 18
    assert d.mem.buf[d.cfg.regs["size"]] != 0                  # a register written after the text, not shifted
    assert wings_open(d.mem)
    lit = lambda img: sum(1 for row in img for p in row if sum(p) > 1.5)
    assert lit(render(d.mem, screen=1)) > 20 and lit(render(d.mem, screen=2)) > 20


def test_wing_routing_shapes_sprites_pictures():
    d = Display(dry=True)
    d.shapes.rect(0, 2, 2, 10, 10, color=4)
    d.shapes.rect(5, 2, 2, 10, 10, color=5, screen="left")
    d.shapes.rect(9, 2, 2, 10, 10, color=6, screen="right")
    d.sprite(2, x=5, y=5, pattern=["1" * 16] * 16, screen="right")
    with pytest.raises(ValueError):
        d.wing_picture("left", [[1] * d.cfg.GW for _ in range(d.cfg.GH)])
        d.present()                                            # wing pictures need the low resolution
    d.wing_picture("left", None)
    d.set_size(0, lowres=True)
    d.wing_picture("left", [[7] * d.cfg.GW for _ in range(d.cfg.GH)])
    d.present()
    regs = _wing_regs(d)
    assert regs["wing_shp"] == (1 << 4) | 2                    # physical slots: main 0, left 1, right 2
    assert (regs["wing_spr"] >> 4) & 3 == 2
    assert regs["wing_gl"] == d.cfg.wing_tiles[0] and regs["wing_gr"] == 0
    assert regs["show"] == 1                                    # wings not asked for: folded


def test_wings_folded_without_content(make_client):
    c = make_client()
    k = c.app_module._kd
    k.set_active(True)
    assert not k.wings_open()
    k.set_wing_text_on(True)
    k.set_wing_text({"right": ("Hello", "EN")})
    assert k.wings_open()
    k.set_settings({"wings": "off"})
    assert not k.wings_open()


class FakeEngine:
    def __init__(self):
        self.calls = []

    def ready(self, s, t):
        return True

    def translate(self, text, src, tgt):
        self.calls.append((src, tgt))
        return {"ja": "テスト訳", "en": "test translation " * 3}[tgt]


def test_translate_api_and_chatbox(make_client, monkeypatch):
    c = make_client()
    a = c.app_module
    fake = FakeEngine()
    monkeypatch.setattr(a, "_tr_engine", fake)
    r = c.get("/api/v1/translate")
    assert r.status_code == 200 and r.json()["settings"]["enabled"] is False
    assert c.put("/api/v1/translate", json={"targets": ["ja", "en", "fr"]}).status_code == 400
    r = c.put("/api/v1/translate", json={"enabled": True, "targets": ["ja", "en"], "chatbox": 2})
    assert r.status_code == 200
    r = c.post("/api/v1/translate/try", json={"text": "今天天气不错"})
    j = r.json()
    assert j["source"] == "zh" and set(j["translations"]) == {"ja", "en"}
    assert j["chatbox"].split("\n")[:2] == ["今天天气不错", "テスト訳"]
    long = "长" * 130
    out = a._chatbox_compose(long, {"ja": "テスト訳" * 10, "en": "x"})
    assert len(out) <= a.MAX_CHARS and out.startswith(long)
    c.put("/api/v1/outputs", json={"chatbox": True, "kd": True})
    m = c.post("/api/v1/messages", json={"text": "你好"}).json()
    assert m["source_lang"] == "zh" and m["translations"]["ja"] == "テスト訳"
    k = a._kd
    assert k.wing_text[1][0] == "テスト訳" and k.wing_text[2][1] == "EN"


def test_language_list_offline(make_client):
    c = make_client()
    r = c.get("/api/v1/translate")
    assert any(l["code"] == "en" and l["state"] == "ready" for l in r.json()["languages"])
    assert c.post("/api/v1/translate/models/xx").status_code == 404
