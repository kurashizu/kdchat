"""Fill keyboard: the text goes into the game's keyboard and nothing follows it into the chatbox (no waiting live
update, the typing indicator off first and not renewed / switched off again afterwards)."""
import socket
import time


def _drain(receiver, wait=0.3):
    out = []
    receiver.sock.settimeout(wait)
    try:
        while True:
            out.append(receiver.message())
    except socket.timeout:
        pass
    receiver.sock.settimeout(2.0)
    return out


def test_fill_after_live_and_typing(make_client, receiver, monkeypatch):
    c = make_client(env={"VRC_HOST": "127.0.0.1", "VRC_PORT": str(receiver.port)})
    a = c.app_module
    monkeypatch.setattr(a._cb, "GAP", 0.5)
    c.put("/api/v1/typing", json={"typing": True})
    m = c.post("/api/v1/messages", json={"text": "hel", "final": False}).json()
    c.patch(f"/api/v1/messages/{m['id']}", json={"text": "hello", "final": False})    # waits for its turn
    _drain(receiver, 0.1)
    c.delete(f"/api/v1/messages/{m['id']}")                       # the console drops the live draft first
    r = c.post("/api/v1/messages", json={"text": "hello keyboard", "immediate": False})
    assert r.status_code == 201
    c.put("/api/v1/typing", json={"typing": False})                # (the console's own typing off arrives late)
    time.sleep(0.6)                                                # (past the live update's turn)
    got = _drain(receiver)
    assert got[-1] == ("/chatbox/input", ["hello keyboard", False, False]), got
    assert ("/chatbox/typing", [False]) in got and got.index(("/chatbox/typing", [False])) < len(got) - 1
    assert not a._typing_state and a._typing_timer is None
    clear = next(i for i, m in enumerate(got) if m == ("/chatbox/input", ["", True, False]))
    assert clear < len(got) - 1


def test_fill_waits_for_the_rate_limit(make_client, receiver, monkeypatch):
    c = make_client(env={"VRC_HOST": "127.0.0.1", "VRC_PORT": str(receiver.port)})
    monkeypatch.setattr(c.app_module._cb, "GAP", 0.4)
    c.post("/api/v1/messages", json={"text": "sent"})
    t0 = time.monotonic()
    c.post("/api/v1/messages", json={"text": "kb", "immediate": False})
    assert time.monotonic() - t0 >= 0.3
    assert _drain(receiver)[-1] == ("/chatbox/input", ["kb", False, False])
