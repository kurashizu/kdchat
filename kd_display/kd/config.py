"""Config loading + the derived memory layout. Shared by build.py (avatar side) and the client, so both always agree.

Memory = one flat byte array, synced in pages of `payload_bytes`:
    [ bitmap | tilecol | palette ]  [ text ]  [ regs ]  [ sprites ]  (hole)  [ shapes ]     each bracket starts on a page boundary
bitmap   GW*GH*bpp/8 bytes (GW = W / gfx_scale), 8x8 tiles row-major, per tile 8 rows of bpp bytes, MSB = left pixel
         (bpp 2: two bits per pixel, MSB pair first). PHOTO mode: the same bytes hold DCT coefficient planes
         (plane 0 = DC of every tile, then AC planes), so a progressive send fills the low addresses first.
tilecol  per tile 2^bpp palette indices (4 bits each, index k = colour of pixel value k). PHOTO mode: byte 0 of each
         entry = chroma (Cb high nibble, Cr low nibble).
palette  16 x RGB565 (one 16-bit word each, high byte first).
text     runs packed back to back, byte aligned: header + codes (MSB-first bit stream); a header with len 0 ends the list.
         header = x, y, scale2, mode(2), len, fg(4), bg(4), box(1), padded to whole bytes.
regs     one byte each (config "registers", meaning in config "_registers_doc"). All registers hold STATE, never
         actions, so a page sent again changes nothing and a late joiner ends up exactly where everyone else is.
sprites  per sprite x, y, attr; per sprite 2 colour bytes; per sprite a size x size 2 bpp pattern (config "sprites").
shapes   (after a one-page hole = the clear command's page id) 10 bytes per shape, 3 per page (config "shapes", kd/shapes.py).
Page id 0 = idle, 1..pages = memory pages, then the command ids (clear graphics).
On the avatar, byte pairs are packed into 16-bit words (one animated material value each: the animator's cost grows
with the square of the number of animated values per renderer), and the words are split over renderers (config
"renderers"; shared words like the palette / registers are animated on every renderer that needs them).
"""
import json, math, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # display/

MODE_ASCII, MODE_COMMON, MODE_EXT, MODE_SKIP = 0, 1, 2, 3   # SKIP: no glyphs, len = data bytes to skip
MODE_TINY = 4          # 3x5 ASCII: stored as mode 3 with the scale bit set (a skip run never has it)
MODE_SMALL = 5         # 5x7 ASCII: stored as mode 3 with the box bit set (no box background for it)
SMALL_FONTS = {"tiny": (MODE_TINY, 4, 5, 6), "small": (MODE_SMALL, 6, 7, 9)}   # scale -> mode, advance, glyph h, line h
FLAG_ON, FLAG_INVERT, FLAG_GFX, FLAG_TEXT, FLAG_MONO, FLAG_DITHER, FLAG_SPRITES, FLAG_WINDOW = 1, 2, 4, 8, 16, 32, 64, 128
SPR_VISIBLE, SPR_FLIPX, SPR_FLIPY, SPR_DOUBLE, SPR_ABOVE = 1, 2, 4, 8, 16
FX_EFFECTS = ["cut", "fade", "wipe_right", "wipe_down", "slide_left", "slide_up", "dissolve", "iris"]
GFX_RAW, GFX_PHOTO = 0, 1


def bits_for(n):
    return max(1, math.ceil(math.log2(n)))


