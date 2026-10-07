"""The display draws every language the translation offers (except the Indic scripts: chatbox only): no fallback boxes,
right-to-left order, Arabic joining, Thai clusters, half-width Latin, punctuation width by its neighbours."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "kd_display"))

import translate as tr                      # noqa: E402
from kd.config import MODE_ASCII, MODE_EXT  # noqa: E402
from kd.display import Display              # noqa: E402

SAMPLES = {
    "en": "The weather is nice today - let's go out!",
    "es": "¿Qué tal? ¡Mañana vamos a la montaña con Íñigo!",
    "fr": "« Ça va très bien », dit-elle. Où êtes-vous ? L'œuvre coûte 5 €.",
    "de": "Schöne Grüße aus München – „Äpfel“ für 3,50 €. Straße, Übung.",
    "it": "Perché è così? Più città, però già fatto.",
    "pt": "Não sei, você está à espera? Ação, coração, pôr.",
    "pl": "Zażółć gęślą jaźń. Łódź, Świętokrzyskie, Źródło.",
    "nl": "Één ruïne, ijsje, café.",
    "sv": "Hej på dig! Åsa äter ölsås.",
    "nb": "Blåbærsyltetøy og ærfugl, Øvre Årdal.",
    "no": "Vær så snill, Ålesund, øl.",
    "da": "Rødgrød med fløde, Æblet på Ørestad.",
    "fi": "Hyvää päivää! Äiti öljyää.",
    "cs": "Příliš žluťoučký kůň úpěl ďábelské ódy. Řeka.",
    "sk": "Kŕdeľ šťastných ďatľov učí pri ústí Váhu mĺkveho koňa.",
    "sl": "Čežana šumi, Žiga.",
    "hu": "Árvíztűrő tükörfúrógép. Őz, Ű.",
    "ro": "Știință și țară, Înaintea, Șase, Ţ, ş.",
    "lt": "Įlinkis, ąžuolas, ėjo, ūkis, ų, Č, Š, Ž.",
    "lv": "Ģimene, ķirbis, ļoti, ņemt, ā, ē, ī, ū, Ā.",
    "et": "Õun, öö, ühe, äge, Šokolaad.",
    "is": "Þetta er ðað, æðislegt. Ýmislegt, Þú.",
    "ca": "L·lusió, què, perquè, Barça, ·, «hola».",
    "gl": "Ñandú, ollo, acción.",
    "eu": "Kaixo, zer moduz? Ñ.",
    "tr": "Iğdır'da şöyle güzel bir gün, İstanbul, ı, ş, ğ, Ç.",
    "az": "Azərbaycan, Ə, ş, ı, ğ, Ü.",
    "id": "Selamat pagi, apa kabar?",
    "ms": "Apa khabar, terima kasih.",
    "af": "Hoe gaan dit? Ek's lekker, ê, ë, ô.",
    "sq": "Përshëndetje, çfarë, Ç, Ë.",
    "bs": "Ćevapi, đak, džep, Š, Ž.",
    "hr": "Čađa, ćup, đak, šuma, žaba.",
    "hbs": "Ćevapčići, đurđevak.",
    "vi": "Tôi đang học tiếng Việt ở trường. Bạn khỏe không? Ở đây, Ứng, Ỷ, ặ, ỹ, ợ.",
    "ru": "Съешь же ещё этих мягких французских булок, да выпей чаю. Ё.",
    "uk": "Їжак і ґанок: є, ї, і — Україна, Ґ, Є.",
    "bg": "Жълтата дюля беше щастлива, ъ, ь.",
    "sr": "Љубав, њива, ђак, ћерка, џеп, ј, Ђ, Ћ.",
    "el": "Καλημέρα! Πώς είσαι; Ϊ, ΐ, ΰ, ς, Ώ.",
    "he": "שלום! מה שלומך? אני בסדר, תודה 123.",
    "ar": "مرحبا! كيف حالك؟ أنا بخير، شكرا لك. ٣٤ لا.",
    "fa": "سلام! حال شما چطور است؟ من می‌خواهم بروم. پژوهش گاه ۱۲۳.",
    "ur": "آپ کیسے ہیں؟ میں ٹھیک ہوں۔ ڈاکٹر، گھر، بڑا، ے.",
    "th": "สวัสดีครับ วันนี้อากาศดีมาก ขอบคุณที่ช่วย น้ำใจ ปี่ ฟ้า ผู้",
    "zh": "你好，世界！“引号”和……省略号——破折号",
    "zh_hant": "你好，世界！佢哋喺度嘅。",
    "ja": "こんにちは、世界！気になる駅。",
    "ko": "안녕하세요, 세계! 반갑습니다.",
}


def test_every_display_language_has_a_sample():
    assert set(SAMPLES) == set(tr.LANGUAGES) - tr.NO_DISPLAY


@pytest.mark.parametrize("lang", sorted(SAMPLES))
def test_no_fallback_boxes(lang):
    d = Display(dry=True)
    d.layout.missing.clear()
    d.text(SAMPLES[lang], 0, 0, d.cfg.W)
    assert not d.layout.missing, "".join(sorted(d.layout.missing))
    r = d.present()
    assert r["dropped"] == 0


def _decode(d, runs):
    out = []
    for r in sorted(runs, key=lambda r: (r.y, r.x)):
        for c in r.codes:
            if r.mode == MODE_ASCII:
                out.append(chr(c + 32))
            else:
                cp = d.layout.cm.table[c]
                out.append(chr(cp) if cp < 0xF0000 else "#")
    return "".join(out)


def test_right_to_left_order():
    d = Display(dry=True)
    runs, _ = d.layout.runs("שלום 123 עולם", 0, 0, None)
    assert _decode(d, runs) == "םלוע 123 םולש"
    assert max(r.x + len(r.codes) * d.cfg.adv(r.mode, 1, r.codes[0]) for r in runs) >= d.cfg.W - 2   # right aligned
    runs, _ = d.layout.runs("abc (שלום) def", 0, 0, None)
    assert _decode(d, runs) == "abc (םולש) def"
    runs, _ = d.layout.runs("(שלום)", 0, 0, None)
    assert _decode(d, runs) == "(םולש)"                        # brackets mirror


def test_arabic_joining():
    import unicodedata
    d = Display(dry=True)
    runs, _ = d.layout.runs("حالك", 0, 0, None)
    names = [unicodedata.name(ch).split()[-3:-1] for ch in _decode(d, runs)]
    # drawn left to right: kaf final, lam initial, alef final, hah initial
    assert names == [["KAF", "FINAL"], ["LAM", "INITIAL"], ["ALEF", "FINAL"], ["HAH", "INITIAL"]], names
    runs, _ = d.layout.runs("لا", 0, 0, None)
    assert "LAM WITH ALEF" in unicodedata.name(_decode(d, runs))


def test_thai_clusters_are_single_glyphs():
    d = Display(dry=True)
    lines = d.layout.lines("ที่นี่", d.cfg.W)
    assert [c[3] for c in lines[0]] == ["ที่", "นี่"]
    assert all(d.layout.cm.table[c[1]] >= 0xF0000 for c in lines[0])


def test_half_width_latin_one_run():
    d = Display(dry=True)
    runs, _ = d.layout.runs("très", 0, 0, None)
    assert len(runs) == 1 and runs[0].mode == MODE_EXT and d.cfg.adv(MODE_EXT, 1, runs[0].codes[0]) == 7
    w, _ = d.measure("café crème")
    assert w == d.measure("cafe creme")[0]                    # accented letters as wide as plain ones


def test_punctuation_width_by_neighbours():
    d = Display(dry=True)
    latin = d.layout.lines("“hello”", 200)[0]
    cjk = d.layout.lines("“你好”", 200)[0]
    assert latin[0][2] == 7 and cjk[0][2] == 13


def test_indic_note_on_the_side_screen(make_client, monkeypatch):
    from test_translate_wings import FakeEngine, _flush
    c = make_client()
    a = c.app_module
    fake = FakeEngine()
    fake.translate = lambda text, s, t: "नमस्ते" if t == "hi" else "ok"
    monkeypatch.setattr(a, "_tr_engine", fake)
    c.put("/api/v1/outputs", json={"chatbox": True, "kd": True})
    c.put("/api/v1/translate", json={"enabled": True, "targets": ["hi"], "kd": True})
    assert c.get("/api/v1/translate").json()["no_display"] == sorted(tr.NO_DISPLAY)
    m = c.post("/api/v1/messages", json={"text": "你好"}).json()
    assert m["translations"]["hi"] == "नमस्ते"                    # the chatbox gets the translation
    k = a._kd
    _flush(k)
    e = k.logs[2].lay[k.msgs[-1]["id"]]
    assert "chatbox only" in " ".join(e["lines"])               # the side screen: the note
