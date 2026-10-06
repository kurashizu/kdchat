"""Driver API: graphics canvas + positioned text + registers -> memory image -> link -> OSC.

    d = Display()                         # OSC to 127.0.0.1:9000 (config)
    d.gfx.rect(0, 0, 128, 128)            # graphics plane (RAW mode)
    t = d.text("你好，Hello", x=4, y=4, width=120)
    d.present()                           # compose the memory image and queue the changed pages
    d.run()                               # pace frames at sync.rate_hz (blocking); or call d.tick() from your loop
"""
from .config import (Config, FLAG_ON, FLAG_INVERT, FLAG_GFX, FLAG_TEXT, FLAG_MONO, FLAG_DITHER, FLAG_SPRITES, FLAG_WINDOW,
                     GFX_RAW, GFX_PHOTO, SPR_VISIBLE, SPR_FLIPX, SPR_FLIPY, SPR_DOUBLE, SPR_ABOVE, FX_EFFECTS)
from .memory import Memory, Charmap
from .layout import Layout
from .canvas import Canvas
from .link import Link
from . import shapes as SH


SCREENS = {"main": 0, "left": 1, "right": 2}


def screen_id(screen):
    """"main" / "left" / "right" (or 0 / 1 / 2) -> 0 / 1 / 2"""
    if screen in (0, 1, 2):
        return screen
    if screen not in SCREENS:
        raise ValueError(f'screen must be "main", "left" or "right", not {screen!r}')
    return SCREENS[screen]


def wing_sides(v):
    """the wings setting -> frozenset of open sides (1 left, 2 right): True / False, "left" / "right" / "both", or a
    collection of those (or of 1 / 2)"""
    if v is True or v == "both":
        return frozenset((1, 2))
    if not v:
        return frozenset()
    if isinstance(v, (str, int)):
        v = [v]
    out = set()
    for x in v:
        k = {"left": 1, "right": 2, 1: 1, 2: 2}.get(x)
        if k is None:
            raise ValueError(f"wings: {x!r} (left / right)")
        out.add(k)
    return frozenset(out)


