"""Configuration of kdchat.

Every setting is looked up in this order: the settings file (changed from the web console's Settings) > the
environment (or a .env file) > the built-in default.

  setting       settings file key   environment     default
  OSC target    osc_host/osc_port   VRC_HOST/PORT   127.0.0.1:9000  (VRChat on the same machine)
  HTTP bind     listen_host         LISTEN_HOST     0.0.0.0         (reachable from your phone on the LAN)
  HTTP port     listen_port         LISTEN_PORT     5555
  password      password / auth     AUTH_PASSWORD   none = no login (the console is open to everyone who can reach it)

The settings file stores a password only as a salted PBKDF2 hash. "auth": "off" in the file turns off a password
that comes from the environment (removing it in the console needs the current password).

Where files live: SETTINGS_FILE / STATE_FILE (environment) or KDCHAT_DATA_DIR, else next to app.py when run from
source, else (the Windows .exe) %APPDATA%\\kdchat.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import sys
import threading
from typing import Any, Optional

log = logging.getLogger("kdchat")

APP_NAME = "kdchat"
OLD_APP_NAME = "vrc-chatbox"                   # the name before 1.3.0 (its data folder is moved over)
DEFAULTS: dict[str, Any] = {"osc_host": "127.0.0.1", "osc_port": 9000, "listen_host": "0.0.0.0", "listen_port": 5555}
ENV_NAMES = {"osc_host": "VRC_HOST", "osc_port": "VRC_PORT", "listen_host": "LISTEN_HOST", "listen_port": "LISTEN_PORT"}
PBKDF2_ITERATIONS = 240_000
MIN_PASSWORD = 4
MAX_PASSWORD = 256


def frozen() -> bool:
    """running from the PyInstaller .exe"""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """where the code and its bundled files (ui/, kd_display/) are"""
    if frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def data_dir() -> str:
    """where settings.json / state.json / .env are kept"""
    d = os.getenv("KDCHAT_DATA_DIR") or os.getenv("VCB_DATA_DIR")     # (VCB_DATA_DIR: the name before 1.3.0)
    if not d:
        if not frozen():
            d = os.path.dirname(os.path.abspath(__file__))
        else:
            base = os.getenv("APPDATA") if os.name == "nt" else os.getenv("XDG_CONFIG_HOME")
            base = base or (os.path.expanduser("~") if os.name == "nt" else os.path.expanduser("~/.config"))
            d = os.path.join(base, APP_NAME)
            old = os.path.join(base, OLD_APP_NAME)
            if not os.path.exists(d) and os.path.isdir(old):
                try:
                    os.rename(old, d)                      # settings of the app's old name move along
                except OSError:
                    d = old
    os.makedirs(d, exist_ok=True)
    return d


def load_dotenv(path: str) -> None:
    """KEY=VALUE lines (# comments) of a .env file: only fills in variables that are not set already"""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("could not read %s: %s", path, e)


# ---------------------------------------------------------------- validation

_LABEL = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")


def valid_host(host: str) -> bool:
    """an IPv4 address or a host name (RFC 1123)"""
    if not isinstance(host, str):
        return False
    host = host.strip()
    if not host or len(host) > 253:
        return False
    if re.fullmatch(r"[0-9.]+", host):                 # looks numeric: must be a real IPv4 address
        try:
            ipaddress.IPv4Address(host)
            return True
        except ValueError:
            return False
    return all(_LABEL.match(p) for p in host.rstrip(".").split("."))


def valid_port(port: Any) -> bool:
    return isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535


def parse_port(v: Any) -> Optional[int]:
    try:
        p = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    return p if valid_port(p) else None


# ---------------------------------------------------------------- passwords

def hash_password(pw: str, salt: Optional[bytes] = None, iterations: int = PBKDF2_ITERATIONS) -> dict:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, iterations)
    return {"algo": "pbkdf2_sha256", "iterations": iterations, "salt": salt.hex(), "hash": dk.hex()}


def check_hash(pw: str, h: dict) -> bool:
    try:
        if h.get("algo") != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(h["salt"]), int(h["iterations"]))
        return hmac.compare_digest(dk.hex(), h["hash"])
    except (KeyError, TypeError, ValueError):
        return False


