"""Test setup: an isolated data directory, no password, the Klaude display in dry-run mode."""
import os
import socket
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_DATA = tempfile.mkdtemp(prefix="kdchat-test-")
os.environ["KDCHAT_DATA_DIR"] = _DATA
os.environ["KD_DRY"] = "1"
for k in ("AUTH_PASSWORD", "VRC_HOST", "VRC_PORT", "LISTEN_HOST", "LISTEN_PORT", "SETTINGS_FILE", "STATE_FILE",
          "ALLOWED_ORIGINS"):
    os.environ.pop(k, None)

import app as appmod                     # noqa: E402
import kdchat_config as cfg                 # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pythonosc.osc_message import OscMessage  # noqa: E402


class Receiver:
    """a UDP socket on 127.0.0.1 that collects OSC messages"""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(2.0)
        self.port = self.sock.getsockname()[1]

    def recv(self):
        data, _ = self.sock.recvfrom(65536)
        return data

    def message(self):
        m = OscMessage(self.recv())
        return m.address, list(m.params)

    def close(self):
        self.sock.close()


@pytest.fixture
def receiver():
    r = Receiver()
    yield r
    r.close()


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    """make_client(env={...}) -> a TestClient on a fresh settings file / state with that environment"""
    clients = []

    def make(env=None, **kw):
        env = dict(env or {})
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setattr(appmod, "SETTINGS", cfg.Settings(str(tmp_path / "settings.json"), env=dict(os.environ)))
        monkeypatch.setattr(appmod, "STATE_FILE", str(tmp_path / "state.json"))
        monkeypatch.setattr(appmod, "SESSION_TOKEN", None)
        appmod._outputs.update(chatbox=True, kd=False)
        appmod._history.clear()
        appmod._cb.last = 0.0                     # (the chatbox rate limit: a fresh start)
        monkeypatch.setattr(appmod, "_cb_typing", False)
        monkeypatch.setattr(appmod, "_typing_state", False)
        monkeypatch.setattr(appmod, "_tr_settings", dict(appmod._TR_DEFAULTS))
        c = TestClient(appmod.app, **kw)
        c.app_module = appmod
        c.__enter__()
        clients.append(c)
        return c

    yield make
    for c in clients:
        c.__exit__(None, None, None)
