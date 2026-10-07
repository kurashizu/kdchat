"""The display memory image and its encoders. Pure python (no numpy), so the client runs anywhere.

Memory layout and bit formats: see config.py. The decoder in sim.py mirrors the shader exactly.
"""
import json, math, os
from .config import Config, ROOT, MODE_ASCII, MODE_COMMON, MODE_EXT, MODE_SKIP, MODE_TINY, MODE_SMALL, GFX_RAW, GFX_PHOTO


class Charmap:
    """the glyph table: code point (or Thai cluster) -> glyph. Besides the CJK tables: a half-width block (6 px: Latin,
    Greek, Cyrillic, symbols; a copy of ASCII first) and a narrow block (8 px: Hebrew, Arabic forms, Thai; a copy of
    ASCII first), see glyphs_extra.py. A character in both the CJK part and the half block (é, Greek, Cyrillic, “ ...)
    is drawn half width unless full=True (the layout decides by its neighbours)."""

    def __init__(self, path=None):
        with open(path or os.path.join(ROOT, "generated", "charmap.json"), encoding="utf-8") as f:
            cm = json.load(f)
        self.version = cm["version"]
        t = cm["table"]
        self.table = [ord(ch) for ch in t] if isinstance(t, str) else t     # (a string since the compact charmap)
        self.n_ascii, self.n_common = cm["ascii"], cm["common"]
        self.half_range = tuple(cm.get("half_range", (len(self.table), len(self.table))))
        self.narrow_range = tuple(cm.get("narrow_range", (len(self.table), len(self.table))))
        h0, h1 = self.half_range
        n0, n1 = self.narrow_range
        self.index, self.half, self.narrow, self.clusters = {}, {}, {}, {}
        cl = cm.get("clusters", [])
        for i, cp in enumerate(self.table):
            if cp >= 0xF0000:                                   # a Thai cluster's stand-in
                self.clusters[cl[cp - 0xF0000]] = i
            elif h0 <= i < h1:
                self.half.setdefault(cp, i)
            elif n0 <= i < n1:
                self.narrow.setdefault(cp, i)
            else:
                self.index.setdefault(cp, i)

    def mode_of(self, ch, full=False):
        """-> (mode, code) or None if the font has no glyph (ch: a character or a Thai cluster)"""
        if len(ch) > 1:
            g = self.clusters.get(ch)
            return (MODE_EXT, g) if g is not None else None
        cp = ord(ch)
        if 0x20 <= cp < 0x7F:
            return MODE_ASCII, cp - 0x20
        g = self.half.get(cp)
        if g is not None and not (full and cp in self.index):
            return MODE_EXT, g
        g = self.index.get(cp)
        if g is None:
            g = self.narrow.get(cp)
            return (MODE_EXT, g) if g is not None else None
        if self.n_ascii <= g < self.n_ascii + self.n_common:
            return MODE_COMMON, g - self.n_ascii
        return MODE_EXT, g

    def both(self, ch):
        """drawn half or full width depending on its neighbours?"""
        return len(ch) == 1 and ord(ch) in self.half and ord(ch) in self.index

    def ascii_as(self, code, block):
        """an ASCII glyph's code in the half / narrow block (code = ASCII code, 0 = space)"""
        return (self.half_range if block == "half" else self.narrow_range)[0] + code


class BitWriter:
    def __init__(self):
        self.bits = []

    def put(self, v, n):
        self.bits.extend((v >> (n - 1 - i)) & 1 for i in range(n))

    def bytes(self):
        b = bytearray(math.ceil(len(self.bits) / 8))
        for i, bit in enumerate(self.bits):
            if bit:
                b[i >> 3] |= 0x80 >> (i & 7)
        return b


class Run:
    """one text run: glyphs advance left to right from (x, y) at a fixed pitch (cfg.adv: 6 / 12 px + gap) x scale.
    fg / bg are palette indices; box draws the cell background in bg. x / y are virtual: anywhere, also beyond the
    screen (set_runs chains what the 7-bit header fields cannot hold).
    mode SKIP: no glyphs, skip = data bytes jumped over (padding; codes empty)."""
    __slots__ = ("x", "y", "mode", "codes", "fg", "bg", "box", "scale", "skip")

    def __init__(self, x, y, mode, codes, fg=1, bg=0, box=False, scale=1, skip=0):
        self.x, self.y, self.mode, self.codes = x, y, mode, list(codes)
        self.fg, self.bg, self.box, self.scale, self.skip = fg, bg, box, scale, skip


