"""VRChat 远程 chatbox 发送服务（带煎蛋认证 + RESTful API）。

通过 RESTful API 把请求转成 OSC 消息，发到 VRChat 的 chatbox（默认 127.0.0.1:9000，见 VRC_HOST）。
OSC 协议细节见 https://docs.vrchat.com/docs/osc-as-input-controller

🍳 煎蛋认证
    方式:   HTTP Basic（用户名任意）
    密码:   环境变量 AUTH_PASSWORD（或同目录 .env 文件），必须设置
    Realm:  煎蛋认证
"""

from __future__ import annotations

import hmac
import logging
import os
import socket
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from pythonosc.udp_client import SimpleUDPClient
from fastapi.responses import Response

import json


def _load_dotenv(path: str) -> None:
    """同目录的 .env（KEY=VALUE 每行一个，# 注释）：只补没设置的环境变量。不进 git，放密码和本机地址。"""
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


_load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
# the Klaude display driver sends to the same VRChat as the chatbox unless KD_OSC_HOST says otherwise
if os.getenv("VRC_HOST"):
    os.environ.setdefault("KD_OSC_HOST", os.environ["VRC_HOST"])

try:                                   # Klaude display output (./kd_chat.py + ./kd_display); optional
    import kd_chat
    _KD_IMPORT_ERROR: Optional[str] = None
except Exception as _e:                # noqa: BLE001
    kd_chat = None
    _KD_IMPORT_ERROR = repr(_e)


# ==================== 配置 ====================

VRC_HOST = os.getenv("VRC_HOST", "127.0.0.1")
VRC_PORT = int(os.getenv("VRC_PORT", "9000"))
LISTEN_HOST = os.getenv("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "8080"))

# 煎蛋认证
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "")
if not AUTH_PASSWORD:
    raise SystemExit("AUTH_PASSWORD 未设置：在环境变量或同目录的 .env 里设置密码（见 .env.example）")
AUTH_REALM = "煎蛋认证"          # 品牌名 / UI 显示 / 日志
WWW_AUTH_REALM = "Chatbox"       # WWW-Authenticate header 的 realm（必须 ASCII，否则 Starlette latin-1 报错）

# 输出模式：chatbox = 游戏自带聊天框（/chatbox/input），kd = Klaude 头顶显示屏（kd 驱动，OSC 参数）
STATE_FILE = os.getenv("STATE_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json"))
KD_DRY = os.getenv("KD_DRY", "") not in ("", "0", "false")      # 测试用：kd 只编码不发送
MODES = ("chatbox", "kd")

# VRChat chatbox 限制
MAX_CHARS = 144
MAX_LINES = 9
KD_MAX_CHARS = 400        # Klaude 显示屏：可以比游戏聊天框长（单条模式会跑马灯）
KD_MAX_LINES = 20
HISTORY_MAX = 50  # 服务端消息历史保留条数

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("vrc-chatbox")


# ==================== FastAPI 应用 ====================

app = FastAPI(
    title="VRChat Chatbox Bridge",
    description=(
        "把 HTTP 请求转成 OSC 消息，发到 VRChat 的 chatbox。\n\n"
        "🔒 **需要煎蛋认证**：用户名任意，密码是环境变量 `AUTH_PASSWORD`"
        "（或同目录 `.env`）里设置的值。\n\n"
        "📖 公开文档: [/docs](/docs)（无需认证）\n"
        "🧪 Swagger UI: [/swagger](/swagger)"
    ),
    version="2.0.0",
    # 默认 /docs 被自定义文档占用，Swagger UI 挪到这里
    docs_url="/swagger",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=[
        {"name": "meta", "description": "元信息 / 配置 / 健康检查"},
        {"name": "messages", "description": "chatbox 消息（发送 + 历史）"},
        {"name": "typing", "description": "typing 指示器状态"},
    ],
)

# 方便同源 / 任意前端直接调。
# 注：如果别的 origin 想带凭证调本 API，需要把 origin 加进 allow_origins
# （浏览器规范不允许 "*" + credentials 同时存在）。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 单例状态 ====================

_client: Optional[SimpleUDPClient] = None
_typing_state: bool = False
_outputs: dict = {"chatbox": True, "kd": False}   # 两个输出各自开关，可以同时打开
_kd = None                      # kd_chat.KdChat，启动时创建
_state_lock = threading.Lock()


def _load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:            # noqa: BLE001
        return {}


def _save_state() -> None:
    with _state_lock:
        data = {"outputs": _outputs, "kd": _kd.s if _kd else _load_state().get("kd", {})}
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_FILE)


# ==================== 输出后端 ====================
# 两种输出共用同一个 VRChat OSC 目标（VRC_HOST:VRC_PORT）。消息和 typing 发到所有打开的输出。


def _chatbox_send(text: str, immediate: bool, sfx: bool) -> None:
    assert _client is not None
    _client.send_message("/chatbox/input", [text, bool(immediate), bool(sfx)])


_cb_typing = False             # what the game's typing indicator was last set to


def _chatbox_typing(on: bool) -> None:
    global _cb_typing
    assert _client is not None
    _cb_typing = bool(on)
    _client.send_message("/chatbox/typing", [bool(on)])


def _chatbox_live(text: str) -> None:
    """a live (not final) update: the game clears its typing indicator on every new message, so light it again"""
    _chatbox_send(text, True, False)
    if _cb_typing:
        _chatbox_typing(True)


def _set_outputs(chatbox: Optional[bool] = None, kd: Optional[bool] = None) -> None:
    """打开 / 关闭输出。kd 打开时显示屏出场（开始发送和补发），关闭时退场，发完后停止发送。"""
    if kd and _kd is None:
        raise HTTPException(status_code=503, detail=f"kd 输出不可用: {_KD_IMPORT_ERROR}")
    if chatbox is not None and bool(chatbox) != _outputs["chatbox"]:
        _outputs["chatbox"] = bool(chatbox)
        if _typing_state:
            _chatbox_typing(_outputs["chatbox"])      # 正在输入的指示器跟着输出走
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


