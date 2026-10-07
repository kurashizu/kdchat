"""kdchat: send messages to the VRChat chatbox from a phone or any browser.

A small web server (FastAPI): a web console at / and a REST API at /api/v1 that turn requests into OSC messages for
VRChat's chatbox (/chatbox/input, /chatbox/typing). It can also drive the Klaude avatar's pixel display (the "kd"
output, see kd_chat.py). OSC details: https://docs.vrchat.com/docs/osc-as-input-controller

Configuration: see kdchat_config.py (settings file > environment / .env > defaults). The login (HTTP Basic, any user
name) is only required when a password is configured.

Run:  uv run python app.py            (or: uv run uvicorn app:app --host 0.0.0.0 --port 5555)
"""

from __future__ import annotations

import argparse
import errno
import hmac
import json
import logging
import os
import socket
import sys
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from pythonosc.udp_client import SimpleUDPClient

import netinfo
import translate as tr
import kdchat_config as cfg
from version import __version__

cfg.load_dotenv(os.path.join(cfg.data_dir(), ".env"))

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("kdchat")

try:                                   # Klaude display output (./kd_chat.py + ./kd_display); optional
    import kd_chat
    _KD_IMPORT_ERROR: Optional[str] = None
except Exception as _e:                # noqa: BLE001
    kd_chat = None
    _KD_IMPORT_ERROR = repr(_e)


# ==================== configuration ====================

SETTINGS_FILE = os.getenv("SETTINGS_FILE") or os.path.join(cfg.data_dir(), "settings.json")
STATE_FILE = os.getenv("STATE_FILE") or os.path.join(cfg.data_dir(), "state.json")   # outputs + display options
SETTINGS = cfg.Settings(SETTINGS_FILE)

KD_DRY = os.getenv("KD_DRY", "") not in ("", "0", "false")      # testing: the display encodes but sends nothing
ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
WWW_AUTH_REALM = "kdchat"   # (must be ASCII)
MODES = ("chatbox", "kd")

# VRChat chatbox limits
MAX_CHARS = 144
MAX_LINES = 9
KD_MAX_CHARS = 400        # the Klaude display can take longer messages (the single layout scrolls them)
KD_MAX_LINES = 20
HISTORY_MAX = 50          # messages kept in the server's history (memory only)

RUNTIME: dict = {"listen_host": None, "listen_port": None}     # what main() / the desktop app actually bound
_server_at_start: dict = {}                                     # the configured address when the server started
SESSION_TOKEN: Optional[str] = None     # set by the desktop app: its own window gets in without the password
SESSION_COOKIE = "kdchat_session"
UI_DIR = os.path.join(cfg.app_dir(), "ui")     # the console: a static SvelteKit build (web/ -> npm run build)
UI_TYPES = {".js": "application/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json",
            ".png": "image/png", ".woff2": "font/woff2"}


# ==================== FastAPI app ====================


@asynccontextmanager
async def _lifespan(_app):
    _startup()
    yield
    log.info("kdchat stopped")


app = FastAPI(
    lifespan=_lifespan,
    title="kdchat",
    description=(
        "Send messages to the VRChat chatbox (OSC) over HTTP.\n\n"
        "🔒 When a password is configured every request needs HTTP Basic auth (any user name, the password).\n\n"
        "📖 Overview: [/docs](/docs) · 🧪 Swagger UI: [/swagger](/swagger)"
    ),
    version=__version__,
    docs_url="/swagger",                # /docs is the readable overview page below
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=[
        {"name": "meta", "description": "Version, configuration, health"},
        {"name": "messages", "description": "Chatbox messages (send, live typing, edit, history)"},
        {"name": "typing", "description": "The typing indicator"},
        {"name": "mode", "description": "Outputs: the game chatbox and the Klaude display"},
        {"name": "settings", "description": "OSC target, server address, password, LAN address"},
        {"name": "kd", "description": "The Klaude display (only with the Klaude avatar)"},
    ],
)

if ALLOWED_ORIGINS:                      # other web front ends that may call the API (cross-origin)
    app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["*"], allow_headers=["*"],
                       allow_credentials=True)


