"""Local translation for kdchat: Mozilla's Firefox Translations models (MPL-2.0) on the CPU, inside this process.

The Bergamot engine (WebAssembly, vendor/bergamot, the build Firefox ships) runs on the wasmtime runtime with a small
Python host for its Emscripten glue (bergamot_wasm.py), so the same code works on every OS and nothing runs on the device you type on. Models are NOT bundled: the user downloads
the languages they want; they come from kdchat's GitHub release (MODELS_TAG, mirrored unchanged from Mozilla, see
tools/mirror_models.py) and are checked against the release's manifest (SHA-256). Every model translates between
English and one language; other pairs go through English (one call, two models).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import shutil
import sys
import threading
import time
import urllib.request

log = logging.getLogger("kdchat.translate")

MODELS_TAG = "models-2026.10"
RELEASE_URL = f"https://github.com/kurashizu/kdchat/releases/download/{MODELS_TAG}/"

# code -> (English name, own name); "en" needs no model
LANGUAGES = {
    "en": ("English", "English"), "zh": ("Chinese (Simplified)", "简体中文"), "zh_hant": ("Chinese (Traditional)", "繁體中文"),
    "ja": ("Japanese", "日本語"), "ko": ("Korean", "한국어"), "es": ("Spanish", "Español"), "fr": ("French", "Français"),
    "de": ("German", "Deutsch"), "it": ("Italian", "Italiano"), "pt": ("Portuguese", "Português"), "ru": ("Russian", "Русский"),
    "uk": ("Ukrainian", "Українська"), "pl": ("Polish", "Polski"), "nl": ("Dutch", "Nederlands"), "sv": ("Swedish", "Svenska"),
    "nb": ("Norwegian Bokmål", "Norsk bokmål"), "no": ("Norwegian", "Norsk"), "da": ("Danish", "Dansk"),
    "fi": ("Finnish", "Suomi"), "cs": ("Czech", "Čeština"), "sk": ("Slovak", "Slovenčina"), "sl": ("Slovenian", "Slovenščina"),
    "hu": ("Hungarian", "Magyar"), "ro": ("Romanian", "Română"), "bg": ("Bulgarian", "Български"), "el": ("Greek", "Ελληνικά"),
    "lt": ("Lithuanian", "Lietuvių"), "lv": ("Latvian", "Latviešu"), "et": ("Estonian", "Eesti"), "is": ("Icelandic", "Íslenska"),
    "ca": ("Catalan", "Català"), "gl": ("Galician", "Galego"), "eu": ("Basque", "Euskara"), "tr": ("Turkish", "Türkçe"),
    "az": ("Azerbaijani", "Azərbaycan"), "ar": ("Arabic", "العربية"), "he": ("Hebrew", "עברית"), "fa": ("Persian", "فارسی"),
    "hi": ("Hindi", "हिन्दी"), "ur": ("Urdu", "اردو"), "bn": ("Bengali", "বাংলা"), "ta": ("Tamil", "தமிழ்"),
    "te": ("Telugu", "తెలుగు"), "kn": ("Kannada", "ಕನ್ನಡ"), "ml": ("Malayalam", "മലയാളം"), "mr": ("Marathi", "मराठी"),
    "gu": ("Gujarati", "ગુજરાતી"), "th": ("Thai", "ไทย"), "vi": ("Vietnamese", "Tiếng Việt"), "id": ("Indonesian", "Bahasa Indonesia"),
    "ms": ("Malay", "Bahasa Melayu"), "af": ("Afrikaans", "Afrikaans"), "sq": ("Albanian", "Shqip"), "bs": ("Bosnian", "Bosanski"),
    "hr": ("Croatian", "Hrvatski"), "sr": ("Serbian", "Српски"), "hbs": ("Serbo-Croatian", "Srpskohrvatski"),
}

# written in the Latin alphabet: these can use the display's small font (5x7: ASCII + the common accented letters;
# other marks are dropped). Not Vietnamese: its tone marks carry the meaning.
LATIN = frozenset("en es fr de it pt pl nl sv nb no da fi cs sk sl hu ro lt lv et is ca gl eu tr az id ms af sq bs hr "
                  "hbs".split())

# scripts the Klaude display cannot draw (Indic: conjuncts and reordered vowel signs need a shaping engine; the display
# has fixed glyph cells): these translations go to the game chatbox only, the side screen says so
NO_DISPLAY = frozenset("hi mr bn gu ta te kn ml".split())

_ALIGN = {"model": 256, "lex": 64, "vocab": 64, "srcvocab": 64, "trgvocab": 64}


def _here():
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


# ------------------------------------------------------------------ language of a text
def detect(text: str, hint: str = "auto", latin: str = "en") -> str:
    """the language of `text`: `hint` if it is not "auto", else by its script (kana -> ja, hangul -> ko, han -> zh, ...);
    latin text -> `latin` (the user's own latin-script language, default English)"""
    if hint and hint != "auto":
        return hint
    counts = {}
    for ch in text:
        o = ord(ch)
        k = ("ja" if 0x3040 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF or 0xFF66 <= o <= 0xFF9F else
             "ko" if 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F else
             "han" if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF else
             "ru" if 0x0400 <= o <= 0x04FF else "ar" if 0x0600 <= o <= 0x06FF else "he" if 0x0590 <= o <= 0x05FF else
             "th" if 0x0E00 <= o <= 0x0E7F else "el" if 0x0370 <= o <= 0x03FF else "hi" if 0x0900 <= o <= 0x097F else
             "bn" if 0x0980 <= o <= 0x09FF else "ta" if 0x0B80 <= o <= 0x0BFF else "te" if 0x0C00 <= o <= 0x0C7F else
             "kn" if 0x0C80 <= o <= 0x0CFF else "ml" if 0x0D00 <= o <= 0x0D7F else "gu" if 0x0A80 <= o <= 0x0AFF else
             "latin" if ch.isalpha() else None)
        if k:
            counts[k] = counts.get(k, 0) + 1
    if not counts:
        return latin
    if counts.get("ja"):                        # kana anywhere: Japanese (it mixes in kanji)
        return "ja"
    k = max(counts, key=counts.get)
    if k == "han":
        return "zh_hant" if latin == "zh_hant" else "zh"
    if k == "latin":
        return latin
    if k == "ru" and latin in ("uk", "bg", "sr"):
        return latin
    if k == "ar" and latin in ("fa", "ur"):
        return latin
    if k == "hi" and latin == "mr":
        return latin
    return k


# ------------------------------------------------------------------ models on disk
class Models:
    """the manifest of MODELS_TAG and the downloaded models under <data>/models/<tag>/<pair>/"""

    def __init__(self, data_dir: str, release_url: str = RELEASE_URL):
        self.root = os.path.join(data_dir, "models", MODELS_TAG)
        self.url = release_url
        self.lock = threading.Lock()
        self.progress = {}                   # lang -> {"state": downloading|error, "done", "total", "error"}
        self._manifest = None

    def manifest(self, fetch: bool = True) -> dict | None:
        if self._manifest is None:
            path = os.path.join(self.root, "manifest.json")
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    self._manifest = json.load(f)
            elif fetch:
                data = self._get(self.url + "manifest.json")
                os.makedirs(self.root, exist_ok=True)
                with open(path + ".part", "wb") as f:
                    f.write(data)
                os.replace(path + ".part", path)
                self._manifest = json.loads(data)
        return self._manifest

    @staticmethod
    def _get(url, timeout=60):
        req = urllib.request.Request(url, headers={"User-Agent": "kdchat"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    def pairs(self, lang: str) -> list:
        return [] if lang == "en" else [f"{lang}-en", f"en-{lang}"]

    def languages(self) -> list:
        """every language the release has both directions for (+ English)"""
        m = self.manifest(fetch=False) or {}
        have = set(m.get("models", {}))
        out = ["en"] + sorted(l for l in LANGUAGES if l != "en" and all(p in have for p in self.pairs(l)))
        return out

    def size(self, lang: str) -> int:
        m = self.manifest(fetch=False) or {}
        return sum(m.get("models", {}).get(p, {}).get("size", 0) for p in self.pairs(lang))

    def pair_dir(self, pair: str) -> str:
        return os.path.join(self.root, pair)

    def installed(self, lang: str) -> bool:
        return all(os.path.exists(os.path.join(self.pair_dir(p), "ok")) for p in self.pairs(lang))

    def installed_languages(self) -> list:
        return [l for l in LANGUAGES if self.installed(l)]

    def status(self) -> list:
        """[{code, name, native, size, state: ready|downloading|error|absent, done, total}] for the picker"""
        try:
            self.manifest()
        except Exception as e:                    # offline: only what is on disk
            log.info("model manifest not available: %s", e)
        out = []
        for l in self.languages() or ["en"]:
            p = dict(self.progress.get(l, {}))
            state = "ready" if self.installed(l) else p.get("state", "absent")
            out.append({"code": l, "name": LANGUAGES[l][0], "native": LANGUAGES[l][1], "size": self.size(l),
                        "state": state, "done": p.get("done", 0), "total": p.get("total", self.size(l)),
                        "error": p.get("error")})
        return out

    def download(self, lang: str) -> None:
        """fetch and verify both directions of `lang` (blocking; status() reports the progress)"""
        if lang == "en" or self.installed(lang):
            return
        m = self.manifest()
        entries = [(p, m["models"][p]) for p in self.pairs(lang)]
        total = sum(e["size"] for _, e in entries)
        st = self.progress[lang] = {"state": "downloading", "done": 0, "total": total}
        try:
            for pair, e in entries:
                d = self.pair_dir(pair)
                if os.path.exists(os.path.join(d, "ok")):
                    st["done"] += e["size"]
                    continue
                tmp = d + ".part"
                shutil.rmtree(tmp, ignore_errors=True)
                os.makedirs(tmp)
                files = {}
                for kind, f in e["files"].items():
                    data = self._fetch(self.url + f["asset"], st)
                    if hashlib.sha256(data).hexdigest() != f["sha256"]:
                        raise ValueError(f"{f['asset']}: checksum mismatch")
                    raw = gzip.decompress(data)
                    if hashlib.sha256(raw).hexdigest() != f["raw_sha256"]:
                        raise ValueError(f"{f['asset']}: content checksum mismatch")
                    with open(os.path.join(tmp, f["name"]), "wb") as out:
                        out.write(raw)
                    files[kind] = f["name"]
                with open(os.path.join(tmp, "files.json"), "w") as out:
                    json.dump({"files": files, "gemm": e["gemm"], "architecture": e["architecture"]}, out)
                open(os.path.join(tmp, "ok"), "w").close()
                shutil.rmtree(d, ignore_errors=True)
                os.replace(tmp, d)
            self.progress.pop(lang, None)
            log.info("translation model ready: %s", lang)
        except Exception as ex:
            st.update(state="error", error=str(ex))
            log.warning("model download failed (%s): %s", lang, ex)
            raise

    def _fetch(self, url, st):
        req = urllib.request.Request(url, headers={"User-Agent": "kdchat"})
        chunks = []
        with urllib.request.urlopen(req, timeout=60) as r:
            while True:
                b = r.read(1 << 16)
                if not b:
                    break
                chunks.append(b)
                st["done"] += len(b)
        return b"".join(chunks)

    def delete(self, lang: str) -> None:
        for p in self.pairs(lang):
            shutil.rmtree(self.pair_dir(p), ignore_errors=True)
        self.progress.pop(lang, None)


# ------------------------------------------------------------------ the engine
class Engine:
    """the Bergamot engine (WebAssembly on wasmtime, bergamot_wasm.py); translate() loads the models it needs (and
    frees ones not used lately). Not thread safe by itself: every call holds the lock."""

    WORKSPACE_MB = 32            # Marian's per-model scratch space (Firefox: 128); 32 keeps the heap small, same output
    MAX_LOADED = 6               # translation directions kept in memory

    def __init__(self, models: Models):
        self.models = models
        self.lock = threading.Lock()
        self.b = None
        self.loaded = {}             # pair -> (model handle, last use)

    def _start(self):
        from bergamot_wasm import Bergamot
        with open(os.path.join(_here(), "vendor", "bergamot", "bergamot-translator.wasm"), "rb") as f:
            self.b = Bergamot(f.read())

    def _config(self, gemm: str) -> str:
        cfg = {"beam-size": "1", "normalize": "1.0", "word-penalty": "0", "max-length-break": "128",
               "mini-batch-words": "1024", "workspace": str(self.WORKSPACE_MB), "max-length-factor": "2.0",
               "skip-cost": "true", "cpu-threads": "0", "quiet": "true", "quiet-translation": "true",
               "gemm-precision": gemm, "alignment": "soft"}
        return "\n" + "".join(f"            {k}: {v}\n" for k, v in cfg.items()) + "            "

    def _ensure(self, pair):
        if pair in self.loaded:
            self.loaded[pair] = (self.loaded[pair][0], time.monotonic())
            return self.loaded[pair][0]
        d = self.models.pair_dir(pair)
        with open(os.path.join(d, "files.json")) as f:
            meta = json.load(f)
        data = {}
        for kind, name in meta["files"].items():
            with open(os.path.join(d, name), "rb") as f:
                data[kind] = f.read()
        vocabs = [data["vocab"]] if "vocab" in data else [data["srcvocab"], data["trgvocab"]]
        src, tgt = pair.split("-")
        m = self.b.model(src, tgt, self._config(meta["gemm"]), data["model"], data.get("lex"), vocabs, _ALIGN)
        self.loaded[pair] = (m, time.monotonic())
        while len(self.loaded) > self.MAX_LOADED:
            old = min(self.loaded, key=lambda k: self.loaded[k][1])
            self.b.free_model(self.loaded.pop(old)[0])
        return m

    def ready(self, src: str, tgt: str) -> bool:
        return src == tgt or all(self.models.installed(l) for l in (src, tgt))

    def translate(self, text: str, src: str, tgt: str) -> str:
        if src == tgt or not text.strip():
            return text
        if not self.ready(src, tgt):
            raise LookupError(f"model not downloaded: {src if not self.models.installed(src) else tgt}")
        with self.lock:
            if self.b is None:
                self._start()
            if src == "en" or tgt == "en":
                a, b = self._ensure(f"{src}-{tgt}"), None
            else:
                a, b = self._ensure(f"{src}-en"), self._ensure(f"en-{tgt}")
            out = []
            for line in text.split("\n"):                 # the engine treats a message as text: keep the line breaks
                out.append(self.b.translate(a, line, via=b) if line.strip() else line)
            return _tidy("\n".join(out), tgt)


_FULLWIDTH = {",": "，", "!": "！", "?": "？", ":": "：", ";": "；", "(": "（", ")": "）"}


_ASCII_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-",
                               "\u2026": "..."})


def _tidy(s: str, lang: str) -> str:
    """CJK output with the half-width punctuation the models sometimes produce -> full width; other languages: curly
    quotes / dashes -> ASCII (the display's font has those only as full-width glyphs)"""
    if lang not in ("zh", "zh_hant", "ja", "ko"):
        s = s.translate(_ASCII_QUOTES)
    if lang in ("zh", "zh_hant", "ja"):
        out = []
        for i, ch in enumerate(s):
            nxt = s[i + 1] if i + 1 < len(s) else ""
            if ch in _FULLWIDTH and not (nxt.isascii() and nxt.isalnum()):
                ch = _FULLWIDTH[ch]
            out.append(ch)
        s = "".join(out).replace("。 ", "。").replace("， ", "，")
    return s.strip()