@app.on_event("startup")
def _startup() -> None:
    global _client
    _client = SimpleUDPClient(VRC_HOST, VRC_PORT)
    global _kd
    st = _load_state()
    if kd_chat is not None:
        try:
            _kd = kd_chat.KdChat(VRC_HOST, VRC_PORT, dry=KD_DRY, settings=st.get("kd"))
        except Exception as e:     # noqa: BLE001
            log.error("kd 输出初始化失败: %r", e)
    else:
        log.warning("kd 输出不可用: %s", _KD_IMPORT_ERROR)
    if isinstance(st.get("outputs"), dict):
        _outputs.update({k: bool(v) for k, v in st["outputs"].items() if k in _outputs})
    elif st.get("mode") == "kd":                       # 旧的单选模式：kd 打开，游戏聊天框也一起打开
        _outputs.update(chatbox=True, kd=True)
    if _kd is None:
        _outputs["kd"] = False
    if _kd is not None:
        _kd.set_active(_outputs["kd"])
    log.info("输出: %s%s", _outputs_label(), " (kd dry)" if KD_DRY else "")
    pw_hint = (
        AUTH_PASSWORD[:2] + "*" * (len(AUTH_PASSWORD) - 2)
        if len(AUTH_PASSWORD) >= 2 else "***"
    )
    log.info("OSC target → udp://%s:%d", VRC_HOST, VRC_PORT)
    log.info("🍳 煎蛋认证已启用 (realm=%s, password=%s)", AUTH_REALM, pw_hint)


# ==================== 煎蛋认证 ====================

security = HTTPBasic(auto_error=False, realm=WWW_AUTH_REALM)


def require_auth(
    creds: Optional[HTTPBasicCredentials] = Depends(security),
) -> str:
    """煎蛋认证：用户名任意，密码必须匹配 AUTH_PASSWORD。

    使用 hmac.compare_digest 做恒定时间比较，防止计时攻击。
    """
    if creds is None:
        log.warning("煎蛋认证失败: 缺少 Authorization 头")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "🍳 煎蛋认证失败：缺少凭证。"
                "试试 Authorization: Basic base64(user:<密码>)"
            ),
            headers={"WWW-Authenticate": f'Basic realm="{WWW_AUTH_REALM}"'},
        )
    expected = AUTH_PASSWORD.encode("utf-8")
    provided = creds.password.encode("utf-8") if creds.password else b""
    if not hmac.compare_digest(provided, expected):
        log.warning(
            "煎蛋认证失败: 密码错误 (user=%s)",
            creds.username or "<empty>",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="🍳 煎蛋认证失败：密码错误（煎糊了）",
            headers={"WWW-Authenticate": f'Basic realm="{WWW_AUTH_REALM}"'},
        )
    return creds.username or "ikun"


# 通用认证依赖（路由器级 + 函数级复用，FastAPI 同请求内会自动缓存）
AuthDep = Depends(require_auth)


# ==================== Pydantic 模型 ====================


class MessageCreate(BaseModel):
    """发送 chatbox 消息的请求体。"""
    text: str = Field(..., description="要发送的 chatbox 文本（最长 144 字符、最多 9 行）")
    immediate: bool = Field(
        True,
        description="True=立即发送，False=只填进键盘（不发送）",
    )
    sfx: bool = Field(
        True,
        description="是否播放通知音效（immediate=True 时才有意义）",
    )
    live: bool = Field(
        False,
        description="自动发送（边打边发）的更新：kd 模式下原地更新正在打的那条，不新增一条（游戏聊天框忽略）",
    )
    final: bool = Field(True, description="False = 还在打（实时显示，之后用 PATCH 更新 / 定稿，DELETE 放弃）")
    targets: Optional[list[str]] = Field(
        None,
        description="这条发到哪些输出（chatbox / kd），只在打开的输出里选；不填 = 所有打开的输出。"
                    "比如显示屏正在显示图片时只发 [\"chatbox\"]，图片不受影响",
    )


class MessageItem(BaseModel):
    """已发送消息资源。"""
    id: int = Field(..., description="消息自增 ID")
    text: str
    immediate: bool
    sfx: bool
    output: str = Field("chatbox", description="发到哪里：chatbox / kd / chatbox+kd")
    created_at: str = Field(..., description="ISO 8601 UTC 时间戳")
    length: int
    edited: bool = Field(False, description="发出后改过（显示屏上显示 edited）")
    reverted: bool = Field(False, description="已撤回（显示屏上显示 message reverted）")
    kd_id: Optional[int] = Field(None, description="它在 Klaude 显示屏上的编号（只有发到显示屏的消息有）")
    final: bool = Field(True, description="False = 还在打")
    targets: list[str] = Field(default_factory=list, description="发到了哪些输出")


class MessageEdit(BaseModel):
    """修改消息：还在打的更新内容 / 定稿；已发出的编辑（显示 edited）。"""
    text: str = Field(..., description="新的内容")
    final: bool = Field(True, description="False = 编辑还在进行（实时显示），True = 定稿")
    cancel: bool = Field(False, description="放弃编辑：恢复成这段文字，不标 edited")


class MessageList(BaseModel):
    """消息列表（分页）。"""
    items: list[MessageItem]
    total: int = Field(..., description="服务端消息总数")
    limit: int
    offset: int


class ModeState(BaseModel):
    """输出模式。"""
    mode: str = Field(..., description="chatbox = 游戏自带聊天框；kd = Klaude 头顶显示屏")
    max_chars: int = Field(0, description="这个模式下一条消息最多几个字符（只读）")
    max_lines: int = Field(0, description="最多几行（只读）")


class TypingState(BaseModel):
    """typing 状态。"""
    typing: bool = Field(..., description="是否显示'正在输入'指示器")
    targets: Optional[list[str]] = Field(None, description="显示在哪些输出上（不填 = 所有打开的输出）")


class HealthResponse(BaseModel):
    """健康检查响应。"""
    ok: bool
    vrc_host: str
    vrc_port: int
    max_chars: int
    max_lines: int
    auth_enabled: bool
    error: Optional[str] = None


class ConfigResponse(BaseModel):
    """运行时配置。"""
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
    """服务元信息。"""
    name: str
    version: str
    description: str
    vrc_target: str
    auth: dict


# ==================== 工具函数 ====================


def _limits(use: Optional[dict] = None) -> tuple[int, int]:
    """长度限制 (字符, 行)：发到游戏聊天框时按它的限制，只发显示屏时可以更长"""
    return (MAX_CHARS, MAX_LINES) if (use or _outputs)["chatbox"] else (KD_MAX_CHARS, KD_MAX_LINES)


def _use(targets: Optional[list[str]]) -> dict:
    """打开的输出里，这一次要用的那些"""
    if targets is None:
        return dict(_outputs)
    bad = [t for t in targets if t not in _outputs]
    if bad:
        raise HTTPException(status_code=400, detail=f"targets 只能是 chatbox / kd: {bad}")
    return {k: _outputs[k] and k in targets for k in _outputs}


