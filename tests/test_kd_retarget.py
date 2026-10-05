"""The Klaude display follows an OSC target change too (its frames go to the new address)."""
import socket
import time

import pytest

import app as appmod

kd_chat = pytest.importorskip("kd_chat")


def test_kd_frames_follow_the_target(receiver, monkeypatch):
    old = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    old.bind(("127.0.0.1", 0)); old.settimeout(3)
    kd = kd_chat.KdChat("127.0.0.1", old.getsockname()[1], dry=False)
    monkeypatch.setattr(appmod, "_kd", kd)
    try:
        kd.set_active(True)
        data, _ = old.recvfrom(65536)                    # frames arrive at the first target
        assert data.startswith(b"#bundle") or data.startswith(b"/avatar")
        appmod._apply_osc_target("127.0.0.1", receiver.port)
        deadline = time.time() + 5
        got = False
        while time.time() < deadline and not got:
            data = receiver.recv()
            got = b"/avatar/parameters/" in data
        assert got
    finally:
        kd.set_active(False)
        kd._stop = True
        old.close()
