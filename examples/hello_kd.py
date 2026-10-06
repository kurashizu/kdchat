"""Hello, Klaude: text, a shape and a picture-free graphic on the Klaude display, sent to VRChat over OSC.

    python3 examples/hello_kd.py                 # VRChat on this PC (127.0.0.1:9000)
    python3 examples/hello_kd.py --host 10.0.0.5 # VRChat on another PC
    python3 examples/hello_kd.py --dry           # no VRChat: writes preview.png (needs Pillow)

Wear the Klaude avatar with OSC enabled. See docs/KD_DRIVER.md for the whole API.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kd_display"))
from kd.display import Display  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--host")
ap.add_argument("--port", type=int)
ap.add_argument("--dry", action="store_true")
a = ap.parse_args()

d = Display(dry=a.dry, host=a.host, port=a.port)
W, H = d.cfg.W, d.cfg.H
d.set(on=True)
d.gfx.rect(0, 0, W, 20, 4, fill=True)                                       # an orange title bar (graphics)
d.text("Hello, Klaude", 0, 4, W, "center", color=1, id="title")
d.text("Sent with the kd driver.", 0, 34, W, "center", color=2)
d.shapes.circle(0, W // 2, 72, 12, color=4, width=2)                        # hardware shapes: 1 frame each
d.shapes.arc(1, W // 2, 72, 6, sweep=90, color=6, thickness=2, anim=("sweep", 1))
info = d.present()
print(f"{info['pages']} pages to send, about {info['eta_s']:.0f} s")
if a.dry:
    print("preview:", d.preview("preview.png"))
else:
    d.run(until_idle=True)
    print("done")