def _validate_text(text: str, use: Optional[dict] = None) -> str:
    max_chars, max_lines = _limits(use)
    if len(text) > max_chars:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"text 过长: {len(text)} > {max_chars} 字符",
        )
    if text == "":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="text 不能为空",
        )
    nlines = text.count("\n") + 1
    if nlines > max_lines:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"text 换行过多: {nlines} > {max_lines} 行",
        )
    return text


def _dns_resolves(host: str) -> tuple[bool, Optional[str]]:
    """判断 host 能否解析（不做端口握手，UDP 无法可靠判断）。"""
    try:
        socket.getaddrinfo(host, None)
        return True, None
    except Exception as e:
        return False, str(e)


def _next_message_id() -> int:
    global _next_id
    with _id_lock:
        _next_id += 1
        return _next_id


# ==================== REST API ====================

api = APIRouter(prefix="/api/v1", dependencies=[AuthDep])


@api.get("/info", response_model=InfoResponse, tags=["meta"], summary="服务元信息")
def get_info() -> InfoResponse:
    """返回服务名 / 版本 / 认证配置等元信息。"""
    return InfoResponse(
        name="VRChat Chatbox Bridge",
        version="2.0.0",
        description="把 HTTP 请求转成 OSC 消息，发到 VRChat 的 chatbox。需要煎蛋认证。",
        vrc_target=f"{VRC_HOST}:{VRC_PORT}",
        auth={
            "type": "basic",
            "realm": AUTH_REALM,
            "password_env": "AUTH_PASSWORD",
            "hint": 'curl 示例: -u ":$AUTH_PASSWORD"  /  header: Authorization: Basic base64(":<密码>")',
        },
    )


@api.get("/config", response_model=ConfigResponse, tags=["meta"], summary="运行时配置")
def get_config() -> ConfigResponse:
    """返回当前运行时配置（环境变量 + 限制）。"""
    return ConfigResponse(
        vrc_host=VRC_HOST,
        vrc_port=VRC_PORT,
        listen_host=LISTEN_HOST,
        listen_port=LISTEN_PORT,
        max_chars=MAX_CHARS,
        max_lines=MAX_LINES,
        history_max=HISTORY_MAX,
        auth_enabled=True,
        auth_realm=AUTH_REALM,
    )


@api.get("/health", response_model=HealthResponse, tags=["meta"], summary="健康检查")
def get_health() -> HealthResponse:
    """健康检查 + 当前目标配置。

    UDP 没有握手，无法可靠判断 VRChat 是否在监听；
    这里只验证目标 host 能否被解析。
    """
    ok, err = _dns_resolves(VRC_HOST)
    return HealthResponse(
        ok=ok,
        vrc_host=VRC_HOST,
        vrc_port=VRC_PORT,
        max_chars=MAX_CHARS,
        max_lines=MAX_LINES,
        auth_enabled=True,
        error=err,
    )


class _ChatboxThrottle:
    """VRChat 的聊天框有频率限制：实时更新最多每 1.5 秒发一次（总是发最新的内容），定稿立即发"""
    GAP = 1.5

    def __init__(self):
        self.lock = threading.Lock()
        self.last = 0.0
        self.pending = None
        self.timer = None

    def send(self, text: str, final: bool, sfx: bool) -> None:
        import time as _t
        with self.lock:
            now = _t.monotonic()
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

    def _flush(self) -> None:
        import time as _t
        with self.lock:
            if self.pending is not None:
                _chatbox_live(self.pending)
                self.last = _t.monotonic()
                self.pending = None
            self.timer = None


_cb = _ChatboxThrottle()


@api.post(
    "/messages",
    response_model=MessageItem,
    status_code=status.HTTP_201_CREATED,
    tags=["messages"],
    summary="发一条消息（或开始实时打一条）",
)
def create_message(req: MessageCreate, user: str = AuthDep) -> MessageItem:
    """发到打开的输出（或 `targets` 里的）。`final=false`：这条还在打，显示屏上实时显示，游戏聊天框节流更新；
    之后 `PATCH /messages/{id}` 更新 / 定稿，`DELETE /messages/{id}` 放弃。`immediate=false`：只填进游戏键盘。"""
    final = bool(req.final) and not req.live
    use = _use(req.targets)
    text = _validate_text(req.text, use)
    if not (use["chatbox"] or use["kd"]):
        raise HTTPException(status_code=409, detail="没有要发的输出：先打开游戏聊天框或 Klaude 显示屏")
    if not req.immediate:                                      # 只填进游戏的键盘（不发送）
        if use["chatbox"]:
            _chatbox_send(text, False, False)
        return MessageItem(id=0, text=text, immediate=False, sfx=False, output="chatbox",
                           created_at=datetime.now(timezone.utc).isoformat(), length=len(text), targets=["chatbox"])
    kd_id = _kd.new_message(text, final, bool(req.sfx)) if use["kd"] and _kd is not None else None
    if use["chatbox"]:
        _cb.send(text, final, bool(req.sfx))
    targets = [k for k in ("chatbox", "kd") if use[k]]
    msg = MessageItem(output="+".join(targets), id=_next_message_id(), text=text, immediate=True, sfx=bool(req.sfx),
                      created_at=datetime.now(timezone.utc).isoformat(), length=len(text), kd_id=kd_id,
                      final=final, targets=targets)
    with _history_lock:
        _history.append(msg)
    log.info("send: id=%d len=%d final=%s to=%s user=%s", msg.id, msg.length, final, msg.output, user)
    return msg


def _find(message_id: int) -> MessageItem:
    with _history_lock:
        for msg in reversed(_history):
            if msg.id == message_id:
                return msg
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"message {message_id} 不存在")


