"""Klaude display (kd) output for vrc-chatbox: chat messages on the OSC screen above Klaude's head.

The kd driver library lives in ./kd_display (a copy of the Klaude avatar's display library: kd/, config.json,
generated/charmap.json + kd_font.png; standard library only, Pillow for pictures). Its config.json must match the
uploaded avatar.

Screen (128 x 128 px):
  header   one 3x5 line: time zone + time, the date, "typing.." (sprites); a rule under it (graphics layer)
  log      the chat lines in a ring of LINE SLOTS: every line owns 2 memory pages at a fixed place in the text area and
           a fixed position in a 128 px ring; the ring scrolls with the text_y register. A new line = its slot's pages
           + one register frame, nothing else is resent. Lines are revealed one at a time: the next line is written
           just below the visible band (hidden), then the register moves up by one line. Lines that leave at the top
           are blanked before they could wrap round into view.
  single   only the newest message, large and centred; too long: a marquee (left or up) the shader runs by itself
  picture  a picture below the header (own colours in 10 of the 16 palette entries), the log hidden meanwhile

A background thread sends one frame per tick at the driver's rate (3 Hz). While the kd mode is active the refresh
keeps going (late joiners, lost frames). Switching the mode off turns the screen off, then the thread stops sending.
"""
from __future__ import annotations

import io
import os
import struct
import sys
import threading
import time
import zlib
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "kd_display"))

from kd.display import Display          # noqa: E402
from kd.config import Config            # noqa: E402

_SIZES = [tuple(v) for v in Config().sizes]

