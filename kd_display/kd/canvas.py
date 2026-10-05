"""Drawing surface for the graphics plane (pure python). Pixels are palette indices 0..15 (0 = black, 1 = white with
the default palette); the encoder keeps at most 2^bpp colours per 8x8 tile."""


class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.px = [[0] * w for _ in range(h)]

    def clear(self, v=0):
        for row in self.px:
            row[:] = [v] * self.w

    def set(self, x, y, v=1):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y][x] = int(v) & 15

    def get(self, x, y):
        return self.px[y][x] if 0 <= x < self.w and 0 <= y < self.h else 0

    def line(self, x0, y0, x1, y1, v=1):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            self.set(x0, y0, v)
            if x0 == x1 and y0 == y1:
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy; x0 += sx
            if e2 <= dx:
                err += dx; y0 += sy

    def rect(self, x, y, w, h, v=1, fill=False):
        if fill:
            for yy in range(y, y + h):
                for xx in range(x, x + w):
                    self.set(xx, yy, v)
        else:
            self.line(x, y, x + w - 1, y, v); self.line(x, y + h - 1, x + w - 1, y + h - 1, v)
            self.line(x, y, x, y + h - 1, v); self.line(x + w - 1, y, x + w - 1, y + h - 1, v)

    def circle(self, cx, cy, r, v=1, fill=False):
        for y in range(-r, r + 1):
            for x in range(-r, r + 1):
                d = x * x + y * y
                if d <= r * r + r and (fill or d > r * r - r):      # (r +- 0.5)^2: round, no single-pixel nubs
                    self.set(cx + x, cy + y, v)

    def blit(self, bitmap, x, y, transparent=True):
        """bitmap: rows of 0/1"""
        for j, row in enumerate(bitmap):
            for i, b in enumerate(row):
                if b or not transparent:
                    self.set(x + i, y + j, b)

    def image(self, path, x=0, y=0, w=None, h=None, threshold=None):
        """paste an image file as 1-bit (Floyd-Steinberg unless threshold is given); needs Pillow"""
        from PIL import Image
        im = Image.open(path).convert("L")
        im = im.resize((w or self.w, h or self.h), Image.LANCZOS)
        bw = im.point(lambda p: 255 if p > threshold else 0).convert("1") if threshold is not None else im.convert("1")
        data = list(bw.getdata())
        for j in range(bw.size[1]):
            for i in range(bw.size[0]):
                self.set(x + i, y + j, data[j * bw.size[0] + i] > 0)

    def image_palette(self, path, palette, dither=True, x=0, y=0, w=None, h=None):
        """paste an image as palette indices (Floyd-Steinberg error diffusion in RGB unless dither=False)"""
        w, h = w or self.w, h or self.h
        rgb = [[tuple(v * 255 for v in p) for p in row] for row in Canvas.rgb_from(path, w, h)]
        for j in range(h):
            for i in range(w):
                old = rgb[j][i]
                k = min(range(16), key=lambda n: sum((a - b) ** 2 for a, b in zip(palette[n], old)))
                self.set(x + i, y + j, k)
                if dither:
                    e = [a - b for a, b in zip(old, palette[k])]
                    for di, dj, f in ((1, 0, 7 / 16), (-1, 1, 3 / 16), (0, 1, 5 / 16), (1, 1, 1 / 16)):
                        if 0 <= i + di < w and j + dj < h:
                            rgb[j + dj][i + di] = tuple(a + f * b for a, b in zip(rgb[j + dj][i + di], e))

    @staticmethod
    def rgb_from(path, w, h):
        """(r, g, b) rows 0..1, cover-cropped to w:h; needs Pillow"""
        from PIL import Image
        im = Image.open(path).convert("RGB")
        sw, sh = im.size
        if sw * h > sh * w:
            nw = sh * w // h; im = im.crop(((sw - nw) // 2, 0, (sw - nw) // 2 + nw, sh))
        else:
            nh = sw * h // w; im = im.crop((0, (sh - nh) // 2, sw, (sh - nh) // 2 + nh))
        im = im.resize((w, h), Image.LANCZOS)
        d = list(im.getdata())
        return [[tuple(v / 255 for v in d[y * w + x]) for x in range(w)] for y in range(h)]

    @staticmethod
    def gray_from(path, w, h):
        """grayscale rows 0..1 for the photo mode; needs Pillow"""
        from PIL import Image
        im = Image.open(path).convert("L")
        sw, sh = im.size
        # cover-crop to the screen aspect
        if sw * h > sh * w:
            nw = sh * w // h; im = im.crop(((sw - nw) // 2, 0, (sw - nw) // 2 + nw, sh))
        else:
            nh = sw * h // w; im = im.crop((0, (sh - nh) // 2, sw, (sh - nh) // 2 + nh))
        im = im.resize((w, h), Image.LANCZOS)
        d = list(im.getdata())
        return [[d[y * w + x] / 255 for x in range(w)] for y in range(h)]