@app.middleware("http")
async def _same_origin_only(request: Request, call_next):
    """Refuse state-changing requests from other web sites (a page you visit must not be able to post to the
    console on your machine). Same origin, origins in ALLOWED_ORIGINS and non-browser clients (no Origin) pass."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin is not None:
            netloc = urlparse(origin).netloc
            hosts = {request.headers.get("host", ""), request.headers.get("x-forwarded-host", "")}
            if origin == "null" or (netloc not in hosts and origin.rstrip("/") not in ALLOWED_ORIGINS):
                log.warning("refused a cross-origin %s %s from %s", request.method, request.url.path, origin)
                return JSONResponse({"detail": "Cross-origin request refused (see ALLOWED_ORIGINS)."}, status_code=403)
    return await call_next(request)


@app.exception_handler(Exception)
async def _unexpected(request: Request, exc: Exception):
    """no stack traces for users: log it, answer with a short message"""
    log.exception("unexpected error in %s %s", request.method, request.url.path)
    return JSONResponse({"detail": f"Internal error: {type(exc).__name__}. See the server log."}, status_code=500)


# ==================== state ====================

_client: Optional[SimpleUDPClient] = None
_osc = {"host": None, "port": None, "ip": None, "error": None}     # the OSC target in use
_osc_lock = threading.Lock()
_typing_state: bool = False
_outputs: dict = {"chatbox": True, "kd": False}   # both outputs can be on at the same time
_kd = None                      # kd_chat.KdChat, created at startup
KD_REV = 2                      # saved kd settings revision (2: show_time covers every screen)
_state_lock = threading.Lock()


def _load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            st = json.load(f)
        return st if isinstance(st, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("state file %s is unreadable (%s); starting with the defaults", STATE_FILE, e)
        return {}


def _save_state() -> None:
    with _state_lock:
        data = {"outputs": _outputs, "kd": _kd.s if _kd else _load_state().get("kd", {}), "translate": _tr_settings,
                "kd_rev": KD_REV}
        tmp = STATE_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, STATE_FILE)
        except OSError as e:
            log.warning("could not save %s: %s", STATE_FILE, e)


# ==================== the OSC target ====================


def _resolve_ipv4(host: str, port: int) -> str:
    return socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_DGRAM)[0][4][0]


def _apply_osc_target(host: str, port: int) -> None:
    """(re)point the chatbox client and the Klaude display at host:port. Raises OSError if host does not resolve."""
    ip = _resolve_ipv4(host, port)
    global _client
    with _osc_lock:
        _client = SimpleUDPClient(ip, port)
        _osc.update(host=host, port=port, ip=ip, error=None)
        if _kd is not None and getattr(_kd.d, "sender", None) is not None:
            _kd.d.sender.addr = (ip, port)          # kd_display's Sender: the next frame goes to the new target
            _kd.d.target = (ip, port)
    log.info("OSC target -> udp://%s:%d%s", host, port, f" ({ip})" if ip != host else "")


def _osc_target_init() -> None:
    host, port = SETTINGS.value("osc_host"), SETTINGS.value("osc_port")
    try:
        _apply_osc_target(host, port)
    except OSError as e:
        global _client
        with _osc_lock:
            _client = None
            _osc.update(host=host, port=port, ip=None, error=str(e))
        log.error("OSC target %s:%d does not resolve (%s): messages cannot be sent until it is fixed in Settings",
                  host, port, e)


def _osc_send(address: str, args: list) -> None:
    with _osc_lock:
        client, host, port, err = _client, _osc["host"], _osc["port"], _osc["error"]
    if client is None:
        raise HTTPException(status_code=502, detail=f"VRChat host {host} cannot be resolved ({err}). Fix the OSC "
                                                    f"target in Settings.")
    try:
        client.send_message(address, args)
    except OSError as e:
        log.warning("OSC send to %s:%s failed: %s", host, port, e)
        raise HTTPException(status_code=502, detail=f"Could not send to VRChat at {host}:{port}: {e.strerror or e}")


# ==================== outputs ====================
# Both outputs use the same VRChat OSC target. Messages and typing go to every output that is on.


def _chatbox_send(text: str, immediate: bool, sfx: bool) -> None:
    _osc_send("/chatbox/input", [text, bool(immediate), bool(sfx)])


_cb_typing = False             # what the game's typing indicator was last set to


def _chatbox_typing(on: bool) -> None:
    global _cb_typing
    _cb_typing = bool(on)
    _osc_send("/chatbox/typing", [bool(on)])


def _chatbox_live(text: str) -> None:
    """a live (not final) update: the game clears its typing indicator on every new message, so light it again"""
    _chatbox_send(text, True, False)
    if _cb_typing:
        _chatbox_typing(True)


def _set_outputs(chatbox: Optional[bool] = None, kd: Optional[bool] = None) -> None:
    """Turn outputs on / off. The display appears when kd is switched on (and starts sending), leaves when it is
    switched off and stops sending afterwards."""
    if kd and _kd is None:
        raise HTTPException(status_code=503, detail=f"The Klaude display output is not available: {_KD_IMPORT_ERROR}")
    if chatbox is not None and bool(chatbox) != _outputs["chatbox"]:
        _outputs["chatbox"] = bool(chatbox)
        if _typing_state:
            try:
                _chatbox_typing(_outputs["chatbox"])      # the typing indicator follows the output
            except HTTPException:
                pass
    if kd is not None and bool(kd) != _outputs["kd"]:
        _outputs["kd"] = bool(kd)
        if _kd is not None:
            _kd.set_active(_outputs["kd"])
            _kd.set_typing(_typing_state and _outputs["kd"])
    _save_state()


def _outputs_label() -> str:
    return "+".join(k for k in ("chatbox", "kd") if _outputs[k]) or "none"


_history: deque = deque(maxlen=HISTORY_MAX)
_history_lock = threading.Lock()
_next_id = 0
_id_lock = threading.Lock()


def _listen() -> tuple[str, int]:
    """the address the server listens on (what main() bound, else the configured one)"""
    return (RUNTIME["listen_host"] or SETTINGS.value("listen_host"), RUNTIME["listen_port"] or SETTINGS.value("listen_port"))


def _startup() -> None:
    global _kd
    _server_at_start.update(listen_host=SETTINGS.value("listen_host"), listen_port=SETTINGS.value("listen_port"))
    if SETTINGS.warning:
        log.warning(SETTINGS.warning)
    st = _load_state()
    host, port = SETTINGS.value("osc_host"), SETTINGS.value("osc_port")
    if kd_chat is not None:
        try:
            try:
                ip = _resolve_ipv4(host, port)
            except OSError:
                ip = "127.0.0.1"                          # fixed later in Settings (_apply_osc_target)
            kd_st = dict(st.get("kd") or {})
            if st.get("kd") and st.get("kd_rev", 1) < 2:
                kd_st["show_time"] = True                  # 1.8.1: one setting for every screen (the side screens
                                                           # always showed the time before): on, as they looked
            _kd = kd_chat.KdChat(ip, port, dry=KD_DRY, settings=kd_st)
        except Exception as e:     # noqa: BLE001
            log.error("Klaude display output failed to start: %r", e)
    else:
        log.warning("Klaude display output not available: %s", _KD_IMPORT_ERROR)
    _osc_target_init()
    if isinstance(st.get("outputs"), dict):
        _outputs.update({k: bool(v) for k, v in st["outputs"].items() if k in _outputs})
    elif st.get("mode") == "kd":                       # the old single-choice mode: kd on, chatbox on too
        _outputs.update(chatbox=True, kd=True)
    if _kd is None:
        _outputs["kd"] = False
    if _kd is not None:
        _kd.set_active(_outputs["kd"])
    try:
        _tr_settings.update(_tr_clean(st.get("translate") or {}, _TR_DEFAULTS))
    except (ValueError, TypeError) as e:
        log.warning("translation settings ignored: %s", e)
    _tr_apply()
    lh, lp = _listen()
    urls = netinfo.urls(lh, lp)
    log.info("kdchat %s | OSC -> udp://%s:%s (%s) | outputs: %s%s | login: %s", __version__, host, port,
             SETTINGS.get("osc_host")[1], _outputs_label(), " (kd dry run)" if KD_DRY else "",
             f"password ({SETTINGS.auth_source()})" if SETTINGS.auth_enabled() else "none")
    log.info("console: http://127.0.0.1:%d/%s", lp, "".join(f"  ·  {u}" for u in urls))
    if not SETTINGS.auth_enabled() and lh in ("0.0.0.0", "", "::"):
        log.info("no password set: everyone on your network can use the console (set one in Settings)")


# ==================== login (only when a password is configured) ====================

security = HTTPBasic(auto_error=False, realm=WWW_AUTH_REALM)


def _session_ok(request: Request) -> bool:
    tok = request.cookies.get(SESSION_COOKIE)
    return bool(SESSION_TOKEN and tok and hmac.compare_digest(tok, SESSION_TOKEN))


def require_auth(request: Request, creds: Optional[HTTPBasicCredentials] = Depends(security)) -> str:
    """No password configured: everyone may. Otherwise HTTP Basic (any user name + the password), or the desktop
    app's own window (session cookie)."""
    if not SETTINGS.auth_enabled():
        return "-"
    if _session_ok(request):
        return "app"
    if creds is not None and SETTINGS.check_password(creds.password or ""):
        return creds.username or "-"
    if creds is not None:
        log.warning("login failed (wrong password) from %s", request.client.host if request.client else "?")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Password required (HTTP Basic: any user name, the password)." if creds is None else "Wrong password.",
        headers={"WWW-Authenticate": f'Basic realm="{WWW_AUTH_REALM}"'},
    )


AuthDep = Depends(require_auth)


# ==================== models ====================


class MessageCreate(BaseModel):
    """A new chatbox message."""
    text: str = Field(..., description="The text (game chatbox: at most 144 characters and 9 lines)")
    immediate: bool = Field(True, description="True = send it; False = only put it into the game's keyboard")
    sfx: bool = Field(True, description="Play the notification sound (only with immediate=True)")
    live: bool = Field(False, description="(old) a live-typing update: same as final=false")
    final: bool = Field(True, description="False = still being typed (shown live; later PATCH to update / finish "
                                          "it, DELETE to drop it)")
    targets: Optional[list[str]] = Field(
        None,
        description='Which outputs this message goes to ("chatbox", "kd"), among the ones that are on; '
                    'empty = all that are on. E.g. only ["chatbox"] while the display shows a picture.',
    )


