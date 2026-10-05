# vrc-chatbox

用手机或电脑的浏览器给 VRChat 发聊天框消息。服务把 HTTP 请求转成 OSC 消息，发到 VRChat 的聊天框（`/chatbox/input`）。
它还可以同时驱动 Klaude avatar 头顶的像素显示屏（kd 输出，见后文）。

- 网页控制台：适配手机，支持边打边发（打字时实时显示，Enter 定稿）、编辑和撤回已发的消息、“正在输入”提示、快捷消息和历史记录。
- REST API（`/api/v1`），带 OpenAPI 文档。
- 所有页面和 API 都要求 HTTP Basic 认证（用户名任意，密码见配置）。

## 目录

| 路径 | 说明 |
|---|---|
| `app.py` | 服务本体（FastAPI）：API、认证、聊天框输出、API 文档页 `/docs` |
| `ui/` | 网页控制台（`index.html`、`app.css`、`app.js`） |
| `kd_chat.py` | Klaude 显示屏输出：聊天记录排版、图片、标题栏 |
| `kd_display/` | 显示屏驱动库（纯标准库，图片用 Pillow），必须和已上传的 avatar 版本一致 |
| `deploy/vrc-chatbox.service` | systemd 服务模板 |
| `.env.example` | 配置模板 |

## 快速开始

