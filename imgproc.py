"""Small RGB image operations for the display's pictures, in plain Python (no Pillow in the desktop build).

Pictures reach kdchat either as raw RGB (the console decodes them in the browser: "KDRGB1" + width, height (u16, big
endian) + width * height * 3 bytes, already upright and on black) or, from API clients, as an image file (JPEG, PNG,
...: decoded with Pillow when it is installed). The display shows at most 208 x 176 graphics pixels, so everything
here works on small images: area-average scaling, auto contrast, colour lift, a light unsharp mask, median cut.
"""
from __future__ import annotations

import io
import struct

MAGIC = b"KDRGB1"
MAX_SIDE = 1024                 # raw pictures bigger than this are refused (the browser sends at most 512)


class Img:
    """w x h RGB, row-major bytes"""

    __slots__ = ("w", "h", "px")

    def __init__(self, w: int, h: int, px: bytes | bytearray | None = None):
        self.w, self.h = w, h
        self.px = bytearray(px) if px is not None else bytearray(w * h * 3)
        assert len(self.px) == w * h * 3, (w, h, len(self.px))

    @property
    def size(self):
        return self.w, self.h

    def getdata(self):
        p = self.px
        return [(p[i], p[i + 1], p[i + 2]) for i in range(0, len(p), 3)]

    def paste(self, other: "Img", x0: int, y0: int):
        for y in range(other.h):
            yy = y0 + y
            if not 0 <= yy < self.h:
                continue
            a = max(0, -x0)
            b = min(other.w, self.w - x0)
            if b <= a:
                continue
            self.px[(yy * self.w + x0 + a) * 3:(yy * self.w + x0 + b) * 3] = other.px[(y * other.w + a) * 3:(y * other.w + b) * 3]

    def crop(self, x0: int, y0: int, w: int, h: int) -> "Img":
        out = Img(w, h)
        for y in range(h):
            out.px[y * w * 3:(y + 1) * w * 3] = self.px[((y0 + y) * self.w + x0) * 3:((y0 + y) * self.w + x0 + w) * 3]
        return out

    def resize(self, w: int, h: int) -> "Img":
        """area average when shrinking (every source pixel counts: no aliasing), bilinear when growing"""
        w, h = max(1, w), max(1, h)
        if (w, h) == (self.w, self.h):
            return Img(w, h, self.px)
        sx, sy = self.w / w, self.h / h
        src, sw = self.px, self.w
        out = bytearray(w * h * 3)
        if sx >= 1 and sy >= 1:
            # per output column: the source columns it covers and their weights (computed once)
            cols = []
            for x in range(w):
                a, b = x * sx, (x + 1) * sx
                cols.append([(i, min(b, i + 1) - max(a, i)) for i in range(int(a), min(self.w, int(-(-b // 1))))
                             if min(b, i + 1) - max(a, i) > 1e-9])
            for y in range(h):
                a, b = y * sy, (y + 1) * sy
                rows = [(j, min(b, j + 1) - max(a, j)) for j in range(int(a), min(self.h, int(-(-b // 1))))
                        if min(b, j + 1) - max(a, j) > 1e-9]
                for x, cw in enumerate(cols):
                    r = g = bl = tot = 0.0
                    for j, wy in rows:
                        base = j * sw
                        for i, wx in cw:
                            k = (base + i) * 3
                            f = wx * wy
                            r += src[k] * f; g += src[k + 1] * f; bl += src[k + 2] * f; tot += f
                    o = (y * w + x) * 3
                    out[o] = int(r / tot + 0.5); out[o + 1] = int(g / tot + 0.5); out[o + 2] = int(bl / tot + 0.5)
            return Img(w, h, out)
        for y in range(h):
            fy = min(max((y + 0.5) * sy - 0.5, 0), self.h - 1)
            y0 = int(fy); y1 = min(y0 + 1, self.h - 1); ty = fy - y0
            for x in range(w):
                fx = min(max((x + 0.5) * sx - 0.5, 0), self.w - 1)
                x0 = int(fx); x1 = min(x0 + 1, self.w - 1); tx = fx - x0
                for c in range(3):
                    p00 = src[(y0 * sw + x0) * 3 + c]; p01 = src[(y0 * sw + x1) * 3 + c]
                    p10 = src[(y1 * sw + x0) * 3 + c]; p11 = src[(y1 * sw + x1) * 3 + c]
                    v = (p00 * (1 - tx) + p01 * tx) * (1 - ty) + (p10 * (1 - tx) + p11 * tx) * ty
                    out[(y * w + x) * 3 + c] = int(v + 0.5)
        return Img(w, h, out)


def load(data: bytes) -> Img:
    """raw RGB from the console, or an image file (needs Pillow) -> Img (upright, transparency on black)"""
    if data[:len(MAGIC)] == MAGIC:
        if len(data) < len(MAGIC) + 4:
            raise ValueError("raw picture: no size")
        w, h = struct.unpack(">HH", data[len(MAGIC):len(MAGIC) + 4])
        body = data[len(MAGIC) + 4:]
        if not (0 < w <= MAX_SIDE and 0 < h <= MAX_SIDE) or len(body) != w * h * 3:
            raise ValueError("raw picture: bad size")
        return Img(w, h, body)
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise ValueError("send the picture from the console (it converts it), or install Pillow for image files") from None
    try:
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    except Exception as e:                       # noqa: BLE001
        raise ValueError(f"not a picture: {e}") from None
    if im.mode in ("RGBA", "LA", "P", "PA"):
        im = Image.alpha_composite(Image.new("RGBA", im.size, (0, 0, 0, 255)), im.convert("RGBA"))
    im = im.convert("RGB")
    if max(im.size) > 512:                        # (like the console: the display needs no more)
        im.thumbnail((512, 512), Image.LANCZOS)
    return Img(im.width, im.height, im.tobytes())


def aspect(data: bytes) -> tuple[int, int]:
    """the picture's (width, height) without decoding it all where possible"""
    return load(data).size


def fit(im: Img, box: tuple[int, int], mode: str, centering=(0.5, 0.42)) -> Img:
    """contain: the whole picture inside the box; cover: fill the box, cropped (slightly above centre)"""
    bw, bh = box
    if mode == "contain":
        k = min(bw / im.w, bh / im.h)
        return im.resize(max(1, round(im.w * k)), max(1, round(im.h * k)))
    k = max(bw / im.w, bh / im.h)
    cw, ch = max(1, min(im.w, round(bw / k))), max(1, min(im.h, round(bh / k)))
    x0 = int((im.w - cw) * centering[0]); y0 = int((im.h - ch) * centering[1])
    return im.crop(x0, y0, cw, ch).resize(bw, bh)


def autocontrast(im: Img, cutoff=1.5) -> Img:
    """one stretch for all channels (from the brightness histogram: no colour cast), cutoff % at each end"""
    p = im.px
    hist = [0] * 256
    for i in range(0, len(p), 3):
        hist[(p[i] * 299 + p[i + 1] * 587 + p[i + 2] * 114) // 1000] += 1
    n = sum(hist)
    cut = n * cutoff / 100
    lo, acc = 0, 0
    while lo < 255 and acc + hist[lo] <= cut:
        acc += hist[lo]; lo += 1
    hi, acc = 255, 0
    while hi > 0 and acc + hist[hi] <= cut:
        acc += hist[hi]; hi -= 1
    if hi <= lo:
        return im
    scale = 255 / (hi - lo)
    lut = bytes(min(255, max(0, int((v - lo) * scale + 0.5))) for v in range(256))
    return Img(im.w, im.h, bytes(p).translate(lut))


def color(im: Img, k=1.3) -> Img:
    """saturation: away from each pixel's grey by k"""
    p = im.px
    out = bytearray(len(p))
    for i in range(0, len(p), 3):
        r, g, b = p[i], p[i + 1], p[i + 2]
        l = (r * 299 + g * 587 + b * 114) / 1000
        out[i] = min(255, max(0, int(l + (r - l) * k + 0.5)))
        out[i + 1] = min(255, max(0, int(l + (g - l) * k + 0.5)))
        out[i + 2] = min(255, max(0, int(l + (b - l) * k + 0.5)))
    return Img(im.w, im.h, out)


def sharpen(im: Img, amount=0.5, threshold=3) -> Img:
    """unsharp mask with a 3x3 blur: detail lifted where it differs from the blur by more than `threshold`"""
    w, h, p = im.w, im.h, im.px
    out = bytearray(p)
    K = ((1, 2, 1), (2, 4, 2), (1, 2, 1))
    for y in range(h):
        for x in range(w):
            for c in range(3):
                s = 0
                for dy in (-1, 0, 1):
                    yy = min(h - 1, max(0, y + dy))
                    for dx in (-1, 0, 1):
                        xx = min(w - 1, max(0, x + dx))
                        s += p[(yy * w + xx) * 3 + c] * K[dy + 1][dx + 1]
                v = p[(y * w + x) * 3 + c]
                d = v - s / 16
                if abs(d) > threshold:
                    out[(y * w + x) * 3 + c] = min(255, max(0, int(v + amount * d + 0.5)))
    return Img(w, h, out)


def median_cut(im: Img, n: int) -> list[tuple[tuple[int, int, int], int]]:
    """-> up to n (colour, pixel count), the most used first: boxes of the colour space split at the median of
    their widest channel, each box's average colour"""
    pts = im.getdata()
    boxes = [pts]
    while len(boxes) < n:
        i = max(range(len(boxes)), key=lambda k: (max(max(c[ch] for c in boxes[k]) - min(c[ch] for c in boxes[k])
                                                      for ch in range(3)) if len(boxes[k]) > 1 else -1, len(boxes[k])))
        b = boxes[i]
        if len(b) < 2:
            break
        ch = max(range(3), key=lambda c: max(p[c] for p in b) - min(p[c] for p in b))
        if max(p[ch] for p in b) == min(p[ch] for p in b):
            break
        b = sorted(b, key=lambda p: p[ch])
        m = len(b) // 2
        boxes[i:i + 1] = [b[:m], b[m:]]
    out = []
    for b in boxes:
        k = len(b)
        out.append(((sum(p[0] for p in b) // k, sum(p[1] for p in b) // k, sum(p[2] for p in b) // k), k))
    return sorted(out, key=lambda t: -t[1])
