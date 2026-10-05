"""Hardware shapes: the shape table format + the reference rasteriser (the simulator draws with it; build.py's shader
implements the same rules in HLSL, kd_test.py compares them).

One shape = 10 bytes (config "shapes"; 3 per page, so a shape never straddles pages: moving one = one frame):
    b0  kind (bits 0-3) | FILL 16 | ABOVE 32 (over the text) | XOR 64 (inverts what is under it) | FOLLOW 128 (moves and
        zooms with the graphics layer)
    b1  fill colour << 4 | stroke colour (palette indices)
    b2..b7  x0 y0 x1 y1 x2 y2: screen px + offset (config shapes.offset = 32: -32..223); some kinds read b4..b7 raw
    b8  stroke width (bits 0-2, 0..7) | pattern << 3 (bits 3-5) | ROUND 64 (round line caps)
    b9  animation (bits 0-2) | speed << 3 (signed 5 bit, -16..15)

kinds (pixel centres are at +0.5; a pixel is painted when its centre's signed distance sd < 0):
    1 line     (x0,y0)-(x1,y1), width max(1, stroke width), butt or ROUND caps
    2 rect     pixels x0..x1, y0..y1 (inclusive); b6 = rotation (raw, 256 = a turn)
    3 rrect    rect + b7 = corner radius (raw px)
    4 ellipse  centre (x0,y0), radii b4 b5 (raw), b6 = rotation
    5 arc      centre (x0,y0), radius b4 (raw, ring centre line), start b5, sweep b6 (raw, 256 = a turn clockwise from
               12 o'clock, 255 = closed), thickness b7 (raw; 0 = the stroke width)
    6 pie      centre (x0,y0), radius b4, start b5, sweep b6 (as arc)
    7 tri      (x0,y0) (x1,y1) (x2,y2)
    8 poly     centre (x0,y0), radius b4 (raw, to the corners), b5 = sides (low 4 bits, 3..12) | star inner radius in
               16ths of the radius << 4 (0 = a regular polygon), b6 = rotation
    9 bezier   quadratic: (x0,y0) start, (x1,y1) control, (x2,y2) end; width max(1, stroke width)
paint: line / arc / bezier are strokes: painted in the stroke colour. The others: FILL paints the inside in the fill
    colour, and a stroke width w > 0 paints the band -w <= sd < 0 in the stroke colour on top; without FILL only that
    band (w = max(1, stroke width)). The pattern applies to the main paint (the fill, or the stroke of a stroke kind /
    an outline-only shape): 0 solid, 1 checker, 2 horizontal stripes, 3 vertical stripes, 4 diagonal stripes, 5 dots
    (the skipped pixels are transparent), 6 / 7 = horizontal / vertical gradient from the main colour to the other
    one (fill <-> stroke), ordered dither over the shape's bounding box.
animations (time based: every viewer's own clock; speed s): 1 rotate s/8 turns per s clockwise around the shape's
    centre (arc / pie: their start angle), 2 pulse: size x (1 + 0.2 sin), s/4 Hz, 3 blink s/4 Hz, 4 sweep: arc / pie
    start angle s/8 turns per s (others: like rotate).
layer: registers shape_x / shape_y (+ shape_vx / shape_vy px/s) move every shape; a shape wraps by its anchor
    (x0, y0) at the screen edge. FOLLOW shapes instead use the graphics layer's offset and zoom (content coordinates).
order: graphics < shapes < sprites < text < ABOVE shapes < sprites above the text; a later shape covers an earlier one.
"""
import math