class MessageItem(BaseModel):
    """A sent message."""
    id: int = Field(..., description="Message id")
    text: str
    immediate: bool
    sfx: bool
    output: str = Field("chatbox", description="Where it went: chatbox / kd / chatbox+kd")
    created_at: str = Field(..., description="ISO 8601 UTC time")
    length: int
    edited: bool = Field(False, description="Changed after it was sent (the display shows 'edited')")
    reverted: bool = Field(False, description="Reverted (the display shows 'message reverted')")
    kd_id: Optional[int] = Field(None, description="Its number on the Klaude display (display messages only)")
    final: bool = Field(True, description="False = still being typed")
    targets: list[str] = Field(default_factory=list, description="The outputs it went to")
    source_lang: Optional[str] = Field(None, description="Its language (translation on)")
    translations: dict[str, str] = Field(default_factory=dict, description="Language code -> translated text")


class MessageEdit(BaseModel):
    """Change a message: update / finish one still being typed, or edit a sent one (shown as edited)."""
    text: str = Field(..., description="The new text")
    final: bool = Field(True, description="False = the edit is still going on (shown live), True = done")
    cancel: bool = Field(False, description="Give the edit up: back to this text, not marked as edited")


class MessageList(BaseModel):
    """A page of the message history."""
    items: list[MessageItem]
    total: int = Field(..., description="Messages in the history")
    limit: int
    offset: int


class ModeState(BaseModel):
    """(old) output mode."""
    mode: str = Field(..., description="chatbox = the game chatbox; kd = the Klaude display")
    max_chars: int = Field(0, description="Longest message in this mode (read only)")
    max_lines: int = Field(0, description="Most lines (read only)")


class TypingState(BaseModel):
    """The typing indicator."""
    typing: bool = Field(..., description="Show the 'typing…' indicator")
    targets: Optional[list[str]] = Field(None, description="Which outputs show it (empty = all that are on)")


class HealthResponse(BaseModel):
    """Health check."""
    ok: bool
    version: str = __version__
    vrc_host: str
    vrc_port: int
    max_chars: int
    max_lines: int
    auth_enabled: bool
    error: Optional[str] = None


class ConfigResponse(BaseModel):
    """Runtime configuration."""
    version: str = __version__
    vrc_host: str
    vrc_port: int
    listen_host: str
    listen_port: int
    max_chars: int
    max_lines: int
    history_max: int
    auth_enabled: bool
    auth_realm: str


class InfoResponse(BaseModel):
    """About this service."""
    name: str
    version: str
    description: str
    vrc_target: str
    auth: dict


class OscTarget(BaseModel):
    """Where OSC messages go (VRChat's OSC input)."""
    host: str = Field(..., description="IPv4 address or host name of the PC that runs VRChat", examples=["127.0.0.1"])
    port: int = Field(9000, description="VRChat's OSC input port (UDP), 1-65535", examples=[9000])


class ServerAddress(BaseModel):
    """Where the web server listens (takes effect after a restart)."""
    listen_host: Optional[str] = Field(None, description="Bind address: 0.0.0.0 = all networks, 127.0.0.1 = this PC only")
    listen_port: Optional[int] = Field(None, description="HTTP port, 1-65535")


class PasswordChange(BaseModel):
    """Set, change or remove the password."""
    current_password: Optional[str] = Field(None, description="Required when a password is set")
    new_password: Optional[str] = Field(None, description="The new password; empty / null = no password")


# ==================== helpers ====================


def _limits(use: Optional[dict] = None) -> tuple[int, int]:
    """length limits (characters, lines): the game chatbox's when it gets the message, longer for the display only"""
    return (MAX_CHARS, MAX_LINES) if (use or _outputs)["chatbox"] else (KD_MAX_CHARS, KD_MAX_LINES)


def _use(targets: Optional[list[str]]) -> dict:
    """the outputs (among the ones that are on) this request goes to"""
    if targets is None:
        return dict(_outputs)
    bad = [t for t in targets if t not in _outputs]
    if bad:
        raise HTTPException(status_code=400, detail=f"targets can only be chatbox / kd: {bad}")
    return {k: _outputs[k] and k in targets for k in _outputs}


def _validate_text(text: str, use: Optional[dict] = None) -> str:
    max_chars, max_lines = _limits(use)
    if len(text) > max_chars:
        raise HTTPException(status_code=400, detail=f"Text too long: {len(text)} > {max_chars} characters")
    if text == "":
        raise HTTPException(status_code=400, detail="Text must not be empty")
    nlines = text.count("\n") + 1
    if nlines > max_lines:
        raise HTTPException(status_code=400, detail=f"Too many lines: {nlines} > {max_lines}")
    return text


def _dns_resolves(host: str) -> tuple[bool, Optional[str]]:
    """does host resolve (UDP has no handshake: this is all that can be checked)"""
    try:
        socket.getaddrinfo(host, None)
        return True, None
    except Exception as e:     # noqa: BLE001
        return False, str(e)


def _next_message_id() -> int:
    global _next_id
    with _id_lock:
        _next_id += 1
        return _next_id


# ==================== REST API ====================

api = APIRouter(prefix="/api/v1", dependencies=[AuthDep])


@api.get("/info", response_model=InfoResponse, tags=["meta"], summary="About this service")
def get_info() -> InfoResponse:
    return InfoResponse(
        name="kdchat",
        version=__version__,
        description="Sends HTTP requests to the VRChat chatbox as OSC messages.",
        vrc_target=f"{_osc['host']}:{_osc['port']}",
        auth={"type": "basic" if SETTINGS.auth_enabled() else "none", "enabled": SETTINGS.auth_enabled(),
              "realm": WWW_AUTH_REALM, "hint": 'curl -u ":$PASSWORD" …  (any user name)'},
    )


@api.get("/config", response_model=ConfigResponse, tags=["meta"], summary="Runtime configuration")
def get_config() -> ConfigResponse:
    lh, lp = _listen()
    return ConfigResponse(vrc_host=_osc["host"], vrc_port=_osc["port"], listen_host=lh, listen_port=lp,
                          max_chars=MAX_CHARS, max_lines=MAX_LINES, history_max=HISTORY_MAX,
                          auth_enabled=SETTINGS.auth_enabled(), auth_realm=WWW_AUTH_REALM)


@api.get("/health", response_model=HealthResponse, tags=["meta"], summary="Health check")
def get_health() -> HealthResponse:
    """`ok` = the OSC target host resolves. UDP has no handshake, so whether VRChat listens cannot be checked."""
    ok, err = _dns_resolves(_osc["host"])
    return HealthResponse(ok=ok, vrc_host=_osc["host"], vrc_port=_osc["port"], max_chars=MAX_CHARS,
                          max_lines=MAX_LINES, auth_enabled=SETTINGS.auth_enabled(), error=err)


# ---------------------------------------------------------------- translation (local, translate.py)

_TR_DEFAULTS = {"enabled": False, "source": "auto", "latin": "en", "targets": [], "chatbox": 1, "kd": True,
                "small": ["en"]}   # small: languages in the display's small font (Latin-script ones: tr.LATIN)
_tr_settings: dict = dict(_TR_DEFAULTS)
_tr_models = tr.Models(cfg.data_dir())
_tr_engine = tr.Engine(_tr_models)
_tr_downloads: dict = {}          # lang -> thread


