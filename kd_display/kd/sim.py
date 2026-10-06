"""Reference decoder: renders a memory image exactly the way the shaders do (same bit formats, same Bayer threshold,
same run walk, same colour maths). Used for offline tests and the client's local preview."""
import math, os
from .config import Config, ROOT, FLAG_ON, FLAG_INVERT, FLAG_GFX, FLAG_TEXT, FLAG_MONO, FLAG_DITHER, FLAG_SPRITES, FLAG_WINDOW

BAYER = [0, 32, 8, 40, 2, 34, 10, 42, 48, 16, 56, 24, 50, 18, 58, 26, 12, 44, 4, 36, 14, 46, 6, 38, 60, 28, 52, 20, 62, 30, 54, 22,
         3, 35, 11, 43, 1, 33, 9, 41, 51, 19, 59, 27, 49, 17, 57, 25, 15, 47, 7, 39, 13, 45, 5, 37, 63, 31, 55, 23, 61, 29, 53, 21]


def zigzag(n):
    zz = sorted([(u, v) for u in range(8) for v in range(8)], key=lambda t: (t[0] + t[1], t[1] if (t[0] + t[1]) % 2 else t[0]))
    return zz[:n]


def dct_c():
    return [[(math.sqrt(1 / 8) if u == 0 else 0.5) * math.cos((2 * x + 1) * u * math.pi / 16) for x in range(8)] for u in range(8)]


def bits(buf, bitoff, n):
    b = bitoff >> 3
    w = 0
    for k in range(5):
        w = (w << 8) | (buf[b + k] if b + k < len(buf) else 0)
    return (w >> (40 - (bitoff & 7) - n)) & ((1 << n) - 1)


def pal_rgb(buf, c, i):
    v = buf[c.pal_base + 2 * i] * 256 + buf[c.pal_base + 2 * i + 1]
    return (((v >> 11) & 31) / 31.0, ((v >> 5) & 63) / 63.0, (v & 31) / 31.0)


def s8(v):
    return v - 256 if v >= 128 else v


def pal_index(buf, c, i, t):
    """palette cycling, then blinking (like kd_pal_index in the shader)"""
    cyc, tim, bv = buf[c.regs["cycle"]], buf[c.regs["timing"]], buf[c.regs["blink_view"]]
    s, n, rate = cyc >> 4, cyc & 15, tim >> 4
    if n > 1 and rate > 0 and s <= i < s + n:
        i = (s + (i - s + math.floor(t * rate)) % n) & 15
    br = tim & 15
    if br > 0 and i == (bv >> 4) and (t * br * 0.5) % 1.0 >= 0.5:
        i = 0
    return i