# every option of the kd mode (all switchable from the console / API)
DEFAULTS = {
    "screen": "176x96",      # the display's shape for the messages (every viewer's screen switches at run time)
    "layout": "chat",        # chat: the log, newest line at the bottom | single: only the newest message, large
    "scale": 1,              # font size of the messages: 1 or 2
    "long": "left",          # single layout, a message too long for the screen: left / up = marquee, cut = cut off
    "speed": "normal",       # marquee speed: slow | normal | fast
    "show_time": False,      # the time of each message (time zone + time, small font, in the gap above it; replaces the divider)
    "divider": False,        # a thin rule between messages (off: the alternating colours already separate them)
    "clock": True,           # the clock in the header
    "date": True,            # the date on the right of the header
    "invert": False,         # dark text on a light screen
    "highlight": True,       # chat layout: the newest message in the accent colour
    "color": 1,              # text colour (palette index)
    "alt": 2,                # every other message in this colour (0 = off), so messages are easy to tell apart
    "accent": 4,             # highlight colour (palette index; 4 = Klaude orange)
    "meta": 2,               # clock, rule, dividers, times, drafts (palette index)
    "image_fit": "cover",    # pictures: cover (fill, crop) | contain (whole picture)
    "image_full": True,      # pictures use the whole screen (the header is hidden while one is shown)
    "image_screen": "auto",  # pictures: auto = the screen size closest to the picture's shape | keep = the message size
    "image_res": "high",     # pictures: high = full resolution (~70 s to arrive) | low = 2x2 px dots (~20 s)
    "size": 0.40,            # the device's width in metres (a 128 px wide screen), 0.20 .. 0.60 (register size)
}
SCREENS = tuple(f"{w}x{h}" for w, h in _SIZES)      # from kd_display/config.json screen.sizes
CHOICES = {
    "screen": SCREENS,
    "layout": ("chat", "single"),
    "scale": (1, 2),
    "long": ("left", "up", "cut"),
    "speed": ("slow", "normal", "fast"),
    "image_fit": ("cover", "contain"),
    "image_screen": ("auto", "keep"),
    "image_res": ("high", "low"),
}
COLOR_KEYS = ("color", "accent", "meta", "alt")
HDR = 10                     # header height: one 3x5 line (time zone + time | date), 2 px space, a 2 px rule
DIVIDER = 3                  # the dividers between messages: dark grey (subtle)
TYPING_COLOR = 15            # the typing indicator: its own palette colour (cream), never offered as a choice
SPEED = {"left": {"slow": 20, "normal": 36, "fast": 60}, "up": {"slow": 8, "normal": 14, "fast": 22}}
SLOT_MEM = -(-Config().text_bytes // Config().P) - 1   # memory pages for the line slots (the text area's pages, the header takes 1)
RING = 1 << Config().yb       # ring period (px): every ring position fits the y field, no chaining needed
TINY_W = 4                   # 3x5 font advance
def _tiny_sprites(text, dot_w=2):
    """3x5 text as 16x16 sprite patterns, left to right, rows 1..5 (the header line); '.' advances dot_w px"""
    from kd_display.kd.tiny import tiny_pixels
    ink, x = set(), 0
    for ch in text:
        ink |= {(x + px, 1 + py) for px, py in tiny_pixels(ch)}
        x += dot_w if ch == "." else TINY_W
    width = max(px for px, _ in ink) + 1
    pats = [["".join("1" if (16 * k + col, row) in ink else "0" for col in range(16)) for row in range(16)]
            for k in range(-(-width // 16))]
    return pats, width


# the typing indicator: "typing.." in the header's 3x5 font on two sprites (sprites 1, 2: no text memory); "..." where the
# header has no room for it
TYPING_PATS, TYPING_W = _tiny_sprites("typing..")
TYPING_SHORT, TYPING_SHORT_W = _tiny_sprites("...")


def clean_settings(new: dict, old: dict | None = None) -> dict:
    """merge + validate settings; unknown keys are ignored"""
    s = dict(DEFAULTS)
    s.update({k: v for k, v in (old or {}).items() if k in DEFAULTS})
    for k, v in (new or {}).items():
        if k not in DEFAULTS:
            continue
        d = DEFAULTS[k]
        if isinstance(d, bool):
            v = bool(v)
        elif isinstance(d, int):
            v = int(v)
            if k in COLOR_KEYS and not (1 if k != "alt" else 0) <= v <= 14:
                raise ValueError(f"{k} must be a palette index 1..14" + (" (0 = off)" if k == "alt" else ""))
        elif isinstance(d, float):
            v = float(v)
            if not 0.2 <= v <= 0.6:
                raise ValueError(f"{k} must be 0.20 .. 0.60 (metres)")
        if k in CHOICES and v not in CHOICES[k]:
            raise ValueError(f"{k} must be one of {CHOICES[k]}")
        s[k] = v
    return s


def tz_label(t: datetime) -> str:
    """UTC+11, UTC-3:30, UTC"""
    off = t.astimezone().utcoffset()
    m = int(off.total_seconds() // 60) if off is not None else 0
    if m == 0:
        return "UTC"
    sign = "+" if m > 0 else "-"
    h, mm = divmod(abs(m), 60)
    return f"UTC{sign}{h}" + (f":{mm:02d}" if mm else "")


def png_bytes(img, scale=2) -> bytes:
    """rows of (r, g, b) floats 0..1 -> PNG (standard library only)"""
    h, w = len(img), len(img[0])
    raw = bytearray()
    for row in img:
        line = bytearray()
        for p in row:
            px = bytes(min(255, max(0, int(round(v * 255)))) for v in p)
            line += px * scale
        for _ in range(scale):
            raw += b"\x00" + line
    def chunk(t, data):
        c = struct.pack(">I", len(data)) + t + data
        return c + struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w * scale, h * scale, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


# ---------------------------------------------------------------- pictures
def _d2(a, b):
    return 2 * (a[0] - b[0]) ** 2 + 4 * (a[1] - b[1]) ** 2 + 3 * (a[2] - b[2]) ** 2


def prepare_image(data: bytes, gw: int, gh: int, top: int, fit: str):
    """picture bytes -> RGB image gw x gh graphics px: black header band of `top` rows, the picture below it
    (cover: fill + crop, slightly above centre; contain: whole picture), contrast / colour / sharpness lifted"""
    from PIL import Image, ImageOps, ImageEnhance, ImageFilter
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    if im.mode in ("RGBA", "LA", "P", "PA"):
        im = Image.alpha_composite(Image.new("RGBA", im.size, (0, 0, 0, 255)), im.convert("RGBA"))
    im = im.convert("RGB")
    box = (gw, gh - top)
    im = ImageOps.contain(im, box, Image.LANCZOS) if fit == "contain" else \
        ImageOps.fit(im, box, Image.LANCZOS, centering=(0.5, 0.42))
    im = ImageOps.autocontrast(im, cutoff=1.5, preserve_tone=True)   # one stretch for all channels: no colour cast
    im = ImageEnhance.Color(im).enhance(1.3)
    im = im.filter(ImageFilter.UnsharpMask(radius=1, percent=50, threshold=3))
    out = Image.new("RGB", (gw, gh), (0, 0, 0))
    out.paste(im, ((gw - im.width) // 2, top + (gh - top - im.height) // 2))
    return out


def adaptive_palette(img, base, keep):
    """the palette with the indices in `keep` unchanged, every other entry a colour of the picture (median cut)"""
    from PIL import Image
    free = [i for i in range(len(base)) if i not in keep]
    q = img.quantize(colors=len(free) + 4, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    cols = [tuple(pal[3 * i:3 * i + 3]) for _, i in sorted(q.getcolors(), reverse=True)]
    cols = [c for c in cols if min(_d2(c, base[k]) for k in keep) > 300]     # the UI colours already cover these
    out = list(base)
    for i, c in zip(free, cols):
        out[i] = c
    return out


def quantize(img, palette, per_tile=4, tile=8, strength=0.55):
    """-> rows of palette indices. 2 colours per 8x8 tile (the 1 bpp screen): the pair whose mixes (dithered) come
    closest to every pixel of the tile, then error diffusion between the two; more colours: greedy, gentle dithering"""
    w, h = img.size
    px = [list(map(float, p)) for p in img.getdata()]
    rgb = [px[y * w:(y + 1) * w] for y in range(h)]
    out = [[0] * w for _ in range(h)]
    W3 = (2 ** 0.5, 2.0, 3 ** 0.5)                               # perceptual weights (green counts most)
    pal = [tuple(c * k for c, k in zip(p, W3)) for p in palette]
    for ty in range(0, h, tile):
        for tx in range(0, w, tile):
            cells = [(x, y) for y in range(ty, min(h, ty + tile)) for x in range(tx, min(w, tx + tile))]
            if per_tile == 2:
                pts = [tuple(c * k for c, k in zip(rgb[y][x], W3)) for x, y in cells]
                # candidates: the palette colours nearest to the tile's pixels (the most used first)
                near = {}
                for p in pts:
                    k = min(range(len(pal)), key=lambda j: sum((a - b) ** 2 for a, b in zip(pal[j], p)))
                    near[k] = near.get(k, 0) + 1
                cand = [k for k, _ in sorted(near.items(), key=lambda kv: -kv[1])][:6]
                for k in sorted(range(len(pal)), key=lambda j: min(sum((a - b) ** 2 for a, b in zip(pal[j], p)) for p in pts))[:4]:
                    if k not in cand:
                        cand.append(k)
                best, be = (cand[0], cand[0]), None
                for i in range(len(cand)):
                    for j in range(i, len(cand)):
                        A, B = pal[cand[i]], pal[cand[j]]
                        D = [b - a for a, b in zip(A, B)]
                        dd = sum(v * v for v in D) or 1e-9
                        e = 0.0
                        for p in pts:                           # distance to the segment A-B (what dithering reaches)
                            t = max(0.0, min(1.0, sum((q - a) * d for q, a, d in zip(p, A, D)) / dd))
                            e += sum((q - (a + t * d)) ** 2 for q, a, d in zip(p, A, D))
                        if be is None or e < be:
                            best, be = (cand[i], cand[j]), e
                chosen, k_str = list(best), 0.85
            else:
                chosen, k_str = [], strength
                for _ in range(per_tile):
                    bk, be = None, None
                    for k in range(len(palette)):
                        if k in chosen:
                            continue
                        ks = chosen + [k]
                        e = sum(min(_d2(palette[j], rgb[y][x]) for j in ks) for x, y in cells)
                        if be is None or e < be:
                            bk, be = k, e
                    chosen.append(bk)
                    if be == 0:
                        break
            for y in range(ty, min(h, ty + tile)):
                for x in range(tx, min(w, tx + tile)):
                    old = rgb[y][x]
                    k = min(chosen, key=lambda j: _d2(palette[j], old))
                    out[y][x] = k
                    e = [(a - b) * k_str for a, b in zip(old, palette[k])]
                    for dx, dy, f in ((1, 0, 7 / 16), (-1, 1, 3 / 16), (0, 1, 5 / 16), (1, 1, 1 / 16)):
                        xx, yy = x + dx, y + dy
                        if tx <= xx < min(w, tx + tile) and yy < min(h, ty + tile):
                            rgb[yy][xx] = [a + f * b for a, b in zip(rgb[yy][xx], e)]
    return out


def best_size(data: bytes, top: int = 0) -> int:
    """index of the screen size whose picture area (below `top` px) is closest to the picture's aspect ratio"""
    import math
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(data)) as im:
        iw, ih = ImageOps.exif_transpose(im).size
    err = lambda wh: abs(math.log((iw / ih) / (wh[0] / (wh[1] - top)))) if wh[1] > top else 9.0
    return min(range(len(_SIZES)), key=lambda i: err(_SIZES[i]))


def _related(a: str, b: str) -> bool:
    """is b an edit of a (the same sentence growing / corrected)?"""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n > 0 and n >= min(len(a), len(b)) // 2


class KdChat:
    def __init__(self, host: str, port: int, dry: bool = False, settings: dict | None = None, log=None, run=True):
        self.lock = threading.RLock()
        self.d = Display(host=host, port=port, dry=dry)
        self.base_palette = list(self.d.mem.palette)
        self.s = clean_settings(settings or {})
        self._apply_screen()
        self.msgs: list[dict] = []          # {id, t, text, live, lines, gap, vy0, h}
        self.draft: str | None = None        # immediate=False: shown greyed at the bottom, not "sent"
        self.typing = False
        self.active = False
        self.log = log
        self.image = None                    # (graphics rows of palette indices, palette) while a picture is shown
        self._next_id = 1
        self._minute = None
        self._stop = False
        # what is on the air (chat layout)
        self.S = 0                           # scroll: virtual y at the top of the log band
        self.slots: list = []                # row key per slot (None = empty)
        self.slot_sig: list = []             # what each slot was drawn with
        self.slot_parts: list = []
        self._phase2 = None                  # scroll value waiting for its rows to be out
        self._full = True                    # redraw everything at the next step
        self._single_sig = None
        self._wait = set()                   # pages the last step changed (the next step waits for them)
        self._relayout()
        self.d.set(on=False)                 # hidden (the device's leave state) until the kd mode is switched on
        self.d.present()
        if run:
            threading.Thread(target=self._loop, name="kd-sender", daemon=True).start()

    def tick(self):
        """one sender step (what the thread does each frame; for tests with run=False)"""
        with self.lock:
            if self.active:
                if self.s["clock"] and datetime.now().strftime("%H:%M") != self._minute:
                    self._header()
                    if self.s["layout"] == "chat":
                        self.d.present()
                self._step()
            if self.active or not self.d.settled():
                return self.d.tick()

    def _apply_screen(self):
        w, h = (int(v) for v in self.s["screen"].split("x"))
        sizes = [tuple(v) for v in self.d.cfg.sizes]
        self.d.set_size(sizes.index((w, h)) if (w, h) in sizes else self.d.cfg.size, lowres=False)

    # ---------------- geometry
    @property
    def slot_pages(self):
        """memory pages per line: 2 (a whole mixed line of a wide screen), 1 on narrow screens (twice the lines)"""
        return 1 if self.d.cfg.W <= 112 and self.s["scale"] == 1 or self.d.cfg.W <= 128 and self.s["scale"] == 2 else 2

    @property
    def K(self):
        """line slots: visible lines + a partial one + the next one"""
        return 14 if self.slot_pages == 1 else SLOT_MEM // 2      # (14: the text's 64-run limit; fills 96x176)

    @property
    def lh(self):
        return self.d.cfg.line_h(self.s["scale"])

    @property
    def gh(self):
        return self.d.cfg.glyph_h(self.s["scale"])

    @property
    def gap(self):
        return 8 if self.s["show_time"] else 4           # px between messages (the time label / divider sit in it)

    @property
    def header_on(self):
        """the header band (clock / Klawd / typing + the rule) is drawn: not with both clock and Klawd off, nor over a
        full-screen picture"""
        if self.image is not None and self.s["image_full"]:
            return False
        return self.s["clock"] or self.s["date"]

    @property
    def top(self):
        """first row of the log band (the header above it). Revealing a line writes it below the band first: the band +
        the gap + one glyph must fit the 128 px ring (a screen lower than the ring leaves that room by itself)."""
        # (and on tall screens: no more lines than the slots hold, K - 2 visible + a partial + the next one)
        return max(HDR if self.header_on else 0, self.d.cfg.H - RING + self.gap + self.gh, self.d.cfg.H - (self.K - 2) * self.lh)

    @property
    def band(self):
        return self.d.cfg.H - self.top

    # ---------------- sending
    def _loop(self):
        while not self._stop:
            with self.lock:
                try:
                    if self.active:
                        if self.s["clock"] and datetime.now().strftime("%H:%M") != self._minute:
                            self._header()
                            if self.s["layout"] == "chat":
                                self.d.present()
                        self._step()
                    if self.active or not self.d.settled():
                        self.d.tick()                        # inactive: only until "screen off" is out
                except Exception as e:                       # never let the sender die
                    if self.log:
                        self.log.exception("kd: %s", e)
            time.sleep(0.3)                                  # ~3.3 frames/s (plus the step's own time)

    def close(self):
        self._stop = True

    # ---------------- public operations (thread safe)
    def set_active(self, on: bool):
        with self.lock:
            self.active = on
            if on:
                self._full = True
                self._step()
            else:
                self.d.set(on=False)
                self.d.present()

    def set_settings(self, new: dict) -> dict:
        with self.lock:
            old = self.s
            self.s = clean_settings(new, self.s)
            if old["screen"] != self.s["screen"]:
                self._apply_screen()
            if any(old[k] != self.s[k] for k in ("scale", "show_time", "divider", "layout", "screen", "clock", "date")):
                self._relayout()
            self._full = True
            if self.active:
                self._step()
            return dict(self.s)

    def add_message(self, text: str, immediate: bool = True, sfx: bool = True, live: bool = False):
        """live: an auto-send update of the message being typed (the console's auto mode): it replaces the last
        live message while it is the same sentence growing / being corrected, else starts a new one"""
        text = text.rstrip("\n")
        with self.lock:
            if not immediate:
                self.draft = text
                if self.active:
                    self._step()
                return None
            self.draft = None
            last = self.msgs[-1] if self.msgs and self.msgs[-1]["live"] else None
            new = True
            mid = None
            if last is not None and live and _related(last["text"], text):
                last["text"] = text; new = False; mid = last["id"]
            elif last is not None and not live and last["text"] == text:
                last["live"] = False; new = False; mid = last["id"]
            else:
                if last is not None:
                    last["live"] = False
                self.msgs.append({"id": self._next_id, "t": datetime.now(), "text": text, "live": live})
                mid = self._next_id
                self._next_id += 1
                if len(self.msgs) > 50:
                    self.msgs = self.msgs[-50:]
            if self.image is not None:
                self.image = None
                self._apply_screen()
                self._relayout()
                self._full = True
            self._relayout(last_only=True)
            if new and sfx and self.active:
                self.d.chime()
            if self.active:
                self._step()
            return mid

    # ---- messages by id (the console's "current message" model: one id from the first keystroke on)
    def new_message(self, text: str, final: bool = True, sfx: bool = True) -> int:
        """a new message; final=False: still being typed (live), updated with update_message"""
        with self.lock:
            self.draft = None
            mid = self._next_id
            self._next_id += 1
            self.msgs.append({"id": mid, "t": datetime.now(), "text": text.rstrip("\n"), "live": not final})
            if len(self.msgs) > 50:
                self.msgs = self.msgs[-50:]
            if self.image is not None:
                self.image = None
                self._apply_screen()
                self._full = True
            self._relayout(last_only=not self._full)
            if final and sfx and self.active:
                self.d.chime()
            if self.active:
                self._step()
            return mid

    def update_message(self, mid, text: str = None, final: bool = None, edited: bool = None, sfx: bool = False) -> bool:
        """change a message: its text (live typing or an edit), final = done typing (chimes once if sfx), edited =
        the "edited" label"""
        with self.lock:
            m = next((m for m in self.msgs if m["id"] == mid), None)
            if m is None:
                return False
            if text is not None:
                m["text"] = text.rstrip("\n")
            if edited is not None:
                m["edited"] = edited
            if final and m.get("live"):
                m["live"] = False
                if sfx and self.active:
                    self.d.chime()
            elif final is False:
                m["live"] = True
            if m is self.msgs[-1] and not self._full:
                self._relayout(last_only=True)          # the newest one: only its own lines change
            else:
                self._relayout()                        # an older one: the messages after it may move
                self._full = True
            if self.active:
                self._step()
            return True

    def remove_message(self, mid) -> bool:
        """take a message off the log entirely (a new message given up while typing)"""
        with self.lock:
            n = len(self.msgs)
            self.msgs = [m for m in self.msgs if m["id"] != mid]
            if len(self.msgs) == n:
                return False
            self._relayout()
            self._full = True
            if self.active:
                self._step()
            return True

    def edit_message(self, mid, text: str) -> bool:
        """change a message that was sent: it shows "edited" in the gap above it"""
        return self._change(mid, text=text.rstrip("\n"), edited=True)

    def revert_message(self, mid) -> bool:
        """take a message back: its body becomes a small grey "message reverted" """
        return self._change(mid, reverted=True)

    def _change(self, mid, **kw) -> bool:
        with self.lock:
            m = next((m for m in self.msgs if m["id"] == mid), None)
            if m is None:
                return False
            m.update(kw)
            m["live"] = False
            self._relayout()                    # its height may change: the messages after it move
            self._full = True
            if self.active:
                self._step()
            return True

    def chime(self):
        with self.lock:
            self.d.chime()

    def set_typing(self, on: bool):
        with self.lock:
            if self.typing != bool(on):
                self.typing = bool(on)
                self._header()
                if self.active and self.s["layout"] == "chat":
                    self.d.present()

    def clear(self):
        with self.lock:
            self.msgs, self.draft, self.typing = [], None, False
            self.image = None
            self._apply_screen()
            self._relayout()
            self._full = True
            if self.active:
                self._step()

    def show_image(self, data: bytes) -> dict:
        """show a picture below the header (until the next message or close_image)"""
        c = self.d.cfg
        with self.lock:
            top = 0 if self.s["image_full"] or not (self.s["clock"] or self.s["date"]) else HDR   # screen px above it
            fit = self.s["image_fit"]
            keep = {0, TYPING_COLOR} | {self.s[k] for k in COLOR_KEYS}
            low = self.s["image_res"] == "low"            # low: 2x2 px dots, a quarter of the pages
            size = best_size(data, top) if self.s["image_screen"] == "auto" else c.size   # closest to the picture's shape
            self.d.set_size(size, lowres=low)
            gw, gh, top_g = c.GW, c.GH, top // c.gscale
        img = prepare_image(data, gw, gh, top_g, fit)                # slow part outside the lock
        pal = adaptive_palette(img, self.base_palette, keep)
        idx = quantize(img, pal, per_tile=c.colors_per_tile)     # 4 colours per 8x8 block
        with self.lock:
            self.image = (idx, pal)
            self._full = True
            if self.active:
                self._step()
            n = len(self.d.link.pending())
            return {"pages": n, "eta_s": round(n / c.rate_hz, 1)}

    def close_image(self):
        with self.lock:
            if self.image is not None:
                self.image = None
                self._apply_screen()                  # back to the message size
                self._relayout()
                self._full = True
                if self.active:
                    self._step()

    def status(self) -> dict:
        with self.lock:
            lk = self.d.link
            pend = len(lk.pending())
            ok = self.d.synced(lk.sent)
            return {"active": self.active, "pending_pages": pend, "eta_s": round(pend / self.d.cfg.rate_hz, 1),
                    "synced": all(ok.values()) and not pend, "rate_hz": self.d.cfg.rate_hz,
                    "frames_sent": lk.frames, "messages": len(self.msgs), "image": self.image is not None,
                    "palette": ["#%02x%02x%02x" % tuple(p) for p in self.base_palette],
                    "width": self.d.cfg.W, "height": self.d.cfg.H}

    def preview_png(self) -> bytes:
        """what the avatar's screen should show right now (the pages sent so far)"""
        from types import SimpleNamespace
        from kd.sim import render
        with self.lock:
            buf = bytearray(self.d.link.sent)
        return png_bytes(render(SimpleNamespace(cfg=self.d.cfg, buf=buf), t=time.monotonic()), 2)

    # ---------------- message layout
    def _deco(self, m):
        """the time label / divider in the gap above a message, y relative to the gap's top -> text parts"""
        s, W = self.s, self.d.cfg.W
        parts = []
        ink = (self.gap - 2) // 2                                   # the divider's pixel row in the gap
        label = " ".join(x for x in ("edited" if m.get("edited") and not m.get("reverted") else "",
                                     f"{tz_label(m['t'])} {m['t'].strftime('%H:%M')}" if s["show_time"] else "") if x)
        if label:                                                   # one line, right-aligned
            parts.append({"s": label, "x": W - 1 - (len(label) * TINY_W - 1), "y": 1, "scale": "tiny", "color": s["meta"]})
            # the time label is the separator (with a rule as well, a whole first line would not fit its slot)
        elif s["divider"]:
            parts.append({"s": "─" * 3, "x": (W - 3 * 13 + 1) // 2, "y": ink - 6, "color": DIVIDER})
        return parts

    def _lines(self, text, deco, sc=None):
        """text -> lines that each fit a line slot (2 pages), the first one together with its decorations"""
        d, sc = self.d, sc or self.s["scale"]
        out = []
        for para in text.split("\n"):
            rest = para
            while True:
                ls = d.layout.lines(rest, d.cfg.W, sc)
                line = "".join(ch[3] for ch in ls[0]) if ls and ls[0] else ""
                parts = deco if not out else []
                n = len(line)
                while n > 1 and not d.fits_pages(parts + [{"s": line[:n], "scale": sc}], self.slot_pages):
                    n -= 1
                if n == 0 and rest:
                    n = 1
                if n < len(line) and " " in line[1:n]:
                    n = line.rindex(" ", 1, n)                      # shortened for memory: break at a word
                out.append(line[:n].rstrip(" ") if n < len(line) else line)
                rest = rest[n:].lstrip(" ")
                if not rest:
                    break
        return out or [""]

    def _layout_msg(self, m, gap):
        labelled = self.s["show_time"] or (m.get("edited") and not m.get("reverted"))
        m["gap"] = (8 if labelled else 4) if gap else (8 if labelled else 0)     # (a label also above the first one)
        m["sc"] = "small" if m.get("reverted") else self.s["scale"]
        body = "message reverted" if m.get("reverted") else m["text"]
        # measured at a positive y (the divider sits a few px above the gap: its runs must be representable there)
        deco = [dict(p, y=p["y"] + 32) for p in self._deco(m)] if m["gap"] else []
        m["lines"] = self._lines(body, deco, m["sc"])
        m["h"] = m["gap"] + len(m["lines"]) * self.lh

    def _relayout(self, last_only=False):
        """line breaks + virtual positions of the messages (last_only: only the newest changed / is new)"""
        msgs = self.msgs
        for i in range(len(msgs) - 1 if last_only else 0, len(msgs)):
            if i < 0:
                continue
            m = msgs[i]
            m["vy0"] = msgs[i - 1]["vy0"] + msgs[i - 1]["h"] if i else 0
            self._layout_msg(m, gap=i > 0)

    def _all(self):
        """the messages incl. the draft (a pseudo message at the end)"""
        msgs = list(self.msgs)
        if self.draft:
            prev = msgs[-1] if msgs else None
            m = {"id": "draft", "t": datetime.now(), "text": self.draft, "live": True, "draft": True,
                 "vy0": prev["vy0"] + prev["h"] if prev else 0}
            if getattr(self, "_draft_cache", (None,))[0] != (self.draft, m["vy0"], self.gap):
                self._layout_msg(m, gap=prev is not None)
                self._draft_cache = ((self.draft, m["vy0"], self.gap), m)
            msgs.append(self._draft_cache[1])
        return msgs

    def _rows(self, msgs):
        """-> {row key: (vy of the line, parts at ring positions, signature, top incl. the gap above)} for every line"""
        rows = {}
        s, top, lh = self.s, self.top, self.lh
        ring = lambda v: (top + v) % RING
        real = [m for m in msgs if not m.get("draft")]
        newest = real[-1]["id"] if real else None
        for m in msgs:
            if m.get("draft") or m.get("reverted"):
                col = s["meta"]
            elif s["highlight"] and m["id"] == newest:
                col = s["accent"]
            else:                                                   # alternate, by id: stable while the log scrolls
                col = s["alt"] if s["alt"] and m["id"] % 2 else s["color"]
            vy = m["vy0"] + m["gap"]
            for k, line in enumerate(m["lines"]):
                parts = []
                if k == 0 and m["gap"]:
                    parts = [dict(p, y=ring(m["vy0"] + p["y"])) for p in self._deco(m)]
                parts.append({"s": line, "x": 0, "y": ring(vy), "scale": m.get("sc", s["scale"]), "color": col})
                sig = tuple((p["s"], p["x"], p["y"], p.get("scale", 1), p["color"]) for p in parts)
                top_y = vy - (m["gap"] if k == 0 else 0)
                rows[(m["id"], k)] = (vy, parts, sig, top_y)
                vy += lh
        return rows

    # ---------------- drawing
    def _header(self):
        """one 3x5 line: time zone + time on the left, the date on the right, "typing.." (sprites) before it"""
        d, s, c = self.d, self.s, self.d.cfg
        now = datetime.now()
        self._minute = now.strftime("%H:%M")
        d.sprite(0, visible=False)
        if not self.header_on:
            d.compose([], id="hdr", page=True, pages=1)
            d.sprite(1, visible=False)
            d.sprite(2, visible=False)
            d.set(blink=None)
            return
        parts = []
        run = lambda n: c.hdr_bytes + -(-n * c.code_bits[0] // 8)           # bytes of an n-character 3x5 run
        left = c.P                                                           # the header has one page
        if s["clock"]:
            clock = f"{tz_label(now)} {self._minute}"
            parts.append({"s": clock, "x": 1, "y": 1, "scale": "tiny", "color": s["meta"]})
            left -= run(len(clock))
        dw = 0
        if s["date"]:
            # spaces in front (invisible) so the runs end exactly at the page end or leave room for a padding run
            # (a run may not end 1..header bytes before the page end): else the date would be cut
            date = f"{now:%a} {now.month}/{now.day}"
            n = len(date)
            while not (left - run(n) == 0 or left - run(n) > c.hdr_bytes) and run(n + 1) <= left:
                n += 1
            date = date.rjust(n)
            dw = len(date.strip()) * TINY_W
            parts.append({"s": date, "x": c.W - 1 - (n * TINY_W - 1), "y": 1, "scale": "tiny", "color": s["meta"]})
        d.compose(parts, id="hdr", page=True, pages=1)
        right = c.W - dw - (5 if dw else 2)                   # the typing text ends here (a gap before the date)
        left = 1 + (len(clock) * TINY_W + 3 if s["clock"] else 0)
        pats, w = (TYPING_PATS, TYPING_W) if right - TYPING_W >= left else (TYPING_SHORT, TYPING_SHORT_W)
        for k in range(2):
            if k < len(pats):
                d.sprite(1 + k, x=right - w + 16 * k, y=0, pattern=pats[k], colors=(TYPING_COLOR, 0, 0), visible=self.typing)
            else:
                d.sprite(1 + k, visible=False)
        d.set(blink=None)                                     # the typing indicator stays lit (no blinking)

    def _base(self):
        """everything but the log: screen state, header, graphics (rule or picture), palette"""
        d, s, c = self.d, self.s, self.d.cfg
        d.set(on=self.active, invert=s["invert"], gfx=True, text=True, sprites=True, mono=False, cycle=None, size_m=s["size"],
              text_x=0, text_vx=0, text_vy=0, window=None)
        self._header()
        d.raw()
        g = d.gfx
        if self.image is not None:
            idx, pal = self.image
            d.palette(pal)
            for y, row in enumerate(idx):
                for x, k in enumerate(row):
                    g.set(x, y, k)
        else:
            d.palette(self.base_palette)
            g.clear()
        if self.header_on:
            ry = (HDR - 2) // c.gscale                           # the rule under the header (2 px)
            g.line(0, ry, c.GW - 1, ry, s["meta"])

    def _step(self):
        if self.s["layout"] == "single":
            return self._single()
        d = self.d
        if self._full:
            self._full = False
            self._phase2 = None
            self._single_sig = None
            d.clear_text()
            self._base()
            K = self.K
            self.slots, self.slot_sig, self.slot_parts = [None] * K, [None] * K, [[] for _ in range(K)]
            msgs = self._all()
            rows = self._rows(msgs)
            T = msgs[-1]["vy0"] + msgs[-1]["h"] if msgs else 0
            self.S = max(0, T - self.band)
            self._assign(rows, self.S)
            self._present_log()
            return
        if self._busy():
            return                                            # one step at a time: wait until the last one is out
        if self._phase2 is not None:
            self.S, self._phase2 = self._phase2, None
            self._present_log()
            return
        msgs = self._all()
        rows = self._rows(msgs)
        T = msgs[-1]["vy0"] + msgs[-1]["h"] if msgs else 0
        St = max(0, T - self.band)
        if St > self.S:
            # reveal the next line (with the gap above it): write it below the band, then scroll
            nxt = min((r[0] + self.lh for r in rows.values() if r[0] + self.lh > self.S + self.band), default=T)
            Sn = min(St, max(self.S + 1, nxt - self.band))
            self._assign(rows, Sn, hidden_at=self.S)
            self._phase2 = Sn
            self._present_log()
        elif St < self.S:
            # the log got shorter (a live message lost a line): blank what leaves, scroll; the top fills next step
            self._assign(rows, St, write=False)
            self.S = St
            self._present_log()
        elif self._assign(rows, self.S):
            self._present_log()

    def _visible(self, row, S):
        """does a line (its ink, or the label / divider in the gap above it) show in the band at scroll S?"""
        return row[0] + self.gh > S and row[3] < S + self.band

    def _assign(self, rows, S, write=True, hidden_at=None):
        """bring the slots to the lines visible at scroll S: free the slots of lines not visible there, draw new /
        changed lines (hidden_at: new lines only if they are still below the band at that scroll). -> changed?"""
        want = {k for k, r in rows.items() if self._visible(r, S)}
        changed = False
        for i, key in enumerate(self.slots):
            if key is not None and key not in want:
                self.slots[i] = None; self.slot_sig[i] = None; self.slot_parts[i] = []
                changed = True
        if write:
            for key in sorted(want, key=lambda k: rows[k][0]):
                vy, parts, sig, top_y = rows[key]
                if key in self.slots:
                    i = self.slots.index(key)
                elif hidden_at is not None and top_y < hidden_at + self.band:
                    continue                                  # would show before the scroll: next step
                elif None in self.slots:
                    i = self.slots.index(None)
                else:
                    continue
                if self.slot_sig[i] != sig:
                    self.slots[i], self.slot_sig[i], self.slot_parts[i] = key, sig, parts
                    changed = True
        for i in range(len(self.slots)):
            self.d.compose(self.slot_parts[i], id=f"s{i}", move=True, page=True, pages=self.slot_pages)
        return changed

    def _busy(self):
        """are the pages of the last step still on their way?"""
        pend = self.d.link.pending()
        return any(p in pend for p in self._wait)

    def _present_log(self):
        d = self.d
        clip = (self.top, d.cfg.H) if self.image is None else (1, 1)
        d.set(text_y=(-self.S) % RING, text_wrap=(0, RING), text_clip=clip)
        P = d.cfg.P
        before = bytes(d.link.want)
        r = d.present()
        after = d.link.want
        self._wait = {p for p in range(d.cfg.pages) if before[p * P:(p + 1) * P] != after[p * P:(p + 1) * P]}
        if r.get("dropped") and self.log:
            self.log.warning("kd: %d glyphs did not fit the text memory", r["dropped"])

    # ---------------- single layout
    def _single(self):
        d, s, c = self.d, self.s, self.d.cfg
        msgs = self._all()
        m = msgs[-1] if msgs else None
        sig = (m["text"] if m else None, bool(m and m.get("draft")), tuple(sorted(s.items())),
               id(self.image), self.typing, self._minute, self.active)
        if sig == self._single_sig and not self._full:
            return
        if d.link.pending() and not self._full and self._single_sig is not None and sig[0] == self._single_sig[0]:
            return
        self._full = False
        self._single_sig = sig
        d.clear_text()
        self._base()
        top = self.top
        d.set(text_y=0, text_wrap=None, text_clip=None)
        if m is not None and self.image is None:
            col = s["meta"] if m.get("draft") else s["color"]          # (the highlight marks the newest line of the log)
            text = "message reverted" if m.get("reverted") else m["text"]
            if m.get("reverted"):
                col = s["meta"]
            band = c.H - top
            placed = False
            for sc in ([2, 1] if s["scale"] == 2 else [1]):
                n = len(d.layout.lines(text, c.W, sc))
                if n * c.line_h(sc) <= band:
                    y = top + (band - n * c.line_h(sc)) // 2
                    d.text(text, 0, y, c.W, "center", scale=sc, color=col, id="msg")
                    placed = True
                    break
            if not placed:
                if s["long"] == "left":
                    d.marquee(text, top, c.H, "left", SPEED["left"][s["speed"]], scale=s["scale"], color=col)
                elif s["long"] == "up":
                    d.marquee(text, top, c.H, "up", SPEED["up"][s["speed"]], scale=s["scale"], color=col,
                              width=c.W, align="center")
                else:
                    d.text(text, 0, top, c.W, scale=s["scale"], color=col, id="msg")
        d.present()
