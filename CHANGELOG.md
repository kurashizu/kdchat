# Changelog

All notable changes to kdchat. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [1.8.3] - 2026-10-07

### Fixed
- Scrolling no longer cuts the top line (or its time label) under the header: only whole lines show at the top of a
  log, on every screen. Most visible on the square screen.
- With side screens on, the square (and 160 x 112) screen's log started far below the header (up to a third of the
  screen empty): every screen's log now starts right under its header.
- While a log scrolled, the second line of a new two-line message could show for a moment without its first one.

## [1.8.2] - 2026-10-07

### Fixed
- **Fill keyboard** left the game's keyboard empty: what the console was still doing in the chatbox (a live draft, a
  live update waiting for its turn, the typing indicator renewed every 5 s) reached the game after the fill. Now the
  live draft is dropped and the typing indicator switched off first, the fill waits for the chatbox's rate limit, and
  nothing follows it; the input box is emptied (the text is in the game's keyboard).
- The Live button's icon was orange on orange while Live is on.

### Added
- "Turn off the Klaude display?" can be answered once for good ("Don't ask again"); Settings > General > Hidden
  confirmations brings it back.

## [1.8.1] - 2026-10-07

### Fixed
- Every screen of the Klaude display looks the same: "Message time" and "Divider" now apply to the main screen and
  the side screens alike (the side screens always showed the time, the main screen only with the setting on). Saved
  settings switch "Message time" on once, so the main screen now matches what the side screens showed.
- Single layout: the side screens centre the translation like the main screen centres the message, and every screen
  shows the message's time with its rule above it.

## [1.8.0] - 2026-10-07

A new console and a much smaller app.

### Changed
- **The console is rebuilt** (SvelteKit + shadcn-svelte, SVG icons, light / dark / system). The main screen has what
  you use while chatting: the two outputs with their switches at the top; under the input "Send to" (one or both of
  the outputs that are on, remembered), **Translate** (shows the languages, opens the translation controls: on/off,
  up to two languages - picking one that is not downloaded starts its download -, typing language, chatbox, side
  screens), Live and Fill keyboard; the display card with the preview, the side screens (Auto / Open / Off and which
  language goes where), the layout, chime, picture, clear (it folds on phones). Translations are shown under each
  message; edit / send again / revert are in each message's menu. Settings are sorted into tabs: General, Display,
  Translation (with the language packs), Connection (VRChat, phone, password, server address), About. Confirmations
  are dialogs, no more browser pop-ups.
- A message being typed can still be sent elsewhere until it shows live (too long for the game chatbox? send it to the
  display only); editing a message and tapping another one switches when nothing was changed yet.
- **Pictures of every common format**: JPEG, PNG, GIF, WebP, AVIF, BMP, TIFF, SVG, ICO and HEIC / HEIF phone photos
  (decoded in the browser, upright by their EXIF orientation; the HEIC and TIFF decoders load only when needed).
- **Smaller download**: the translation engine runs on wasmtime instead of an embedded V8 (same output, starts in
  0.4 s); the server needs no image library (the console sends pictures as raw RGB; image files still work through the
  API with Pillow installed) and no psutil; the fallback window without WebView2 is a native message box. The
  `.exe` is about a third smaller.
- The typing indicator goes off by itself 15 s after the last word from the console (a closed page or a lost
  connection no longer leaves "typing" on), and at once when the page closes.

### Removed
- The old console (`ui/app.js`, `ui/i18n.js`); its URLs `/ui/...` are gone (the console loads from `/_app/...`).

## [1.7.0] - 2026-10-07

### Added
- **Korean on the Klaude display** (needs the avatar with the 1.7.0 menu icon; older avatars show □): the 2,350 common
  Hangul syllables of KS X 1001 and the compatibility jamo. Korean lines break at spaces, like English; the space between Korean words is a full-width blank (a
  line stays in one code mode and fits its memory). The font grew
  by 2,443 glyphs; the codes of every other character are unchanged.

## [1.6.1] - 2026-10-07

### Fixed
- The console's display preview was stretched with one side screen open (it assumed three screens): its box now
  follows the picture (main screen + the open side screens).

## [1.6.0] - 2026-10-07

Three screens, each with its own scroll. **Needs the Klaude avatar of 2026-10-07 (1.6.0 menu icon) or later** (new
display registers and 24 hardware shapes).

### Changed
- **Each screen scrolls on its own.** A translation that takes more lines than the original no longer pushes the main
  log up (no more empty rows under the last message): the main screen and each side screen keep their own log and
  scroll (registers `wing_ly` / `wing_ry` for the side screens' text, `wing_lsy` / `wing_rsy` for their shapes).
- **The side screens unfold one by one.** One translation language: only the right screen unfolds, and the device turns
  around the seam between the main screen and it. Going from two languages to one folds the left screen (its text is
  cleared); register `show` bit 1 = left, bit 2 = right.
- Every message on a side screen shows its time; a line in the message's colour runs from the left edge to the time
  label (also on the main screen when "Show time" is on, and before "edited").

### Added
- **Small font per language** (Translation > Small font, default English): messages and translations in a chosen
  Latin-script language use the display's 5x7 font, so more of a longer translation fits. The 5x7 font now has the
  common accented letters (á à â ä ã å é è ê ë í ì î ï ó ò ô ö õ ú ù û ü ñ ç ß ø æ œ Ä Ö Ü É); other marks are left
  out (ł -> l).

## [1.5.0] - 2026-10-07

Three screens, one chat. **Needs the Klaude avatar of 2026-10-07 01:40 or later** (the display's text memory grew).

### Changed
- **The side screens mirror the chat log.** With translation on, each side screen shows the whole log in its
  language, line by line in step with the main screen: they scroll together (the same scroll registers), every message
  takes the rows of its longest language on all three, highlight and colours match. The side screens' top bar shows
  their language instead of repeating the clock and date.
- The display's text memory is 1,530 bytes (was 630): each screen gets 8 line slots, so the main log no longer starts
  lower than the top bar when translation is on (1.4.0 cut scrolling messages off in the middle of the screen).
- Pictures are shown on the main screen only (the "Show on" choice is gone).
- Translations into Latin-script languages use plain quotes and dashes (curly ones are full-width glyphs on the display).

### Added
- Driver: moving text on side screens (`move=True` with `screen=`): it moves with the main screen's text registers;
  register `wing_mv`.

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
  is shown by the chatbox / display buttons next to it. The line count only appears once there is more than one line.
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