def _tr_clean(body: dict, old: dict) -> dict:
    s = dict(old)
    for k, v in (body or {}).items():
        if k not in _TR_DEFAULTS:
            continue
        if k in ("enabled", "kd"):
            v = bool(v)
        elif k == "chatbox":
            v = int(v)
            if not 0 <= v <= 2:
                raise ValueError("chatbox: how many translations the game chatbox gets, 0..2")
        elif k == "source":
            if v != "auto" and v not in tr.LANGUAGES:
                raise ValueError(f"source: auto or a language code, not {v!r}")
        elif k == "latin":
            if v not in tr.LANGUAGES:
                raise ValueError(f"latin: a language code, not {v!r}")
        elif k == "targets":
            v = [x for i, x in enumerate(v or []) if x not in (v or [])[:i]]
            if len(v) > 2 or any(x not in tr.LANGUAGES for x in v):
                raise ValueError("targets: at most 2 language codes")
        elif k == "small":
            v = sorted(set(v or []))
            if any(x not in tr.LATIN for x in v):
                raise ValueError("small: Latin-script language codes (the small font has no other letters)")
        s[k] = v
    return s


def _tr_tag(code: str) -> str:
    return {"zh": "ZH", "zh_hant": "ZH-T"}.get(code, code.upper())


def _tr_wings_on() -> bool:
    st = _tr_settings
    return bool(st["enabled"] and st["kd"] and st["targets"])


def _tr_sides() -> dict:
    """side screen -> language: one target on the right, two on the left and the right"""
    ts = list(_tr_settings["targets"]) if _tr_wings_on() else []
    return {} if not ts else {"right": ts[0]} if len(ts) == 1 else {"left": ts[0], "right": ts[1]}


def _tr_label(code: str) -> str:
    """the side screen's header (3x5 ASCII font): "JA  JAPANESE" """
    import unicodedata
    name = unicodedata.normalize("NFKD", tr.LANGUAGES[code][0]).encode("ascii", "ignore").decode().upper()
    return f"{_tr_tag(code)}  {name}"


def _tr_apply() -> None:
    """the side screens follow the setting (languages, headers, text regions); models load in the background (the
    first message is quick)"""
    if _kd is not None:
        sides = _tr_sides()
        l, r = sides.get("left"), sides.get("right")
        _kd.set_small_langs(_tr_settings["small"])
        _kd.set_wing_text_on(_tr_wings_on())
        _kd.set_wing_langs(l, r, (_tr_label(l) if l else None, _tr_label(r) if r else None))
    st = _tr_settings
    if st["enabled"] and st["targets"]:
        src = st["source"] if st["source"] != "auto" else st["latin"]
        def warm():
            for t in st["targets"]:
                try:
                    if t != src and _tr_engine.ready(src, t):
                        _tr_engine.translate("ok", src, t)
                except Exception as e:     # noqa: BLE001
                    log.info("translation warm-up (%s -> %s): %s", src, t, e)
        threading.Thread(target=warm, name="tr-warm", daemon=True).start()


def _translate(text: str) -> tuple[Optional[str], dict]:
    """-> (its language, {target: translation}) with the translation on; models not downloaded are left out"""
    st = _tr_settings
    if not (st["enabled"] and st["targets"]) or not text.strip():
        return None, {}
    src = tr.detect(text, st["source"], st["latin"])
    out = {}
    for t in st["targets"]:
        if t == src:
            continue
        try:
            out[t] = _tr_engine.translate(text, src, t)
        except LookupError as e:
            log.info("translation skipped: %s", e)
        except Exception as e:     # noqa: BLE001
            log.warning("translation failed (%s -> %s): %r", src, t, e)
    return src, out


def _chatbox_compose(text: str, trs: dict) -> str:
    """the original + up to `chatbox` translations, as many as fit the game chatbox (144 characters, 9 lines); a
    translation that does not fit whole is shortened (…) when at least a few characters of it fit"""
    n = _tr_settings["chatbox"]
    out = text
    for t in [x for x in _tr_settings["targets"] if x in trs][:n]:
        cand = out + "\n" + trs[t]
        if len(cand) <= MAX_CHARS and cand.count("\n") + 1 <= MAX_LINES:
            out = cand
            continue
        room = MAX_CHARS - len(out) - 2
        if room >= 12 and out.count("\n") + 2 <= MAX_LINES:
            out = out + "\n" + trs[t].replace("\n", " ")[:room].rstrip() + "…"
        break
    return out


def _kd_trs(trs: dict) -> dict:
    """translations for the display: a script it cannot draw (tr.NO_DISPLAY) becomes a note"""
    return {k: (f"({tr.LANGUAGES[k][0]}: in the game chatbox only)" if k in tr.NO_DISPLAY else v) for k, v in trs.items()}


def _kd_wings(trs: dict, kd_id: Optional[int] = None, src: Optional[str] = None) -> None:
    """a message's translations on the side screens: the chat layout shows them in the translated logs (in step with
    the main one), the single layout the newest one"""
    if _kd is None or not _tr_wings_on():
        return
    trs = _kd_trs(trs)
    if kd_id is not None:
        _kd.set_translations(kd_id, trs, src)
    sides = _tr_sides()                                   # (a side screen without a language: nothing, it folds)
    _kd.set_wing_text({side: ((trs[sides[side]], _tr_tag(sides[side])) if sides.get(side) in trs else None)
                       for side in ("left", "right")})


class _ChatboxThrottle:
    """VRChat rate-limits the chatbox: live updates at most every 1.5 s (always the newest text), final ones at once"""
    GAP = 1.5

    def __init__(self):
        self.lock = threading.Lock()
        self.last = 0.0
        self.pending = None
        self.timer = None

    def send(self, text: str, final: bool, sfx: bool) -> None:
        with self.lock:
            now = time.monotonic()
            if self.timer is not None:
                self.timer.cancel(); self.timer = None
            if final or now - self.last >= self.GAP:
                self.last = now
                self.pending = None
                if final:
                    _chatbox_send(text, True, sfx)
                else:
                    _chatbox_live(text)
                return
            self.pending = text
            self.timer = threading.Timer(self.GAP - (now - self.last), self._flush)
            self.timer.daemon = True
            self.timer.start()

    def drop(self) -> None:
        """forget a live update still waiting for its turn"""
        with self.lock:
            if self.timer is not None:
                self.timer.cancel(); self.timer = None
            self.pending = None

    def _flush(self) -> None:
        with self.lock:
            if self.pending is not None:
                try:
                    _chatbox_live(self.pending)
                except HTTPException as e:              # (a timer thread: nobody to answer)
                    log.warning("live update not sent: %s", e.detail)
                self.last = time.monotonic()
                self.pending = None
            self.timer = None


_cb = _ChatboxThrottle()


@api.post("/messages", response_model=MessageItem, status_code=status.HTTP_201_CREATED, tags=["messages"],
          summary="Send a message (or start typing one live)")