@api.patch("/messages/{message_id}", response_model=MessageItem, tags=["messages"], summary="更新 / 定稿 / 编辑一条消息")
def edit_message(message_id: int, body: MessageEdit, user: str = AuthDep) -> MessageItem:
    """还在打的消息：更新内容，`final=true` 定稿。已经发出的消息：编辑（显示屏上原地改，显示 edited；可以
    `final=false` 实时改，最后 `final=true` 定稿；`cancel=true` 恢复原文）。游戏聊天框只显示最新的一条：
    改的是它最新那条时会重新发。"""
    msg = _find(message_id)
    if msg.reverted:
        raise HTTPException(status_code=409, detail="这条已经撤回了")
    use = {"chatbox": "chatbox" in msg.targets and _outputs["chatbox"], "kd": msg.kd_id is not None and _outputs["kd"]}
    text = _validate_text(body.text, use)
    with _history_lock:
        latest_cb = next((m for m in reversed(_history) if "chatbox" in m.targets), None)
    done = body.final or body.cancel
    if not msg.final:
        # a new message still being typed: update it, final = sent (the chime, if asked for, plays now)
        if use["kd"] and _kd is not None:
            _kd.update_message(msg.kd_id, text, final=True if done else None, sfx=done and msg.sfx)
        if use["chatbox"] and latest_cb is msg:
            _cb.send(text, done, done and msg.sfx)
        msg.text, msg.length = text, len(text)
        msg.final = done
        return msg
    # editing a sent message (live while typing, then final; cancel = back to the text the client had)
    was = _edit_sessions.setdefault(msg.id, msg.edited)
    edited = was if body.cancel else True
    if done:
        _edit_sessions.pop(msg.id, None)
    if use["kd"] and _kd is not None:
        _kd.update_message(msg.kd_id, text, edited=edited)
    if use["chatbox"] and latest_cb is msg:
        _cb.send(text, done, False)                              # the game only shows its newest message
    msg.text, msg.length, msg.edited = text, len(text), edited
    if done:
        log.info("edit: id=%d cancel=%s user=%s", msg.id, body.cancel, user)
    return msg


_edit_sessions: dict = {}         # message id -> its "edited" state before the edit in progress


@api.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["messages"],
            summary="放弃一条还在打的消息", response_class=Response)
def drop_message(message_id: int, user: str = AuthDep) -> Response:
    """只用于还没定稿的消息（输入框清空 / Esc）：显示屏上整条去掉，游戏聊天框清空。"""
    msg = _find(message_id)
    if msg.final:
        raise HTTPException(status_code=409, detail="已经发出的消息请用撤回")
    if msg.kd_id is not None and _kd is not None:
        _kd.remove_message(msg.kd_id)
    if "chatbox" in msg.targets and _outputs["chatbox"]:
        _cb.send("", True, False)
    with _history_lock:
        try:
            _history.remove(msg)
        except ValueError:
            pass
    return Response(status_code=204)


@api.post("/messages/{message_id}/revert", response_model=MessageItem, tags=["messages"], summary="撤回消息")
def revert_message(message_id: int, user: str = AuthDep) -> MessageItem:
    """Klaude 显示屏上这条变成 message reverted。游戏聊天框里的消息 VRChat 没法撤回。"""
    msg = _find(message_id)
    if msg.kd_id is None or _kd is None or not _kd.revert_message(msg.kd_id):
        raise HTTPException(status_code=409, detail="只有发到 Klaude 显示屏、而且还在屏幕记录里的消息能撤回")
    msg.reverted = True
    msg.final = True
    log.info("revert: id=%d user=%s", msg.id, user)
    return msg


@api.get(
    "/messages",
    response_model=MessageList,
    tags=["messages"],
    summary="分页列出历史消息",
)
def list_messages(
    limit: int = Query(20, ge=1, le=HISTORY_MAX, description="返回条目数量（1-50）"),
    offset: int = Query(0, ge=0, description="跳过的条目数"),
) -> MessageList:
    """分页列出最近发送的消息（最新在前）。"""
    with _history_lock:
        snapshot = list(_history)
    snapshot.reverse()
    page = snapshot[offset:offset + limit]
    return MessageList(
        items=page,
        total=len(snapshot),
        limit=limit,
        offset=offset,
    )


@api.get(
    "/messages/{message_id}",
    response_model=MessageItem,
    tags=["messages"],
    summary="获取单条历史消息",
)
def get_message(message_id: int) -> MessageItem:
    """按 ID 获取单条已发送的消息。"""
    with _history_lock:
        for msg in reversed(_history):
            if msg.id == message_id:
                return msg
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"message {message_id} 不存在",
    )


@api.delete(
    "/messages",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["messages"],
    summary="清空消息历史",
    response_class=HTMLResponse,  # 占位，避免 FastAPI 默认生成空 body 文档
)
def clear_messages() -> None:
    """清空服务端消息历史（不影响 VRChat 端）。"""
    with _history_lock:
        n = len(_history)
        _history.clear()
    log.info("message history cleared (%d items)", n)
    return None


@api.put(
    "/typing",
    response_model=TypingState,
    tags=["typing"],
    summary="设置 typing 状态",
)
def set_typing(
    state: TypingState,
    user: str = AuthDep,
) -> TypingState:
    """更新 typing 指示器状态（'正在输入'）。

    OSC 地址: `/chatbox/typing <bool>`
    """
    global _typing_state
    _typing_state = bool(state.typing)
    use = _use(state.targets)
    if _kd is not None and _outputs["kd"]:
        _kd.set_typing(_typing_state and use["kd"])            # (off where this text does not go)
    if _outputs["chatbox"]:
        _chatbox_typing(_typing_state and use["chatbox"])
    log.info("typing: %s user=%s", _typing_state, user)
    return TypingState(typing=_typing_state)


@api.get(
    "/typing",
    response_model=TypingState,
    tags=["typing"],
    summary="获取 typing 状态",
)
def get_typing() -> TypingState:
    """获取当前 typing 指示器状态。"""
    return TypingState(typing=_typing_state)


class OutputsState(BaseModel):
    """输出开关（可以同时打开）。"""
    chatbox: Optional[bool] = Field(None, description="游戏自带聊天框")
    kd: Optional[bool] = Field(None, description="Klaude 头顶显示屏（需要穿着 Klaude，PC）")


def _outputs_body() -> dict:
    mc, ml = _limits()
    return {"chatbox": _outputs["chatbox"], "kd": _outputs["kd"], "kd_available": _kd is not None,
            "max_chars": mc, "max_lines": ml}


@api.get("/outputs", tags=["mode"], summary="输出开关")
def get_outputs() -> dict:
    """chatbox / kd 各自是否打开，以及当前的长度限制。"""
    return _outputs_body()


@api.put("/outputs", tags=["mode"], summary="打开 / 关闭输出（部分更新）")
def put_outputs(state: OutputsState, user: str = AuthDep) -> dict:
    """例如 `{"kd": false}` 关闭显示屏（退场动画），游戏聊天框不受影响。会保存，重启后保持。"""
    _set_outputs(state.chatbox, state.kd)
    log.info("outputs: %s user=%s", _outputs_label(), user)
    return _outputs_body()


