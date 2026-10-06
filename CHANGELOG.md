# Changelog

All notable changes to kdchat. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [1.4.0] - 2026-10-07

Translation, and the Klaude display's two side screens. **Needs the Klaude avatar of 2026-10-07 or later** (older
avatars and kdchat versions do not match: the display's command ids and memory layout changed).

### Added
- **Translation of your messages, on your computer.** Pick up to two languages; every message you send is translated
  locally (Mozilla's Firefox Translations models on the CPU, about 0.1 s per message, nothing goes online). The game
  chatbox gets the original and as many translations as fit (Settings → Translation: 0, 1 or 2); the Klaude display
  shows them on its side screens. The language you type is detected (or set it). 54 languages; each is downloaded
  on request (about 85 MB, from this repository's release `models-2026.10`, checked with SHA-256) and stays on your
  computer. English needs no download.
- **Side screens on the Klaude display.** Two screens the size of the main one unfold from behind it like a
  satellite's solar panels. Display setting "Side screens": auto (open while they show something), open, off. At the
  left / right positions the display moves outward while they open, never into the avatar.
- **Up to three pictures at once**: Image → "Show on" main / left / right. With pictures on side screens all of them
  use the low resolution (they share the graphics memory) and one palette picked from all of them.
- The display font covers Japanese (JIS X 0208: kana, both kanji levels, ー) and traditional Chinese (Big5 level 1).
- Driver (`kd_display`, docs/KD_DRIVER.md): `d.set(wings=True)`, `screen="left" / "right"` for text, shapes and
  sprites, `d.wing_picture(side, pixels)`, `d.set(wing_pages=(l, r))`.
- API: `GET/PUT /api/v1/translate`, `POST/DELETE /api/v1/translate/models/{code}`, `POST /api/v1/translate/try`;
  `POST /api/v1/kd/image?screen=`, `DELETE /api/v1/kd/image?screen=`; messages carry `source_lang` and `translations`.

### Changed
- Display command frames are allocated from 255 down (clear graphics 254, chime 255); the memory has no hole page
  any more (209 pages) and can grow later.
- Mixed kana / kanji text is encoded with fewer run headers (longer Japanese fits).

## [1.3.0] - 2026-10-06

### Changed
- **Renamed from vrc-chatbox to kdchat**: the repository (github.com/kurashizu/kdchat), the app, the Windows exe
  (`kdchat-<version>-windows-x64.exe`), the systemd unit (`deploy/kdchat.service`). Nothing to do when updating: the
  Windows app moves `%APPDATA%\vrc-chatbox` to `%APPDATA%\kdchat` on the first start, the console keeps its browser
  settings, and `VCB_DATA_DIR` still works as an alias of `KDCHAT_DATA_DIR`. You may have to log in once again.
- A shorter, user-facing README; the advanced topics moved to `docs/ADVANCED.md`.

### Added
- `docs/KD_DRIVER.md`: the complete Klaude display driver API (text, graphics, shapes, sprites, screen state,
  transitions, sync, the wire protocol and memory map) for building your own programs on the display.
- `examples/hello_kd.py`: a minimal program on the driver (`--dry` renders `preview.png` without VRChat).
- Links to the Klaude avatar on VRChat.

## [1.2.0] - 2026-10-05

The Klaude Display now draws its lines with the display's own hardware shapes instead of pixels.

### Changed
- The rule under the header, the dividers between messages and a new blinking caret after the text you are typing are
  hardware shapes: the avatar draws them itself. With no picture on the screen no graphics data is sent at all, so the
  screen is complete sooner for people who just joined, and the dividers scroll together with the text in the same
  frame.
- The bundled display library knows the 16 hardware shapes (lines, boxes, rounded boxes, circles / ellipses, arcs,
  pies, triangles, polygons / stars, curves; fill patterns, XOR, animations) and the web preview draws them.

### Compatibility
- Works with older versions of the Klaude avatar too (they ignore the shape frames: no rule / dividers there).

## [1.1.0] - 2026-10-05

A cleaner console: the same features, better organised, on computers and phones.

### Fixed
- The send button no longer covers the character / line counter (it did with both outputs on, e.g. "Send to game").
- Nothing overlaps or runs off the screen at any width, in English and Chinese: the action row wraps instead.
- The display preview keeps its shape on phones before the first picture arrives.

### Changed
- Composer: the input, then one line with the status and the counter, then the quick toggles (where to send, Live,
  Fill keyboard) on the left and Cancel + Send on the right. The send button just says **Send**; where the message goes
  is shown by the 🎮 / 🖥 buttons next to it. The line count only appears once there is more than one line.
- Wide screens: the display and **Use it on your phone** sit in a side column next to the input and the history; the
  display stays in view while you scroll.
- **Recent messages**: **Clear** is now in the list header (was in Settings); the "Game / Display" tag only appears
  when the list has messages for different outputs; quieter buttons.
- Settings: language only here (the extra language button at the top is gone); the VRChat connection comes right after
  the sending options; the last section is **About** (version, API docs, GitHub). The page footer that repeated it is gone.
- Proper headings for screen readers.

## [1.0.0] - 2026-10-05

The first release for everyone: a Windows app, an optional password and settings in the console.

### Added
- **Windows app**: a single `.exe` (no installation). It starts the server and opens the console in its own window
  (Edge WebView2; falls back to the browser). Closing the window stops it. Built and released by GitHub Actions.
- **Settings** in the console (a bottom sheet on phones, a side panel on desktop): language, sending options, the
  VRChat OSC target (host / port, applies at once, reset to default), password, server address, version.
- **Use it on your phone**: the console shows this PC's LAN address(es) and a QR code (made locally), and a notice
  when there is no password and the console is reachable from the network.
- **English and Simplified Chinese** UI, picked from the browser language, switchable and remembered.
- REST API: `/api/v1/osc`, `/api/v1/settings`, `/api/v1/settings/server`, `/api/v1/settings/password`,
  `/api/v1/network`, `/api/v1/network/qr.svg`; `version` in `/health` and `/config`.
- Settings file (`settings.json`): settings file > environment / `.env` > defaults.
- Tests (pytest, a JS check) and CI on Ubuntu and Windows.
- `CHANGELOG.md`, `THIRD_PARTY_NOTICES.md`, an app icon.

### Changed
- **The password is optional** and off by default. It is on when `AUTH_PASSWORD` is set (as before) or a password
  was set in the console (stored as a salted PBKDF2 hash). Existing setups with `AUTH_PASSWORD` stay protected.
- Defaults: OSC target `127.0.0.1:9000`, web server `0.0.0.0:5555` (was port 8080 when `LISTEN_PORT` was not set).
- A mobile-first console: the input is pinned above the keyboard, 44 px tap targets, one clear send button, sending /
  live / typing status, rarely used options moved into Settings.
- Requests that change something are refused when they come from another web site; cross-origin API use needs
  `ALLOWED_ORIGINS` (before: CORS allowed every origin).
- All documentation, server messages and the `/docs` page are in English.
- Clear startup log (version, URLs, OSC target, login), a clear message when the port is in use, no stack traces in
  API responses, OSC send errors answered with `502` and a reason. The HTTP access log is off.
- The Klaude display always uses the same OSC target as the chatbox (`KD_OSC_HOST` is not used).

## [0.1.0] - 2026-10-05

- First version: web console and REST API for the VRChat chatbox over OSC, live typing, edit / revert, the Klaude
  display output.
