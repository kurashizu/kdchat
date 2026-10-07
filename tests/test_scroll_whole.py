"""Scrolling on every screen shape, with and without side screens: no line is cut by the header at the top, every
line in the band has a line slot (none missing), on the main screen and the side screens."""
import pytest

import kd_chat

TEXTS = ["测试", "hi", "你好", "你好，你是谁", "你可以做什么", "今天天气不错呢我们出去玩吧，顺便买点东西回来", "好啊",
         "去哪里", "公园", "OK", "a much longer English line that wraps over more than one line on every screen",
         "这是一条很长的消息，" * 12]                    # (wrapped lines without a gap: the most lines in the band)


def _run(k, check):
    for i, t in enumerate(TEXTS * 2):
        mid = k.new_message(t, True, False)
        if k.wing_text_on:
            long = i % len(TEXTS) == len(TEXTS) - 1
            k.set_translations(mid, {"en": f"translation {i} " + "word " * (40 if long else i % 4),
                                     "ja": "訳" * (90 if long else i % 7 + 1)}, "zh")
        for _ in range(40):
            k.d.link.pending = lambda: []
            with k.lock:
                k._step()
            check(k, False)
        check(k, True)                                  # (settled)


@pytest.mark.parametrize("screen", kd_chat.SCREENS)
@pytest.mark.parametrize("wings", [0, 1, 2], ids=["main", "one", "two"])
@pytest.mark.parametrize("show_time", [True, False], ids=["time", "plain"])
def test_whole_lines(screen, wings, show_time):
    k = kd_chat.KdChat("127.0.0.1", 9, dry=True, settings={"screen": screen, "show_time": show_time}, run=False)
    k.set_active(True)
    if wings:
        k.set_wing_text_on(True)
        k.set_wing_langs("ja" if wings == 2 else None, "en", ("JA", "EN"))

    def check(k, settled):
        msgs = k._all()
        for j, log in enumerate(k.logs):
            if not k.log_on(j):
                continue
            rows = k._rows(j, msgs)
            S = log.S
            for key, r in rows.items():
                assert not (r[3] < S < r[4]) or key not in log.slots, (j, key, S, r[3:5])   # cut by the header
            if settled:                                  # at rest: every line in the band is there
                missing = [key for key, r in rows.items() if r[3] >= S and r[4] <= S + k.band and key not in log.slots]
                assert not missing, (j, missing, S)
    _run(k, check)