def create_message(req: MessageCreate, user: str = AuthDep) -> MessageItem:
    """Goes to the outputs that are on (or the ones in `targets`). `final=false`: still being typed, shown live
    (the display in place, the game chatbox throttled); then `PATCH /messages/{id}` to update / finish it,
    `DELETE /messages/{id}` to drop it. `immediate=false`: only put it into the game's keyboard."""
    global _typing_timer
    final = bool(req.final) and not req.live
    use = _use(req.targets)
    text = _validate_text(req.text, use)
    if not (use["chatbox"] or use["kd"]):
        raise HTTPException(status_code=409, detail="No output to send to: turn on the game chatbox or the Klaude display")
    if not req.immediate:                                      # only into the game's keyboard (not sent)
        if use["chatbox"]:
            # (nothing may follow it into the chatbox: a waiting live update or the typing indicator would make the
            # game replace / empty the keyboard)
            _cb.drop()
            if _typing_timer is not None:
                _typing_timer.cancel(); _typing_timer = None
            if _typing_state or _cb_typing:
                _typing_apply(False)
            wait = _cb.GAP - (time.monotonic() - _cb.last)     # (the chatbox was just written / cleared: the game's
            if wait > 0:                                       # rate limit would drop the fill)
                time.sleep(wait)
            _chatbox_send(text, False, False)
        return MessageItem(id=0, text=text, immediate=False, sfx=False, output="chatbox",
                           created_at=datetime.now(timezone.utc).isoformat(), length=len(text), targets=["chatbox"])
    src, trs = _translate(text) if final else (None, {})
    if use["chatbox"]:
        _cb.send(_chatbox_compose(text, trs) if final else text, final, bool(req.sfx))   # (first: an OSC error must not leave a kd message)
    kd_id = _kd.new_message(text, final, bool(req.sfx)) if use["kd"] and _kd is not None else None
    if final and use["kd"]:
        _kd_wings(trs, kd_id, src)
    targets = [k for k in ("chatbox", "kd") if use[k]]
    msg = MessageItem(output="+".join(targets), id=_next_message_id(), text=text, immediate=True, sfx=bool(req.sfx),
                      created_at=datetime.now(timezone.utc).isoformat(), length=len(text), kd_id=kd_id,
                      final=final, targets=targets, source_lang=src, translations=trs)
    with _history_lock:
        _history.append(msg)
    log.info("send: id=%d len=%d final=%s to=%s user=%s", msg.id, msg.length, final, msg.output, user)
    return msg


def _find(message_id: int) -> MessageItem:
    with _history_lock:
        for msg in reversed(_history):
            if msg.id == message_id:
                return msg
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Message {message_id} not found")


@api.patch("/messages/{message_id}", response_model=MessageItem, tags=["messages"],
           summary="Update / finish / edit a message")
def edit_message(message_id: int, body: MessageEdit, user: str = AuthDep) -> MessageItem:
    """A message still being typed: new text, `final=true` finishes it. A sent message: an edit (the display
    changes it in place and shows 'edited'; `final=false` while editing live, `final=true` at the end;
    `cancel=true` restores the text). The game chatbox only shows its newest message: it is resent only when that
    one is edited."""
    msg = _find(message_id)
    if msg.reverted:
        raise HTTPException(status_code=409, detail="This message was reverted")
    use = {"chatbox": "chatbox" in msg.targets and _outputs["chatbox"], "kd": msg.kd_id is not None and _outputs["kd"]}
    text = _validate_text(body.text, use)
    with _history_lock:
        latest_cb = next((m for m in reversed(_history) if "chatbox" in m.targets), None)
    done = body.final or body.cancel
    if not msg.final:
        # a new message still being typed: update it, final = sent (the chime, if asked for, plays now)
        src, trs = _translate(text) if done and not body.cancel else (None, {})
        if use["kd"] and _kd is not None:
            _kd.update_message(msg.kd_id, text, final=True if done else None, sfx=done and msg.sfx)
            if done:
                _kd_wings(trs, msg.kd_id, src)
        if use["chatbox"] and latest_cb is msg:
            _cb.send(_chatbox_compose(text, trs) if done else text, done, done and msg.sfx)
        msg.text, msg.length = text, len(text)
        msg.final = done
        if done:
            msg.source_lang, msg.translations = src, trs
        return msg
    # editing a sent message (live while typing, then final; cancel = back to the text the client had)
    was = _edit_sessions.setdefault(msg.id, msg.edited)
    edited = was if body.cancel else True
    if done:
        _edit_sessions.pop(msg.id, None)
    src, trs = _translate(text) if done else (None, {})
    if use["kd"] and _kd is not None:
        _kd.update_message(msg.kd_id, text, edited=edited)
        with _history_lock:
            newest_kd = next((m for m in reversed(_history) if m.kd_id is not None and m.final), None)
        if done:
            if newest_kd is msg:
                _kd_wings(trs, msg.kd_id, src)
            elif _tr_wings_on():
                _kd.set_translations(msg.kd_id, _kd_trs(trs), src)  # an older message: its rows in the translated logs
    if use["chatbox"] and latest_cb is msg:
        _cb.send(_chatbox_compose(text, trs) if done else text, done, False)   # the game only shows its newest message
    msg.text, msg.length, msg.edited = text, len(text), edited
    if done:
        msg.source_lang, msg.translations = src, trs
    if done:
        log.info("edit: id=%d cancel=%s user=%s", msg.id, body.cancel, user)
    return msg


_edit_sessions: dict = {}         # message id -> its "edited" state before the edit in progress


@api.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["messages"],
            summary="Drop a message that is still being typed", response_class=Response)
def drop_message(message_id: int, user: str = AuthDep) -> Response:
    """Only for messages not finished yet (input emptied / Esc): removed from the display, the game chatbox is
    cleared."""
    msg = _find(message_id)
    if msg.final:
        raise HTTPException(status_code=409, detail="This message was already sent: revert it instead")
    if msg.kd_id is not None and _kd is not None:
        _kd.remove_message(msg.kd_id)
    with _history_lock:
        try:
            _history.remove(msg)
        except ValueError:
            pass
    if "chatbox" in msg.targets and _outputs["chatbox"]:
        _cb.send("", True, False)
    return Response(status_code=204)


@api.post("/messages/{message_id}/revert", response_model=MessageItem, tags=["messages"], summary="Revert a message")
def revert_message(message_id: int, user: str = AuthDep) -> MessageItem:
    """The Klaude display shows 'message reverted' instead. VRChat cannot revert game chatbox messages."""
    msg = _find(message_id)
    if msg.kd_id is None or _kd is None or not _kd.revert_message(msg.kd_id):
        raise HTTPException(status_code=409, detail="Only messages on the Klaude display (still in its log) can be reverted")
    msg.reverted = True
    msg.final = True
    log.info("revert: id=%d user=%s", msg.id, user)
    return msg


@api.get("/messages", response_model=MessageList, tags=["messages"], summary="Message history (newest first)")
def list_messages(
    limit: int = Query(20, ge=1, le=HISTORY_MAX, description="How many (1-50)"),
    offset: int = Query(0, ge=0, description="How many to skip"),
) -> MessageList:
    with _history_lock:
        snapshot = list(_history)
    snapshot.reverse()
    return MessageList(items=snapshot[offset:offset + limit], total=len(snapshot), limit=limit, offset=offset)


@api.get("/messages/{message_id}", response_model=MessageItem, tags=["messages"], summary="One message")
def get_message(message_id: int) -> MessageItem:
    return _find(message_id)


@api.delete("/messages", status_code=status.HTTP_204_NO_CONTENT, tags=["messages"], summary="Clear the history",
            response_class=Response)
def clear_messages() -> Response:
    """Clears the server's history (nothing changes in VRChat)."""
    with _history_lock:
        n = len(_history)
        _history.clear()
    log.info("message history cleared (%d items)", n)
    return Response(status_code=204)


TYPING_TTL = 15.0               # s: the indicator goes off unless renewed (a closed page / lost connection never sticks)
_typing_timer: Optional[threading.Timer] = None


def _typing_apply(on: bool, targets: Optional[list[str]] = None) -> None:
    global _typing_state
    _typing_state = bool(on)
    use = _use(targets)
    if _kd is not None and _outputs["kd"]:
        _kd.set_typing(_typing_state and use["kd"])            # (off where this text does not go)
    cb = _typing_state and use["chatbox"]
    if _outputs["chatbox"] and (cb or _cb_typing):             # (off only when it is on: nothing after a keyboard fill)
        _chatbox_typing(cb)


