"""kdchat desktop app (the Windows .exe): starts the server and opens the console in its own window.

- The window uses the system's Edge WebView2 (pywebview). Without WebView2 (or pywebview) the console opens in the
  default browser and a small window keeps the server running; closing either window stops the server.
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
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk(); root.withdraw()
        messagebox.showerror(title, text)
        root.destroy()
    except Exception:          # noqa: BLE001
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
        webview.create_window(title, url, width=1120, height=820, min_size=(360, 560), background_color="#101218")
        webview.start(gui="edgechromium" if os.name == "nt" else None, private_mode=False,
                      storage_path=os.path.join(_data_dir(), "webview"))
        return True
    except Exception as e:     # noqa: BLE001
        logging.getLogger("kdchat").warning("the app window failed (%s): opening the browser instead", e)
        return False


def _data_dir() -> str:
    import kdchat_config as cfg
    return cfg.data_dir()


def _fallback_window(url: str, lan: list[str], log_path: str) -> None:
    """no WebView2: open the browser, keep a small window; closing it stops the server"""
    webbrowser.open(url)
    try:
        import tkinter
        from tkinter import ttk
    except Exception:          # noqa: BLE001
        while True:                                      # no GUI at all: run until killed
            time.sleep(3600)
    root = tkinter.Tk()
    root.title("kdchat")
    root.resizable(False, False)
    try:
        from version import __version__
    except Exception:          # noqa: BLE001
        __version__ = ""
    f = ttk.Frame(root, padding=16)
    f.grid()
    ttk.Label(f, text=f"kdchat {__version__} is running", font=("Segoe UI", 12, "bold")).grid(sticky="w")
    ttk.Label(f, text="Console: " + url.split("?")[0]).grid(sticky="w", pady=(8, 0))
    for u in lan:
        ttk.Label(f, text="On your phone: " + u).grid(sticky="w")
    ttk.Label(f, text="Closing this window stops kdchat.", foreground="#666").grid(sticky="w", pady=(8, 8))
    b = ttk.Frame(f)
    b.grid(sticky="w")
    ttk.Button(b, text="Open in browser", command=lambda: webbrowser.open(url)).grid(row=0, column=0, padx=(0, 8))
    open_log = (lambda: os.startfile(log_path)) if os.name == "nt" else (lambda: webbrowser.open("file://" + log_path))
    ttk.Button(b, text="Open log", command=open_log).grid(row=0, column=1, padx=(0, 8))
    ttk.Button(b, text="Quit", command=root.destroy).grid(row=0, column=2)
    root.mainloop()


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
            _fallback_window(url, netinfo.urls(host, port), log_path)
    finally:
        server.should_exit = True                        # window closed: stop the server cleanly
        th.join(timeout=8)
    return 0


if __name__ == "__main__":
    sys.exit(main())
