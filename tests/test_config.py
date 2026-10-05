import json
import os

import pytest

import vcb_config as cfg


@pytest.mark.parametrize("host,ok", [
    ("127.0.0.1", True), ("192.168.1.20", True), ("localhost", True), ("my-pc.local", True), ("vrchat-pc", True),
    ("", False), ("256.1.1.1", False), ("1.2.3", False), ("bad host", False), ("-x.com", False), ("a" * 64, False),
    ("http://x", False), ("1.2.3.4:9000", False),
])
def test_valid_host(host, ok):
    assert cfg.valid_host(host) is ok


@pytest.mark.parametrize("port,ok", [(1, True), (9000, True), (65535, True), (0, False), (65536, False),
                                     ("9000", False), (True, False), (-1, False)])
def test_valid_port(port, ok):
    assert cfg.valid_port(port) is ok


def test_defaults(tmp_path):
    s = cfg.Settings(str(tmp_path / "s.json"), env={})
    assert s.get("osc_host") == ("127.0.0.1", "default")
    assert s.get("osc_port") == (9000, "default")
    assert s.get("listen_host") == ("0.0.0.0", "default")
    assert s.get("listen_port") == (5555, "default")
    assert not s.auth_enabled()


def test_precedence_settings_over_env_over_default(tmp_path):
    env = {"VRC_HOST": "10.1.2.3", "VRC_PORT": "9001", "LISTEN_PORT": "6000"}
    s = cfg.Settings(str(tmp_path / "s.json"), env=env)
    assert s.get("osc_host") == ("10.1.2.3", "env")
    assert s.get("osc_port") == (9001, "env")
    assert s.get("listen_port") == (6000, "env")
    s.set(osc_host="192.168.0.5", osc_port=9100)
    assert s.get("osc_host") == ("192.168.0.5", "settings")
    assert s.env_or_default("osc_host") == ("10.1.2.3", "env")
    assert s.get("osc_host") == ("192.168.0.5", "settings")      # (env_or_default leaves the setting alone)
    s2 = cfg.Settings(str(tmp_path / "s.json"), env=env)          # saved
    assert s2.get("osc_port") == (9100, "settings")
    s2.set(osc_host=None, osc_port=None)                          # reset
    assert s2.get("osc_host") == ("10.1.2.3", "env")


def test_invalid_env_falls_back(tmp_path):
    s = cfg.Settings(str(tmp_path / "s.json"), env={"VRC_PORT": "abc", "VRC_HOST": "not a host"})
    assert s.get("osc_port") == (9000, "default")
    assert s.get("osc_host") == ("127.0.0.1", "default")


def test_broken_settings_file(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{ this is not json", encoding="utf-8")
    s = cfg.Settings(str(p), env={})
    assert s.warning and "unreadable" in s.warning
    assert s.get("osc_host") == ("127.0.0.1", "default")
    assert (tmp_path / "s.json.bad").exists()


def test_invalid_values_in_file_are_ignored(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"osc_host": "bad host!", "osc_port": 99999, "listen_port": 7000}), encoding="utf-8")
    s = cfg.Settings(str(p), env={})
    assert s.get("osc_host")[1] == "default"
    assert s.get("osc_port")[1] == "default"
    assert s.get("listen_port") == (7000, "settings")


def test_password_hash_roundtrip():
    h = cfg.hash_password("secret", iterations=1000)
    assert h["hash"] != "secret" and "secret" not in json.dumps(h)
    assert cfg.check_hash("secret", h)
    assert not cfg.check_hash("Secret", h)
    assert not cfg.check_hash("secret", {"algo": "md5"})


def test_password_sources(tmp_path):
    p = str(tmp_path / "s.json")
    s = cfg.Settings(p, env={"AUTH_PASSWORD": "envpw"})
    assert s.auth_source() == "env" and s.check_password("envpw") and not s.check_password("x")
    s.set_password("newpw")                                   # settings beat the environment
    assert s.auth_source() == "settings" and s.check_password("newpw") and not s.check_password("envpw")
    assert "newpw" not in open(p, encoding="utf-8").read()
    s.set_password(None)                                      # removing it also turns the env password off
    assert s.auth_source() is None and s.check_password("anything")
    assert cfg.Settings(p, env={"AUTH_PASSWORD": "envpw"}).auth_source() is None
    s3 = cfg.Settings(str(tmp_path / "t.json"), env={})
    s3.set_password(None)
    assert "auth" not in s3.data


def test_settings_file_permissions(tmp_path):
    s = cfg.Settings(str(tmp_path / "s.json"), env={})
    s.set_password("pw12")
    if os.name != "nt":
        assert oct(os.stat(tmp_path / "s.json").st_mode & 0o777) == "0o600"
