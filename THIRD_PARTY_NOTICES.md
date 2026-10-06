# Third-party notices

kdchat itself is released under the [MIT License](LICENSE). It uses the following third-party software. Running
from source, these are installed by `uv sync`; the Windows `.exe` bundles them. Each keeps its own license; the full
license texts ship inside each package (in the `.exe`: in its unpacked `*.dist-info` folders) and on the linked
project pages.

| Component | License | Used for |
|---|---|---|
| [Fusion Pixel Font](https://github.com/TakWolf/fusion-pixel-font) | SIL Open Font License 1.1 (`kd_display/generated/OFL.txt`) | Klaude display font atlas (`kd_display/generated/kd_font.png`) |
| [Python](https://www.python.org/) | PSF License 2.0 | runtime (bundled in the `.exe`) |
| [FastAPI](https://github.com/fastapi/fastapi) | MIT | web framework |
| [Starlette](https://github.com/encode/starlette) | BSD-3-Clause | web framework |
| [Pydantic](https://github.com/pydantic/pydantic), pydantic-core | MIT | request / response models |
| [Uvicorn](https://github.com/encode/uvicorn) | BSD-3-Clause | web server |
| [h11](https://github.com/python-hyper/h11) | MIT | HTTP/1.1 |
| [AnyIO](https://github.com/agronholm/anyio) | MIT | async I/O |
| [idna](https://github.com/kjd/idna) | BSD-3-Clause | host names |
| [click](https://github.com/pallets/click) | BSD-3-Clause | (uvicorn dependency) |
| typing-extensions | PSF-2.0 | (dependency) |
| annotated-types, annotated-doc, typing-inspection | MIT | (dependencies) |
| [python-osc](https://github.com/attwad/python-osc) | Unlicense (public domain) | OSC messages |
| [Bergamot translator](https://github.com/mozilla/translations) (WebAssembly build shipped with Firefox, `vendor/bergamot/`, unchanged; source: [mozilla/translations `inference/`](https://github.com/mozilla/translations/tree/main/inference), version in `bergamot-translator.js`) | MPL-2.0 (`vendor/bergamot/LICENSE`) | translation engine |
| [Firefox Translations models](https://github.com/mozilla/translations) (not bundled: downloaded on request from the kdchat release `models-2026.10`, mirrored unchanged with their manifest) | MPL-2.0 | translation models |
| [mini-racer](https://github.com/bpcreech/PyMiniRacer) (with [V8](https://v8.dev/), BSD-3-Clause, and ICU data, Unicode license) | ISC | runs the translation engine (WebAssembly) inside kdchat |
| [Pillow](https://github.com/python-pillow/Pillow) | MIT-CMU (HPND) | pictures for the Klaude display, icon |
| [psutil](https://github.com/giampaolo/psutil) | BSD-3-Clause | finding the LAN address |
| [segno](https://github.com/heuer/segno) | BSD-3-Clause | QR codes (generated locally) |
| [pywebview](https://github.com/r0x0r/pywebview) (Windows `.exe` only) | BSD-3-Clause | the app window (Microsoft Edge WebView2) |
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) bootloader (Windows `.exe` only) | GPL-2.0-or-later with the bootloader exception (allows distributing bundled apps under any license) | packaging the `.exe` |

Microsoft Edge WebView2 Runtime is part of Windows 10/11 and is not bundled.