KINDS = {"line": 1, "rect": 2, "rrect": 3, "ellipse": 4, "arc": 5, "pie": 6, "tri": 7, "poly": 8, "bezier": 9}
STROKE_KINDS = (1, 5, 9)
FILL, ABOVE, XOR, FOLLOW = 16, 32, 64, 128
ROUND = 64
PATTERNS = {"solid": 0, "checker": 1, "hstripes": 2, "vstripes": 3, "diagonal": 4, "dots": 5, "hgradient": 6, "vgradient": 7}
ANIMS = {None: 0, "none": 0, "rotate": 1, "pulse": 2, "blink": 3, "sweep": 4}
BAYER4 = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5]
TAU = 2 * math.pi


def turn(v):
    """an angle in turns (or degrees with deg=True elsewhere) -> raw byte"""
    return int(round(v * 256)) % 256


def s5(v):
    v &= 31
    return v - 32 if v >= 16 else v


class Shape:
    """decoded shape (all geometry in screen px, pixel centres at +0.5)"""

    def __init__(self, b, off=32):
        self.b = b
        self.kind = b[0] & 15
        self.flags = b[0] & 0xF0
        self.fill_col, self.stroke_col = b[1] >> 4, b[1] & 15
        self.raw = b[2:8]
        self.pt = [(b[2 + 2 * k] - off, b[3 + 2 * k] - off) for k in range(3)]
        self.sw = b[8] & 7
        self.pattern = (b[8] >> 3) & 7
        self.round = bool(b[8] & ROUND)
        self.anim = b[9] & 7
        self.speed = s5(b[9] >> 3)


def _rot(p, a):
    c, s = math.cos(a), math.sin(a)
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


def _len(x, y):
    return math.sqrt(x * x + y * y)


def sd_segment(p, a, b):
    pa = (p[0] - a[0], p[1] - a[1]); ba = (b[0] - a[0], b[1] - a[1])
    bb = ba[0] * ba[0] + ba[1] * ba[1]
    h = (pa[0] * ba[0] + pa[1] * ba[1]) / bb if bb > 0 else 0.0
    return h, _len(pa[0] - ba[0] * max(0, min(1, h)), pa[1] - ba[1] * max(0, min(1, h)))