class ShapeLayer:
    """24 hardware shapes (config shapes.count), drawn by the shader from a 10-byte table entry each (kd/shapes.py): moving / recolouring a
    shape = one frame, no bitmap. Slots are retained: calling a method on slot i again replaces it. Angles in degrees
    (0 = 12 o'clock, clockwise), positions in screen px. Common options:
        pattern  "solid" | "checker" | "hstripes" | "vstripes" | "diagonal" | "dots" | "hgradient" | "vgradient"
        above    draw over the text (default: under it)        xor  invert what is under it (cursors, selections)
        follow   move and zoom with the graphics layer          anim ("rotate", turns/s) | ("pulse", Hz) | ("blink", Hz)
                                                                     | ("sweep", turns/s: arc / pie start angle)"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.data = [None] * cfg.shp_n
        self.screen = [0] * cfg.shp_n           # 0 main, 1 left wing, 2 right wing (wing coordinates: its own screen)

    def _put(self, i, kind, coords, raw=(), fill=None, color=1, width=1, pattern="solid", round_caps=False, above=False,
             xor=False, follow=False, anim=None, screen="main"):
        if not 0 <= i < self.cfg.shp_n:
            raise IndexError(f"shape slot {i} (0..{self.cfg.shp_n - 1})")
        self.screen[i] = screen_id(screen)
        a, sp = None, 0
        if anim:
            a, v = anim
            sp = round(v * 8) if a in ("rotate", "sweep") else round(v * 4)
            if sp == 0:
                a = None
        for v in coords:
            if not -self.cfg.shp_off <= round(v) <= 255 - self.cfg.shp_off:
                raise ValueError(f"shape coordinate {v} outside -{self.cfg.shp_off}..{255 - self.cfg.shp_off}")
        self.data[i] = SH.encode(kind, fill, color, coords, raw, width, pattern, round_caps, above, xor, follow, a, sp,
                                 self.cfg.shp_off)
        return i

    @staticmethod
    def _deg(v):
        return int(round(v / 360 * 256)) % 256

    def line(self, i, x0, y0, x1, y1, color=1, width=1, round_caps=False, **kw):
        return self._put(i, "line", (x0, y0, x1, y1), (), None, color, width, round_caps=round_caps, **kw)

    def rect(self, i, x, y, w, h, color=1, fill=None, width=1, radius=0, angle=0, **kw):
        """w x h pixels from (x, y); fill = fill colour (None: outline only); width = outline (0 with a fill: none)"""
        raw = {4: self._deg(angle)} if not radius else {4: self._deg(angle), 5: min(255, int(radius))}
        return self._put(i, "rrect" if radius else "rect", (x, y, x + w - 1, y + h - 1), raw, fill, color, width, **kw)

    def ellipse(self, i, cx, cy, rx, ry=None, color=1, fill=None, width=1, angle=0, **kw):
        ry = rx if ry is None else ry
        return self._put(i, "ellipse", (cx, cy), {2: min(255, int(rx)), 3: min(255, int(ry)), 4: self._deg(angle)},
                         fill, color, width, **kw)

    circle = ellipse

    def arc(self, i, cx, cy, r, start=0, sweep=360, color=1, thickness=None, **kw):
        sw = 255 if sweep >= 360 else self._deg(sweep)
        return self._put(i, "arc", (cx, cy), {2: min(255, int(r)), 3: self._deg(start), 4: sw, 5: min(255, int(thickness or 0))},
                         None, color, max(1, min(7, int(thickness or 1))), **kw)

    def pie(self, i, cx, cy, r, start=0, sweep=90, color=1, fill=None, width=1, **kw):
        sw = 255 if sweep >= 360 else self._deg(sweep)
        return self._put(i, "pie", (cx, cy), {2: min(255, int(r)), 3: self._deg(start), 4: sw}, fill, color, width, **kw)

    def tri(self, i, p0, p1, p2, color=1, fill=None, width=1, **kw):
        return self._put(i, "tri", (*p0, *p1, *p2), (), fill, color, width, **kw)

    def poly(self, i, cx, cy, r, sides=6, star=0.0, angle=0, color=1, fill=None, width=1, **kw):
        """regular polygon (3..12 sides) or, with star = inner radius / r (0..1), a star with that many points"""
        inner = max(0, min(15, round(star * 16))) if star else 0
        return self._put(i, "poly", (cx, cy), {2: min(255, int(r)), 3: (inner << 4) | max(3, min(12, int(sides))),
                                               4: self._deg(angle)}, fill, color, width, **kw)

    def bezier(self, i, p0, p1, p2, color=1, width=1, **kw):
        """quadratic curve from p0 to p2 pulled toward p1"""
        return self._put(i, "bezier", (*p0, *p1, *p2), (), None, color, width, **kw)

    def hide(self, i):
        self.data[i] = None

    def clear(self):
        self.data = [None] * self.cfg.shp_n
        self.screen = [0] * self.cfg.shp_n

    def physical(self):
        """-> (slot data in memory order, wing_shp register): main shapes first, then the left wing's, then the right's
        (a wing's range starts at slot >= 1: 0 means none, so slot 0 stays empty when only wings have shapes)"""
        used = [i for i in range(self.cfg.shp_n) if self.data[i] is not None]
        groups = [[i for i in used if self.screen[i] == k] for k in (0, 1, 2)]
        order = groups[0][:]
        if not order and (groups[1] or groups[2]):
            order.append(None)
        starts = []
        for k in (1, 2):
            starts.append(len(order) if groups[k] else 0)
            order += groups[k]
        if max(starts) > 15:
            raise ValueError("too many main / left-wing shapes (a wing's range must start at slot 15 or before)")
        if len(order) > self.cfg.shp_n:
            raise ValueError("too many shapes (an empty slot 0 is needed when only wings have shapes)")
        data = [self.data[i] if i is not None else None for i in order] + [None] * (self.cfg.shp_n - len(order))
        return data, ((starts[0] & 15) << 4) | (starts[1] & 15)

    def free(self):
        """the first empty slot (or None)"""
        return next((k for k, v in enumerate(self.data) if v is None), None)


class Display:
    def __init__(self, cfg=None, sender=None, dry=False, log=None, host=None, port=None, feedback=False,
                 listen_host=None, listen_port=None):
        """host / port: VRChat's OSC input (default: KD_OSC_HOST / KD_OSC_PORT env, else config.json "osc").
        feedback: listen to VRChat's OSC output (listen_host / listen_port, default 127.0.0.1:9001): every frame is
        checked against the parameters the avatar reports back and resent when it did not arrive; /avatar/change
        resends everything."""
        self.cfg = cfg or Config()
        self.cm = Charmap()
        self.layout = Layout(self.cfg, self.cm, self.cfg.raw["text"]["fallback_char"])
        self.gfx = Canvas(self.cfg.GW, self.cfg.GH)      # graphics plane (screen / gfx_scale)
        self.mem = Memory(self.cfg)
        self.items = {}                      # id -> runs, in draw order
        self.item_opts = {}                  # id -> (move, page, x, y)
        self.item_screen = {}                # id -> 0 main, 1 left wing, 2 right wing
        self.wing_gfx = {}                   # 1 / 2 -> Canvas: a wing's picture (low-resolution mode only)
        self.clip_count = {}                 # id -> glyphs left out (outside the screen)
        self._next = 1
        self.photo_gray = None
        c = self.cfg.raw["color"]
        self.state = dict(on=True, wings=frozenset(), wing_text_y=(None, None), wing_shape_y=(0, 0), wing_pages=None, invert=False, gfx=True, text=True, mono=False, mono_fg=c["mono_fg"], mono_bg=c["mono_bg"],
                          dither=False, sprites=True, window=None, gfx_x=0, gfx_y=0, text_x=0, text_y=0,
                          gfx_vx=0, gfx_vy=0, text_vx=0, text_vy=0, zoom=1, mirror_x=False, mirror_y=False,
                          cycle=None, blink=None, text_wrap=None, text_clip=None, size_m=self.cfg.size_m,
                          shape_x=0, shape_y=0, shape_vx=0, shape_vy=0)
        self.shapes = ShapeLayer(self.cfg)    # hardware shapes (d.shapes.line(...), see kd/shapes.py)
        import random
        self.fx = random.randrange(2) << 6        # transition register; a random toggle so a restart replays nothing stale
        self.fx_queue = []                        # transitions waiting to be written (see transition())
        self.gfx_manual = False              # True: present() leaves bitmap + tile colours alone (raw memory writes)
        self.sprites = [dict(x=0, y=0, visible=False, flip_x=False, flip_y=False, double=False, above=False,
                             colors=(1, 2, 3), pattern=None) for _ in range(self.cfg.spr_n)]
        self.log = log
        self._shown = None                   # the appear / leave parameter as last sent
        self._shown_at = 0.0
        if sender is None and not dry:
            from .osc import Sender
            self.target = self.cfg.osc_target(host, port)
            sender = Sender(*self.target)
        self.sender = sender
        self.link = Link(self.cfg, self._send)
        self.seen = {}
        self.listen = None
        if feedback and not dry:
            from .osc import Listener
            self.listen = self.cfg.osc_listen(listen_port, listen_host)
            Listener(self.listen[1], self._on_osc, self.listen[0]).start()
            c = self.cfg
            names = [c.param_page()] + [c.param_byte(k) for k in range(c.P)]
            # nothing heard yet = unknown (VRChat only reports changes; no report at all = no feedback)
            self.link.check = lambda: (None if not any(n in self.seen for n in names) else
                                       (self.seen.get(names[0], 0), bytes(self.seen.get(n, 0) & 255 for n in names[1:])))

    def _on_osc(self, addr, args):
        if addr == "/avatar/change":
            self.seen.clear()
            self.link.forget()
        elif addr.startswith("/avatar/parameters/") and args:
            self.seen[addr[19:]] = int(round(args[0])) if not isinstance(args[0], str) else 0

    # ---------------- frames
    def _send(self, pid, payload):
        c = self.cfg
        items = [(f"/avatar/parameters/{c.param_page()}", pid)]
        items += [(f"/avatar/parameters/{c.param_byte(k)}", int(b)) for k, b in enumerate(payload)]
        if self.sender:
            self.sender.send(items)
        if self.log:
            self.log(pid, payload)

    # ---------------- text
    def text(self, s, x=0, y=0, width=None, align="left", scale=1, color=1, bg=0, box=False, invert=False,
             wrap=True, line_h=None, id=None, clip=True, move=False, page=False, pages=None, screen="main"):
        """color / bg: palette indices; box: paint the background; invert: box with the colours swapped.
        move: this text moves with text_x / text_y (and their speeds); once any item moves, only the moving items do,
        they are drawn after the others, wrap with text_wrap and are clipped to text_clip. Positions may lie beyond the
        screen (with clip=False): long marquee lines, a scrolled log.
        page: the item owns whole memory pages (padding, runs split at page ends): each of its pages can arrive in any
        order with any other page item's pages, so a changed line never blanks or moves other text (a chat line).
        pages: a fixed number of pages for it (it is cut to fit; it never moves the items after it).
        screen: "main", or "left" / "right" = a side screen (in its own coordinates; shows while the wings are open,
        d.set(wings=True), or only that one: wings="left" / "right"). Wing text goes into its wing's region of the text area (config wings.text_pages,
        d.set(wing_pages=...)); moving wing text moves with the main screen's text registers (three logs in step)."""
        sid = screen_id(screen)
        if scale not in (1, 2, "small", "tiny"):
            raise ValueError('text scale must be 1, 2, "small" (5x7 ASCII) or "tiny" (3x5 ASCII)')
        if scale in ("small", "tiny") and box:
            box = scale == "tiny"                     # the 5x7 font has no box background (its header bit is taken)
        if invert:
            color, bg, box = bg, color, True
        before = self.layout.clipped
        runs, bbox = self.layout.runs(s, x, y, width, align, scale, color, bg, box, wrap, line_h, clip)
        if id is None:
            id = self._next; self._next += 1
        self.items[id] = runs
        self.item_opts[id] = (move, page or bool(pages), x, y, pages)
        self.item_screen[id] = sid
        self.clip_count[id] = self.layout.clipped - before
        return id

    def compose(self, parts, id=None, move=False, page=False, pages=None, screen="main"):
        """several texts as ONE item (one page group: a chat line with its divider). parts: dicts with the text()
        arguments s, x, y, width, align, scale, color, bg, box (wrap and clip default to False). -> id"""
        runs = []
        before = self.layout.clipped
        for p in parts:
            r, _ = self.layout.runs(p["s"], p.get("x", 0), p.get("y", 0), p.get("width"), p.get("align", "left"),
                                    p.get("scale", 1), p.get("color", 1), p.get("bg", 0), p.get("box", False),
                                    p.get("wrap", False), p.get("line_h"), p.get("clip", False))
            runs += r
        if id is None:
            id = self._next; self._next += 1
        self.items[id] = runs
        self.item_opts[id] = (move, page or bool(pages), 0, 0, pages)
        self.item_screen[id] = screen_id(screen)
        self.clip_count[id] = self.layout.clipped - before
        return id

    def fits_pages(self, parts, pages):
        """would compose(parts, page=True, pages=pages) keep every glyph?"""
        from .memory import Memory, Page
        runs = []
        for p in parts:
            r, _ = self.layout.runs(p["s"], p.get("x", 0), p.get("y", 0), p.get("width"), p.get("align", "left"),
                                    p.get("scale", 1), 1, 0, False, False, None, False)
            runs += r
        m = Memory(self.cfg)
        m.set_runs([Page(True, 0, 0, pages)] + runs + [Page(False, 0, 0, pages)])
        return m.dropped == 0

    def pages_needed(self, s, scale=1, x=0, width=None):
        """memory pages this text takes as a page item"""
        from .memory import Memory, Page
        m = Memory(self.cfg)
        runs, _ = self.layout.runs(s, x, 0, width, "left", scale, 1, 0, False, False, None, False)
        used, _ = m.set_runs([Page(True)] + runs + [Page(False)])
        return used // self.cfg.P

    def remove(self, id):
        self.items.pop(id, None)
        self.item_opts.pop(id, None)
        self.item_screen.pop(id, None)

    def clear_text(self):
        self.items.clear()
        self.item_opts.clear()
        self.item_screen.clear()

    def marquee(self, s, y0, y1, direction="left", speed=40, scale=1, color=1, x=0, width=None, align="left",
                gap=None, id="marquee"):
        """text running through the rows y0..y1 pixel by pixel (the shader moves it: no frames while it runs, every
        viewer at his own phase). left: one line, right to left; up: wrapped lines, bottom to top (width, align).
        Uses the moving-text registers (text_x / text_y, speeds, text_wrap, text_clip): one marquee at a time.
        -> the wrap period in px."""
        c = self.cfg
        lh = c.line_h(scale)
        if direction == "left":
            line = s.replace("\n", " ")
            y = y0 + max(0, (y1 - y0 - c.glyph_h(scale)) // 2)
            self.text(line, x, y, wrap=False, scale=scale, color=color, clip=False, move=True, id=id)
            w = sum(c2[2] for l in self.layout.lines(line, None, scale, False) for c2 in l)
            gap = lh * 3 if gap is None else gap
            period = min(255, max(-(-(w + gap) // 8), -(-(c.W + lh * 2) // 8)))
            self.set(text_x=0, text_y=0, text_vx=-abs(speed), text_vy=0, text_wrap=(period * 8, 0), text_clip=(y0, y1))
            return period * 8
        width = width or c.W - x
        n = len(self.layout.lines(s, width, scale))
        self.text(s, x, y0, width, align, scale=scale, color=color, clip=False, move=True, id=id)
        gap = lh * 2 if gap is None else gap
        period = min(255, max(-(-(n * lh + gap) // 2), -(-(y1 - y0 + lh) // 2)))
        self.set(text_x=0, text_y=0, text_vx=0, text_vy=-abs(speed), text_wrap=(0, period * 2), text_clip=(y0, y1))
        return period * 2

    def measure(self, s, width=None, scale=1):
        lines = self.layout.lines(s, width or self.cfg.W, scale)
        return (max((max(0, sum(c[2] for c in l) - self.layout.slack(scale)) for l in lines if l), default=0),
                len(lines) * self.cfg.line_h(scale))

    # ---------------- graphics
    def photo(self, path_or_pixels):
        """show a picture in PHOTO mode (progressive DCT luminance + per-tile colour); the canvas is ignored until raw()
        is called. Accepts an image path (needs Pillow) or GH rows of gray floats / (r, g, b) tuples 0..1."""
        self.photo_gray = (Canvas.rgb_from(path_or_pixels, self.cfg.GW, self.cfg.GH) if isinstance(path_or_pixels, str)
                           else path_or_pixels)

    def image(self, path, dither=True):
        """colour picture in RAW mode: nearest palette colour per pixel (Floyd-Steinberg in palette space unless
        dither=False); each tile then keeps its best 2^bpp colours. Needs Pillow."""
        self.photo_gray = None
        self.gfx.image_palette(path, self.mem.palette, dither)

    def palette(self, colors):
        """16 (r, g, b) 0..255"""
        self.mem.set_palette(colors)

    def raw(self):
        self.photo_gray = None

    # ---------------- registers (all STATE: what the screen is, never "move by")
    def set(self, **kw):
        """on / invert / gfx / text / mono / mono_fg / mono_bg / dither / sprites: switches and colours
        gfx_x, gfx_y, text_x, text_y: layer offsets in screen pixels (content moves by +offset and wraps around)
        gfx_vx .. text_vy: auto-scroll in px/s, -128..127 (time based: every viewer has his own phase)
        zoom 1/2/4 (graphics), mirror_x / mirror_y (whole screen), window (x0, y0, x1, y1) screen px on graphics-tile cells or None
        cycle (start, length, steps_per_s) or None: palette colours start..start+length-1 rotate
        blink (colour, hz) or None: that palette colour blinks to colour 0 (hz in 0.5 steps, up to 7.5)
        size_m: the device's width in metres (a 128 px wide screen; menu size_min .. size_max, register size)
        shape_x, shape_y, shape_vx, shape_vy: the shape layer's offset / auto-scroll (like the text layer)
        wings: True / False / "left" / "right" (the side screens that unfold); wing_text_y (left, right): a side
        screen's own vertical offset for its moving text (None: it moves with text_y / text_vy); wing_shape_y (left, right):
        the offset of a side screen's shapes (like shape_y; its follow=True shapes stay put)
        legacy: scroll = graphics rows of 8 graphics px up, text_dy = text_y"""
        for k, v in kw.items():
            if k == "scroll":
                k, v = "gfx_y", (-v * 8 * self.cfg.gscale) % 256
            elif k == "text_dy":
                k = "text_y"
            assert k in self.state, k
            if k == "zoom":
                assert v in (1, 2, 4), v
            if k == "size_m":
                v = min(self.cfg.size_max, max(self.cfg.size_min, float(v)))
            if k == "wings":
                v = wing_sides(v)
            if k == "wing_text_y":
                v = tuple(None if x is None else int(round(x)) for x in v)
                assert len(v) == 2, "wing_text_y: (left, right), None = with text_y"
            if k == "text_wrap" and v is not None:
                wx, wy = v
                assert 0 <= wx <= 2040 and wx % 8 == 0 and 0 <= wy <= 510 and wy % 2 == 0, "text_wrap: x in 8 px, y in 2 px steps"
            if k == "text_clip" and v is not None:
                assert 0 <= v[0] <= v[1] <= self.cfg.H, v      # y0 == y1: the moving text is hidden
            if k in ("gfx_x", "gfx_y", "text_x", "text_y", "gfx_vx", "gfx_vy", "text_vx", "text_vy",
                     "shape_x", "shape_y", "shape_vx", "shape_vy"):
                v = int(round(v))
            self.state[k] = v

    def transition(self, effect="fade", show=True, duration=0.5):
        """play a transition on every viewer's screen (each starts it when the register reaches him; a late joiner plays
        it once on arrival and ends in the same state). effect: config effects.names; show False = hide the screen"""
        e = FX_EFFECTS.index(effect)
        d = min(range(len(self.cfg.fx_durations)), key=lambda k: abs(self.cfg.fx_durations[k] - duration))
        # queued, applied in order by tick(): a hide as soon as the previous value is on the air (and, at startup,
        # after the start value); a show additionally waits for the content that is on its way when the next
        # present() runs (each of those pages sent once; at most effects.wait_s). The toggle bit is chosen when the
        # value is applied, relative to what viewers hold, so every transition replays.
        self.fx_queue.append({"e": e, "show": show, "d": d, "wait": None, "asked": None})

    def set_size(self, i, lowres=None):
        """switch the screen to cfg.sizes[i] (e.g. 0 = 176x96, 1 = 128x128): every viewer's screen changes shape when
        the register arrives. lowres True / False switches the graphics resolution too (None = keep): low resolution =
        every graphics pixel 2x2 screen px, a quarter of the data (a picture in ~1/4 of the time). The graphics canvas
        starts empty at the new size / resolution; text positions are the caller's."""
        gs = None if lowres is None else (2 if lowres else 1) * self.cfg.gscale0
        if i == self.cfg.size and gs in (None, self.cfg.gscale):
            return
        self.cfg.set_size(i, gs)
        self.gfx = Canvas(self.cfg.GW, self.cfg.GH)
        self.wing_gfx = {}                            # (pictures of the old size / resolution)
        self.photo_gray = None

    def sprite(self, i, x=None, y=None, pattern=None, colors=None, visible=None, flip_x=None, flip_y=None,
               double=None, above_text=None, screen=None):
        """hardware sprite i: x, y screen px of its top left; pattern rows of 0..3 (0 transparent) or strings;
        colors = palette indices of values 1, 2, 3; double = 2 screen px per sprite pixel; above_text draws it over text;
        screen "main" / "left" / "right" (a wing: its own coordinates)"""
        sp = self.sprites[i]
        if screen is not None:
            sp["screen"] = screen_id(screen)
        x = None if x is None else int(round(x)); y = None if y is None else int(round(y))
        for k, v in (("x", x), ("y", y), ("pattern", pattern), ("colors", colors), ("visible", visible),
                     ("flip_x", flip_x), ("flip_y", flip_y), ("double", double), ("above", above_text)):
            if v is not None:
                sp[k] = v
        if pattern is not None and visible is None:
            sp["visible"] = True

    def wing_picture(self, side, pixels=None):
        """a picture on a side screen ("left" / "right"): rows of palette indices at the low-resolution graphics size
        (cfg.GW x cfg.GH after set_size(i, lowres=True)); None removes it. The palette is shared by all screens and every
        8x8 tile keeps at most 4 colours, like the main screen's. -> the wing's Canvas (draw into it, then present())"""
        k = screen_id(side)
        if k == 0:
            raise ValueError("wing_picture: side must be left or right (the main screen's picture is d.gfx)")
        if pixels is None:
            self.wing_gfx.pop(k, None)
            return None
        cv = Canvas(self.cfg.GW, self.cfg.GH)
        for y, row in enumerate(pixels[:self.cfg.GH]):
            for x, v in enumerate(row[:self.cfg.GW]):
                cv.set(x, y, v)
        self.wing_gfx[k] = cv
        return cv

    # ---------------- view helpers (driver side: draw where the screen shows, whatever the offsets are)
    def gfx_xy(self, sx, sy):
        """screen pixel -> graphics canvas pixel under the current offset / zoom"""
        st, gs, z = self.state, self.cfg.gscale, self.state["zoom"]
        return (int((sx / z - st["gfx_x"]) % self.cfg.W) // gs, int((sy / z - st["gfx_y"]) % self.cfg.H) // gs)

    def text_xy(self, sx, sy):
        """screen pixel -> text coordinates (where a run must start to appear there)"""
        return (sx - self.state["text_x"]) % self.cfg.W, (sy - self.state["text_y"]) % self.cfg.H

    def scroll(self, dx, dy, layer="gfx", clear=True):
        """move a layer's content by (dx, dy) screen px with ONE register change instead of resending it. For the graphics
        the strip that wrapped in from the other side is cleared (clear=True), ready for new content; returns that
        strip as screen rectangles [(x, y, w, h)] to draw into (use gfx_xy / text_xy for the coordinates)."""
        st, W, H = self.state, self.cfg.W, self.cfg.H
        kx, ky = ("gfx_x", "gfx_y") if layer == "gfx" else ("text_x", "text_y")
        st[kx] = (st[kx] + dx) % W; st[ky] = (st[ky] + dy) % H          # the shader wraps at the screen size
        z = st["zoom"] if layer == "gfx" else 1                         # graphics content moves dx * zoom screen px
        rects = []
        if dx: rects.append((0 if dx > 0 else max(0, W + dx * z), 0, min(W, abs(dx) * z), H))
        if dy: rects.append((0, 0 if dy > 0 else max(0, H + dy * z), W, min(H, abs(dy) * z)))
        if clear and layer == "gfx":
            gs = self.cfg.gscale
            for (x, y, w, h) in rects:
                for yy in range(y, y + h, gs):
                    for xx in range(x, x + w, gs):
                        cx, cy = self.gfx_xy(xx, yy)
                        self.gfx.set(cx, cy, 0)
        return rects

    # ---------------- compose
    def present(self):
        m, st = self.mem, self.state
        clipped = sum(self.clip_count.get(i, 0) for i in self.items)
        wings_cfg = self.cfg.wings
        wpics = {k: c for k, c in self.wing_gfx.items() if c is not None}
        if wpics and (self.photo_gray is not None or self.cfg.gscale == self.cfg.gscale0):
            raise ValueError("wing pictures need the low-resolution mode (set_size(i, lowres=True)) and no photo")
        if self.photo_gray is not None:
            m.set_photo(self.photo_gray)
        elif not self.gfx_manual:
            m.clear_gfx(); m.set_gfx(self.gfx.px)
            for k, cv in wpics.items():
                m.set_gfx(cv.px, tile0=self.cfg.wing_tiles[k - 1])
        if wings_cfg:
            m.reg("wing_gl", self.cfg.wing_tiles[0] if 1 in wpics else 0)
            m.reg("wing_gr", self.cfg.wing_tiles[1] if 2 in wpics else 0)
        from .memory import Page
        scr = lambda i: self.item_screen.get(i, 0)
        moving = any(o[0] for i, o in self.item_opts.items() if not scr(i))
        order = sorted((i for i in self.items if not scr(i)),
                       key=lambda i: bool(moving and self.item_opts.get(i, (False,))[0]))   # stable: still before moving

        def runs_of(ids, mark_move=False):
            runs, first = [], None
            for i in ids:
                mv, pg, x, y, npg = self.item_opts.get(i, (False, False, 0, 0, None))
                if mark_move and moving and mv and first is None:
                    first = len(runs)
                if pg:
                    runs.append(Page(True, 0, y, npg))
                runs += self.items[i]
                if pg:
                    runs.append(Page(False, 0, y, npg))
            return runs, first
        runs, first_move = runs_of(order, True)
        mvd = lambda i: self.item_opts.get(i, (False,))[0]
        wing_runs = {k - 1: (runs_of([i for i in self.items if scr(i) == k and not mvd(i)])[0],
                             runs_of([i for i in self.items if scr(i) == k and mvd(i)])[0]) for k in (1, 2)}
        if wings_cfg:
            wp = st["wing_pages"] or self.cfg.wing_text_pages
            used, glyphs = m.set_text(runs, {k: r for k, r in wing_runs.items() if r[0] or r[1]}, wp)
        else:
            used, glyphs = m.set_runs(runs)
        move_from = 0                                 # 0: everything moves (no item asked for move)
        if moving:
            idx = [k for k in m.run_index[first_move:] if k is not None] if first_move is not None else []
            move_from = idx[0] + 1 if idx else 255    # walk index + 1 of the first moving run (padding draws nothing)
        m.reg("text_move", min(255, move_from))
        if "screen" in self.cfg.regs:
            m.reg("screen", self.cfg.screen_reg())
        if "show" in self.cfg.regs:
            # the device's appear / leave (FX layer KD Show) | 2: the side screens unfold (FX layer KD Wings)
            # bits 1 / 2: the left / right side screen unfolds (FX layers KD Wing L / KD Wing R), each on its own
            m.reg("show", (1 | (sum(2 << (k - 1) for k in st["wings"]) if wings_cfg else 0)) if st["on"] else 0)
        if "size" in self.cfg.regs:                         # 1..255 = size_min..size_max (0 = not set: the default)
            c = self.cfg
            m.reg("size", 1 + round((st["size_m"] - c.size_min) / (c.size_max - c.size_min) * 254))
        tw = st["text_wrap"] or (0, 0)
        m.reg("text_wrap_x", tw[0] // 8); m.reg("text_wrap_y", tw[1] // 2)
        tc = st["text_clip"] or (0, 0)
        if tc[0] == tc[1]:
            tc = (1, 1)                               # empty band (y1 = 0 would mean "to the bottom")
        m.reg("text_clip_y0", tc[0]); m.reg("text_clip_y1", tc[1] % 256 if tc[1] < self.cfg.H else 0)
        m.reg("flags", (FLAG_ON if st["on"] else 0) | (FLAG_INVERT if st["invert"] else 0)
              | (FLAG_GFX if st["gfx"] else 0) | (FLAG_TEXT if st["text"] else 0)
              | (FLAG_MONO if st["mono"] else 0) | (FLAG_DITHER if st["dither"] else 0)
              | (FLAG_SPRITES if st["sprites"] else 0) | (FLAG_WINDOW if st["window"] else 0))
        m.reg("mono", ((st["mono_fg"] & 15) << 4) | (st["mono_bg"] & 15))
        for k in ("gfx_x", "gfx_y", "text_x", "text_y"):
            m.reg(k, st[k] % 256)
        if "wing_ly" in self.cfg.regs:                      # a wing's own scroll (0: it follows text_y)
            for k, v in zip(("wing_ly", "wing_ry"), st["wing_text_y"]):
                m.reg(k, 0 if v is None else 1 + int(v) % 255)
        if "wing_lsy" in self.cfg.regs:                     # a wing's shape offset (its FOLLOW shapes stay put)
            for k, v in zip(("wing_lsy", "wing_rsy"), st["wing_shape_y"]):
                m.reg(k, int(v or 0) % self.cfg.H)
        for k in ("gfx_vx", "gfx_vy", "text_vx", "text_vy"):
            m.reg(k, max(-128, min(127, int(st[k]))) & 0xFF)
        if self.cfg.shp_n:
            m.reg("shape_x", st["shape_x"] % self.cfg.W); m.reg("shape_y", st["shape_y"] % self.cfg.H)
            for k in ("shape_vx", "shape_vy"):
                m.reg(k, max(-128, min(127, int(st[k]))) & 0xFF)
            data, wing_shp = self.shapes.physical() if wings_cfg else (self.shapes.data, 0)
            for i in range(self.cfg.shp_n):
                m.set_shape(i, data[i])
            if wings_cfg:
                m.reg("wing_shp", wing_shp)
        m.reg("fx", self.fx)
        cy = st["cycle"]
        m.reg("cycle", ((cy[0] & 15) << 4) | (cy[1] & 15) if cy else 0)
        bl = st["blink"]
        m.reg("timing", ((min(15, int(cy[2])) if cy else 0) << 4) | (min(15, round(bl[1] * 2)) if bl else 0))
        zoom = {1: 0, 2: 1, 4: 2}[st["zoom"]]
        m.reg("blink_view", ((bl[0] & 15) << 4 if bl else 0) | zoom | (4 if st["mirror_x"] else 0) | (8 if st["mirror_y"] else 0))
        w = st["window"]
        if w:
            x0, y0, x1, y1 = (max(0, min(lim, int(v))) for v, lim in zip(w, (self.cfg.W, self.cfg.H, self.cfg.W, self.cfg.H)))
            if x1 <= x0 or y1 <= y0:
                raise ValueError(f"empty window {w}")
            q = 16                                    # cells of 16 screen px (4 bits reach 256 px)
            m.reg("win_x", ((x0 // q & 15) << 4) | (max(0, (x1 - 1)) // q & 15))
            m.reg("win_y", ((y0 // q & 15) << 4) | (max(0, (y1 - 1)) // q & 15))
        else:
            m.reg("win_x", 0); m.reg("win_y", 0)
        if wings_cfg:
            m.reg("wing_spr", sum((sp.get("screen", 0) & 3) << (2 * i) for i, sp in enumerate(self.sprites)))
        for i, sp in enumerate(self.sprites):
            attr = ((SPR_VISIBLE if sp["visible"] else 0) | (SPR_FLIPX if sp["flip_x"] else 0) | (SPR_FLIPY if sp["flip_y"] else 0)
                    | (SPR_DOUBLE if sp["double"] else 0) | (SPR_ABOVE if sp["above"] else 0))
            m.set_sprite(i, sp["x"], sp["y"], attr)
            m.set_sprite_colors(i, sp["colors"])
            if sp["pattern"] is not None:
                m.set_sprite_pattern(i, sp["pattern"])
        self.link.update(m.buf)
        for q in self.fx_queue:                       # a show requested before this present() waits for its content
            if q["wait"] is None:
                q["wait"], q["asked"] = set(self.link.pending()), self.link._ticks
        return {"runs": len(runs), "glyphs": glyphs, "text_bytes": used, "pages": len(self.link.pending()),
                "eta_s": round(self.link.eta(), 1), "missing": "".join(sorted(self.layout.missing)),
                "clipped": clipped, "dropped": m.dropped}

    def checksums(self, buf):
        """renderer name -> 16-bit position-weighted sum of its words, sum((2 * local index + 1) * word) mod 65536 with
        the checksum words left out, as every viewer's shader computes it. Odd weights are invertible mod 65536, so any
        error in a single word changes the sum; different weights catch swapped / moved words."""
        out = {}
        for r in self.cfg.renderers:
            if r.get("checksum"):
                out[r["name"]] = sum((2 * i + 1) * (buf[2 * w] * 256 + buf[2 * w + 1]) for i, w in enumerate(r["words"])
                                     if w not in self.cfg.sum_words and 2 * w + 1 < len(buf)) & 0xFFFF
        return out

    def _update_checksums(self):
        """write the checksums once everything else has been sent (otherwise every change would also resend the register
        page): until then viewers see the status LED amber, then green when their copy matches"""
        changed = self._update_fx()
        if self.link.pending():
            if changed:
                self.link.update(self.mem.buf)
            return
        sums = self.checksums(self.mem.buf)
        for r in self.cfg.renderers:
            if r.get("checksum"):
                a = 2 * r["sum_word"]
                v = sums[r["name"]]
                if self.mem.buf[a] != v >> 8 or self.mem.buf[a + 1] != v & 255:
                    self.mem.buf[a], self.mem.buf[a + 1] = v >> 8, v & 255
                    changed = True
        if changed:
            self.link.update(self.mem.buf)

    def _update_fx(self):
        """apply the first queued transition when it may go out (see transition()); True when the register changed"""
        if not self.fx_queue:
            return False
        lk, q = self.link, self.fx_queue[0]
        at = self.cfg.regs["fx"]
        reg_page = self.cfg.reg_base // self.cfg.P
        if reg_page in lk.force or lk.sent[at] != self.fx:
            return False                                  # the previous value (or the start value) is not out yet
        if q["wait"] is None:                             # no present() since the request: take the snapshot now
            q["wait"], q["asked"] = set(lk.pending()), lk._ticks
        if q["show"]:
            waited = (lk._ticks - q["asked"]) / self.cfg.rate_hz
            done = all(lk.sent_tick.get(p, -1) >= q["asked"] or not lk.dirty(p) for p in q["wait"])
            if not done and waited <= self.cfg.raw["effects"].get("wait_s", 10):
                return False
        toggle = (self.fx >> 6 & 1) ^ 1                   # differs from what viewers hold: it replays
        self.fx = q["e"] | (0 if q["show"] else 8) | (q["d"] << 4) | (toggle << 6)
        self.mem.reg("fx", self.fx)
        self.fx_queue.pop(0)
        return True

    def synced(self, buf):
        """renderer name -> does this copy of the memory match its checksum (what the status LED shows)"""
        sums = self.checksums(buf)
        return {n: buf[2 * w] * 256 + buf[2 * w + 1] == sums[n]
                for n, w in ((r["name"], r["sum_word"]) for r in self.cfg.renderers if r.get("checksum"))}

    def chime(self):
        """play the notification sound on the avatar once: one command frame (config commands.chime) goes out next"""
        self.link.command(self.cfg.commands[self.cfg.raw["sound"]["command"]])

    def _param(self, name, value):
        if self.sender:
            self.sender.send([(f"/avatar/parameters/{name}", value)])

    def _show_param(self, force=False):
        """the device's appear / leave parameter follows the on switch; resent now and then (an avatar reload resets
        it to hidden)"""
        import time
        sh = self.cfg.raw.get("show")
        if not sh or not sh.get("param"):
            return                                          # appear / leave travels in register show
        on, now = bool(self.state["on"]), time.monotonic()
        if force or on != self._shown or now - self._shown_at >= sh.get("resend_s", 5):
            self._param(sh["param"], on)
            self._shown, self._shown_at = on, now

    def tick(self):
        import time
        self._show_param()
        self._update_checksums()
        return self.link.tick()

    def settled(self):
        """nothing left to send and the checksums written (what until_idle waits for)"""
        if self.link.pending() or self.fx_queue or self.link.cmds:
            return False
        sums = self.checksums(self.link.want)
        return all(self.link.want[2 * r["sum_word"]] * 256 + self.link.want[2 * r["sum_word"] + 1] == sums[r["name"]]
                   for r in self.cfg.renderers if r.get("checksum"))

    def run(self, until_idle=False, stop=None):
        """send at sync.rate_hz until stop() (or, with until_idle, until everything incl. the checksums is out)"""
        import time
        t = time.monotonic()
        while not (stop and stop()):
            self.tick()
            if until_idle and self.settled() and not self.link.pending():
                return
            t += 1.0 / self.cfg.rate_hz
            d = t - time.monotonic()
            if d > 0:
                time.sleep(d)
            else:
                t = time.monotonic()

    def preview(self, path, scale=4):
        from .sim import render, to_png
        return to_png(render(self.mem), path, scale)