def chroma(buf, c, tx, ty):
    tx = min(max(tx, 0), c.tiles_x - 1); ty = min(max(ty, 0), c.tiles_y - 1)
    v = buf[c.tc_base + (ty * c.tiles_x + tx) * c.tc_bytes_per]
    q = 1 << c.chroma_bits
    return ((v >> 4) - q // 2) / q, ((v & 15) - q // 2) / q


def gfx_buffer(buf, c, pal, tile0=0):
    """the graphics plane at zoom 1 in screen units (W x H), no offset: what the tiles hold"""
    W, H, S = c.W, c.H, c.gscale
    img = [[(0.0, 0.0, 0.0)] * W for _ in range(H)]
    flags = buf[c.regs["flags"]]
    mode = buf[c.regs["gfx_mode"]]
    zz, C = zigzag(c.coefs), dct_c()
    L = (1 << (c.ac_bits - 1)) - 1
    for ty in range(c.tiles_y):
        for tx in range(c.tiles_x):
            mt = tile0 + ty * c.tiles_x + tx
            if mode == 0:
                ev = 0
                for b in range(c.tc_bytes_per):
                    ev = (ev << 8) | buf[c.tc_base + mt * c.tc_bytes_per + b]
                K = c.colors_per_tile
                cols = [pal((ev >> (4 * (K - 1 - k))) & 15) for k in range(K)]
                for y in range(8):
                    row = 0
                    for b in range(c.bpp):
                        row = (row << 8) | buf[c.bitmap_base + (mt * 8 + y) * c.bpp + b]
                    for x in range(8):
                        v = (row >> (c.bpp * (7 - x))) & ((1 << c.bpp) - 1)
                        for sy in range(S):
                            for sx in range(S):
                                img[(ty * 8 + y) * S + sy][(tx * 8 + x) * S + sx] = cols[v]
            else:
                co = [(bits(buf, mt * 64 * c.bpp, c.dc_bits) / ((1 << c.dc_bits) - 1) - 0.5) * 8.0]
                for j in range(1, c.coefs):
                    off = mt * 64 * c.bpp + c.dc_bits + (j - 1) * c.ac_bits     # tile by tile
                    co.append((bits(buf, off, c.ac_bits) - L) / L * c.ac_range)
                corner = {}
                for cy in (0, 1):
                    for cx in (0, 1):
                        vals = [chroma(buf, c, tx + cx - 1 + i, ty + cy - 1 + j) for i in (0, 1) for j in (0, 1)]
                        corner[(cx, cy)] = (sum(v[0] for v in vals) / 4, sum(v[1] for v in vals) / 4)
                T = 8 * S
                for py in range(T):
                    for px in range(T):
                        lx, ly = px // S, py // S
                        Y = 0.5 + sum(C[u][ly] * C[v][lx] * co[k] for k, (u, v) in enumerate(zz))
                        fu, fv = (px + 0.5) / T, (py + 0.5) / T
                        cb = ((1 - fu) * (1 - fv) * corner[(0, 0)][0] + fu * (1 - fv) * corner[(1, 0)][0]
                              + (1 - fu) * fv * corner[(0, 1)][0] + fu * fv * corner[(1, 1)][0])
                        cr = ((1 - fu) * (1 - fv) * corner[(0, 0)][1] + fu * (1 - fv) * corner[(1, 0)][1]
                              + (1 - fu) * fv * corner[(0, 1)][1] + fu * fv * corner[(1, 1)][1])
                        rgb = (Y + 1.402 * cr, Y - 0.344 * cb - 0.714 * cr, Y + 1.772 * cb)
                        rgb = tuple(min(1.0, max(0.0, v)) for v in rgb)
                        if flags & FLAG_DITHER:
                            gx, gy = tx * 8 + lx, ty * 8 + ly
                            tt = (BAYER[(gy & 7) * 8 + (gx & 7)] + 0.5) / 64
                            rgb = tuple(min(1.0, math.floor(v * 3 + tt) / 3) for v in rgb)
                        img[ty * T + py][tx * T + px] = rgb
    return img


def fx_visibility(c, fx, fx_time):
    """-> (effect, a): a = how far the screen is shown, 0 hidden .. 1 shown (the shader's kd_fx)"""
    e, hide = fx & 7, (fx >> 3) & 1
    dur = c.fx_durations[(fx >> 4) & 3]
    p = 1.0 if fx_time is None else min(1.0, max(0.0, min(fx_time, c.fx_clip) / dur))
    if e == 0:
        p = 1.0
    return e, (1.0 - p) if hide else p


def fx_pixel(c, e, a, sx, sy):
    """visibility of content at screen pixel (sx, sy) for effects that cut the screen (fade handled as a factor)"""
    W, H = c.W, c.H
    if e == 0:
        return 1.0 if a > 0.5 else 0.0
    if e == 1:
        return a
    if e == 2:
        return 1.0 if sx + 0.5 < a * W else 0.0
    if e == 3:
        return 1.0 if sy + 0.5 < a * H else 0.0
    if e == 6:
        return 1.0 if (BAYER[((sy >> 1) & 7) * 8 + ((sx >> 1) & 7)] + 0.5) / 64 < a else 0.0
    if e == 7:
        return 1.0 if math.hypot(sx + 0.5 - W / 2, sy + 0.5 - H / 2) < a * math.hypot(W, H) / 2 else 0.0
    return 1.0                                  # slides move the content instead


def routes(buf, c):
    """the wing routing registers -> functions: text page -> screen, shape slot -> screen, sprite -> screen, tile0 per wing"""
    R = lambda n: buf[c.regs[n]] if n in c.regs else 0
    tl, tr = R("wing_tl"), R("wing_tr")
    shp, spr = R("wing_shp"), R("wing_spr")
    sl, sr = shp >> 4, shp & 15

    def text(page):
        if tr and page >= tr:
            return 2
        return 1 if tl and page >= tl else 0

    def shape(i):
        if sr and i >= sr:
            return 2
        return 1 if sl and i >= sl else 0
    return text, shape, (lambda i: (spr >> (2 * i)) & 3), {1: R("wing_gl"), 2: R("wing_gr")}


def wings_open(mem, side=None):
    """does the register say a side screen is unfolded (show bit 1 left, bit 2 right; side None: either)?"""
    c = mem.cfg
    if "show" not in c.regs or not mem.buf[c.regs["flags"]] & FLAG_ON:
        return False
    v = mem.buf[c.regs["show"]]
    return bool(v & (6 if side is None else 2 << (side - 1)))


def render(mem, font_png=None, t=0.0, fx_time=None, screen=0):
    """-> H rows of W (r, g, b) floats 0..1 (all black when the display is off).
    t = the viewer's clock in seconds (auto-scroll, palette cycling, blinking); fx_time = seconds since the transition
    register reached the viewer (None = long ago: the transition has finished). screen 1 / 2 = the left / right wing
    (its own coordinates; no scrolling, transitions or graphics window there)."""
    c = mem.cfg
    buf = mem.buf
    if "screen" in c.regs and len(c.sizes) > 1:
        c = c.for_size(buf[c.regs["screen"]])       # the size the register on the air says
    W, H = c.W, c.H
    R = lambda n: buf[c.regs[n]]
    flags = R("flags")
    if not flags & FLAG_ON:
        return [[(0.0, 0.0, 0.0)] * W for _ in range(H)]
    pal = lambda i: pal_rgb(buf, c, pal_index(buf, c, i, t))
    route_text, route_shape, route_sprite, wing_tile0 = routes(buf, c)
    bv = R("blink_view")
    z = (1, 2, 4, 1)[bv & 3] if screen == 0 else 1
    e, a = fx_visibility(c, R("fx"), fx_time) if screen == 0 else (0, 1.0)
    # slides move every layer (in the shader: the quads), the screen background stays
    shx = round((1 - a) * W) if e == 4 else 0
    shy = round((1 - a) * H) if e == 5 else 0
    BG = (0.0, 0.0, 0.0)
    img = [[BG] * W for _ in range(H)]
    cover = [[False] * W for _ in range(H)]
    zb = [[0.0] * W for _ in range(H)]              # the layer's lift (the shader's depth): XOR shapes respect it

    def put(x, y, col, z=0.3):
        x += shx; y += shy
        if 0 <= x < W and 0 <= y < H:
            img[y][x] = col; cover[y][x] = True; zb[y][x] = z

    # hardware shapes (kd/shapes.py): lift 0.4 (+ index / 1000) under the text, 0.7 over it; XOR shapes last
    shp = []
    if getattr(c, "shp_n", 0):
        from .shapes import Shape, paint, ABOVE, XOR, FOLLOW, bbox, geometry
        for i in range(c.shp_n):
            a0 = c.shp_base + i * c.shp_bytes_per
            sh = Shape(buf[a0:a0 + c.shp_bytes_per], c.shp_off)
            if sh.kind and route_shape(i) == screen:
                shp.append((i, sh))
        sox = math.floor(R("shape_x") + s8(R("shape_vx")) * (t % W)) % W if "shape_x" in c.regs and not screen else 0
        soy = math.floor(R("shape_y") + s8(R("shape_vy")) * (t % H)) % H if "shape_y" in c.regs and not screen else 0
        if screen and "wing_lsy" in c.regs:
            soy = R("wing_lsy" if screen == 1 else "wing_rsy") % H
        gox = math.floor(R("gfx_x") + s8(R("gfx_vx")) * (t % W)) % W if not screen else 0
        goy = math.floor(R("gfx_y") + s8(R("gfx_vy")) * (t % H)) % H if not screen else 0

    def shape_pixels(sh):
        """screen pixels to test for a shape (its bounding box grown for rotation / pulse, or everything)"""
        if sh.flags & FOLLOW or sh.speed and sh.anim in (1, 2, 4) or (sh.kind in (2, 3, 4, 8) and sh.raw[4]):
            return ((x, y) for y in range(H) for x in range(W))
        b = bbox(sh)
        dx = sox - (W if sh.pt[0][0] + sox >= W else 0); dy = soy - (H if sh.pt[0][1] + soy >= H else 0)
        return ((x, y) for y in range(max(0, b[1] + dy - 1), min(H, b[3] + dy + 1))
                for x in range(max(0, b[0] + dx - 1), min(W, b[2] + dx + 1)))

    def shapes(above, xor=False):
        for i, sh in shp:
            if bool(sh.flags & XOR) != xor or (not xor and bool(sh.flags & ABOVE) != above):
                continue
            lift = (0.7 if sh.flags & ABOVE else 0.4) + i * 0.001
            follow = ((gox, goy), z, (W, H))
            for x, y in shape_pixels(sh):
                v = paint(sh, x, y, t, ((sox, soy), (W, H)), follow)
                if v is None:
                    continue
                if xor:
                    X, Y = x + shx, y + shy
                    if 0 <= X < W and 0 <= Y < H and zb[Y][X] <= lift:
                        cur = img[Y][X] if cover[Y][X] else BG
                        img[Y][X] = tuple(_inv_linear(u) for u in cur); cover[Y][X] = True
                else:
                    put(x, y, pal(v), lift)

    if flags & FLAG_GFX and screen and wing_tile0[screen]:
        gb = gfx_buffer(buf, c, pal, wing_tile0[screen])       # a wing's picture: no offset, zoom or window
        for sy in range(H):
            for sx in range(W):
                put(sx, sy, gb[sy][sx])
    elif flags & FLAG_GFX and not screen:
        gb = gfx_buffer(buf, c, pal)
        ox = math.floor(R("gfx_x") + s8(R("gfx_vx")) * (t % W)) % W
        oy = math.floor(R("gfx_y") + s8(R("gfx_vy")) * (t % H)) % H
        win = None
        if flags & FLAG_WINDOW:
            wx, wy = R("win_x"), R("win_y")
            q = 16                                           # window cells: 16 screen px (4 bits reach 256 px)
            win = ((wx >> 4) * q, (wy >> 4) * q, (wx & 15) * q + q, (wy & 15) * q + q)
        for sy in range(H):
            for sx in range(W):
                bx = ((sx - ox * z) % (W * z)) // z
                by = ((sy - oy * z) % (H * z)) // z
                col = gb[by][bx]
                if win and not (win[0] <= sx < win[2] and win[1] <= sy < win[3]):
                    col = BG
                put(sx, sy, col)
    else:
        for sy in range(H):
            for sx in range(W):
                put(sx, sy, BG)

    def sprites(above):
        if not flags & FLAG_SPRITES:
            return
        for i in range(c.spr_n):
            a0 = c.spr_regs + 3 * i
            x, y, attr = buf[a0] - c.spr_off, buf[a0 + 1] - c.spr_off, buf[a0 + 2]
            if not attr & 1 or bool(attr & 16) != above or route_sprite(i) != screen:
                continue
            sc = 2 if attr & 8 else 1
            n = c.spr_size
            k0, k1 = buf[c.spr_cols + 2 * i], buf[c.spr_cols + 2 * i + 1]
            cols = [None, pal(k0 & 15), pal(k1 >> 4), pal(k1 & 15)]
            base = c.spr_pat + i * c.spr_pat_bytes
            for py in range(n * sc):
                for px in range(n * sc):
                    lx, ly = px // sc, py // sc
                    if attr & 2: lx = n - 1 - lx
                    if attr & 4: ly = n - 1 - ly
                    byte = buf[base + ly * c.spr_row_bytes + (lx >> 2)]
                    v = (byte >> (6 - 2 * (lx & 3))) & 3
                    if v:
                        put(x + px, y + py, cols[v], 0.75 if above else 0.45)

    shapes(False)
    sprites(False)
    if flags & FLAG_TEXT:
        glyph = _font(c, font_png)
        tb = c.text_base
        off, cum = tb, 0
        mv, wxr, wyr = R("text_move"), R("text_wrap_x"), R("text_wrap_y")
        WX, WY = (wxr * 8 if wxr else W), (wyr * 2 if wyr else H)
        cy0 = R("text_clip_y0") if mv else 0
        cy1 = R("text_clip_y1") if mv and R("text_clip_y1") else H
        dx = math.floor(R("text_x") + s8(R("text_vx")) * (t % WX)) % WX
        dy = math.floor(R("text_y") + s8(R("text_vy")) * (t % WY)) % WY
        px0 = py0 = pend = 0
        for r in range(c.max_runs):
            if off + c.hdr_bytes > tb + c.text_bytes:
                break
            h = bits(buf, off * 8, c.hdr_bytes * 8)
            box = h & 1
            bg = (h >> 1) & ((1 << c.bgb) - 1)
            fg = (h >> c.o_fg) & 15
            n = (h >> c.o_len) & ((1 << c.lenb) - 1)
            if n == 0:
                break
            sh = c.o_mode
            mode = (h >> sh) & 3
            sb = (h >> (sh + 2)) & 1
            tiny = mode == 3 and sb
            small = mode == 3 and not sb and box
            skip = mode == 3 and not tiny and not small
            if small:
                box = 0
            scale = 1 if mode == 3 else sb + 1
            yf = (h >> (sh + 3)) & ((1 << c.yb) - 1)
            xf = (h >> (sh + 3 + c.yb)) & ((1 << c.xb) - 1)
            rx, ry = xf, yf
            if (h >> c.chain_bit) & 1:
                ry = py0 + yf
                rx = pend + xf if yf == 0 else xf
            cb = c.code_bits[0] if mode == 3 else c.code_bits.get(mode, c.code_bits[2])   # like the shader: 2 / 3 read as extended
            adv = 4 if tiny else 6 if small else ((c.half if mode == 0 else c.cell) + c.gap) * scale
            gh = 5 if tiny else 7 if small else c.cell * scale
            pgi = (off - tb) // c.P
            rs = route_text(pgi)
            ddy = dy
            if rs == 0:
                moving = mv == 0 or r + 1 >= mv
            else:                                           # a wing: its runs from page wing_mv on move (0 = none)
                wmv = (R("wing_mv") >> (4 if rs == 1 else 0)) & 15 if "wing_mv" in c.regs else 0
                start = R("wing_tl") if rs == 1 else R("wing_tr")
                moving = wmv > 0 and pgi >= start + wmv
            wy = R("wing_ly" if rs == 1 else "wing_ry") if rs and "wing_ly" in c.regs else 0
            ddy = (wy - 1) % WY if wy else dy
            fgc, bgc = pal(fg), pal(bg)
            if not skip and rs == screen:
                for i in range(n):
                    if cum + i >= c.max_glyphs:
                        break
                    code = bits(buf, (off + c.hdr_bytes) * 8 + i * cb, cb)
                    g = glyph["tiny"] + code if tiny else glyph["small"] + code if small else (code if mode != 1 else glyph["ascii"] + code)
                    ox, oy = rx + i * adv, ry
                    if moving:
                        ox = (ox + dx) % WX
                        oy = (oy - cy0 + ddy) % WY
                        if wxr and ox > WX - adv:
                            ox -= WX
                        if wyr and oy > WY - gh:
                            oy -= WY
                        oy += cy0
                    gp = glyph["get"](g)
                    qh = gh + 1 if mode == 3 else gh
                    for py in range(qh):
                        for px in range(adv):
                            sx, sy = ox + px, oy + py
                            if not (0 <= sx < W and 0 <= sy < H) or (moving and mv and not cy0 <= sy < cy1):
                                continue
                            gx, gy = min(px // scale, c.cell - 1), min(py // scale, c.cell - 1)
                            if (gx, gy) in gp:
                                put(sx, sy, fgc, 0.6)
                            elif box:
                                put(sx, sy, bgc, 0.6)
            if not skip:
                cum += n                                # glyph slots count every screen's glyphs
            px0, py0, pend = rx, ry, (rx if skip else rx + n * adv)
            off += c.hdr_bytes + (n if skip else (n * cb + 7) // 8)
    shapes(True)
    sprites(True)
    if shp:
        shapes(False, xor=True)

    m = R("mono")
    mf, mb = pal(m >> 4), pal(m & 15)

    def look(p):
        if flags & FLAG_MONO:
            l = 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]
            p = tuple(b + (f - b) * l for f, b in zip(mf, mb))
        if flags & FLAG_INVERT:
            p = tuple(1 - v for v in p)
        return p
    bg = look(BG)                                   # the screen background (drawn behind everything)
    for sy in range(H):
        row = img[sy]
        for sx in range(W):
            p = look(row[sx]) if cover[sy][sx] else bg
            if cover[sy][sx] and e not in (1, 4, 5) and fx_pixel(c, e, a, sx, sy) < 0.5:
                p = bg                              # cut away by the transition: the background shows
            if e == 1:
                p = tuple(v * a for v in p)         # fade: the whole screen
            row[sx] = p
    if bv & 4:
        img = [row[::-1] for row in img]
    if bv & 8:
        img = img[::-1]
    return img


def _inv_linear(u):
    """XOR shapes invert the frame buffer, which holds linear colour: 1 - linear, back to sRGB"""
    lin = u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4
    lin = 1 - lin
    return lin * 12.92 if lin <= 0.0031308 else 1.055 * lin ** (1 / 2.4) - 0.055


_FONT = {}


def _font(c, font_png=None):
    if "get" in _FONT:
        return _FONT
    import json
    with open(os.path.join(ROOT, "generated", "charmap.json"), encoding="utf-8") as f:
        cm = json.load(f)
    path = font_png or c.file("font_png")
    if not os.path.exists(path):                      # client copied without the Unity project next to it
        path = os.path.join(ROOT, "generated", "kd_font.png")
    S, data = read_gray_png(path)
    per_row, per_plane, cell = cm["atlas_row"], cm["atlas_plane"], cm["cell"]
    cache = {}

    def get(g):
        if g not in cache:
            plane, cl = divmod(g, per_plane)
            cy, cx = divmod(cl, per_row)
            if plane > 7 or (cy + 1) * cell > len(data) // S:      # garbage code (half-sent text): no glyph there
                cache[g] = set()
            else:
                cache[g] = {(x, y) for y in range(cell) for x in range(cell)
                            if data[(cy * cell + y) * S + cx * cell + x] >> plane & 1}
        return cache[g]
    _FONT.update(get=get, ascii=cm["ascii"], tiny=cm.get("tiny", 0), small=cm.get("small", 0))
    return _FONT


def read_gray_png(path):
    """8-bit grayscale PNG -> (width, bytes) with the standard library only (the font atlas; Pillow not needed)"""
    import struct, zlib
    with open(path, "rb") as f:
        b = f.read()
    assert b[:8] == b"\x89PNG\r\n\x1a\n", path
    i, idat, w = 8, b"", 0
    while i < len(b):
        n, t = struct.unpack(">I4s", b[i:i + 8])
        d = b[i + 8:i + 8 + n]
        if t == b"IHDR":
            w, h, depth, ctype, _, _, inter = struct.unpack(">IIBBBBB", d)
            assert depth == 8 and ctype == 0 and inter == 0, "font atlas must be 8-bit grayscale, not interlaced"
        elif t == b"IDAT":
            idat += d
        i += 12 + n
    raw = zlib.decompress(idat)
    out = bytearray(w * h)
    prev = bytearray(w)
    for y in range(h):
        ft, row = raw[y * (w + 1)], bytearray(raw[y * (w + 1) + 1:(y + 1) * (w + 1)])
        for x in range(w):
            a = row[x - 1] if x else 0
            up = prev[x]
            if ft == 1: row[x] = (row[x] + a) & 255
            elif ft == 2: row[x] = (row[x] + up) & 255
            elif ft == 3: row[x] = (row[x] + ((a + up) >> 1)) & 255
            elif ft == 4:
                c = prev[x - 1] if x else 0
                p = a + up - c; pa, pb, pc = abs(p - a), abs(p - up), abs(p - c)
                row[x] = (row[x] + (a if pa <= pb and pa <= pc else (up if pb <= pc else c))) & 255
        out[y * w:(y + 1) * w] = row
        prev = row
    return w, bytes(out)


def to_png(img, path, scale=4):
    from PIL import Image
    H, W = len(img), len(img[0])
    im = Image.new("RGB", (W, H))
    im.putdata([tuple(int(round(v * 255)) for v in p) for row in img for p in row])
    im.resize((W * scale, H * scale), Image.NEAREST).save(path)
    return path
