# vrc-chatbox

Type into the VRChat chatbox from your phone or any browser. vrc-chatbox runs next to VRChat, shows a web console,
and sends what you type to VRChat over OSC (`/chatbox/input`, `/chatbox/typing`). It can also drive the pixel
display above the Klaude avatar's head (the "Klaude display").

<p>
  <img src="docs/screenshot-phone.png" alt="The console on a phone" width="260">
  <img src="docs/screenshot-phone-settings.png" alt="Settings on a phone" width="260">
</p>
<img src="docs/screenshot-desktop.png" alt="The console on a desktop browser" width="800">

- **Made for phones**: the input stays above the keyboard, big buttons, settings in a bottom sheet. Works on desktop too.
- **Live typing**: the text shows up in VRChat while you type (Enter finishes it), plus the "typing…" indicator.
- Edit or revert sent messages, resend from the history, put text into the game keyboard without sending it.
- **English and Simplified Chinese** (picked from your browser; switch with the language button).
- Optional password, a QR code to open the console on your phone, a REST API with docs.

## Contents

- [Download and run (Windows)](#download-and-run-windows)
- [Use it from your phone](#use-it-from-your-phone)
- [Settings](#settings)
- [The Klaude display](#the-klaude-display)
- [Run from source (Windows, macOS, Linux)](#run-from-source-windows-macos-linux)
- [Self-hosting on a Linux server (systemd)](#self-hosting-on-a-linux-server-systemd)
- [Configuration reference](#configuration-reference)
- [REST API](#rest-api)
- [Troubleshooting](#troubleshooting)
- [Development and tests](#development-and-tests)
- [License](#license)

## Download and run (Windows)

1. Download `vrc-chatbox-<version>-windows-x64.exe` from the
   [Releases page](https://github.com/kurashizu/vrc-chatbox/releases/latest). No installation is needed.
2. Double-click it. The app is not code-signed, so Windows SmartScreen may show **"Windows protected your PC"**:
   click **More info**, then **Run anyway**. (You can compare the file with the `.sha256` next to it on the
   Releases page.)
3. Windows Firewall asks whether vrc-chatbox may use the network: allow it on **Private networks** (needed for your
   phone; not needed if you only use it on this PC).
4. In VRChat, turn OSC on: **Action Menu → Options → OSC → Enabled**.
5. The console opens in its own window. Type, press Enter: the message appears in your VRChat chatbox.

Closing the window stops vrc-chatbox. The window uses Microsoft Edge WebView2, which is part of Windows 10 and 11; if
it is missing, the console opens in your default browser instead and a small "vrc-chatbox is running" window keeps it
going (close that one to stop). Starting the app a second time just opens the running console.

## Use it from your phone

1. Phone and PC must be on the same network (the same Wi-Fi / router).
2. In the app window, scan the QR code under **Use it on your phone** (also in **Settings ⚙︎**) with your phone's
   camera, or type the address shown there, for example `http://192.168.1.23:5555`.
3. Tip: add the page to your home screen; it then opens like an app.

Without a password, everyone on your network can use the console; the console says so and offers to set one
(**Settings → Password**). On a home network that is usually fine; on a shared network (dorm, event), set a password.

On the phone: **Enter sends** (the keyboard shows a Send key). To type several lines, turn **Settings → Enter sends**
off; Enter then makes a new line and the round ➤ button sends.

## Settings

Everything is in **Settings ⚙︎** (top right):

| Section | What |
|---|---|
| Language | English / 中文. The first visit follows the browser language; your choice is remembered (per browser). |
| Sending | Live typing, typing indicator, sound on send, Enter sends. Remembered per browser. |
| Use it on your phone | The LAN address(es) of this PC and a QR code. |
| VRChat connection (OSC) | Where messages go: `127.0.0.1` port `9000` = VRChat on the same PC (the default). If VRChat runs on another PC, enter that PC's LAN IP. Applies at once. **Reset to default** goes back to the default (or the server's `VRC_HOST` / `VRC_PORT`). |
| Klaude display | Options of the avatar display (only when it is turned on, 🖥 at the top). |
| Password | Set, change or remove the password (changing or removing needs the current one). Stored as a salted hash. With a password, browsers ask for it (any user name); the app's own window does not. |
| Server address | Listen address and HTTP port (default `0.0.0.0:5555`). `127.0.0.1` = this PC only. Applies after a restart. |

The two buttons at the top turn the outputs on and off: 🎮 the game chatbox, 🖥 the Klaude display. Both can be on;
when both are on, the 🎮 / 🖥 buttons next to the input choose where the next message goes.

Server-side settings are saved in `settings.json` (Windows app: `%APPDATA%\vrc-chatbox\`; from source: next to
`app.py`), the outputs and display options in `state.json` next to it.

## The Klaude display

The Klaude avatar has a pixel display above its head that is driven through OSC avatar parameters, page by page. This
output **only does something with the Klaude avatar**; with any other avatar, leave it off (the game chatbox is not
affected).

- A header line with the time zone, time and date, "typing.." while you type.
- A chat log: neighbouring messages alternate between two colours, the newest is highlighted; optional dividers and
  message times. New lines scroll in; only the changed pages are sent.
- Live typing updates the message in place. Six screen sizes, a size slider, a "single message" layout that scrolls
  long text by itself.
- Pictures: paste, drop or pick an image; it is cropped and enhanced. Two qualities: high (~70 s to transfer) and low
  (2×2 pixel dots, ~20 s).
- `kd_display/` is a copy of the display library on the avatar and **must match the uploaded avatar version**
  (otherwise the screen stays black or shows garbage). When both change, upload the avatar first, then update this.
- One frame is sent about every 0.3 s; people who join later get the full picture from the refresh cycle.

## Run from source (Windows, macOS, Linux)

Needs [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for the project by itself).

```bash
git clone https://github.com/kurashizu/vrc-chatbox.git
cd vrc-chatbox
uv sync
uv run python app.py                 # http://127.0.0.1:5555/ (and your LAN address, see the log)
```

Options: `uv run python app.py --port 5600 --host 127.0.0.1`. The desktop window from source:
`uv sync --group build && uv run python desktop.py` (Windows; elsewhere it falls back to the browser).

## Self-hosting on a Linux server (systemd)

For running vrc-chatbox on an always-on machine in your network (VRChat on another PC). Assumes the repository is
cloned to `~/vrc-chatbox` and the service runs as your user.

```bash
# 1. code and dependencies
git clone https://github.com/kurashizu/vrc-chatbox.git ~/vrc-chatbox
cd ~/vrc-chatbox
uv sync

# 2. configuration: at least AUTH_PASSWORD (a server should have one) and VRC_HOST (the VRChat PC)
cp .env.example .env && chmod 600 .env && $EDITOR .env

# 3. systemd service (replace USER in the template with your user name)
sed "s/USER/$USER/g" deploy/vrc-chatbox.service | sudo tee /etc/systemd/system/vrc-chatbox.service
sudo systemctl daemon-reload
sudo systemctl enable --now vrc-chatbox

# 4. check
systemctl status vrc-chatbox
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5555/api/v1/health   # 401 = running, password required
curl -s -u ":$(grep ^AUTH_PASSWORD .env | cut -d= -f2-)" http://localhost:5555/api/v1/health
```

- The template's `ExecStart` finds `uv` through `/usr/bin/env`. If systemd's PATH does not contain uv (e.g. it is in
  `~/.local/bin`), put uv's absolute path there (`which uv`).
- The log goes to `~/vrc-chatbox/server.log`: `tail -f ~/vrc-chatbox/server.log`.
- Settings changed in the console are stored in `~/vrc-chatbox/settings.json` and take precedence over `.env`.

### Updating

```bash
cd ~/vrc-chatbox
tar czf ~/vrc-chatbox-backup-$(date +%Y%m%d-%H%M).tgz app.py kd_chat.py kd_display ui .env state.json settings.json   # optional
git pull
uv sync
sudo systemctl restart vrc-chatbox
```

- Browsers may cache the old page: reload it after an update.
- Before updating `kd_display/`, make sure the avatar with the matching version is uploaded (see above).

### Security

- HTTP Basic sends the password readable to anyone on the same network who listens. Use it on trusted networks; for
  access from the internet put vrc-chatbox behind an HTTPS reverse proxy (Caddy, nginx, …) or a VPN such as
  Tailscale. Do not expose the port to the internet directly.
- Requests that change something are refused when they come from another web site (another origin), so a page you
  visit cannot post to your console. Other front ends can be allowed with `ALLOWED_ORIGINS`. Behind a reverse proxy,
  keep the `Host` header (or send `X-Forwarded-Host`).
- `/docs` is public; the console and the API need the password when one is set.

## Configuration reference

Every setting comes from (first match wins): **the settings file** (changed in the console) > **the environment** (or a
`.env` file: `KEY=VALUE` lines next to `app.py`, or in the data folder of the Windows app) > **the default**.

| Variable | Default | Meaning |
|---|---|---|
| `VRC_HOST` | `127.0.0.1` | The PC that runs VRChat (IPv4 address or host name). Console: Settings → VRChat connection |
| `VRC_PORT` | `9000` | VRChat's OSC input port (UDP) |
| `LISTEN_HOST` | `0.0.0.0` | HTTP bind address (`0.0.0.0` = all networks, `127.0.0.1` = this machine only) |
| `LISTEN_PORT` | `5555` | HTTP port |
| `AUTH_PASSWORD` | (none) | Password for the console and the API. None = no login. A password set or removed in the console overrides it |
| `ALLOWED_ORIGINS` | (none) | Comma-separated origins (e.g. `https://my-site.example`) that may call the API from their web pages |
| `VCB_DATA_DIR` | see above | Folder for `settings.json`, `state.json`, `.env` (and the Windows app's log) |
| `SETTINGS_FILE` / `STATE_FILE` | in the data folder | Paths of the two files |
| `KD_DRY` | (empty) | `1`: the Klaude display only encodes, sends nothing (testing) |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

`uv run uvicorn app:app --host 0.0.0.0 --port 5555` works as well; then uvicorn's options decide the address.

### VRChat side

1. Turn OSC on: Action Menu → Options → OSC → Enabled.
2. VRChat receives OSC on UDP port 9000. If vrc-chatbox runs on another machine, allow UDP 9000 from that machine to
   the VRChat PC and set the OSC target to the VRChat PC's LAN IP.
3. OSC is UDP: vrc-chatbox can only make sure the packets left; it cannot know whether VRChat received them.
   `/api/v1/health` only checks that the target host resolves.

## REST API

Everything is under `/api/v1`. With a password: HTTP Basic auth (any user name). Field details: `/docs` (overview),
`/swagger` (Swagger UI), `/openapi.json`.

| Method | Path | What |
|---|---|---|
| `GET` | `/info`, `/config`, `/health` | About / runtime configuration / health check (with `version`) |
| `POST` | `/messages` | Send a message; `final=false` = still being typed (shown live; later PATCH it or DELETE it) |
| `PATCH` | `/messages/{id}` | Update, finish or edit a message (`cancel=true` restores the text) |
| `DELETE` | `/messages/{id}` | Drop a message that is still being typed |
| `POST` | `/messages/{id}/revert` | Revert a message (Klaude display) |
| `GET` / `DELETE` | `/messages` | History / clear the history |
| `GET` / `PUT` | `/typing` | The typing indicator |
| `GET` / `PUT` | `/outputs` | Outputs on / off: `{"chatbox": true, "kd": false}` |
| `GET` / `PUT` / `DELETE` | `/osc` | The OSC target: `{"host": "192.168.1.20", "port": 9000}`; PUT applies and saves it, DELETE resets it |
| `GET` / `PUT` / `DELETE` | `/settings/server` | Listen address and port (apply after a restart) |
| `GET` / `PUT` | `/settings/password` | Password on? Set / change / remove: `{"current_password": "…", "new_password": "…" or null}` |
| `GET` | `/settings` | All of the above at once, plus the version |
| `GET` | `/network`, `/network/qr.svg?url=…` | LAN URLs of the console / a QR code (SVG, made locally) |
| `GET` / `PUT` | `/kd/settings` | Klaude display options |
| `POST` | `/kd/chime`, `/kd/clear` | Display: chime / clear |
| `POST` / `DELETE` | `/kd/image` | Display: show a picture (the body is the image file) / close it |
| `GET` | `/kd/status`, `/kd/preview.png` | Display: sending status / preview |

Examples:

```bash
curl -X POST http://localhost:5555/api/v1/messages \
  -H 'Content-Type: application/json' -d '{"text":"Hello VRChat!","sfx":true}'
curl -X PUT http://localhost:5555/api/v1/typing -H 'Content-Type: application/json' -d '{"typing":true}'
curl -X PUT http://localhost:5555/api/v1/osc -H 'Content-Type: application/json' -d '{"host":"192.168.1.20","port":9000}'
# with a password:
curl -u ":$PASSWORD" http://localhost:5555/api/v1/health
```

Limits: the game chatbox takes at most 144 characters and 9 lines (longer = `400`); when only the Klaude display gets a
message, 400 characters and 20 lines. VRChat rate-limits the chatbox: live typing updates it at most every 1.5 s, the
final message is sent at once.

## Troubleshooting

| Problem | What to do |
|---|---|
| Nothing appears in VRChat | OSC on in VRChat (Action Menu → Options → OSC → Enabled)? Settings → VRChat connection: `127.0.0.1` / `9000` when VRChat runs on the same PC, else the VRChat PC's LAN IP. Another program using port 9000 (e.g. an OSC router)? Then send to that program's port. |
| The phone cannot open the page | Same Wi-Fi? Guest Wi-Fi often blocks devices from each other. Allow vrc-chatbox in Windows Firewall (Settings → Privacy & security → Windows Security → Firewall → Allow an app; tick **Private**). Is your network set to **Private** in Windows? Server address not `127.0.0.1`? |
| "Port 5555 is already in use" | vrc-chatbox is probably already running (another window), or another program uses the port: close it, or start with `--port 5600` / set another port. |
| SmartScreen blocks the .exe | **More info → Run anyway** (the app is not code-signed). |
| The app window stays white / does not open | WebView2 missing or broken: install the "Evergreen" WebView2 Runtime from Microsoft, or just use the browser window vrc-chatbox opens instead. |
| Forgot the password | Stop vrc-chatbox, delete `settings.json` (Windows: `%APPDATA%\vrc-chatbox\settings.json`; this resets all server settings), start again. If the password comes from `AUTH_PASSWORD`, change it there. |
| Where is the log? | Windows app: `%APPDATA%\vrc-chatbox\vrc-chatbox.log`. From source / systemd: the terminal / `server.log`. |
| "Text too long" | The game chatbox allows 144 characters and 9 lines. |

## Development and tests

```bash
uv sync                       # includes the dev tools (pytest, httpx)
uv run pytest                 # config, auth, OSC target (real UDP packets on 127.0.0.1), API, desktop launcher
node tests/js_check.mjs       # UI: JavaScript syntax, en/zh strings complete (plain node, nothing to install)
```

- `app.py` server and API · `vcb_config.py` settings / precedence / passwords · `netinfo.py` LAN addresses ·
  `desktop.py` the Windows app · `kd_chat.py` + `kd_display/` the Klaude display · `ui/` the console (plain
  HTML/CSS/JS, no build step; strings in `ui/i18n.js`) · `version.py` the version (single source).
- The UI keeps all text in `ui/i18n.js` (one dictionary per language). Add a key to both `en` and `zh`; the JS check
  fails on missing keys.
- Windows build locally: `uv sync --group build` then `uv run pyinstaller packaging/vrc-chatbox.spec --noconfirm --clean`
  → `dist/vrc-chatbox.exe`. The icon is made by `uv run python packaging/make_icon.py`.
- CI (`.github/workflows/ci.yml`) runs the tests on Ubuntu and Windows for every push and pull request.

### Releasing

1. Set the version in `version.py` **and** `pyproject.toml` (a test checks they match), run `uv lock`, add a section
   `## [x.y.z] - date` to `CHANGELOG.md`, commit.
2. Tag and push: `git tag vx.y.z && git push origin main vx.y.z`.
3. `.github/workflows/release.yml` tests, checks the tag against `version.py`, builds the `.exe` on Windows, smoke-tests
   it and publishes a GitHub Release with the `.exe`, its SHA-256 and the changelog section. (Run the workflow by hand
   from the Actions tab to get a test build as an artifact without a release.)

## License

The code is released under the [MIT License](LICENSE). Third-party components and their licenses:
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

The Klaude display's font atlas `kd_display/generated/kd_font.png` comes from
[Fusion Pixel Font](https://github.com/TakWolf/fusion-pixel-font), released under the SIL Open Font License 1.1 (full
text in `kd_display/generated/OFL.txt`).

References: [VRChat OSC Overview](https://docs.vrchat.com/docs/osc-overview) ·
[OSC as Input Controller (chatbox)](https://docs.vrchat.com/docs/osc-as-input-controller)