# ---------------------------------------------------------------- the settings file

class Settings:
    """settings file (JSON object) + environment + defaults. Thread-safe; saves atomically."""

    def __init__(self, path: str, env: Optional[dict] = None):
        self.path = path
        self.env = os.environ if env is None else env
        self.lock = threading.RLock()
        self.warning: Optional[str] = None             # set when the file could not be used
        self.data: dict = self._load()
        self._hash_cache: dict = {}                     # (sha256(password), salt, hash) -> ok: Basic auth stays fast

    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("not a JSON object")
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            self.warning = f"settings file {self.path} is unreadable ({e}); using the defaults"
            log.warning(self.warning)
            try:                                        # keep it for the user, a save would overwrite it
                os.replace(self.path, self.path + ".bad")
                log.warning("moved it to %s.bad", self.path)
            except OSError:
                pass
            return {}
        clean = {}
        for k, v in data.items():                       # drop invalid values (hand edits) with a warning
            ok = {"osc_host": valid_host, "listen_host": valid_host}.get(k)
            if k in ("osc_port", "listen_port"):
                ok = valid_port
            if ok is not None and not ok(v):
                log.warning("settings file: ignoring invalid %s=%r", k, v)
                continue
            clean[k] = v
        return clean

    def save(self) -> None:
        with self.lock:
            d = os.path.dirname(self.path)
            if d:
                os.makedirs(d, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, self.path)

    # values with their source -------------------------------------------------
    def get(self, key: str) -> tuple[Any, str]:
        """(value, "settings" | "env" | "default")"""
        with self.lock:
            if key in self.data:
                return self.data[key], "settings"
        env = self.env.get(ENV_NAMES[key], "")
        if env.strip():
            if key.endswith("port"):
                p = parse_port(env)
                if p is not None:
                    return p, "env"
                log.warning("%s=%r is not a valid port; using %s", ENV_NAMES[key], env, DEFAULTS[key])
            elif valid_host(env.strip()):
                return env.strip(), "env"
            else:
                log.warning("%s=%r is not a valid host; using %s", ENV_NAMES[key], env, DEFAULTS[key])
        return DEFAULTS[key], "default"

    def value(self, key: str) -> Any:
        return self.get(key)[0]

    def env_or_default(self, key: str) -> tuple[Any, str]:
        """what the value would be without the settings file (the "reset" value)"""
        with self.lock:
            saved = self.data.pop(key, None)
            try:
                return self.get(key)
            finally:
                if saved is not None:
                    self.data[key] = saved

    def set(self, **kv) -> None:
        with self.lock:
            for k, v in kv.items():
                if v is None:
                    self.data.pop(k, None)
                else:
                    self.data[k] = v
            self.save()

    # password ------------------------------------------------------------------
    def auth_source(self) -> Optional[str]:
        """None (no password) | "settings" | "env" """
        with self.lock:
            if isinstance(self.data.get("password"), dict):
                return "settings"
            if self.data.get("auth") == "off":
                return None
        return "env" if self.env.get("AUTH_PASSWORD", "") else None

    def auth_enabled(self) -> bool:
        return self.auth_source() is not None

    def check_password(self, pw: str) -> bool:
        src = self.auth_source()
        if src is None:
            return True
        if src == "env":
            return hmac.compare_digest(pw.encode("utf-8"), self.env.get("AUTH_PASSWORD", "").encode("utf-8"))
        h = self.data["password"]
        key = (hashlib.sha256(pw.encode("utf-8")).hexdigest(), h.get("salt"), h.get("hash"))
        if key not in self._hash_cache:
            if len(self._hash_cache) > 64:
                self._hash_cache.clear()
            self._hash_cache[key] = check_hash(pw, h)
        return self._hash_cache[key]

    def set_password(self, pw: Optional[str]) -> None:
        """a new password (hashed into the file), or None = no password (also overrides AUTH_PASSWORD)"""
        with self.lock:
            self._hash_cache.clear()
            if pw:
                self.data["password"] = hash_password(pw)
                self.data.pop("auth", None)
            else:
                self.data.pop("password", None)
                if self.env.get("AUTH_PASSWORD", ""):
                    self.data["auth"] = "off"
                else:
                    self.data.pop("auth", None)
            self.save()