@api.get("/mode", response_model=ModeState, tags=["mode"], summary="（旧）当前输出模式")
def get_mode() -> ModeState:
    """兼容旧接口：kd 打开时返回 kd，否则 chatbox。新代码请用 /outputs。"""
    return ModeState(mode="kd" if _outputs["kd"] else "chatbox", max_chars=_limits()[0], max_lines=_limits()[1])


@api.put("/mode", response_model=ModeState, tags=["mode"], summary="（旧）只用一个输出")
def put_mode(state: ModeState, user: str = AuthDep) -> ModeState:
    """兼容旧接口：chatbox = 只用游戏聊天框；kd = 只用显示屏。新代码请用 /outputs。"""
    if state.mode not in MODES:
        raise HTTPException(status_code=400, detail=f"mode 必须是 {MODES}")
    _set_outputs(chatbox=state.mode == "chatbox", kd=state.mode == "kd")
    log.info("outputs: %s user=%s", _outputs_label(), user)
    return get_mode()


def _need_kd():
    if _kd is None:
        raise HTTPException(status_code=503, detail=f"kd 输出不可用: {_KD_IMPORT_ERROR}")
    return _kd


@api.get("/kd/settings", tags=["kd"], summary="kd 显示屏选项")
def get_kd_settings() -> dict:
    """所有选项及可选值：layout(chat/single)、scale(1/2)、long(left/up/cut)、speed、show_time、divider、clock、
    date、invert、highlight、image_full、color / alt / accent / meta（调色板序号；alt 0 = 关）、image_fit、image_screen、image_res（high / low：图片全分辨率或 2×2 像素点，低分辨率约快 3 倍）、size（显示屏宽度，米，0.20–0.60）、screen。"""
    k = _need_kd()
    return {"settings": k.s, "choices": {k2: list(v) for k2, v in kd_chat.CHOICES.items()}, "defaults": kd_chat.DEFAULTS}


@api.put("/kd/settings", tags=["kd"], summary="修改 kd 显示屏选项（部分更新）")
def put_kd_settings(body: dict, user: str = AuthDep) -> dict:
    k = _need_kd()
    try:
        s = k.set_settings(body)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    _save_state()
    log.info("kd settings: %s user=%s", body, user)
    return {"settings": s}


@api.post("/kd/clear", status_code=status.HTTP_204_NO_CONTENT, tags=["kd"], summary="清空 kd 显示屏上的消息",
          response_class=Response)
def kd_clear(user: str = AuthDep) -> Response:
    _need_kd().clear()
    return Response(status_code=204)


@api.post("/kd/chime", status_code=status.HTTP_204_NO_CONTENT, tags=["kd"], summary="在 avatar 上播放一次提示音",
          response_class=Response)
def kd_chime(user: str = AuthDep) -> Response:
    """需要穿着 Klaude（PC）。和发送时的提示音是同一个。"""
    _need_kd().chime()
    return Response(status_code=204)


