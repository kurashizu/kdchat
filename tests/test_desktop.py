"""The desktop launcher: server in a thread, the window URL logs in with the session token, closing stops it.
(The window itself is stubbed: there is no WebView2 here.)"""
import http.cookiejar
import socket
import urllib.request

import app as appmod
import desktop


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


def test_desktop_window_flow(monkeypatch, tmp_path):
    import vcb_config as cfg
    monkeypatch.setattr(appmod, "SETTINGS", cfg.Settings(str(tmp_path / "s.json"), env={"AUTH_PASSWORD": "pw-123"}))
    monkeypatch.setattr(appmod, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(appmod, "SESSION_TOKEN", None)
    monkeypatch.setattr(appmod, "RUNTIME", {"listen_host": None, "listen_port": None})
    port = _free_port()
    seen = {}

    def fake_window(url, title):
        seen["url"], seen["title"] = url, title
        assert desktop._already_running(port)                       # (answers like vrc-chatbox, with a password)
        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        with op.open(url, timeout=5) as r:                          # the window's first load: sets the cookie
            seen["page"] = r.status
        with op.open(f"http://127.0.0.1:{port}/api/v1/info", timeout=5) as r:
            seen["api"] = r.status
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/info", timeout=5)
            seen["no_cookie"] = 200
        except urllib.error.HTTPError as e:
            seen["no_cookie"] = e.code
        return True

    monkeypatch.setattr(desktop, "_open_window", fake_window)
    assert desktop.main(["--host", "127.0.0.1", "--port", str(port)]) == 0
    assert "?session=" in seen["url"] and seen["title"].startswith("vrc-chatbox")
    assert seen == {**seen, "page": 200, "api": 200, "no_cookie": 401}
    assert appmod.port_free("127.0.0.1", port) is None              # stopped: the port is free again