@api.put("/typing", response_model=TypingState, tags=["typing"], summary="Set the typing indicator")
def set_typing(state: TypingState, user: str = AuthDep) -> TypingState:
    """OSC: `/chatbox/typing <bool>` (and the display's 'typing..'). On lasts TYPING_TTL (15) s: send it again to
    keep it on (the console does every 5 s while you type)."""
    global _typing_timer
    _use(state.targets)                                        # (400 on bad targets before anything changes)
    _typing_apply(state.typing, state.targets)
    if _typing_timer is not None:
        _typing_timer.cancel()
        _typing_timer = None
    if state.typing:
        _typing_timer = threading.Timer(TYPING_TTL, lambda: _typing_apply(False))
        _typing_timer.daemon = True
        _typing_timer.start()
    log.debug("typing: %s user=%s", _typing_state, user)
    return TypingState(typing=_typing_state)


@api.get("/typing", response_model=TypingState, tags=["typing"], summary="The typing indicator")
def get_typing() -> TypingState:
    return TypingState(typing=_typing_state)


class OutputsState(BaseModel):
    """Outputs on / off (both can be on)."""
    chatbox: Optional[bool] = Field(None, description="The game's chatbox")
    kd: Optional[bool] = Field(None, description="The Klaude display (needs the Klaude avatar, PC)")


def _outputs_body() -> dict:
    mc, ml = _limits()
    return {"chatbox": _outputs["chatbox"], "kd": _outputs["kd"], "kd_available": _kd is not None,
            "max_chars": mc, "max_lines": ml}


@api.get("/outputs", tags=["mode"], summary="Outputs on / off")
def get_outputs() -> dict:
    """Whether chatbox / kd are on, and the current length limits."""
    return _outputs_body()


@api.put("/outputs", tags=["mode"], summary="Turn outputs on / off (partial update)")
def put_outputs(state: OutputsState, user: str = AuthDep) -> dict:
    """E.g. `{"kd": false}` turns the display off (it leaves); the game chatbox is not affected. Saved."""
    _set_outputs(state.chatbox, state.kd)
    log.info("outputs: %s user=%s", _outputs_label(), user)
    return _outputs_body()


@api.get("/mode", response_model=ModeState, tags=["mode"], summary="(old) The output mode")
def get_mode() -> ModeState:
    """Kept for old clients: kd when the display is on, else chatbox. Use /outputs."""
    return ModeState(mode="kd" if _outputs["kd"] else "chatbox", max_chars=_limits()[0], max_lines=_limits()[1])


@api.put("/mode", response_model=ModeState, tags=["mode"], summary="(old) Use one output only")
def put_mode(state: ModeState, user: str = AuthDep) -> ModeState:
    """Kept for old clients: chatbox = the game chatbox only; kd = the display only. Use /outputs."""
    if state.mode not in MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {MODES}")
    _set_outputs(chatbox=state.mode == "chatbox", kd=state.mode == "kd")
    log.info("outputs: %s user=%s", _outputs_label(), user)
    return get_mode()


# ---------------------------------------------------------------- settings: OSC target, server, password, LAN


def _osc_body() -> dict:
    (h, hs), (p, ps) = SETTINGS.get("osc_host"), SETTINGS.get("osc_port")
    (dh, dhs), (dp, dps) = SETTINGS.env_or_default("osc_host"), SETTINGS.env_or_default("osc_port")
    return {"host": _osc["host"], "port": _osc["port"], "ip": _osc["ip"], "error": _osc["error"],
            "source": "settings" if "settings" in (hs, ps) else hs if hs == ps else "env",
            "default": {"host": dh, "port": dp, "source": "env" if "env" in (dhs, dps) else "default"}}


@api.get("/osc", tags=["settings"], summary="The OSC target (where VRChat listens)")
def get_osc() -> dict:
    """`source`: settings (changed in the console) / env (VRC_HOST, VRC_PORT) / default (127.0.0.1:9000).
    `default` = the target after a reset."""
    return _osc_body()


@api.put("/osc", tags=["settings"], summary="Change the OSC target (applies at once, saved)")
def put_osc(body: OscTarget, user: str = AuthDep) -> dict:
    host = body.host.strip()
    if not cfg.valid_host(host):
        raise HTTPException(status_code=400, detail="Host must be an IPv4 address or a host name")
    if not cfg.valid_port(body.port):
        raise HTTPException(status_code=400, detail="Port must be 1-65535")
    try:
        _apply_osc_target(host, body.port)
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"Cannot resolve {host}: {e.strerror or e}")
    SETTINGS.set(osc_host=host, osc_port=body.port)
    log.info("OSC target changed to %s:%d user=%s", host, body.port, user)
    return _osc_body()


@api.delete("/osc", tags=["settings"], summary="Reset the OSC target (VRC_HOST/VRC_PORT, else 127.0.0.1:9000)")
def reset_osc(user: str = AuthDep) -> dict:
    SETTINGS.set(osc_host=None, osc_port=None)
    _osc_target_init()
    log.info("OSC target reset to %s:%s user=%s", _osc["host"], _osc["port"], user)
    return _osc_body()


def _server_body() -> dict:
    (h, hs), (p, ps) = SETTINGS.get("listen_host"), SETTINGS.get("listen_port")
    rh, rp = _listen()
    at_start = (_server_at_start.get("listen_host", h), _server_at_start.get("listen_port", p))
    return {"listen_host": h, "listen_port": p, "source": {"listen_host": hs, "listen_port": ps},
            "running": {"listen_host": rh, "listen_port": rp}, "restart_needed": (h, p) != at_start}


@api.get("/settings/server", tags=["settings"], summary="The web server's address")
def get_server() -> dict:
    return _server_body()


@api.put("/settings/server", tags=["settings"], summary="Change the web server's address (after a restart)")
def put_server(body: ServerAddress, user: str = AuthDep) -> dict:
    upd = {}
    if body.listen_host is not None:
        h = body.listen_host.strip()
        if not cfg.valid_host(h):
            raise HTTPException(status_code=400, detail="Bind address must be an IPv4 address or a host name")
        upd["listen_host"] = h
    if body.listen_port is not None:
        if not cfg.valid_port(body.listen_port):
            raise HTTPException(status_code=400, detail="Port must be 1-65535")
        upd["listen_port"] = body.listen_port
    if upd:
        SETTINGS.set(**upd)
        log.info("server address saved: %s (restart to apply) user=%s", upd, user)
    return _server_body()


@api.delete("/settings/server", tags=["settings"], summary="Reset the web server's address")
def reset_server(user: str = AuthDep) -> dict:
    SETTINGS.set(listen_host=None, listen_port=None)
    return _server_body()


@api.get("/settings/password", tags=["settings"], summary="Is a password set")
def get_password() -> dict:
    """`source`: settings (set in the console) / env (AUTH_PASSWORD) / null (no password)."""
    return {"enabled": SETTINGS.auth_enabled(), "source": SETTINGS.auth_source()}


@api.put("/settings/password", tags=["settings"], summary="Set, change or remove the password")
def put_password(body: PasswordChange, request: Request, user: str = AuthDep) -> dict:
    """Needs `current_password` when a password is set. `new_password` empty = no password (also turns off
    AUTH_PASSWORD). Stored as a salted PBKDF2 hash. Browsers then ask for the new password."""
    if SETTINGS.auth_enabled() and not SETTINGS.check_password(body.current_password or ""):
        raise HTTPException(status_code=403, detail="The current password is wrong")
    new = body.new_password or ""
    if new and not (cfg.MIN_PASSWORD <= len(new) <= cfg.MAX_PASSWORD):
        raise HTTPException(status_code=400, detail=f"The password must be {cfg.MIN_PASSWORD}-{cfg.MAX_PASSWORD} characters")
    SETTINGS.set_password(new or None)
    log.info("password %s by %s", "set" if new else "removed", request.client.host if request.client else "?")
    return get_password()