@api.post("/kd/image", tags=["kd"], summary="在 kd 显示屏上显示一张图片")
async def kd_image(request: Request, user: str = AuthDep) -> dict:
    """请求体 = 图片文件本身（png / jpg / webp / gif…，最大 10 MB）。图片会被裁切、调整对比度和颜色，
    用 16 色（其中 10 色取自图片）显示在标题栏下面，直到下一条消息或 DELETE /kd/image。约 40 页，3 Hz 下约 15 秒传完。"""
    k = _need_kd()
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="空的图片")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="图片太大（最大 10 MB）")
    try:
        info = await run_in_threadpool(k.show_image, data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无法读取图片: {e}")
    log.info("kd image: %d B user=%s", len(data), user)
    return info


@api.delete("/kd/image", status_code=status.HTTP_204_NO_CONTENT, tags=["kd"], summary="关闭图片，回到消息",
            response_class=Response)
def kd_image_close(user: str = AuthDep) -> Response:
    _need_kd().close_image()
    return Response(status_code=204)


@api.get("/kd/status", tags=["kd"], summary="kd 发送状态")
def kd_status() -> dict:
    """active、pending_pages（还没发出去的页）、eta_s、synced（全部发完且校验和一致 = 头顶状态灯是绿的）。"""
    return _need_kd().status()


@api.get("/kd/preview.png", tags=["kd"], summary="kd 显示屏预览（已发出的内容）", response_class=Response)
def kd_preview() -> Response:
    return Response(_need_kd().preview_png(), media_type="image/png", headers={"Cache-Control": "no-store"})


# 注册 API 路由
app.include_router(api)


# ==================== UI（也受煎蛋认证保护） ====================


UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
UI_FILES = {"app.js": "application/javascript", "i18n.js": "application/javascript", "app.css": "text/css"}


@app.get("/", response_class=HTMLResponse, include_in_schema=False, dependencies=[AuthDep])
def landing() -> Response:
    """控制台（ui/index.html；也受煎蛋认证保护）"""
    with open(os.path.join(UI_DIR, "index.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read(), headers={"Cache-Control": "no-store"})


@app.get("/ui/{name}", include_in_schema=False, dependencies=[AuthDep])
def ui_file(name: str) -> Response:
    if name not in UI_FILES:
        raise HTTPException(status_code=404)
    with open(os.path.join(UI_DIR, name), encoding="utf-8") as f:
        return Response(f.read(), media_type=UI_FILES[name] + "; charset=utf-8", headers={"Cache-Control": "no-store"})


# ==================== 公开文档（无需煎蛋认证） ====================


def _render_docs_html() -> str:
    """渲染公开的 API 文档页面（人类可读版）。"""
    return f"""<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VRChat Chatbox Bridge · API 文档</title>
  <style>
    :root {{
      --bg: #0f1117;
      --bg-2: #181b25;
      --bg-3: #232733;
      --fg: #e8eaf0;
      --fg-dim: #9aa0b0;
      --accent: #6c8cff;
      --accent-2: #5a78e8;
      --ok: #4ade80;
      --warn: #fbbf24;
      --err: #f87171;
      --border: #2a2f3d;
      --code-bg: #0b0d13;
      --radius: 12px;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{
      margin: 0; padding: 0;
      background: var(--bg); color: var(--fg);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui,
                   "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      font-size: 16px; line-height: 1.65;
      -webkit-text-size-adjust: 100%;
    }}
    body {{
      max-width: 920px; margin: 0 auto;
      padding: 40px 22px 100px;
    }}

    /* Hero */
    .hero {{
      text-align: center;
      padding: 24px 0 36px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 32px;
    }}
    .hero h1 {{
      font-size: 30px; margin: 0 0 8px; font-weight: 700;
      letter-spacing: -0.5px;
    }}
    .hero .sub {{ color: var(--fg-dim); font-size: 15px; margin: 0 0 14px; }}
    .hero .badges {{ display: inline-flex; gap: 8px; flex-wrap: wrap; justify-content: center; }}
    .badge {{
      display: inline-block;
      font-size: 11px; font-weight: 700; letter-spacing: 0.5px;
      padding: 4px 10px; border-radius: 999px;
      font-family: ui-monospace, "SF Mono", monospace;
    }}
    .badge.eg {{
      background: linear-gradient(135deg, #fbbf24, #f59e0b);
      color: #1f1300;
    }}
    .badge.ver {{
      background: var(--bg-3); color: var(--fg-dim);
      border: 1px solid var(--border);
    }}
    .badge.target {{
      background: var(--bg-2); color: var(--accent);
      border: 1px solid var(--border);
    }}

    /* TOC */
    nav.toc {{
      background: var(--bg-2);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 14px 18px;
      margin-bottom: 36px;
    }}
    nav.toc h3 {{
      margin: 0 0 8px;
      font-size: 11px; text-transform: uppercase; letter-spacing: 1.2px;
      color: var(--fg-dim); font-weight: 700;
    }}
    nav.toc ul {{ list-style: none; margin: 0; padding: 0; columns: 2; column-gap: 24px; }}
    nav.toc li {{ margin: 3px 0; break-inside: avoid; }}
    nav.toc a {{
      color: var(--accent); text-decoration: none; font-size: 14px;
      display: block; padding: 2px 0;
    }}
    nav.toc a:hover {{ text-decoration: underline; }}

    /* Sections */
    section {{ margin: 44px 0; scroll-margin-top: 16px; }}
    section h2 {{
      font-size: 22px;
      border-left: 3px solid var(--accent);
      padding-left: 12px;
      margin: 0 0 18px;
    }}
    section h3 {{
      font-size: 17px;
      color: var(--fg);
      margin: 28px 0 10px;
      font-weight: 600;
    }}
    section h4 {{
      font-size: 12px;
      color: var(--fg-dim);
      margin: 18px 0 6px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.8px;
    }}
    section p {{ color: var(--fg-dim); margin: 10px 0; }}
    section ul {{ color: var(--fg-dim); padding-left: 22px; }}
    section li {{ margin: 5px 0; }}
    section strong {{ color: var(--fg); }}

    /* Inline code */
    code {{ font-family: ui-monospace, "SF Mono", "Cascadia Code", Menlo, monospace; }}
    .ic {{
      background: var(--bg-3);
      color: var(--fg);
      padding: 1px 6px;
      border-radius: 4px;
      font-size: 0.88em;
    }}

    /* Endpoint card */
    .ep {{
      background: var(--bg-2);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 16px 18px;
      margin: 14px 0;
    }}
    .ep-head {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
    .m {{
      display: inline-block;
      padding: 3px 9px;
      border-radius: 6px;
      font-family: ui-monospace, monospace;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.5px;
    }}
    .m.get    {{ background: #14532d; color: #bbf7d0; }}
    .m.post   {{ background: #1e3a8a; color: #bfdbfe; }}
    .m.put    {{ background: #78350f; color: #fde68a; }}
    .m.delete {{ background: #7f1d1d; color: #fecaca; }}
    .ep-path {{
      font-family: ui-monospace, monospace; font-size: 15px;
      font-weight: 600;
    }}
    .ep-desc {{ color: var(--fg-dim); font-size: 13.5px; margin: 8px 0 12px; }}

    /* Code block */
    pre {{
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px 16px;
      overflow-x: auto;
      margin: 10px 0;
      font-size: 13px;
      line-height: 1.55;
      cursor: pointer;
      position: relative;
      transition: box-shadow .15s, border-color .15s;
    }}
    pre:hover {{ border-color: var(--accent); }}
    pre::after {{
      content: "点击复制";
      position: absolute; top: 8px; right: 12px;
      font-size: 10px; color: var(--fg-dim);
      opacity: 0; transition: opacity .15s;
      pointer-events: none;
    }}
    pre:hover::after {{ opacity: 0.6; }}

    /* Tables */
    table {{
      width: 100%; border-collapse: collapse;
      margin: 14px 0;
      background: var(--bg-2);
      border-radius: var(--radius);
      overflow: hidden;
      border: 1px solid var(--border);
    }}
    th, td {{
      padding: 10px 14px; text-align: left;
      border-bottom: 1px solid var(--border);
      font-size: 14px;
      vertical-align: top;
    }}
    th {{
      background: var(--bg-3); color: var(--fg-dim);
      font-size: 11px; text-transform: uppercase; letter-spacing: 0.8px;
      font-weight: 700;
    }}
    tr:last-child td {{ border-bottom: 0; }}
    td code {{ background: var(--bg-3); padding: 2px 6px; border-radius: 4px; font-size: 12px; }}

    /* Auth box */
    .auth {{
      background: rgba(251,191,36,.08);
      border: 1px solid rgba(251,191,36,.25);
      border-radius: var(--radius);
      padding: 16px 18px;
      margin: 14px 0;
      color: var(--fg);
    }}
    .auth strong {{ color: var(--warn); }}
    .auth code {{ background: var(--bg-3); padding: 2px 6px; border-radius: 4px; }}

    /* Links section */
    .links {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 14px 0; }}
    .links a {{
      display: inline-flex; align-items: center; gap: 6px;
      padding: 10px 14px;
      background: var(--bg-2);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      color: var(--accent);
      text-decoration: none;
      font-size: 14px;
      transition: background .15s, border-color .15s;
    }}
    .links a:hover {{ background: var(--bg-3); border-color: var(--accent); }}

    /* Footer */
    footer {{
      margin-top: 60px; padding-top: 24px;
      border-top: 1px solid var(--border);
      color: var(--fg-dim); font-size: 12px; text-align: center;
    }}

    /* Responsive */
    @media (max-width: 600px) {{
      body {{ padding: 24px 14px 60px; }}
      .hero h1 {{ font-size: 22px; }}
      .hero .sub {{ font-size: 13px; }}
      nav.toc ul {{ columns: 1; }}
      section h2 {{ font-size: 18px; }}
      section h3 {{ font-size: 15px; }}
      pre {{ font-size: 12px; }}
      table {{ font-size: 13px; }}
      th, td {{ padding: 8px 10px; }}
    }}
  </style>
</head>
<body>

<div class="hero">
  <h1>🍳 VRChat Chatbox Bridge</h1>
  <p class="sub">HTTP → OSC 网关，把请求转成 VRChat chatbox 消息</p>
  <div class="badges">
    <span class="badge eg">煎蛋认证</span>
    <span class="badge ver">v2.0.0</span>
    <span class="badge target">→ {VRC_HOST}:{VRC_PORT}</span>
  </div>
</div>

<nav class="toc">
  <h3>目录</h3>
  <ul>
    <li><a href="#quickstart">30 秒上手</a></li>
    <li><a href="#auth">煎蛋认证</a></li>
    <li><a href="#api">API 参考</a></li>
    <li><a href="#config">配置</a></li>
    <li><a href="#limits">限制</a></li>
    <li><a href="#links">相关链接</a></li>
  </ul>
</nav>

<section id="quickstart">
  <h2>30 秒上手</h2>
  <p>服务默认跑在 <code class="ic">0.0.0.0:8080</code>，把 HTTP 请求转成 OSC 消息发给 VRChat（<code class="ic">VRC_HOST:VRC_PORT</code>，默认 <code class="ic">127.0.0.1:9000</code>）。</p>
  <p>发一条消息只需要：</p>
  <pre>curl -u ":$AUTH_PASSWORD" -X POST http://localhost:8080/api/v1/messages \\
  -H 'Content-Type: application/json' \\
  -d '{{"text":"Hello VRChat!","immediate":true,"sfx":true}}'</pre>
  <p>或者打开 <a href="/">/</a> 用网页控制台（浏览器会弹原生登录框，输入 <code class="ic">AUTH_PASSWORD</code> 里的密码）。</p>
</section>

<section id="auth">
  <h2>煎蛋认证 🍳</h2>
  <div class="auth">
    <strong>所有 API 请求</strong>都需要 HTTP Basic Auth。
    用户名任意，密码是环境变量 <code>AUTH_PASSWORD</code>（或同目录 <code>.env</code>）里设置的值。
    下面的例子假设 shell 里已经 <code class="ic">export AUTH_PASSWORD=...</code>。
  </div>

  <h3>1. curl（最常用）</h3>
  <pre>curl -u ":$AUTH_PASSWORD" http://localhost:8080/api/v1/health</pre>
  <p>注意 <code class="ic">-u ":$AUTH_PASSWORD"</code> 中冒号前是用户名（任意），冒号后是密码。</p>

  <h3>2. Authorization 头（任意 HTTP 客户端）</h3>
  <pre>Authorization: Basic $(echo -n ":$AUTH_PASSWORD" | base64)</pre>

  <h3>3. 浏览器</h3>
  <p>访问 <code class="ic">/</code> 或 <code class="ic">/swagger</code> 时浏览器会弹原生登录框，
  输入密码（用户名随便填）即可。浏览器会记住凭证，后续请求自动带上。</p>

  <h3>4. 设置密码</h3>
  <pre>echo 'AUTH_PASSWORD=换成你自己的密码' >> .env      # 或 export AUTH_PASSWORD=...
uv run uvicorn app:app --host 0.0.0.0 --port 5555</pre>
</section>

<section id="api">
  <h2>API 参考</h2>
  <p>所有 API 都在 <code class="ic">/api/v1</code> 前缀下，遵循标准 REST 约定：</p>
  <ul>
    <li><strong>POST</strong> 创建资源</li>
    <li><strong>GET</strong> 读取资源（列表 / 单条 / 状态）</li>
    <li><strong>PUT</strong> 更新状态资源</li>
    <li><strong>DELETE</strong> 删除 / 清空</li>
  </ul>

  <h3>元信息 / 配置 / 健康</h3>

  <div class="ep">
    <div class="ep-head"><span class="m get">GET</span><span class="ep-path">/api/v1/info</span></div>
    <div class="ep-desc">服务元信息（名称、版本、认证配置）。无需传参。</div>
    <pre>curl -u ":$AUTH_PASSWORD" http://localhost:8080/api/v1/info</pre>
  </div>

  <div class="ep">
    <div class="ep-head"><span class="m get">GET</span><span class="ep-path">/api/v1/config</span></div>
    <div class="ep-desc">运行时配置（VRC host/port、监听地址、限制、认证 realm）。</div>
    <pre>curl -u ":$AUTH_PASSWORD" http://localhost:8080/api/v1/config</pre>
  </div>

  <div class="ep">
    <div class="ep-head"><span class="m get">GET</span><span class="ep-path">/api/v1/health</span></div>
    <div class="ep-desc">健康检查 + 目标 host DNS 解析结果。UDP 无法可靠判断对端是否监听，只能告诉你 host 至少能解析。</div>
    <pre>curl -u ":$AUTH_PASSWORD" http://localhost:8080/api/v1/health</pre>
  </div>

  <h3>消息（messages）</h3>

  <div class="ep">
    <div class="ep-head"><span class="m post">POST</span><span class="ep-path">/api/v1/messages</span></div>
    <div class="ep-desc">发送一条 chatbox 消息。成功返回 <code class="ic">201 Created</code>。</div>
    <h4>请求体</h4>
    <pre>{{
  "text": "Hello VRChat!",   // 必填，最长 144 字符、最多 9 行
  "immediate": true,         // 可选，默认 true。true=立刻发，false=只填键盘
  "sfx": true                // 可选，默认 true。是否播放通知音效
}}</pre>
    <h4>示例</h4>
    <pre>curl -u ":$AUTH_PASSWORD" -X POST http://localhost:8080/api/v1/messages \\
  -H 'Content-Type: application/json' \\
  -d '{{"text":"Hello!","immediate":true,"sfx":true}}'</pre>
    <h4>响应 (201 Created)</h4>
    <pre>{{
  "id": 1,
  "text": "Hello!",
  "immediate": true,
  "sfx": true,
  "created_at": "2024-01-01T12:00:00+00:00",
  "length": 6
}}</pre>
    <h4>错误</h4>
    <ul>
      <li><code class="ic">400</code> — text 为空 / 超过 144 字符 / 超过 9 行</li>
      <li><code class="ic">401</code> — 煎蛋认证失败（密码错）</li>
    </ul>
  </div>

  <div class="ep">
    <div class="ep-head"><span class="m get">GET</span><span class="ep-path">/api/v1/messages</span></div>
    <div class="ep-desc">分页列出最近发送的消息（最新在前）。</div>
    <h4>Query 参数</h4>
    <pre>?limit=20     // 1-50，默认 20
?offset=0      // 跳过的条目数，默认 0</pre>
    <pre>curl -u ":$AUTH_PASSWORD" 'http://localhost:8080/api/v1/messages?limit=5'</pre>
  </div>

  <div class="ep">
    <div class="ep-head"><span class="m get">GET</span><span class="ep-path">/api/v1/messages/{{id}}</span></div>
    <div class="ep-desc">按 ID 获取单条消息。ID 不存在返回 <code class="ic">404 Not Found</code>。</div>
    <pre>curl -u ":$AUTH_PASSWORD" http://localhost:8080/api/v1/messages/1</pre>
  </div>

  <div class="ep">
    <div class="ep-head"><span class="m delete">DELETE</span><span class="ep-path">/api/v1/messages</span></div>
    <div class="ep-desc">清空服务端消息历史。返回 <code class="ic">204 No Content</code>（不影响 VRChat 端已发送的消息）。</div>
    <pre>curl -u ":$AUTH_PASSWORD" -X DELETE http://localhost:8080/api/v1/messages</pre>
  </div>

  <h3>Typing 指示器</h3>

  <div class="ep">
    <div class="ep-head"><span class="m put">PUT</span><span class="ep-path">/api/v1/typing</span></div>
    <div class="ep-desc">设置 typing 指示器（"正在输入"）。OSC 地址 <code class="ic">/chatbox/typing</code>。</div>
    <pre>curl -u ":$AUTH_PASSWORD" -X PUT http://localhost:8080/api/v1/typing \\
  -H 'Content-Type: application/json' \\
  -d '{{"typing":true}}'</pre>
  </div>

  <div class="ep">
    <div class="ep-head"><span class="m get">GET</span><span class="ep-path">/api/v1/typing</span></div>
    <div class="ep-desc">获取当前 typing 状态。</div>
    <pre>curl -u ":$AUTH_PASSWORD" http://localhost:8080/api/v1/typing</pre>
  </div>
</section>

<section id="config">
  <h2>环境变量配置</h2>
  <table>
    <tr><th>变量</th><th>默认值</th><th>说明</th></tr>
    <tr><td><code>VRC_HOST</code></td><td><code>127.0.0.1</code></td><td>VRChat 所在机器的 IP</td></tr>
    <tr><td><code>VRC_PORT</code></td><td><code>9000</code></td><td>VRChat 的 OSC 入站端口</td></tr>
    <tr><td><code>LISTEN_HOST</code></td><td><code>0.0.0.0</code></td><td>HTTP 服务监听地址</td></tr>
    <tr><td><code>LISTEN_PORT</code></td><td><code>8080</code></td><td>HTTP 服务监听端口</td></tr>
    <tr><td><code>AUTH_PASSWORD</code></td><td>（必填）</td><td>煎蛋认证密码</td></tr>
    <tr><td><code>LOG_LEVEL</code></td><td><code>INFO</code></td><td>日志级别（DEBUG/INFO/WARNING/ERROR）</td></tr>
  </table>
</section>

<section id="limits">
  <h2>限制</h2>
  <ul>
    <li><strong>text</strong> 最长 <code class="ic">{MAX_CHARS}</code> 字符、最多 <code class="ic">{MAX_LINES}</code> 行（VRChat 限制）。超出返回 <code class="ic">400 Bad Request</code>。</li>
    <li>OSC 是 UDP，服务端<strong>无法</strong>知道 VRChat 是否真的收到了 —— 只能保证本地 socket 把包送出去了。</li>
    <li>VRChat 端需要在 Action Menu → Osc → Enabled 启用 OSC。</li>
    <li>服务端消息历史最多保留 <code class="ic">{HISTORY_MAX}</code> 条，重启进程会清空。</li>
    <li>跨域请求如果带凭证（Authorization 头），浏览器要求显式 CORS 来源配置，不允许 <code class="ic">*</code> + credentials 同时存在。</li>
  </ul>
</section>

<section id="links">
  <h2>相关链接</h2>
  <div class="links">
    <a href="/">🏠 回到控制台</a>
    <a href="/swagger">🧪 Swagger UI（交互式 API 浏览器）</a>
    <a href="/redoc">📖 ReDoc（只读 OpenAPI 渲染）</a>
    <a href="/openapi.json">⚙️ OpenAPI JSON Schema</a>
  </div>
  <h3>外部参考</h3>
  <ul>
    <li><a href="https://docs.vrchat.com/docs/osc-overview" target="_blank" rel="noopener">VRChat OSC Overview</a></li>
    <li><a href="https://docs.vrchat.com/docs/osc-as-input-controller" target="_blank" rel="noopener">OSC as Input Controller</a></li>
    <li><a href="https://github.com/attwad/python-osc" target="_blank" rel="noopener">python-osc（底层 OSC 库）</a></li>
  </ul>
</section>

<footer>
  🍳 煎蛋认证 · 由 VRChat Chatbox Bridge 提供 · 本页面公开无需认证
</footer>

<script>
  // 点击代码块复制内容
  document.querySelectorAll('pre').forEach((pre) => {{
    pre.addEventListener('click', async () => {{
      try {{
        await navigator.clipboard.writeText(pre.innerText);
        const orig = pre.style.boxShadow;
        pre.style.boxShadow = '0 0 0 2px var(--accent)';
        setTimeout(() => {{ pre.style.boxShadow = orig; }}, 500);
      }} catch (e) {{
        // clipboard API 可能被禁用，忽略
      }}
    }});
  }});
</script>

</body>
</html>
"""


@app.get(
    "/docs",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def public_docs() -> str:
    """公开的 API 文档（无需煎蛋认证）。

    任何人（包括没拿到密码的人）都能查看这份文档，
    但实际调用 API 仍需要 Basic Auth。
    """
    return _render_docs_html()


if __name__ == "__main__":             # `uv run python app.py`: listens on LISTEN_HOST:LISTEN_PORT
    import uvicorn
    uvicorn.run(app, host=LISTEN_HOST, port=LISTEN_PORT, log_level=os.getenv("LOG_LEVEL", "INFO").lower())