class Page:
    """set_runs marker: the runs between Page(start=True) and Page(start=False) begin on a page boundary, are split so
    that every page starts with a run of their own, and are padded (skip runs at x, y) to the end of their last page, or
    to `pages` pages (fixed size: the item never moves what follows when it grows or shrinks; it is cut at that size).
    So every page of the item can change in any order with any other page: a chat line. Empty: one page (or pages)."""
    __slots__ = ("start", "x", "y", "pages")

    def __init__(self, start, x=0, y=0, pages=None):
        self.start, self.x, self.y, self.pages = start, x, y, pages

    def __repr__(self):
        return f"Run({self.x},{self.y},m{self.mode},{len(self.codes)}ch,c{self.fg}/{self.bg}{',box' if self.box else ''}{',x2' if self.scale == 2 else ''})"


def rgb565(c):
    r, g, b = c
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def rgb565_float(v):
    return (((v >> 11) & 31) / 31.0, ((v >> 5) & 63) / 63.0, (v & 31) / 31.0)


def nearest(palette, rgb):
    return min(range(len(palette)), key=lambda i: sum((a - b) ** 2 for a, b in zip(palette[i], rgb)))


class Memory:
    def __init__(self, cfg=None):
        self.cfg = cfg or Config()
        self.buf = bytearray(self.cfg.pages * self.cfg.P)
        self.set_palette(self.cfg.palette)

    # ---------------- registers
    def reg(self, name, value=None):
        a = self.cfg.regs[name]
        if value is not None:
            self.buf[a] = value & 0xFF
        return self.buf[a]

    # ---------------- palette
    def set_palette(self, colors):
        """colors: 16 (r, g, b) 0..255"""
        assert len(colors) == 16
        self.palette = [tuple(c) for c in colors]
        for i, c in enumerate(self.palette):
            v = rgb565(c)
            self.buf[self.cfg.pal_base + 2 * i] = v >> 8
            self.buf[self.cfg.pal_base + 2 * i + 1] = v & 255

    # ---------------- graphics
    def set_gfx(self, pixels, tile0=0):
        """pixels: GH rows of GW palette indices -> RAW mode. Each 8x8 tile keeps at most 2^bpp colours: if it has more,
        the set with the smallest total RGB error is kept and the other pixels take their nearest kept colour.
        tile0: first tile (a wing's picture: config wings.tiles)."""
        c = self.cfg
        K = c.colors_per_tile
        pal = self.palette
        err = [[sum((a - b) ** 2 for a, b in zip(pal[i], pal[j])) for j in range(16)] for i in range(16)]
        for ty in range(c.tiles_y):
            for tx in range(c.tiles_x):
                t = tile0 + ty * c.tiles_x + tx
                cells = [pixels[ty * 8 + y][tx * 8 + x] & 15 for y in range(8) for x in range(8)]
                counts = {}
                for v in cells:
                    counts[v] = counts.get(v, 0) + 1
                if len(counts) <= K:
                    chosen = sorted(counts, key=lambda v: (v != 0, v))       # colour 0 first (value 0 = background)
                else:
                    chosen = []
                    for _ in range(K):
                        best = min((i for i in counts if i not in chosen),
                                   key=lambda i: sum(n * min(err[v][j] for j in chosen + [i]) for v, n in counts.items()))
                        chosen.append(best)
                slot = {}
                for v in counts:
                    slot[v] = chosen.index(v) if v in chosen else min(range(len(chosen)), key=lambda k: err[v][chosen[k]])
                entry = chosen + [0] * (K - len(chosen))
                # tile entry: nibble k = colour of pixel value k
                ev = 0
                for k in range(K):
                    ev = (ev << 4) | entry[k]
                for b in range(c.tc_bytes_per):
                    self.buf[c.tc_base + t * c.tc_bytes_per + b] = (ev >> (8 * (c.tc_bytes_per - 1 - b))) & 255
                # bitmap rows
                for y in range(8):
                    row = 0
                    for x in range(8):
                        row = (row << c.bpp) | slot[cells[y * 8 + x]]
                    for b in range(c.bpp):
                        self.buf[c.bitmap_base + (t * 8 + y) * c.bpp + b] = (row >> (8 * (c.bpp - 1 - b))) & 255
        self.reg("gfx_mode", GFX_RAW)

    def set_photo(self, img):
        """img: GH rows of GW values, each a gray float 0..1 or an (r, g, b) tuple 0..1 -> PHOTO mode:
        luminance as per-tile DCT planes (progressive), chroma one byte per tile in the tile-colour area"""
        c = self.cfg
        rgb = [[(p, p, p) if isinstance(p, (int, float)) else p for p in row] for row in img]
        Y = [[0.299 * r + 0.587 * g + 0.114 * b for (r, g, b) in row] for row in rgb]
        coefs = photo_coefs(c, Y)
        # tile by tile: each tile's coefficients inside its own bitmap bytes (a renderer only holds its own tiles)
        tb = 64 * c.bpp // 8
        assert c.dc_bits + (c.coefs - 1) * c.ac_bits <= tb * 8, "photo coefficients do not fit a tile"
        self.clear_gfx()
        for t in range(c.n_tiles):
            w = BitWriter()
            w.put(coefs[t][0], c.dc_bits)
            for j in range(1, c.coefs):
                w.put(coefs[t][j], c.ac_bits)
            b = w.bytes()
            self.buf[c.bitmap_base + t * tb:c.bitmap_base + t * tb + len(b)] = b
        q = (1 << c.chroma_bits)
        for ty in range(c.tiles_y):
            for tx in range(c.tiles_x):
                cb = cr = 0.0
                for y in range(8):
                    for x in range(8):
                        r, g, bl = rgb[ty * 8 + y][tx * 8 + x]
                        yy = Y[ty * 8 + y][tx * 8 + x]
                        cb += (bl - yy) * 0.564; cr += (r - yy) * 0.713
                enc = lambda v: max(0, min(q - 1, round(v / 64 * q) + q // 2))      # value = (n - q/2) / q
                self.buf[c.tc_base + (ty * c.tiles_x + tx) * c.tc_bytes_per] = (enc(cb) << 4) | enc(cr)
        self.reg("gfx_mode", GFX_PHOTO)

    def clear_gfx(self):
        c = self.cfg
        self.buf[0:c.clear_bytes] = bytes(c.clear_bytes)

    # ---------------- text
    def run_bytes(self, r):
        c = self.cfg
        if r.mode == MODE_SKIP:
            return c.hdr_bytes + r.skip
        return c.hdr_bytes + (len(r.codes) * c.code_bits[MODE_ASCII if r.mode in (MODE_TINY, MODE_SMALL) else r.mode] + 7) // 8

    def set_text(self, main, wings=None, wing_pages=(0, 0)):
        """the text area with side-screen regions: main runs first, then (when wings has runs) the left wing's region
        (wing_pages[0] pages) and the right wing's (wing_pages[1]) at the END of the area, each starting on its own page.
        wings: {0: left, 1: right}, each a run list (still) or (still runs, moving runs): the moving ones start on a page
        of their own (register wing_mv = that page counted from the region start) and move with the main screen's text
        registers. The main part is padded up to the first region (the walk must reach it); wing runs use the wing's
        own screen coordinates. Sets wing_tl / wing_tr / wing_mv. -> (bytes, glyphs) like set_runs"""
        c, P = self.cfg, self.cfg.P
        wings = {k: (v if isinstance(v, tuple) else (v, [])) for k, v in (wings or {}).items() if v}
        wings = {k: v for k, v in wings.items() if v[0] or v[1]}
        npg = [wing_pages[k] if k in wings else 0 for k in (0, 1)]
        total = c.text_bytes // P
        has_mv = "wing_mv" in c.regs

        def off():
            if "wing_tl" in c.regs:
                self.reg("wing_tl", 0); self.reg("wing_tr", 0)
            if has_mv:
                self.reg("wing_mv", 0)
        if not any(npg):
            off()
            return self.set_runs(main)
        assert sum(npg) < total, "wing regions take the whole text area"
        tl = total - npg[0] - npg[1]
        tr = total - npg[1]
        self.reg("wing_tl", tl if npg[0] else 0); self.reg("wing_tr", tr if npg[1] else 0)
        used, glyphs = self.set_runs(main, limit=tl * P, fill=True)
        dropped, index = self.dropped, self.run_index         # (run_index: the main runs, for text_move)
        if self.fill_failed:                          # the run limit: the wings cannot be reached this time
            off()
            self.buf[c.text_base + tl * P:c.text_base + c.text_bytes] = bytes(c.text_bytes - tl * P)
            self.dropped = dropped + sum(len(r.codes) for v in wings.values() for part in v for r in part if isinstance(r, Run))
            self.run_index = index
            return used, glyphs
        counts = (self._runs, glyphs)
        mv = [0, 0]
        for k, start in ((0, tl), (1, tr)):
            if not npg[k]:
                continue
            still, moving = wings[k]
            last = k == 1 or not npg[1]
            if not moving:
                u, g = self.set_runs(still, base=start * P, limit=npg[k] * P, fill=not last, counts=counts)
                dropped += self.dropped; counts = (self._runs, g); glyphs = g
                continue
            # still part: whole pages of its own (at least one: wing_mv 0 would mean "nothing moves"), padded to its end
            c0 = counts
            u, g = self.set_runs(still, base=start * P, limit=npg[k] * P, counts=c0)
            sp = max(1, -(-u // P))
            u, g = self.set_runs(still, base=start * P, limit=sp * P, fill=True, counts=c0)
            dropped += self.dropped; counts = (self._runs, g); glyphs = g
            mv[k] = min(15, sp)
            u, g = self.set_runs(moving, base=(start + sp) * P, limit=(npg[k] - sp) * P, fill=not last, counts=counts)
            dropped += self.dropped; counts = (self._runs, g); glyphs = g
        if has_mv:
            self.reg("wing_mv", (mv[0] << 4) | mv[1])
        self.dropped, self.run_index = dropped, index
        return used, glyphs

    def set_runs(self, runs, base=0, limit=None, fill=False, counts=(0, 0)):
        """pack runs (and Page markers) into the text area, in order, up to the first run that does not fit (runs, glyphs,
        bytes); self.dropped = glyphs left out (that run and all after it, so later text never shows while earlier text
        is missing). No terminator is needed when fewer than hdr_bytes bytes are left: the decoders stop there anyway.
        Positions: a run whose x, y fit the header fields is absolute; else it is chained (top header bit) to the run
        before it: y field = rows below that run; with y field 0 the run continues that run's line and the x field is
        the gap after its last glyph, else x is absolute. self.run_index[i] = walk index of runs[i] (None: no run)."""
        c = self.cfg
        P = c.P
        out = bytearray()
        n_runs, n_glyphs = counts                     # (earlier regions count against the same limits)
        limit = c.text_bytes - base if limit is None else limit
        self.dropped = 0
        self.run_index = [None] * len(runs)
        prev = None                                   # (x, y, end x) of the last packed run
        X, Y = 1 << c.xb, 1 << c.yb
        stop = False

        def encode(r):
            if 0 <= r.x < X and 0 <= r.y < Y:
                return 0, r.x, r.y
            if prev is None:
                return None
            if r.y == prev[1] and 0 <= r.x - prev[2] < X:
                return 1, r.x - prev[2], 0
            if 0 < r.y - prev[1] < Y and 0 <= r.x < X:
                return 1, r.x, r.y - prev[1]
            return None

        def pack(r):
            nonlocal prev, n_glyphs, n_runs, out
            e = encode(r)
            if e is None:
                return False
            chain, fx, fy = e
            skip = r.mode == MODE_SKIP
            tiny, small = r.mode == MODE_TINY, r.mode == MODE_SMALL
            cb = c.code_bits.get(MODE_ASCII if tiny or small else r.mode, 8)
            w = BitWriter()
            w.put(chain, c.hdr_bytes * 8 - c.hdr_bits_used)         # padding first (the top bit = chain)
            w.put(fx, c.xb)
            w.put(fy, c.yb)
            w.put(1 if (r.scale == 2 or tiny) else 0, 1)
            w.put(MODE_SKIP if tiny or small else r.mode, 2)
            w.put(r.skip if skip else len(r.codes), c.lenb)
            w.put(r.fg & 15, 4)
            w.put(r.bg & ((1 << c.bgb) - 1), c.bgb)
            w.put(1 if (r.box and not tiny) or small else 0, 1)
            if skip:
                w.put(0, 8 * r.skip)
            for code in r.codes:
                w.put(code, cb)
            b = w.bytes()
            if (n_runs + 1 > c.max_runs or n_glyphs + len(r.codes) > c.max_glyphs or len(out) + len(b) > limit):
                return None
            out += b
            n_glyphs += len(r.codes); n_runs += 1
            prev = (r.x, r.y, r.x + (0 if skip else len(r.codes) * c.adv(r.mode, r.scale, r.codes[0] if r.codes else None)))
            return True

        def pad(x, y, whole):
            """skip runs up to the next page boundary (a whole page if already on one and whole)"""
            r = (-len(out)) % P
            if r == 0 and whole:
                r = P
            if r == 0:
                return True
            if r <= c.hdr_bytes:
                r += P                                  # a skip run is its header + >= 1 byte (length 0 = the end)
            while r:
                n = min(r, c.hdr_bytes + (1 << c.lenb) - 1)
                if r - n and r - n <= c.hdr_bytes:
                    n = r - c.hdr_bytes - 1
                if not pack(Run(x, y, MODE_SKIP, [], skip=n - c.hdr_bytes)):
                    return False
                r -= n
            return True

        def fit(rem, r):
            """glyphs of r that fit the rem bytes left in this page, leaving 0 or room for a padding run (> hdr_bytes)"""
            cb = c.code_bits[MODE_ASCII if r.mode in (MODE_TINY, MODE_SMALL) else r.mode]
            for n in range(len(r.codes), 0, -1):
                left = rem - c.hdr_bytes - (n * cb + 7) // 8
                if left == 0 or left > c.hdr_bytes:
                    return n
            return 0

        item = None                                   # open page item: (start offset, Page)
        for i, r in enumerate(runs):
            if isinstance(r, Page):
                if r.start:
                    ok = pad(r.x, r.y, False)
                    item = (len(out), r)
                else:
                    start, pg = item
                    item = None
                    ok = pad(r.x, r.y, len(out) == start)
                    if ok and pg.pages:
                        while ok and len(out) < start + pg.pages * P:
                            ok = pad(r.x, r.y, True)
                if not ok:
                    self.dropped += sum(len(x.codes) for x in runs[i:] if isinstance(x, Run))
                    break
                continue
            assert r.mode == MODE_SKIP or 0 < len(r.codes) <= c.max_run_len, r
            if item is not None and r.mode != MODE_SKIP:
                # inside a page item: split the run at page ends (each page starts with a run), stay in its pages
                start, pg = item
                codes, x, res = list(r.codes), r.x, True
                first = None                          # walk index of the first part
                while codes and res:
                    rem = P - (len(out) - start) % P
                    if pg.pages and len(out) >= start + pg.pages * P:
                        res = False                   # the item is full: the rest is cut
                        break
                    n = fit(rem, Run(x, r.y, r.mode, codes, scale=r.scale))
                    if n == 0:
                        if not pad(pg.x, pg.y, False) or (pg.pages and len(out) > start + pg.pages * P):
                            res = None
                        continue
                    part = Run(x, r.y, r.mode, codes[:n], r.fg, r.bg, r.box, r.scale)
                    res = pack(part)
                    if res:
                        if first is None:
                            first = n_runs - 1
                        x += n * c.adv(r.mode, r.scale, r.codes[0] if r.codes else None)
                        codes = codes[n:]
                if res is None:
                    self.dropped += sum(len(x.codes) for x in runs[i:] if isinstance(x, Run))
                    break
                self.run_index[i] = first
                if res is False or codes:
                    self.dropped += len(codes)
                continue
            # outside page items: split where needed so that no run ends 1..hdr_bytes bytes before a page boundary
            # (the next header must lie in one page: its length / mode / font bits would otherwise depend on two pages)
            pieces, first, stop = [r], None, False
            while pieces:
                q = pieces.pop(0)
                if q.mode != MODE_SKIP:
                    cb = c.code_bits[MODE_ASCII if q.mode in (MODE_TINY, MODE_SMALL) else q.mode]
                    def ok(k):
                        rem = (-(len(out) + c.hdr_bytes + (k * cb + 7) // 8)) % P
                        return rem == 0 or rem > c.hdr_bytes
                    k = next((k for k in range(len(q.codes), 0, -1) if ok(k)), None)
                    if k is None:                    # no split helps: start it on the next page
                        if len(out) % P and pad(q.x, q.y, False):
                            pieces.insert(0, q)
                            continue
                        k = len(q.codes)
                    if k < len(q.codes):
                        pieces.insert(0, Run(q.x + k * c.adv(q.mode, q.scale, q.codes[0] if q.codes else None), q.y, q.mode, q.codes[k:], q.fg, q.bg, q.box, q.scale))
                        q = Run(q.x, q.y, q.mode, q.codes[:k], q.fg, q.bg, q.box, q.scale)
                res = pack(q)
                if res is None:                      # full: this run and everything after it
                    self.dropped += len(q.codes) + sum(len(x.codes) for x in pieces) + \
                        sum(len(x.codes) for x in runs[i + 1:] if isinstance(x, Run))
                    stop = True
                    break
                if res is False:                     # position not representable: only this piece
                    self.dropped += len(q.codes)
                    continue
                if first is None:
                    first = n_runs - 1
            if stop:
                break
            self.run_index[i] = first
        if fill and len(out) < limit:
            # pad to the region's end with skip runs: the walk goes on into the next region (a zero header would end it)
            while len(out) < limit and pad(0, 0, True):
                pass
        self.fill_failed = fill and len(out) < limit   # (out of runs: the regions after it cannot be reached)
        area = bytearray(limit)
        area[:len(out)] = out                       # zero header after the last run = end
        assert len(area) == limit, (len(area), limit)
        self.buf[c.text_base + base:c.text_base + base + limit] = area
        self._runs = n_runs
        return len(out), n_glyphs

    # ---------------- sprites
    def set_sprite(self, i, x, y, attr):
        """screen position (top left, may be negative / beyond the edge by up to config sprites.offset) + attr bits"""
        c = self.cfg
        o = c.spr_off
        a = c.spr_regs + 3 * i
        self.buf[a] = max(0, min(255, x + o)); self.buf[a + 1] = max(0, min(255, y + o)); self.buf[a + 2] = attr & 0xFF

    def set_sprite_colors(self, i, colors):
        """palette indices of pixel values 1, 2, 3 (value 0 is transparent)"""
        c = self.cfg
        k = [0] + list(colors)[:3] + [0] * (3 - len(list(colors)[:3]))
        self.buf[c.spr_cols + 2 * i] = ((k[0] & 15) << 4) | (k[1] & 15)
        self.buf[c.spr_cols + 2 * i + 1] = ((k[2] & 15) << 4) | (k[3] & 15)

    def set_sprite_pattern(self, i, rows):
        """rows: size rows of size values 0..3 (or strings: ' ' / '.' = 0, digits = value)"""
        c = self.cfg
        n = c.spr_size
        base = c.spr_pat + i * c.spr_pat_bytes
        for y in range(n):
            row = rows[y] if y < len(rows) else []
            vals = [(0 if ch in " ." else int(ch)) for ch in row] if isinstance(row, str) else list(row)
            vals = (vals + [0] * n)[:n]
            for b in range(c.spr_row_bytes):
                v = 0
                for k in range(4):
                    v = (v << 2) | (vals[b * 4 + k] & 3)
                self.buf[base + y * c.spr_row_bytes + b] = v

    # ---------------- shapes
    def set_shape(self, i, data):
        """shape slot i <- 10 bytes (kd.shapes.encode), or None = empty"""
        c = self.cfg
        a = c.shp_base + i * c.shp_bytes_per
        self.buf[a:a + c.shp_bytes_per] = data if data is not None else bytes(c.shp_bytes_per)

    def page(self, p):
        return self.buf[p * self.cfg.P:(p + 1) * self.cfg.P]


def photo_coefs(c, gray):
    """per 8x8 tile: zigzag DCT coefficients quantised like the shader expects"""
    from .sim import zigzag, dct_c
    zz = zigzag(c.coefs)
    C = dct_c()
    L = (1 << (c.ac_bits - 1)) - 1
    dmax = (1 << c.dc_bits) - 1
    out = []
    for ty in range(c.tiles_y):
        for tx in range(c.tiles_x):
            blk = [[gray[ty * 8 + y][tx * 8 + x] - 0.5 for x in range(8)] for y in range(8)]
            q = []
            for k, (u, v) in enumerate(zz):
                d = sum(C[u][y] * C[v][x] * blk[y][x] for y in range(8) for x in range(8))
                if k == 0:
                    q.append(max(0, min(dmax, round((d / 8 + 0.5) * dmax))))
                else:
                    q.append(max(0, min(2 * L, round(d / c.ac_range * L) + L)))
            out.append(q)
    return out