def _network_body(request: Request) -> dict:
    lh, lp = _listen()
    if RUNTIME["listen_port"] is None and request.url.port:       # (run by uvicorn directly: the port in use)
        lp = request.url.port
    urls = netinfo.urls(lh, lp)
    all_ifaces = lh in ("0.0.0.0", "", "::")
    return {"urls": urls, "listen_host": lh, "listen_port": lp, "all_interfaces": all_ifaces,
            "auth_enabled": SETTINGS.auth_enabled(), "open_on_lan": all_ifaces and not SETTINGS.auth_enabled(),
            "version": __version__}


@api.get("/network", tags=["settings"], summary="Where phones on the LAN can open the console")
def get_network(request: Request) -> dict:
    """`urls`: http://<LAN IPv4>:<port>/ for every LAN address (virtual / VPN adapters skipped).
    `open_on_lan`: no password and listening on all networks = everyone on the LAN can use the console."""
    return _network_body(request)


@api.get("/network/qr.svg", tags=["settings"], summary="QR code (SVG) of a URL", response_class=Response)
def get_qr(url: str = Query(..., max_length=300, description="The URL to encode (http/https)")) -> Response:
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Only http(s) URLs")
    import io
    import segno
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=6, border=2, dark="#101218", light="#ffffff",
                                     xmldecl=False, svgns=True)
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@api.get("/settings", tags=["settings"], summary="All settings at once")
def get_settings(request: Request) -> dict:
    return {"version": __version__, "osc": _osc_body(), "server": _server_body(), "password": get_password(),
            "network": _network_body(request), "warning": SETTINGS.warning}


# ---------------------------------------------------------------- translation


@api.get("/translate", tags=["translate"], summary="Translation settings and languages")
def get_translate() -> dict:
    """settings: enabled, source (auto or a language code: the language you type), latin (your language when you type
    latin script and source is auto), targets (up to 2: shown with the original), chatbox (how many translations the
    game chatbox gets, 0-2), kd (on the Klaude display's side screens). languages: every language with its download
    state (ready / downloading / error / absent), size and progress. Models are downloaded on request only."""
    return {"settings": _tr_settings, "languages": _tr_models.status(), "models": tr.MODELS_TAG,
            "small_ok": sorted(tr.LATIN),           # (the languages the small font can write)
            "no_display": sorted(tr.NO_DISPLAY)}    # (scripts the display cannot draw: chatbox only)


@api.put("/translate", tags=["translate"], summary="Change translation settings (partial update)")
def put_translate(body: dict, user: str = AuthDep) -> dict:
    global _tr_settings
    try:
        new = _tr_clean(body, _tr_settings)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    _tr_settings = new
    _tr_apply()
    _save_state()
    log.info("translate settings: %s user=%s", body, user)
    return {"settings": _tr_settings}


@api.post("/translate/models/{code}", status_code=status.HTTP_202_ACCEPTED, tags=["translate"],
          summary="Download a language (both directions to and from English)")
def download_language(code: str, user: str = AuthDep) -> dict:
    if code not in tr.LANGUAGES:
        raise HTTPException(status_code=404, detail=f"Unknown language {code}")
    if _tr_models.installed(code):
        return {"state": "ready"}
    th = _tr_downloads.get(code)
    if th is None or not th.is_alive():
        def run():
            try:
                _tr_models.download(code)
                _tr_apply()
            except Exception:     # noqa: BLE001  (reported through the languages' state)
                pass
        th = threading.Thread(target=run, name=f"tr-dl-{code}", daemon=True)
        _tr_downloads[code] = th
        th.start()
        log.info("translation model download: %s user=%s", code, user)
    return {"state": "downloading"}


@api.delete("/translate/models/{code}", status_code=status.HTTP_204_NO_CONTENT, tags=["translate"],
            summary="Delete a downloaded language", response_class=Response)
def delete_language(code: str, user: str = AuthDep) -> Response:
    if code not in tr.LANGUAGES:
        raise HTTPException(status_code=404, detail=f"Unknown language {code}")
    with _tr_engine.lock:
        for p in _tr_models.pairs(code):
            if p in _tr_engine.loaded and _tr_engine.ctx is not None:
                _tr_engine.ctx.call("kd_unload", p)
                _tr_engine.loaded.pop(p, None)
        _tr_models.delete(code)
    return Response(status_code=204)


class TranslateTry(BaseModel):
    text: str


@api.post("/translate/try", tags=["translate"], summary="Translate a text with the current settings (nothing is sent)")
def translate_try(body: TranslateTry, user: str = AuthDep) -> dict:
    src, trs = _translate(body.text)
    return {"source": src, "translations": trs, "chatbox": _chatbox_compose(body.text, trs)}


# ---------------------------------------------------------------- the Klaude display


def _need_kd():
    if _kd is None:
        raise HTTPException(status_code=503, detail=f"The Klaude display output is not available: {_KD_IMPORT_ERROR}")
    return _kd


@api.get("/kd/settings", tags=["kd"], summary="Display options")
def get_kd_settings() -> dict:
    """All options and their choices: layout (chat/single), scale (1/2), long (left/up/cut), speed, show_time,
    divider, clock, date, invert, highlight, image_full, color / alt / accent / meta (palette index; alt 0 = off),
    image_fit, image_screen, image_res (high / low: full resolution or 2×2 pixels, low is ~3× faster), size (the
    display's width in metres, 0.20-0.60), screen."""
    k = _need_kd()
    return {"settings": k.s, "choices": {k2: list(v) for k2, v in kd_chat.CHOICES.items()}, "defaults": kd_chat.DEFAULTS}


@api.put("/kd/settings", tags=["kd"], summary="Change display options (partial update)")
def put_kd_settings(body: dict, user: str = AuthDep) -> dict:
    k = _need_kd()
    try:
        s = k.set_settings(body)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    _save_state()
    log.info("kd settings: %s user=%s", body, user)
    return {"settings": s}


@api.post("/kd/clear", status_code=status.HTTP_204_NO_CONTENT, tags=["kd"], summary="Clear the display's messages",
          response_class=Response)
def kd_clear(user: str = AuthDep) -> Response:
    _need_kd().clear()
    return Response(status_code=204)


@api.post("/kd/chime", status_code=status.HTTP_204_NO_CONTENT, tags=["kd"], summary="Play the chime on the avatar",
          response_class=Response)
def kd_chime(user: str = AuthDep) -> Response:
    """Needs the Klaude avatar (PC). The same sound as on sending."""
    _need_kd().chime()
    return Response(status_code=204)


@api.post("/kd/image", tags=["kd"], summary="Show a picture on the display")
async def kd_image(request: Request, user: str = AuthDep) -> dict:
    """Body = the image file itself (png / jpg / webp / gif…, at most 10 MB). It is cropped, its contrast and
    colours adjusted, shown with 16 colours (10 taken from the picture) on the main screen under the header until the
    next message or DELETE /kd/image."""
    k = _need_kd()
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Empty image")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large (at most 10 MB)")
    try:
        info = await run_in_threadpool(k.show_image, data)
    except Exception as e:     # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Cannot read the image: {e}")
    log.info("kd image: %d B user=%s", len(data), user)
    return info