class Config:
    def __init__(self, path=None):
        self.path = path or os.path.join(ROOT, "config.json")
        with open(self.path, encoding="utf-8") as f:
            self.raw = json.load(f)
        c = self.raw
        s, sy, t, ph, co = c["screen"], c["sync"], c["text"], c["photo"], c["color"]
        self.tile = s["tile"]
        self.gscale0 = self.gscale = s.get("gfx_scale", 1)
        assert self.tile == 8, "tile must be 8"
        # screen sizes the avatar can switch between at run time (register "screen"): the memory layout and the text
        # header are sized for the largest, the current size (set_size) decides how the graphics tiles are arranged
        self.sizes = [tuple(v) for v in s.get("sizes", [[s["width"], s["height"]]])]
        for w, h in self.sizes:     # (multiples of 16: the low-resolution graphics mode has 16 px tiles)
            assert w % 16 == 0 and h % 16 == 0, (w, h)
        self.W_max, self.H_max = max(w for w, _ in self.sizes), max(h for _, h in self.sizes)
        self.tiles_mem = max((w // self.gscale // 8) * (h // self.gscale // 8) for w, h in self.sizes)
        self.set_size(s.get("size", 0))
        self.bpp = co["bpp"]
        assert self.bpp in (1, 2)
        self.colors_per_tile = 1 << self.bpp
        self.tc_bytes_per = self.colors_per_tile * 4 // 8            # 1 (bpp 1) or 2 (bpp 2)
        self.palette = [tuple(p) for p in co["palette"]]
        assert len(self.palette) == 16
        self.P = sy["payload_bytes"]
        self.prefix = sy["param_prefix"]
        self.rate_hz = sy["rate_hz"]

        # text header: x, y, scale2, mode(2), len, fg(4), bg(4), box
        self.xb, self.yb = bits_for(self.W_max), bits_for(self.H_max)
        self.lenb = t["len_bits"]
        # background colour: 4 bits, fewer (palette 0..7 / 0..3) when screens wider / taller than 128 px need the bits
        self.bgb = next(b for b in (4, 3, 2, 1) if self.xb + self.yb + 1 + 2 + self.lenb + 4 + b + 1 < 32)
        self.hdr_bits_used = self.xb + self.yb + 1 + 2 + self.lenb + 4 + self.bgb + 1
        # field offsets from bit 0: box(1) bg(bgb) fg(4) len(lenb) mode(2) scale(1) y(yb) x(xb), chain = top bit
        self.o_fg = 1 + self.bgb
        self.o_len = self.o_fg + 4
        self.o_mode = self.o_len + self.lenb
        self.o_scale = self.o_mode + 2
        self.o_y = self.o_scale + 1
        self.o_x = self.o_y + self.yb
        self.hdr_bytes = math.ceil(self.hdr_bits_used / 8)
        self.max_run_len = (1 << self.lenb) - 1
        self.code_bits = {MODE_ASCII: t["ascii_bits"], MODE_COMMON: t["common_bits"], MODE_EXT: t["ext_bits"]}
        self.cell, self.half = t["cell"], t["half"]
        self.gap, self.line_gap = t.get("gap_px", 0), t.get("line_gap_px", 1)   # extra px after every glyph / between lines (x scale)
        assert self.hdr_bytes * 8 > self.hdr_bits_used, "the text header needs a spare bit for chaining"
        self.chain_bit = self.hdr_bytes * 8 - 1          # top bit: position relative to the previous run (see memory.py)
        self.max_glyphs, self.max_runs = t["max_glyphs"], t["max_runs"]

        self.coefs, self.dc_bits, self.ac_bits, self.ac_range = ph["coefs"], ph["dc_bits"], ph["ac_bits"], ph["ac_range"]
        self.chroma_bits = ph.get("chroma_bits", 4)

        P = self.P
        pages = lambda n: math.ceil(n / P)
        assert P % 2 == 0, "payload must be even (16-bit words)"
        self.bitmap_bytes = self.tiles_mem * 64 * self.bpp // 8
        photo_bits = self.tiles_mem * (self.dc_bits + (self.coefs - 1) * self.ac_bits)
        assert photo_bits <= self.bitmap_bytes * 8, "photo coefficients do not fit in the bitmap"
        self.bitmap_base = 0
        self.tc_base = self.bitmap_base + self.bitmap_bytes
        self.tc_bytes = self.tiles_mem * self.tc_bytes_per
        self.pal_base = self.tc_base + self.tc_bytes
        assert self.pal_base % 2 == 0
        self.pal_bytes = 32
        self.gfx_base, self.gfx_bytes = 0, self.pal_base + self.pal_bytes        # bitmap + tilecol + palette
        self.clear_bytes = self.pal_base                                           # the clear command: bitmap + tilecol
        self.text_base = pages(self.gfx_bytes) * P
        self.text_bytes = t["area_bytes"]
        self.reg_names = c["registers"]
        self.reg_base = self.text_base + pages(self.text_bytes) * P
        self.regs = {n: self.reg_base + i for i, n in enumerate(self.reg_names)}
        self.reg_npages = pages(len(self.reg_names))                # (the transition register must be in the first)
        sp = c["sprites"]
        self.spr_n, self.spr_size, self.spr_off = sp["count"], sp["size"], sp["offset"]
        self.spr_base = self.reg_base + self.reg_npages * P
        self.spr_regs = self.spr_base                                   # x, y, attr per sprite
        self.spr_cols = self.spr_regs + 3 * self.spr_n                  # 2 colour bytes per sprite
        self.spr_row_bytes = self.spr_size * 2 // 8                     # 2 bpp
        self.spr_pat_bytes = self.spr_size * self.spr_row_bytes
        self.spr_pat = self.spr_cols + 2 * self.spr_n
        self.spr_bytes = self.spr_pat + self.spr_n * self.spr_pat_bytes - self.spr_base
        assert self.spr_cols + 2 * self.spr_n - self.spr_base <= P, "sprite registers + colours must share one page"
        self.spr_end = self.spr_base + self.spr_bytes
        # command frames: page ids from 255 down (config "commands"), above every memory page and the clear command.
        # The clear command keeps its page id (commands.clear_gfx) when the memory grows: the regions added later (shapes)
        # start after it, its page is a hole that is never sent as memory (older clients keep working)
        self.commands = {k: v for k, v in c.get("commands", {}).items() if not k.startswith("_")}
        self.id_clear_gfx = self.commands.pop("clear_gfx", pages(self.spr_end) + 1)
        assert self.id_clear_gfx > pages(self.spr_end), "the clear command's page id lies inside the memory"
        sh = c.get("shapes", {"count": 0, "bytes": 10, "offset": 32})
        self.shp_n, self.shp_bytes_per, self.shp_off = sh["count"], sh["bytes"], sh["offset"]
        self.shp_per_page = P // self.shp_bytes_per
        self.shp_base = self.id_clear_gfx * P                          # first page after the clear command's id
        assert P % self.shp_bytes_per == 0, "shapes must not straddle pages"
        self.shp_bytes = self.shp_n * self.shp_bytes_per
        self.hole_pages = {self.id_clear_gfx - 1} if self.shp_n else set()   # memory page index whose id is the clear
        self.mem_bytes = self.shp_base + self.shp_bytes if self.shp_n else self.spr_end
        self.pages = pages(self.mem_bytes)
        fx = c["effects"]
        self.fx_clip = fx["clip_seconds"]
        self.fx_durations = fx["durations"]
        assert self.pages < min(self.commands.values(), default=256) and max(self.commands.values(), default=0) <= 255, \
            "page ids: memory pages + clear command run into the command ids"
        mn = c["menu"]
        self.size_min, self.size_max, self.size_m = mn["size_min"], mn["size_max"], s["size_m"]
        self.regions = {
            "bitmap": (self.bitmap_base, self.bitmap_bytes), "tilecol": (self.tc_base, self.tc_bytes),
            "palette": (self.pal_base, self.pal_bytes), "text": (self.text_base, self.text_bytes),
            "regs": (self.reg_base, len(self.reg_names)), "sprites": (self.spr_base, self.spr_bytes),
            "shapes": (self.shp_base, self.shp_bytes),
        }
        self.used = bytearray(self.pages * P)
        for a, n in self.regions.values():
            self.used[a:a + n] = b"\x01" * n
        self.n_words = math.ceil(self.mem_bytes / 2)
        self.sync_bits = 8 + 8 * P

        # renderers: which 16-bit words each one animates (local index = position in its sorted list)
        self.renderers = []
        for r in c["renderers"]:
            # "tiles": [t0, t1]: of the graphics only the bitmap + tile colours of these tiles (memory tile order)
            t0, t1 = r.get("tiles", [0, self.tiles_mem])
            t1 = min(t1, self.tiles_mem)
            spans = []
            for reg in r["regions"]:
                a, n = self.regions[reg]
                if reg == "bitmap":
                    tb = 64 * self.bpp // 8
                    a, n = a + t0 * tb, (t1 - t0) * tb
                elif reg == "tilecol":
                    a, n = a + t0 * self.tc_bytes_per, (t1 - t0) * self.tc_bytes_per
                spans.append((a, n))
            words = sorted({w for a, n in spans for w in range(a // 2, (a + n + 1) // 2)})
            self.renderers.append({"name": r["name"], "regions": r["regions"], "draws": r["draws"], "words": words,
                                   "checksum": r.get("checksum"), "tiles": (t0, t1)})
        # status checksums: one 16-bit register word per renderer, left out of every sum
        for r in self.renderers:
            if r["checksum"]:
                a = self.regs[r["checksum"] + "_hi"]
                assert a % 2 == 0 and self.regs[r["checksum"] + "_lo"] == a + 1, "checksum registers must form a word"
                r["sum_word"] = a // 2
        self.sum_words = {r["sum_word"] for r in self.renderers if r.get("checksum")}

    def osc_target(self, host=None, port=None):
        """where to send: argument > environment (KD_OSC_HOST / KD_OSC_PORT) > config.json "osc" """
        o = self.raw["osc"]
        return (host or os.environ.get("KD_OSC_HOST") or o["host"],
                int(port or os.environ.get("KD_OSC_PORT") or o["port"]))

    def osc_listen(self, port=None, host=None):
        """where to listen for VRChat's replies: argument > KD_OSC_LISTEN_PORT / KD_OSC_LISTEN_HOST > config"""
        o = self.raw["osc"]
        return (host or os.environ.get("KD_OSC_LISTEN_HOST") or o.get("listen_host", "127.0.0.1"),
                int(port or os.environ.get("KD_OSC_LISTEN_PORT") or o["listen_port"]))

    def param_page(self):
        return self.prefix + "P"

    def param_byte(self, k):
        return f"{self.prefix}B{k}"

    def set_size(self, i, gscale=None):
        """switch the logical screen size (index into sizes) and, with gscale, the graphics resolution: gscale 2 = the
        low-resolution mode (each graphics pixel 2x2 screen px, a quarter of the tiles, packed from tile 0 = a quarter of
        the pages to send). Both are run-time state (register screen: size | 16 for low resolution)."""
        if gscale is not None:
            assert gscale in (self.gscale0, 2 * self.gscale0) and self.gscale0 == 1, gscale
            self.gscale = gscale
        self.size = max(0, min(len(self.sizes) - 1, int(i)))
        self.W, self.H = self.sizes[self.size]
        self.GW, self.GH = self.W // self.gscale, self.H // self.gscale
        self.tiles_x, self.tiles_y = self.GW // 8, self.GH // 8
        self.n_tiles = self.tiles_x * self.tiles_y
        return self

    def screen_reg(self):
        """the value of register screen: size index, + 16 in the low-resolution graphics mode"""
        return self.size | (16 if self.gscale != self.gscale0 else 0)

    def for_size(self, v):
        """a copy at the size / resolution a screen register value says (the simulator renders what is on the air)"""
        import copy
        return copy.copy(self).set_size(v & 15, 2 * self.gscale0 if v & 16 else self.gscale0)

    def adv(self, mode, scale=1):
        """pixels from one glyph to the next (scale "tiny" / "small": the 3x5 / 5x7 ASCII fonts)"""
        if scale in SMALL_FONTS:
            return SMALL_FONTS[scale][1]
        return ((self.half if mode == MODE_ASCII else self.cell) + self.gap) * scale

    def line_h(self, scale=1):
        return SMALL_FONTS[scale][3] if scale in SMALL_FONTS else (self.cell + self.line_gap) * scale

    def glyph_h(self, scale=1):
        return SMALL_FONTS[scale][2] if scale in SMALL_FONTS else self.cell * scale

    def file(self, key):
        return os.path.normpath(os.path.join(ROOT, self.raw["unity"][key]))

    def summary(self):
        rs = ", ".join(f"{r['name']} {len(r['words'])} words" for r in self.renderers)
        return (f"screen {self.W}x{self.H}, graphics {self.GW}x{self.GH} x{self.gscale} {self.bpp} bpp "
                f"({self.colors_per_tile} colours/tile), memory {self.mem_bytes} B (bitmap {self.bitmap_bytes}, tilecol "
                f"{self.tc_bytes}, palette @{self.pal_base}, text {self.text_bytes} @{self.text_base}, regs @{self.reg_base}, "
                f"sprites {self.spr_bytes} @{self.spr_base}), "
                f"{self.pages} pages x {self.P} B, renderers: {rs}; sync {self.sync_bits} bits/frame, header {self.hdr_bytes} B")
