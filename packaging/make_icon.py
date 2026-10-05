"""Draws packaging/icon.ico (the .exe icon) and packaging/icon.png; the same picture as ui/icon.svg.
Run: uv run python packaging/make_icon.py"""
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ACCENT, S = (217, 119, 87, 255), 1024          # drawn large, scaled down (anti-aliasing)


def draw() -> Image.Image:
    k = S / 256
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=56 * k, fill=ACCENT)
    d.rounded_rectangle([40 * k, 64 * k, 216 * k, 172 * k], radius=20 * k, fill="white")
    d.polygon([(80 * k, 168 * k), (80 * k, 204 * k), (124 * k, 168 * k)], fill="white")
    for cx in (88, 128, 168):
        d.ellipse([(cx - 13) * k, 105 * k, (cx + 13) * k, 131 * k], fill=ACCENT)
    return im


if __name__ == "__main__":
    im = draw()
    im.resize((256, 256), Image.LANCZOS).save(os.path.join(HERE, "icon.png"))
    im.resize((256, 256), Image.LANCZOS).save(os.path.join(HERE, "icon.ico"),
                                               sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon.ico / icon.png written")