@api.delete("/kd/image", status_code=status.HTTP_204_NO_CONTENT, tags=["kd"], summary="Close the picture",
            response_class=Response)
def kd_image_close(user: str = AuthDep) -> Response:
    _need_kd().close_image()
    return Response(status_code=204)


@api.get("/kd/status", tags=["kd"], summary="Display sending status")
def kd_status() -> dict:
    """active, pending_pages (not sent yet), eta_s, synced (all sent and the checksum matches = the green light)."""
    return _need_kd().status()


@api.get("/kd/preview.png", tags=["kd"], summary="Display preview (what was sent)", response_class=Response)
def kd_preview() -> Response:
    return Response(_need_kd().preview_png(), media_type="image/png", headers={"Cache-Control": "no-store"})


app.include_router(api)


# ==================== the web console ====================


def _read_ui(name: str) -> str:
    with open(os.path.join(UI_DIR, name), encoding="utf-8") as f:
        return f.read()


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def landing(request: Request, session: Optional[str] = None,
            creds: Optional[HTTPBasicCredentials] = Depends(security)) -> Response:
    """the console (ui/index.html). ?session=<token>: the desktop app's window (sets its cookie)."""
    if session is not None:
        if SESSION_TOKEN and hmac.compare_digest(session, SESSION_TOKEN):
            r = RedirectResponse("/", status_code=303)
            r.set_cookie(SESSION_COOKIE, SESSION_TOKEN, httponly=True, samesite="strict")
            return r
        return RedirectResponse("/", status_code=303)
    require_auth(request, creds)
    return HTMLResponse(_read_ui("index.html"), headers={"Cache-Control": "no-store"})


@app.get("/_app/{path:path}", include_in_schema=False, dependencies=[AuthDep])
def ui_asset(path: str) -> Response:
    """the console's scripts and styles (ui/_app/...); hashed file names under immutable/ never change"""
    root = os.path.realpath(os.path.join(UI_DIR, "_app"))
    f = os.path.realpath(os.path.join(root, path))
    ext = os.path.splitext(f)[1]
    if not f.startswith(root + os.sep) or not os.path.isfile(f) or ext not in UI_TYPES:
        raise HTTPException(status_code=404)
    with open(f, "rb") as fh:
        data = fh.read()
    cache = "public, max-age=31536000, immutable" if path.startswith("immutable/") else "no-store"
    return Response(data, media_type=UI_TYPES[ext], headers={"Cache-Control": cache})


@app.get("/icon.svg", include_in_schema=False)
@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(_read_ui("icon.svg"), media_type="image/svg+xml")


# ==================== /docs: a readable API overview (public; the API itself still needs the password) ====================


def _render_docs_html() -> str:
    import html
    spec = app.openapi()
    rows = []
    for path, ops in spec.get("paths", {}).items():
        for method, op in ops.items():
            rows.append(f"<tr><td><span class='m {method}'>{method.upper()}</span></td><td><code>{html.escape(path)}</code>"
                        f"</td><td>{html.escape(op.get('summary', ''))}</td></tr>")
    auth = "-u &quot;:$PASSWORD&quot; " if SETTINGS.auth_enabled() else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>kdchat API</title>
<style>
 body {{ margin: 0 auto; max-width: 900px; padding: 24px 16px 48px; background: #101218; color: #e9e7e3;
        font: 15px/1.6 -apple-system, "Segoe UI", system-ui, sans-serif; }}
 a {{ color: #8aa4ff; }} h1 {{ margin: 0 0 4px; }} .sub {{ color: #9aa0ab; margin: 0 0 20px; }}
 pre, code {{ font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 13px; }}
 pre {{ background: #171a22; border: 1px solid #2a2f3b; border-radius: 10px; padding: 12px; overflow-x: auto; }}
 table {{ width: 100%; border-collapse: collapse; }} td {{ padding: 6px 8px; border-bottom: 1px solid #2a2f3b; vertical-align: top; }}
 .m {{ display: inline-block; min-width: 58px; text-align: center; border-radius: 6px; font: 700 11px ui-monospace, monospace; padding: 2px 6px; }}
 .get {{ background: #1f3b2c; color: #7fe0a0; }} .post {{ background: #3b2f1f; color: #ffc27a; }}
 .put, .patch {{ background: #1f2c3b; color: #8ac4ff; }} .delete {{ background: #3b1f1f; color: #ff9a9a; }}
</style></head><body>
<h1>kdchat API</h1>
<p class="sub">v{__version__} · HTTP → OSC for the VRChat chatbox · <a href="/">console</a> · <a href="/swagger">Swagger UI</a> ·
<a href="/redoc">ReDoc</a> · <a href="/openapi.json">OpenAPI JSON</a></p>
<h2>Quick start</h2>
<pre>curl {auth}-X POST http://localhost:5555/api/v1/messages \\
  -H 'Content-Type: application/json' -d '{{"text":"Hello VRChat!"}}'</pre>
<p>All endpoints live under <code>/api/v1</code>. {"A password is set: use HTTP Basic auth (any user name, the password)." if SETTINGS.auth_enabled() else "No password is set: no login is needed."}
Requests from other web sites are refused unless their origin is listed in <code>ALLOWED_ORIGINS</code>.
OSC is UDP: the server cannot know whether VRChat received a message.</p>
<h2>Endpoints</h2><table>{''.join(rows)}</table>
<p class="sub">Field details: <a href="/swagger">Swagger UI</a>. VRChat OSC: <a href="https://docs.vrchat.com/docs/osc-as-input-controller">OSC as Input Controller</a>.</p>
</body></html>"""


@app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
def public_docs() -> str:
    return _render_docs_html()


# ==================== command line ====================


def port_free(host: str, port: int) -> Optional[str]:
    """None if host:port can be bound, else a message for the user"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name != "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        return None
    except OSError as e:
        if e.errno in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", -1), 10048):
            return (f"Port {port} is already in use (is kdchat already running?). Close the other program or "
                    f"choose another port: LISTEN_PORT=<port>, --port <port>, or the Settings of a running console.")
        if e.errno in (errno.EADDRNOTAVAIL, getattr(errno, "WSAEADDRNOTAVAIL", -1), 10049):
            return f"Cannot listen on {host}: this computer has no such address. Use 0.0.0.0 (all networks) or 127.0.0.1."
        if e.errno in (errno.EACCES, getattr(errno, "WSAEACCES", -1), 10013):
            return f"Not allowed to listen on port {port}. Choose a port above 1024."
        return f"Cannot listen on {host}:{port}: {e.strerror or e}"
    finally:
        s.close()


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="kdchat", description="VRChat chatbox web console and REST API")
    p.add_argument("--host", help="bind address for this run (default: settings / LISTEN_HOST / 0.0.0.0)")
    p.add_argument("--port", type=int, help="HTTP port for this run (default: settings / LISTEN_PORT / 5555)")
    p.add_argument("--version", action="version", version=f"kdchat {__version__}")
    a = p.parse_args(argv)
    host = a.host or SETTINGS.value("listen_host")
    port = a.port or SETTINGS.value("listen_port")
    if not cfg.valid_port(port):
        print(f"error: invalid port {port}", file=sys.stderr)
        return 2
    msg = port_free(host, port)
    if msg:
        log.error(msg)
        return 2
    RUNTIME.update(listen_host=host, listen_port=port)
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level=os.getenv("LOG_LEVEL", "INFO").lower(), access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
