"""kdchat desktop app (the Windows .exe): starts the server and opens the console in its own window.

- The window uses the system's Edge WebView2 runtime (pywebview); closing it stops the server. Without WebView2 (or
  pywebview) the console opens in the default browser and a small message box keeps the server running: its OK
  button stops it (no other GUI toolkit is bundled).
- The app's own window gets in without the password (a per-run session token), browsers on your phone still need it.
- Already running (the port answers like kdchat)? Then the running console is opened instead.
- No console window in the .exe: the log goes to kdchat.log in the data folder (%APPDATA%\\kdchat).

Command line: kdchat.exe [--no-window] [--port N] [--host H]
  --no-window   server only (no window, logs to the console): for servers, scripts and the release smoke test
"""
from __future__ import annotations

import argparse
import logging
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser


def _setup_output() -> str:
    """windowed .exe: stdout / stderr are None; send them to a log file (uvicorn writes there)"""
    import kdchat_config as cfg
    path = os.path.join(cfg.data_dir(), "kdchat.log")
    if sys.stdout is None or sys.stderr is None:
        try:
            if os.path.exists(path) and os.path.getsize(path) > 2_000_000:
                os.replace(path, path + ".1")
            f = open(path, "a", encoding="utf-8", buffering=1)
        except OSError:
            f = open(os.devnull, "w")
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f
    return path


def _message(title: str, text: str) -> None:
    """an error the user sees even without a console"""
    print(f"{title}: {text}", file=sys.stderr)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
            return
        except Exception:      # noqa: BLE001
            pass


def _already_running(port: int) -> bool:
    """does 127.0.0.1:port answer like kdchat"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=2) as r:
            return r.status == 200 and b"vrc_host" in r.read()
    except urllib.error.HTTPError as e:                 # 401: has a password
        return e.code == 401 and "kdchat" in (e.headers.get("WWW-Authenticate") or "")
    except Exception:          # noqa: BLE001
        return False


def _webview2_installed() -> bool:
    if os.name != "nt":
        return True
    try:
        import winreg
        guid = r"{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
        for root, key in ((winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}"),
                          (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}"),
                          (winreg.HKEY_CURRENT_USER, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}")):
            try:
                with winreg.OpenKey(root, key) as k:
                    v, _ = winreg.QueryValueEx(k, "pv")
                    if v and v != "0.0.0.0":
                        return True
            except OSError:
                continue
    except Exception:          # noqa: BLE001
        return True                                      # unknown: let pywebview try
    return False


def _open_window(url: str, title: str) -> bool:
    """the console in a WebView2 window; blocks until it is closed. False if that is not possible."""
    if not _webview2_installed():
        logging.getLogger("kdchat").warning("Edge WebView2 is not installed: opening the browser instead")
        return False
    try:
        import webview
    except Exception as e:     # noqa: BLE001
        logging.getLogger("kdchat").warning("no pywebview (%s): opening the browser instead", e)
        return False
    try:
        webview.create_window(title, url, width=1180, height=840, min_size=(360, 560), background_color="#0c0a09")
        webview.start(gui="edgechromium" if os.name == "nt" else None, private_mode=False,
                      storage_path=os.path.join(_data_dir(), "webview"))
        return True
    except Exception as e:     # noqa: BLE001
        logging.getLogger("kdchat").warning("the app window failed (%s): opening the browser instead", e)
        return False


def _data_dir() -> str:
    import kdchat_config as cfg
    return cfg.data_dir()


def _fallback_window(url: str, lan: list[str]) -> None:
    """no WebView2: the default browser + a message box (Windows) whose OK stops the server; elsewhere: until Ctrl+C"""
    webbrowser.open(url)
    try:
        from version import __version__
    except Exception:          # noqa: BLE001
        __version__ = ""
    if os.name == "nt":
        import ctypes
        text = (f"kdchat {__version__} is running.\n\nConsole: {url.split('?')[0]}\n"
                + "".join(f"On your phone: {u}\n" for u in lan) + "\nPress OK to stop kdchat.")
        ctypes.windll.user32.MessageBoxW(None, text, "kdchat", 0x40)      # (MB_ICONINFORMATION; blocks)
        return
    print(f"kdchat {__version__} is running: {url.split('?')[0]} (Ctrl+C stops it)")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kdchat")
    p.add_argument("--no-window", action="store_true", help="server only, no window")
    p.add_argument("--host", help="bind address for this run")
    p.add_argument("--port", type=int, help="HTTP port for this run")
    p.add_argument("--version", action="store_true")
    a = p.parse_args(argv)
    if a.version:
        from version import __version__
        print(__version__)
        return 0
    log_path = _setup_output()

    import app as A                                       # (after the output is set up: it configures logging)
    if a.no_window:
        return A.main([*(["--host", a.host] if a.host else []), *(["--port", str(a.port)] if a.port else [])])

    import uvicorn
    host = a.host or A.SETTINGS.value("listen_host")
    port = a.port or A.SETTINGS.value("listen_port")
    problem = A.port_free(host, port)
    if problem:
        if _already_running(port):                       # a second start: show the running one
            webbrowser.open(f"http://127.0.0.1:{port}/")
            return 0
        _message("kdchat", problem)
        return 2

    token = secrets.token_urlsafe(24)
    A.SESSION_TOKEN = token
    A.RUNTIME.update(listen_host=host, listen_port=port)
    server = uvicorn.Server(uvicorn.Config(A.app, host=host, port=port, loop="asyncio", http="h11", ws="none",
                                           log_level=os.getenv("LOG_LEVEL", "info").lower(), access_log=False,
                                           log_config=None))
    th = threading.Thread(target=server.run, name="server", daemon=True)
    th.start()
    for _ in range(300):                                 # up to 15 s
        if server.started or not th.is_alive():
            break
        time.sleep(0.05)
    if not server.started:
        _message("kdchat", f"The server did not start. Details: {log_path}")
        return 1

    url = f"http://127.0.0.1:{port}/?session={token}"
    try:
        from version import __version__
        if not _open_window(url, f"kdchat {__version__}"):
            import netinfo
            _fallback_window(url, netinfo.urls(host, port))
    finally:
        server.should_exit = True                        # window closed: stop the server cleanly
        th.join(timeout=8)
    return 0


if __name__ == "__main__":
    sys.exit(main())
