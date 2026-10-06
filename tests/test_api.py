import base64
import os
import re
import socket
import time

import app as appmod
import kdchat_config as cfg
from version import __version__


def basic(pw, user="u"):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


# ---------------------------------------------------------------- auth

def test_no_password_no_login(make_client):
    c = make_client()
    assert c.get("/api/v1/info").json()["auth"]["enabled"] is False
    r = c.get("/")
    assert r.status_code == 200 and "<html" in r.text
    js = next(f for f in os.listdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui", "_app", "immutable")) if f.endswith(".js"))
    assert c.get(f"/_app/immutable/{js}").status_code == 200
    assert c.get("/_app/immutable/nope.js").status_code == 404
    assert c.get("/_app/../app.py").status_code == 404
    assert c.get("/icon.svg").status_code == 200


def test_env_password_required(make_client):
    c = make_client(env={"AUTH_PASSWORD": "hunter2"})
    r = c.get("/api/v1/health")
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Basic")
    assert c.get("/api/v1/health", headers=basic("wrong")).status_code == 401
    assert c.get("/api/v1/health", headers=basic("hunter2")).status_code == 200
    assert c.get("/", headers=basic("hunter2")).status_code == 200
    assert c.get("/").status_code == 401
    assert c.get("/docs").status_code == 200                     # the overview page stays public


def test_set_change_remove_password(make_client):
    c = make_client()
    r = c.put("/api/v1/settings/password", json={"new_password": "abc"})
    assert r.status_code == 400                                  # too short
    r = c.put("/api/v1/settings/password", json={"new_password": "first-pw"})
    assert r.json() == {"enabled": True, "source": "settings"}
    assert c.get("/api/v1/info").status_code == 401
    h = basic("first-pw")
    r = c.put("/api/v1/settings/password", headers=h, json={"current_password": "nope", "new_password": "second"})
    assert r.status_code == 403
    r = c.put("/api/v1/settings/password", headers=h, json={"new_password": "second"})   # no current password
    assert r.status_code == 403
    r = c.put("/api/v1/settings/password", headers=h, json={"current_password": "first-pw", "new_password": "second"})
    assert r.status_code == 200
    h = basic("second")
    r = c.put("/api/v1/settings/password", headers=h, json={"current_password": "second", "new_password": None})
    assert r.json() == {"enabled": False, "source": None}
    assert c.get("/api/v1/info").status_code == 200


def test_desktop_session_cookie(make_client, monkeypatch):
    c = make_client(env={"AUTH_PASSWORD": "pw-x"})
    monkeypatch.setattr(appmod, "SESSION_TOKEN", "tok123")
    assert c.get("/api/v1/info").status_code == 401
    r = c.get("/?session=wrong", follow_redirects=False)
    assert r.status_code == 303 and "set-cookie" not in r.headers
    r = c.get("/?session=tok123", follow_redirects=False)
    assert r.status_code == 303 and "kdchat_session=tok123" in r.headers["set-cookie"]
    assert c.get("/api/v1/info").status_code == 200              # (the client keeps the cookie)


def test_cross_origin_refused(make_client):
    c = make_client()
    body = {"text": "hi"}
    r = c.post("/api/v1/messages", json=body, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = c.post("/api/v1/messages", json=body, headers={"Origin": "null"})
    assert r.status_code == 403
    r = c.post("/api/v1/messages", json=body, headers={"Origin": "http://testserver"})
    assert r.status_code == 201
    assert c.get("/api/v1/info", headers={"Origin": "https://evil.example"}).status_code == 200   # reads: no CORS headers


# ---------------------------------------------------------------- OSC target

def test_osc_default_and_env(make_client):
    c = make_client()
    o = c.get("/api/v1/osc").json()
    assert (o["host"], o["port"], o["source"]) == ("127.0.0.1", 9000, "default")
    c = make_client(env={"VRC_HOST": "127.0.0.1", "VRC_PORT": "9123"})
    o = c.get("/api/v1/osc").json()
    assert (o["port"], o["source"]) == (9123, "env")


def test_osc_target_change_moves_packets(make_client, receiver):
    other = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    other.bind(("127.0.0.1", 0)); other.settimeout(0.3)
    c = make_client(env={"VRC_HOST": "127.0.0.1", "VRC_PORT": str(other.getsockname()[1])})
    r = c.put("/api/v1/osc", json={"host": "127.0.0.1", "port": receiver.port})
    assert r.status_code == 200 and r.json()["source"] == "settings"
    assert c.post("/api/v1/messages", json={"text": "hello", "sfx": False}).status_code == 201
    assert receiver.message() == ("/chatbox/input", ["hello", True, False])
    try:
        other.recvfrom(1024)
        raise AssertionError("the old target still got a packet")
    except socket.timeout:
        pass
    assert c.put("/api/v1/typing", json={"typing": True}).status_code == 200
    assert receiver.message() == ("/chatbox/typing", [True])
    # saved: a new Settings object on the same file sees it
    assert cfg.Settings(appmod.SETTINGS.path, env={}).get("osc_port") == (receiver.port, "settings")
    # reset: back to the environment's target
    o = c.delete("/api/v1/osc").json()
    assert (o["port"], o["source"]) == (other.getsockname()[1], "env")
    c.post("/api/v1/messages", json={"text": "back"})
    data, _ = other.recvfrom(1024)
    assert b"back" in data
    other.close()


def test_osc_validation(make_client):
    c = make_client()
    assert c.put("/api/v1/osc", json={"host": "bad host", "port": 9000}).status_code == 400
    assert c.put("/api/v1/osc", json={"host": "127.0.0.1", "port": 0}).status_code == 400
    assert c.put("/api/v1/osc", json={"host": "127.0.0.1", "port": 70000}).status_code == 400
    assert c.put("/api/v1/osc", json={"host": "no-such-host.invalid", "port": 9000}).status_code == 400
    assert c.put("/api/v1/osc", json={"host": "127.0.0.1", "port": "x"}).status_code == 422
    assert c.get("/api/v1/osc").json()["source"] == "default"      # nothing was saved


def test_unresolvable_target_at_startup(make_client):
    c = make_client(env={"VRC_HOST": "no-such-host.invalid"})
    o = c.get("/api/v1/osc").json()
    assert o["error"] and o["ip"] is None
    r = c.post("/api/v1/messages", json={"text": "x"})
    assert r.status_code == 502 and "Settings" in r.json()["detail"]
    assert c.get("/api/v1/health").json()["ok"] is False


# ---------------------------------------------------------------- messages

def test_message_flow(make_client, receiver):
    c = make_client(env={"VRC_HOST": "127.0.0.1", "VRC_PORT": str(receiver.port)})
    assert c.post("/api/v1/messages", json={"text": ""}).status_code == 400
    assert c.post("/api/v1/messages", json={"text": "x" * 145}).status_code == 400
    assert c.post("/api/v1/messages", json={"text": "\n".join("a" * 10)}).status_code == 400
    r = c.post("/api/v1/messages", json={"text": "typing", "final": False})
    assert r.status_code == 201 and r.json()["final"] is False
    mid = r.json()["id"]
    assert receiver.message()[0] == "/chatbox/input"
    r = c.patch(f"/api/v1/messages/{mid}", json={"text": "typed", "final": True})
    assert r.json()["final"] is True and r.json()["text"] == "typed"
    assert receiver.message() == ("/chatbox/input", ["typed", True, True])
    items = c.get("/api/v1/messages").json()["items"]
    assert [m["text"] for m in items] == ["typed"]
    assert c.get(f"/api/v1/messages/{mid}").json()["id"] == mid
    assert c.get("/api/v1/messages/999").status_code == 404
    assert c.delete(f"/api/v1/messages/{mid}").status_code == 409     # sent: revert instead
    r = c.post("/api/v1/messages", json={"text": "kb", "immediate": False})
    assert r.json()["immediate"] is False
    assert receiver.message() == ("/chatbox/input", ["kb", False, False])
    assert c.delete("/api/v1/messages").status_code == 204
    assert c.get("/api/v1/messages").json()["total"] == 0


def test_outputs(make_client):
    c = make_client()
    o = c.get("/api/v1/outputs").json()
    assert o["chatbox"] is True and o["max_chars"] == 144
    o = c.put("/api/v1/outputs", json={"chatbox": False}).json()
    assert o["chatbox"] is False
    assert c.post("/api/v1/messages", json={"text": "x"}).status_code == 409   # no output on


# ---------------------------------------------------------------- settings, network, meta

def test_server_address_settings(make_client):
    c = make_client()
    s = c.get("/api/v1/settings/server").json()
    assert (s["listen_host"], s["listen_port"], s["restart_needed"]) == ("0.0.0.0", 5555, False)
    s = c.put("/api/v1/settings/server", json={"listen_port": 6001}).json()
    assert s["listen_port"] == 6001 and s["restart_needed"] is True
    assert c.put("/api/v1/settings/server", json={"listen_port": 0}).status_code == 400
    assert c.put("/api/v1/settings/server", json={"listen_host": "x y"}).status_code == 400
    s = c.delete("/api/v1/settings/server").json()
    assert s["listen_port"] == 5555 and s["restart_needed"] is False


def test_network_and_qr(make_client):
    c = make_client()
    n = c.get("/api/v1/network").json()
    assert set(n) >= {"urls", "listen_host", "listen_port", "open_on_lan", "auth_enabled"}
    for u in n["urls"]:
        assert re.fullmatch(r"http://\d+\.\d+\.\d+\.\d+:\d+/", u)
    r = c.get("/api/v1/network/qr.svg", params={"url": "http://192.168.1.2:5555/"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg") and b"<svg" in r.content
    assert c.get("/api/v1/network/qr.svg", params={"url": "javascript:x"}).status_code == 400
    s = c.get("/api/v1/settings").json()
    assert s["version"] == __version__ and {"osc", "server", "password", "network"} <= set(s)


def test_netinfo_urls():
    import netinfo
    assert netinfo.urls("127.0.0.1", 5555) == []
    assert netinfo.urls("192.168.5.5", 80) == ["http://192.168.5.5:80/"]
    for ip in netinfo.lan_ipv4():
        assert not ip.startswith(("127.", "169.254."))
    assert netinfo._virtual("vEthernet (WSL)") and netinfo._virtual("docker0") and netinfo._virtual("utun3")
    assert netinfo._virtual("lo0") and netinfo._virtual("br-1a2b") and netinfo._virtual("veth12ab")
    for real in ("Wi-Fi", "en0", "Ethernet", "Ethernet 2", "Local Area Connection", "wlan0", "eth0", "enp3s0", "WLAN"):
        assert not netinfo._virtual(real), real


def test_version_single_source():
    import tomllib
    with open(os.path.join(os.path.dirname(appmod.__file__), "pyproject.toml"), "rb") as f:
        assert tomllib.load(f)["project"]["version"] == __version__
    assert appmod.app.version == __version__


def test_meta_endpoints(make_client):
    c = make_client()
    assert c.get("/api/v1/health").json()["version"] == __version__
    assert c.get("/api/v1/config").json()["listen_port"] == 5555
    assert c.get("/openapi.json").status_code == 200
    assert "kdchat API" in c.get("/docs").text


def test_port_in_use_message():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0)); s.listen(1)
    try:
        msg = appmod.port_free("127.0.0.1", s.getsockname()[1])
        assert msg and "already in use" in msg
    finally:
        s.close()
    assert appmod.port_free("127.0.0.1", 0) is None