需要 Python 3.12 和 [uv](https://docs.astral.sh/uv/)。

```bash
git clone https://github.com/kurashizu/vrc-chatbox.git
cd vrc-chatbox
uv sync
cp .env.example .env
chmod 600 .env
$EDITOR .env                      # 至少改 AUTH_PASSWORD 和 VRC_HOST
uv run python app.py              # 监听 LISTEN_HOST:LISTEN_PORT（默认 0.0.0.0:5555）
```

然后在浏览器里打开 `http://<这台机器的 IP>:5555/`，弹出登录框后用户名随便填，密码填 `AUTH_PASSWORD`。

- API 文档（不需要登录）：`/docs`
- Swagger UI：`/swagger`

## 配置

配置写在 `app.py` 同目录的 `.env` 里（`KEY=VALUE`，每行一个），也可以直接用环境变量，环境变量优先。
`.env` 已被 git 忽略，不会进仓库。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `AUTH_PASSWORD` | （必填） | 网页和 API 的密码。没设置时服务拒绝启动 |
| `VRC_HOST` | `127.0.0.1` | 运行 VRChat 的机器的 IP |
| `VRC_PORT` | `9000` | VRChat 的 OSC 输入端口（UDP） |
| `LISTEN_HOST` | `0.0.0.0` | HTTP 监听地址（`python app.py` 启动时生效） |
| `LISTEN_PORT` | `8080` | HTTP 监听端口（`.env.example` 里设成 5555） |
| `KD_OSC_HOST` | 同 `VRC_HOST` | Klaude 显示屏的 OSC 目标 |
| `KD_DRY` | 空 | 设成 `1`：显示屏只编码，不发送（调试用） |
| `STATE_FILE` | `./state.json` | 输出开关和显示屏设置的保存位置 |
| `LOG_LEVEL` | `INFO` | 日志级别 |

也可以用 uvicorn 直接启动，这时监听地址由命令行参数决定：
`uv run uvicorn app:app --host 0.0.0.0 --port 5555`。

### VRChat 这边

1. 打开 OSC：Action Menu → Options → OSC → Enabled。
2. VRChat 在 UDP 9000 端口接收 OSC。如果本服务和 VRChat 不在同一台机器上，要放行这台机器到 VRChat 机器的 UDP 9000，
   再把 `VRC_HOST` 设成 VRChat 机器的局域网 IP。
3. OSC 是 UDP，服务只能保证包发出去了，没法知道 VRChat 有没有收到。`/api/v1/health` 只检查 `VRC_HOST` 能不能解析。

## 部署（Linux + systemd）

下面假设仓库克隆到 `~/vrc-chatbox`，服务用当前用户运行。

```bash
# 1. 代码和依赖
git clone https://github.com/kurashizu/vrc-chatbox.git ~/vrc-chatbox
cd ~/vrc-chatbox
uv sync

# 2. 配置
cp .env.example .env && chmod 600 .env && $EDITOR .env

# 3. systemd 服务（把模板里的 USER 换成你的用户名）
sed "s/USER/$USER/g" deploy/vrc-chatbox.service | sudo tee /etc/systemd/system/vrc-chatbox.service
sudo systemctl daemon-reload
sudo systemctl enable --now vrc-chatbox

# 4. 检查
systemctl status vrc-chatbox
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5555/api/v1/health   # 401 = 服务在线，认证生效
curl -s -u ":$(grep ^AUTH_PASSWORD .env | cut -d= -f2-)" http://localhost:5555/api/v1/health
```

- 模板里的 `ExecStart` 通过 `/usr/bin/env` 找 `uv`。如果 systemd 的 PATH 里没有 uv（比如装在 `~/.local/bin`），把它换成 uv 的绝对路径（`which uv`）。
- 日志写到 `~/vrc-chatbox/server.log`，看日志用 `tail -f ~/vrc-chatbox/server.log`。

### 更新

```bash
cd ~/vrc-chatbox
tar czf ~/vrc-chatbox-backup-$(date +%Y%m%d-%H%M).tgz app.py kd_chat.py kd_display ui state.json   # 可选：先备份
git pull
uv sync
sudo systemctl restart vrc-chatbox
```

- 浏览器可能缓存了旧的 `ui/app.js`，更新后刷新一下页面。
- 更新 `kd_display/` 前，先确认 avatar 已经上传了对应的版本，见下文“Klaude 显示屏”。

### 安全

- 认证是 HTTP Basic，密码在明文 HTTP 里可以被同一网络里的人看到。只在可信的局域网里用；要从外网访问，请放在 HTTPS 反向代理
  （Caddy、nginx 等）或 Tailscale 这类 VPN 后面，不要直接把端口暴露到公网。
- 每个人都能打开 `/docs`，但所有 API 和控制台都要密码。

## API 概览

所有接口都在 `/api/v1` 下，需要 Basic 认证。完整的字段说明见 `/docs` 或 `/swagger`。

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/info`、`/config`、`/health` | 元信息 / 运行时配置 / 健康检查 |
| `POST` | `/messages` | 发一条消息；`final=false` 表示还在打（实时显示，之后用 PATCH 更新或定稿） |
| `PATCH` | `/messages/{id}` | 更新、定稿或编辑一条消息（`cancel=true` 恢复原文） |
| `DELETE` | `/messages/{id}` | 放弃一条还没定稿的消息 |
| `POST` | `/messages/{id}/revert` | 撤回消息 |
| `GET` / `DELETE` | `/messages` | 历史记录 / 清空历史 |
| `GET` / `PUT` | `/typing` | “正在输入”提示 |
| `GET` / `PUT` | `/outputs` | 输出开关：`{"chatbox": true, "kd": false}` |
| `GET` / `PUT` | `/kd/settings` | 显示屏选项 |
| `POST` | `/kd/chime`、`/kd/clear` | 显示屏：提示音 / 清空 |
| `POST` / `DELETE` | `/kd/image` | 显示屏：显示 / 关闭图片 |
| `GET` | `/kd/status`、`/kd/preview.png` | 显示屏：同步状态 / 当前画面预览 |

例子：

```bash
export AUTH_PASSWORD=...          # 和 .env 里的一样
curl -u ":$AUTH_PASSWORD" -X POST http://localhost:5555/api/v1/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hello VRChat!","immediate":true,"sfx":true}'
curl -u ":$AUTH_PASSWORD" -X PUT http://localhost:5555/api/v1/typing \
  -H 'Content-Type: application/json' -d '{"typing":true}'
```

## 输出：游戏聊天框 + Klaude 显示屏

控制台顶部有两个开关：🎮 游戏聊天框、🖥 Klaude 显示屏，可以同时打开。消息和“正在输入”会发到所有打开的输出。

- 设置保存在 `state.json`，重启后保持。
- 长度限制：游戏聊天框打开时是 144 字 / 9 行（VRChat 的限制）；只用显示屏时可以到 400 字 / 20 行。
- 游戏聊天框有频率限制：边打边发时最多每 1.5 秒更新一次，定稿立即发出。

### Klaude 显示屏（kd）

Klaude avatar 头顶有一块像素显示屏，靠 OSC avatar 参数逐页传输画面。这个输出**只对 Klaude avatar 有用**，
用别的 avatar 时关掉它就行，游戏聊天框不受影响。

- **标题栏**：一行 3×5 小字。左边是时区和时间，右边是日期，正在输入时显示三个点。
- **聊天记录**：
  - 相邻的消息交替用两种颜色，最新一条用高亮色；
  - 可以打开分隔线，或者在消息上方显示时区和时间；
  - 新消息一行一行滚上来，只发改动的那几页。
- **边打边发**：显示屏上原地更新这一条，不会刷屏。
- **屏幕尺寸**：6 种可选（`screen` 设置项），大小可以在网页上调。
- **单条大字**：太长时由显示屏自己按像素跑马灯，不占带宽。
- **图片**：
  - 可以直接粘贴、拖进页面，或者点“发图片”；
  - 自动裁切和增强；
  - 清晰度两档：高（约 70 秒传完）和低（2×2 像素点，约 20 秒）。

注意：
- `kd_display/` 是 avatar 那边显示屏库的拷贝，**必须和已上传的 avatar 版本一致**，不一致时屏幕会全黑或乱码。
  avatar 和这里同时有改动时，先上传 avatar，再更新服务。
- 显示屏同一时间只发一帧（每 0.3 秒左右一帧），后加入房间的人会在刷新循环里补齐画面。

## 限制

- 聊天框文本最多 144 字符、9 行，超出会被拒绝（`400`）。
- OSC 走 UDP，服务端无法确认 VRChat 是否收到。

## 参考

- [VRChat OSC Overview](https://docs.vrchat.com/docs/osc-overview)
- [OSC as Input Controller（聊天框部分）](https://docs.vrchat.com/docs/osc-as-input-controller)

## 字体

显示屏的字体图集 `kd_display/generated/kd_font.png` 来自 [Fusion Pixel Font](https://github.com/TakWolf/fusion-pixel-font)，
按 SIL Open Font License 1.1 发布，许可证全文见 `kd_display/generated/OFL.txt`。