def sd_box(p, h, r=0.0):
    qx, qy = abs(p[0]) - (h[0] - r), abs(p[1]) - (h[1] - r)
    return _len(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r


def sd_ellipse(p, ab):
    """approximate signed distance (exact on circles)"""
    a, b = ab
    k0 = _len(p[0] / a, p[1] / b)
    k1 = _len(p[0] / (a * a), p[1] / (b * b))
    if k1 < 1e-6:
        return -min(a, b)
    return k0 * (k0 - 1) / k1


def sd_wedge(p, start, sweep):
    """< 0 inside the wedge from angle start (clockwise from 12 o'clock, y down) over sweep (radians, 0..2pi)"""
    if sweep >= TAU - 1e-4:
        return -1e9
    u0 = (math.sin(start), -math.cos(start)); u1 = (math.sin(start + sweep), -math.cos(start + sweep))
    d0 = -(p[0] * -u0[1] + p[1] * u0[0])        # clockwise side of the start ray
    d1 = -(p[0] * u1[1] + p[1] * -u1[0])        # counter-clockwise side of the end ray
    return max(d0, d1) if sweep <= math.pi else min(d0, d1)


def sd_polygon(p, v):
    n = len(v)
    d = (p[0] - v[0][0]) ** 2 + (p[1] - v[0][1]) ** 2
    s = 1.0
    j = n - 1
    for i in range(n):
        e = (v[j][0] - v[i][0], v[j][1] - v[i][1]); w = (p[0] - v[i][0], p[1] - v[i][1])
        ee = e[0] * e[0] + e[1] * e[1]
        h = max(0.0, min(1.0, (w[0] * e[0] + w[1] * e[1]) / ee)) if ee > 0 else 0.0
        bx, by = w[0] - e[0] * h, w[1] - e[1] * h
        d = min(d, bx * bx + by * by)
        c1 = p[1] >= v[i][1]; c2 = p[1] < v[j][1]; c3 = e[0] * w[1] > e[1] * w[0]
        if (c1 and c2 and c3) or (not c1 and not c2 and not c3):
            s = -s
        j = i
    return s * math.sqrt(d)


def poly_vertices(r, sides, inner, a0):
    sides = max(3, min(12, sides))
    if inner:
        ri = r * inner / 16.0
        return [_rot((0.0, -(r if k % 2 == 0 else ri)), a0 + k * math.pi / sides) for k in range(2 * sides)]
    return [_rot((0.0, -r), a0 + k * TAU / sides) for k in range(sides)]


def sd_bezier(p, A, B, C):
    """distance to a quadratic Bezier (Inigo Quilez' cubic solution)"""
    a = (B[0] - A[0], B[1] - A[1]); b = (A[0] - 2 * B[0] + C[0], A[1] - 2 * B[1] + C[1])
    c = (a[0] * 2, a[1] * 2); d = (A[0] - p[0], A[1] - p[1])
    bb = b[0] * b[0] + b[1] * b[1]
    if bb < 1e-6:                                   # straight: a segment
        return sd_segment(p, A, C)[1]
    kk = 1.0 / bb
    kx = kk * (a[0] * b[0] + a[1] * b[1])
    ky = kk * (2 * (a[0] * a[0] + a[1] * a[1]) + (d[0] * b[0] + d[1] * b[1])) / 3.0
    kz = kk * (d[0] * a[0] + d[1] * a[1])
    pp = ky - kx * kx; p3 = pp * pp * pp
    q = kx * (2 * kx * kx - 3 * ky) + kz
    h = q * q + 4 * p3

    def at(t):
        t = max(0.0, min(1.0, t))
        x = d[0] + (c[0] + b[0] * t) * t; y = d[1] + (c[1] + b[1] * t) * t
        return x * x + y * y
    if h >= 0:
        h = math.sqrt(h)
        x = ((h - q) / 2, (-h - q) / 2)
        uv = tuple(math.copysign(abs(v) ** (1 / 3), v) for v in x)
        res = at(uv[0] + uv[1] - kx)
    else:
        z = math.sqrt(-pp)
        v = math.acos(max(-1, min(1, q / (pp * z * 2)))) / 3
        m = math.cos(v); n = math.sin(v) * 1.732050808
        res = min(at((m + m) * z - kx), at((-n - m) * z - kx))
    return math.sqrt(res)


def geometry(s, t):
    """-> (centre, rotation, scale, visible, start_extra) of shape s at time t (animation)"""
    k = s.kind
    if k in (2, 3):
        x0, y0 = s.pt[0]; x1, y1 = s.pt[1]
        cen = ((x0 + x1 + 1) / 2, (y0 + y1 + 1) / 2)
    elif k in (4, 5, 6, 8):
        cen = (s.pt[0][0] + 0.5, s.pt[0][1] + 0.5)
    else:
        pts = s.pt[:2] if k == 1 else s.pt
        xs = [p[0] + 0.5 for p in pts]; ys = [p[1] + 0.5 for p in pts]
        cen = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    rot = s.raw[4] / 256 * TAU if k in (2, 3, 4, 8) else 0.0
    sc, vis, start = 1.0, True, 0.0
    sp = s.speed
    if sp:
        if s.anim == 1 or (s.anim == 4 and k not in (5, 6)):
            if k in (5, 6):
                start += sp / 8 * t * TAU
            else:
                rot += sp / 8 * t * TAU
        elif s.anim == 4:
            start += sp / 8 * t * TAU
        elif s.anim == 2:
            sc = 1 + 0.2 * math.sin(TAU * abs(sp) / 4 * t)
        elif s.anim == 3:
            vis = (t * abs(sp) / 4) % 1.0 < 0.5
    return cen, rot, sc, vis, start


def bbox(s):
    """conservative screen bounding box (x0, y0, x1, y1) of the unanimated shape, before rotation / pulse growth"""
    k, (x0, y0) = s.kind, s.pt[0]
    w = max(1, s.sw)
    if k in (2, 3):
        x1, y1 = s.pt[1]
        return (min(x0, x1), min(y0, y1), max(x0, x1) + 1, max(y0, y1) + 1)
    if k == 4:
        r = (s.raw[2], s.raw[3])
        return (x0 - r[0], y0 - r[1], x0 + r[0] + 1, y0 + r[1] + 1)
    if k in (5, 6, 8):
        r = s.raw[2] + (max(s.raw[5], w) if k == 5 else 0)
        return (x0 - r, y0 - r, x0 + r + 1, y0 + r + 1)
    pts = s.pt[:2] if k == 1 else s.pt
    return (min(p[0] for p in pts) - w, min(p[1] for p in pts) - w, max(p[0] for p in pts) + w + 1, max(p[1] for p in pts) + w + 1)


def sd(s, q, start_extra=0.0):
    """signed distance of point q (shape space: rotation / pulse already undone) to shape s's main region"""
    k = s.kind
    if k == 1:
        A = (s.pt[0][0] + 0.5, s.pt[0][1] + 0.5); B = (s.pt[1][0] + 0.5, s.pt[1][1] + 0.5)
        h, d = sd_segment(q, A, B)
        w = max(1, s.sw) * 0.5
        if not s.round and (A != B):
            L = _len(B[0] - A[0], B[1] - A[1])
            ext = 0.5 / L                                        # butt caps a half pixel past the end pixels' centres
            if h < -ext or h > 1 + ext:
                return 1.0
            # perpendicular distance
            ba = ((B[0] - A[0]) / L, (B[1] - A[1]) / L)
            d = abs((q[0] - A[0]) * -ba[1] + (q[1] - A[1]) * ba[0])
        return d - w
    if k in (2, 3):
        x0, y0 = s.pt[0]; x1, y1 = s.pt[1]
        h = (abs(x1 - x0 + 0.0) / 2 + 0.5, abs(y1 - y0 + 0.0) / 2 + 0.5)
        r = min(s.raw[5], h[0], h[1]) if k == 3 else 0.0
        return sd_box(q, h, r)
    if k == 4:
        return sd_ellipse(q, (s.raw[2] + 0.5, s.raw[3] + 0.5))
    if k in (5, 6):
        R = s.raw[2]
        start = s.raw[3] / 256 * TAU + start_extra
        sweep = TAU if s.raw[4] == 255 else s.raw[4] / 256 * TAU
        d = _len(q[0], q[1])
        if k == 5:
            th = s.raw[5] or max(1, s.sw)
            ring = abs(d - R) - th * 0.5
        else:
            ring = d - (R + 0.5)
        return max(ring, sd_wedge(q, start, sweep))
    if k == 7:
        return sd_polygon(q, [(p[0] + 0.5, p[1] + 0.5) for p in s.pt])
    if k == 8:
        return sd_polygon(q, poly_vertices(s.raw[2] + 0.5, s.raw[3] & 15, s.raw[3] >> 4, 0.0))
    if k == 9:
        P = [(p[0] + 0.5, p[1] + 0.5) for p in s.pt]
        return sd_bezier(q, P[0], P[1], P[2]) - max(1, s.sw) * 0.5
    return 1.0


def pattern_on(pat, x, y):
    if pat == 1: return (x + y) & 1 == 0
    if pat == 2: return y & 1 == 0
    if pat == 3: return x & 1 == 0
    if pat == 4: return (x + y) % 4 < 2
    if pat == 5: return x & 1 == 0 and y & 1 == 0
    return True


def paint(s, sx, sy, t, layer_off=(0, 0), follow=None):
    """palette index painted by shape s at screen pixel (sx, sy) at time t, or None. layer_off = the shape layer's
    offset (whole px, already wrapped 0..W-1 / 0..H-1) and the screen size: ((ox, oy), (W, H)); follow = ((gx, gy), z,
    (W, H)) for FOLLOW shapes (the graphics offset and zoom)."""
    if s.kind == 0 or s.kind > 9:
        return None
    cen, rot, sc, vis, start = geometry(s, t)
    if not vis:
        return None
    if s.flags & FOLLOW and follow:
        (gx, gy), z, (W, H) = follow
        dx, dy = gx * z, gy * z
        ax, ay = s.pt[0][0] * z + dx, s.pt[0][1] * z + dy
        if ax >= W * z: dx -= W * z
        if ay >= H * z: dy -= H * z
        q = ((sx + 0.5 - dx) / z, (sy + 0.5 - dy) / z)
        q = (math.floor(q[0]) + 0.5, math.floor(q[1]) + 0.5)        # content pixel centres: zoomed pixels
    else:
        (ox, oy), (W, H) = layer_off
        dx, dy = ox, oy
        if s.pt[0][0] + dx >= W: dx -= W
        if s.pt[0][1] + dy >= H: dy -= H
        q = (sx + 0.5 - dx, sy + 0.5 - dy)
    p = (q[0] - cen[0], q[1] - cen[1])
    if rot:
        p = _rot(p, -rot)
    if sc != 1.0:
        p = (p[0] / sc, p[1] / sc)
    if s.kind in (4, 5, 6, 8):
        lp = p                                          # centred kinds: shape space = around the centre
    else:
        lp = (p[0] + cen[0], p[1] + cen[1]) if s.kind not in (2, 3) else p
    d = sd(s, lp, start)
    if d >= 0:
        return None
    k = s.kind
    stroke_kind = k in STROKE_KINDS
    filled = bool(s.flags & FILL) and not stroke_kind
    if filled and s.sw > 0 and d >= -s.sw:
        return s.stroke_col                             # outline over the fill
    if not filled and not stroke_kind and d < -max(1, s.sw):
        return None                                     # outline only: the inside stays clear
    main, other = (s.fill_col, s.stroke_col) if filled else (s.stroke_col, s.fill_col)
    pat = s.pattern
    if pat >= 6:
        b = bbox(s)
        ex = max(1e-6, (b[2] - b[0]) if pat == 6 else (b[3] - b[1]))
        u = ((q[0] - b[0]) if pat == 6 else (q[1] - b[1])) / ex
        thr = (BAYER4[(sy & 3) * 4 + (sx & 3)] + 0.5) / 16
        return other if u > thr else main
    if not pattern_on(pat, sx, sy):
        return None
    return main


def encode(kind, fill=None, stroke=1, coords=(0, 0, 0, 0, 0, 0), raw=(), width=1, pattern="solid", round_caps=False,
           above=False, xor=False, follow=False, anim=None, speed=0, off=32):
    """-> 10 bytes. coords = screen points (offset added); raw = {index 2..5 of the coords: raw value} for b4..b7"""
    k = KINDS[kind] if isinstance(kind, str) else kind
    b = bytearray(10)
    b[0] = (k & 15) | (FILL if fill is not None else 0) | (ABOVE if above else 0) | (XOR if xor else 0) | (FOLLOW if follow else 0)
    b[1] = (((fill if fill is not None else 0) & 15) << 4) | (stroke & 15)
    for i, v in enumerate(coords):
        b[2 + i] = max(0, min(255, int(round(v)) + off))
    for i, v in dict(raw).items():
        b[2 + i] = max(0, min(255, int(round(v))))
    p = PATTERNS[pattern] if isinstance(pattern, str) else pattern
    b[8] = (max(0, min(7, int(width))) & 7) | ((p & 7) << 3) | (ROUND if round_caps else 0)
    b[9] = (ANIMS[anim] if not isinstance(anim, int) else anim) | ((max(-16, min(15, int(speed))) & 31) << 3)
    return bytes(b)
