# Changelog

All notable changes to vrc-chatbox. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

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
