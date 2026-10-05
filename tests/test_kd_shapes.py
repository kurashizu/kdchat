"""The kd chat draws its header rule, dividers and draft caret as hardware shapes. The log's shapes scroll through
the shape layer's offset: check, frame by frame on what the viewers hold, that none ever shows outside the log band."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from kd_chat import KdChat, SHP_LOG0  # noqa: E402
from kd.shapes import Shape  # noqa: E402


def _viewer_shapes(k):
    c, buf = k.d.cfg, k.d.link.sent
    oy = buf[c.regs["shape_y"]]
    out = []
    for i in range(SHP_LOG0, c.shp_n):
        a = c.shp_base + i * c.shp_bytes_per
        sh = Shape(buf[a:a + c.shp_bytes_per], c.shp_off)
        if sh.kind:
            y = sh.pt[0][1] + oy
            if y >= c.H:
                y -= c.H
            out.append((i, y, sh))
    return out


def test_log_shapes_stay_in_the_band():
    k = KdChat("127.0.0.1", 9, dry=True, settings={"divider": True}, run=False)
    k.set_active(True)
    seen = 0
    texts = ["Hello everyone!", "brb, getting tea", "OK I'm back. 好的我回来了", "Anyone up for the cabin?",
             "a longer message that wraps over more than one line of the little screen", "sure", "ok", "see you there"]
    for n, t in enumerate(texts * 2):
        k.add_message(t[: len(t) // 2], immediate=False)            # a draft first (the caret)
        for _ in range(40):
            k.tick()
        k.new_message(t)
        for _ in range(120):
            k.tick()
            for i, y, sh in _viewer_shapes(k):
                seen += 1
                h = sh.pt[1][1] - sh.pt[0][1] if sh.kind == 2 else 0
                assert k.top <= y and y + h < k.d.cfg.H, (n, i, y, k.top, k.S)
    assert seen > 0


def test_header_rule_is_a_shape_and_graphics_stay_empty():
    k = KdChat("127.0.0.1", 9, dry=True, run=False)
    k.set_active(True)
    k.new_message("hi")
    for _ in range(300):
        k.tick()
    c = k.d.cfg
    assert k.d.shapes.data[0] is not None
    assert not any(k.d.link.want[c.bitmap_base:c.pal_base])        # no bitmap / tile colours to send
