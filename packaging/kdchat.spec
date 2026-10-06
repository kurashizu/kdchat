# PyInstaller spec: one-file, windowed kdchat.exe (also builds on macOS / Linux for testing).
# Build: uv sync --group build && uv run pyinstaller packaging/kdchat.spec --noconfirm --clean
# -> dist/kdchat(.exe)
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, ROOT)
from version import __version__  # noqa: E402


def tree(src, dest):
    """every file under ROOT/src (no caches) -> (file, folder in the bundle)"""
    out = []
    for d, dirs, files in os.walk(os.path.join(ROOT, src)):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for f in files:
            if f.endswith((".pyc", ".DS_Store")) or f.startswith("._"):
                continue
            rel = os.path.relpath(d, os.path.join(ROOT, src))
            out.append((os.path.join(d, f), os.path.normpath(os.path.join(dest, rel))))
    return out


# ui/ (the console) and kd_display/ (the Klaude display library: kd/*.py is imported from this folder at run time
# by kd_chat.py, plus config.json, the font atlas and its OFL licence)
datas = tree("ui", "ui") + tree("kd_display", "kd_display") + tree("vendor", "vendor")      # vendor: the translation engine
# mini-racer: the V8 library + its ICU data (runs the translation engine's WebAssembly)
datas += collect_data_files("py_mini_racer")
binaries = collect_dynamic_libs("py_mini_racer")
datas += [(os.path.join(ROOT, f), ".") for f in ("LICENSE", "THIRD_PARTY_NOTICES.md") if os.path.exists(os.path.join(ROOT, f))]

# uvicorn: only the parts this app runs (h11 HTTP, asyncio loop, lifespan; no websockets / httptools / uvloop)
UVICORN = ["uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio", "uvicorn.protocols",
           "uvicorn.protocols.http", "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
           "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto", "uvicorn.lifespan", "uvicorn.lifespan.on",
           "uvicorn.lifespan.off", "uvicorn.middleware", "uvicorn.middleware.proxy_headers"]
hiddenimports = (
    UVICORN
    + ["kd_chat", "netinfo", "kdchat_config", "version", "segno", "psutil", "translate", "py_mini_racer"]
    # what kd_display/kd/*.py imports (it is not analysed: it is loaded from the data folder)
    + ["http.server", "copy", "random", "zlib", "struct", "base64", "math", "PIL.Image", "PIL.ImageOps",
       "PIL.ImageEnhance", "PIL.ImageFilter", "PIL.ImageDraw", "PIL.PngImagePlugin", "PIL.JpegImagePlugin",
       "PIL.WebPImagePlugin", "PIL.GifImagePlugin", "PIL.BmpImagePlugin"]
)
if sys.platform == "win32":
    hiddenimports += collect_submodules("webview")

version_file = None
if sys.platform == "win32":                    # the version shown in the .exe's Properties -> Details
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)
    nums = tuple(int(x) for x in (__version__.split("-")[0].split(".") + ["0", "0", "0"])[:4])
    version_file = VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums),
        kids=[StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "kurashizu"),
            StringStruct("FileDescription", "kdchat: VRChat chatbox from your phone"),
            StringStruct("FileVersion", __version__),
            StringStruct("InternalName", "kdchat"),
            StringStruct("LegalCopyright", "MIT License"),
            StringStruct("OriginalFilename", "kdchat.exe"),
            StringStruct("ProductName", "kdchat"),
            StringStruct("ProductVersion", __version__)])]),
              VarFileInfo([VarStruct("Translation", [1033, 1200])])])

a = Analysis(
    [os.path.join(ROOT, "desktop.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hiddenimports,
    binaries=binaries,
    # not used: test / dev tools, other web servers' extras, standard-library parts the app never imports, Pillow's
    # GUI bindings and formats we do not read
    excludes=["uvloop", "watchfiles", "pytest", "httpx", "websockets", "httptools", "yaml", "dotenv",
              "unittest", "pydoc", "doctest", "lib2to3", "pdb", "test", "pip",
              "PIL.ImageQt", "PIL.ImageTk", "PIL._avif", "PIL.FpxImagePlugin", "PIL.MicImagePlugin",
              "numpy", "IPython", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="kdchat",
    console=False,                             # a windowed app (the log goes to %APPDATA%\kdchat)
    icon=os.path.join(ROOT, "packaging", "icon.ico"),
    version=version_file,
    upx=False,                                 # UPX-packed files trip antivirus scanners more often
    runtime_tmpdir=None,
    disable_windowed_traceback=True,
)
