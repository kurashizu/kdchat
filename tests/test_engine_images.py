"""The translation engine host (bergamot_wasm: wasmtime + a small embind) and the picture pipeline (imgproc)."""
import os
import struct

import pytest

import bergamot_wasm as BW
import imgproc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def engine():
    with open(os.path.join(ROOT, "vendor", "bergamot", "bergamot-translator.wasm"), "rb") as f:
        return BW.Bergamot(f.read())


def test_engine_starts_and_registers_the_api(engine):
    for cls in ("AlignedMemory", "AlignedMemoryList", "TranslationModel", "BlockingService", "VectorString",
                "VectorResponseOptions", "VectorResponse", "Response"):
        assert cls in engine.classes, cls
    assert engine.service
    m = engine._aligned(b"x" * 1000, 64)                       # memory blocks go in and the view points at them
    assert engine._method("AlignedMemory", "size", m) == 1000
    size, ptr = engine._method("AlignedMemory", "getByteArrayView", m)
    assert size == 1000 and engine._read(ptr, 4) == b"xxxx" and ptr % 64 == 0
    engine._delete("AlignedMemory", m)
    assert not engine.emvals                                    # every handle given back


def test_engine_bad_model_is_an_error_not_a_crash(engine):
    with pytest.raises(BW.EngineError):
        engine.model("de", "en", "\n            quiet: true\n            ", b"not a model", None, [b"nor a vocab"],
                     {"model": 256, "lex": 64, "vocab": 64, "srcvocab": 64, "trgvocab": 64})


@pytest.mark.parametrize("text,parts", [
    ("", [""]),
    ("Hello", ["Hello"]),
    ("Hi. How are you? Fine!", ["Hi. ", "How are you? ", "Fine!"]),
    ("Mr. Smith said \"go.\" Then left.", ["Mr. ", "Smith said \"go.\" ", "Then left."]),
    ("你好。今天天气不错！要出去吗？", ["你好。", "今天天气不错！", "要出去吗？"]),
    ("3.14 is pi", ["3.14 is pi"]),
    ("trailing space. ", ["trailing space. "]),
], ids=["empty", "word", "three", "abbreviation", "cjk", "decimal", "trailing-space"])
def test_sentences_cover_the_text(text, parts):
    got = BW._sentences(text)
    assert "".join(got) == text
    assert got == parts


def _raw(w, h, px=None):
    return imgproc.MAGIC + struct.pack(">HH", w, h) + (px if px is not None else bytes(w * h * 3))


@pytest.mark.parametrize("data", [
    _raw(0, 5), _raw(5, 0), _raw(2000, 10), _raw(4, 4, b"\0" * 47), imgproc.MAGIC + b"\0", b"",
], ids=["no-width", "no-height", "too-wide", "short-body", "short-header", "empty"])
def test_raw_pictures_are_checked(data):
    with pytest.raises(ValueError):
        imgproc.load(data)


@pytest.mark.parametrize("w,h", [(1, 1), (1, 300), (500, 2), (3, 7), (176, 96), (40, 30)])
@pytest.mark.parametrize("mode", ["cover", "contain"])
def test_fit_any_shape(w, h, mode):
    im = imgproc.Img(w, h, bytes(((x * 7 + y * 3) % 256) for y in range(h) for x in range(w) for _ in range(3)))
    out = imgproc.fit(im, (176, 86), mode)
    if mode == "cover":
        assert out.size == (176, 86)
    else:
        assert out.w <= 176 and out.h <= 86 and (out.w == 176 or out.h == 86)


def test_pipeline_flat_and_tiny_pictures():
    import kd_chat
    for im in (imgproc.Img(1, 1, b"\x80\x80\x80"), imgproc.Img(8, 8, b"\xff" * 192), imgproc.Img(3, 2)):
        out = kd_chat.prepare_image(im, 176, 96, 10, "cover")
        assert out.size == (176, 96)
        assert out.px[:176 * 10 * 3] == bytes(176 * 10 * 3)             # the header band stays black
        pal = kd_chat.adaptive_palette(out, [(0, 0, 0)] * 16, {0, 1})
        assert len(pal) == 16
        idx = kd_chat.quantize(out, pal, per_tile=4)
        assert len(idx) == 96 and len(idx[0]) == 176


def test_median_cut_counts():
    im = imgproc.Img(4, 1, bytes([255, 0, 0] * 3 + [0, 0, 255]))
    cols = imgproc.median_cut(im, 4)
    assert sum(n for _, n in cols) == 4 and cols[0][0] == (255, 0, 0)


def test_image_api_raw_and_errors(make_client):
    c = make_client()
    c.put("/api/v1/outputs", json={"kd": True})
    assert c.post("/api/v1/kd/image", content=_raw(64, 48, bytes(range(256)) * 36)).status_code == 200
    assert c.post("/api/v1/kd/image", content=b"").status_code == 400
    assert c.post("/api/v1/kd/image", content=b"garbage").status_code == 400
    assert c.post("/api/v1/kd/image", content=_raw(10, 10, b"\0" * 5)).status_code == 400
    assert c.delete("/api/v1/kd/image").status_code == 204


def test_typing_indicator_expires(make_client, monkeypatch):
    """a page that goes away while typing never leaves "typing" on: it lasts TYPING_TTL unless renewed"""
    import time
    c = make_client()
    a = c.app_module
    monkeypatch.setattr(a, "TYPING_TTL", 0.3)
    assert c.put("/api/v1/typing", json={"typing": True}).json()["typing"] is True
    time.sleep(0.15)
    c.put("/api/v1/typing", json={"typing": True})              # renewed: still on after the first period
    time.sleep(0.2)
    assert c.get("/api/v1/typing").json()["typing"] is True
    time.sleep(0.4)
    assert c.get("/api/v1/typing").json()["typing"] is False
    assert c.put("/api/v1/typing", json={"typing": True, "targets": ["nope"]}).status_code == 400
    assert c.get("/api/v1/typing").json()["typing"] is False    # (a bad request changes nothing)
