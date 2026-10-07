# Third-party notices

kdchat itself is released under the [MIT License](LICENSE). It uses the following third-party software. Running
from source, these are installed by `uv sync`; the Windows `.exe` bundles them. Each keeps its own license; the full
license texts ship inside each package (in the `.exe`: in its unpacked `*.dist-info` folders) and on the linked
project pages.

| Component | License | Used for |
|---|---|---|
| [Fusion Pixel Font](https://github.com/TakWolf/fusion-pixel-font) | SIL Open Font License 1.1 (`kd_display/generated/OFL.txt`) | Klaude display font atlas (`kd_display/generated/kd_font.png`) |
| [GNU Unifont](https://unifoundry.com/unifont/) 16.0.04 | SIL Open Font License 1.1 (`kd_display/generated/UNIFONT-OFL.txt`) | Hebrew, Arabic and Thai glyphs in the display font atlas (fitted to 12 px) |
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
| [wasmtime](https://github.com/bytecodealliance/wasmtime-py) (wasmtime-py with the Wasmtime runtime) | Apache-2.0 WITH LLVM-exception | runs the translation engine (WebAssembly) inside kdchat |
| [Pillow](https://github.com/python-pillow/Pillow) (optional, not in the `.exe`: image files sent to the API) | MIT-CMU (HPND) | decoding image files on the server, the app icon (build time) |
| [segno](https://github.com/heuer/segno) | BSD-3-Clause | QR codes (generated locally) |
| [pywebview](https://github.com/r0x0r/pywebview) (Windows `.exe` only) | BSD-3-Clause | the app window (Microsoft Edge WebView2) |
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) bootloader (Windows `.exe` only) | GPL-2.0-or-later with the bootloader exception (allows distributing bundled apps under any license) | packaging the `.exe` |

Microsoft Edge WebView2 Runtime is part of Windows 10/11 and is not bundled.

The console (`ui/`, built from `web/`) contains:

| Component | License | Used for |
|---|---|---|
| [Svelte](https://github.com/sveltejs/svelte), [SvelteKit](https://github.com/sveltejs/kit) | MIT | the console |
| [shadcn-svelte](https://github.com/huntabyte/shadcn-svelte), [bits-ui](https://github.com/huntabyte/bits-ui), tailwind-variants, tailwind-merge, clsx | MIT | UI components |
| [Tailwind CSS](https://github.com/tailwindlabs/tailwindcss), tw-animate-css | MIT | styles |
| [Lucide](https://github.com/lucide-icons/lucide) (`@lucide/svelte`) | ISC | icons (SVG) |
| [svelte-sonner](https://github.com/wobsoriano/svelte-sonner), [mode-watcher](https://github.com/svecosystem/mode-watcher) | MIT | notifications, light / dark mode |
| [heic2any](https://github.com/alexcorvi/heic2any) (bundles [libheif](https://github.com/strukturag/libheif), LGPL-3.0, as a separate file loaded only for HEIC pictures: `ui/_app/immutable/assets/heic2any.min.*.js`, replaceable) | MIT | HEIC / HEIF phone photos |
| [UTIF.js](https://github.com/photopea/UTIF.js) | MIT | TIFF pictures |
