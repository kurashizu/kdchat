# kd: the Klaude display driver

`kd` is the Python library that drives the screen above the **Klaude** VRChat avatar's head. It encodes text, graphics,
sprites, shapes and screen commands into a block of memory and sends it to VRChat over OSC, one page per frame; the
shader on the avatar draws the screen from that memory, for everyone who sees the avatar.

kdchat (this repository) is one application built on it: `kd_chat.py` turns chat messages into a scrolling chat log.
Everything below is what you need to write your own: clocks, now-playing, games, slides.

- **Location:** `kd_display/kd/` (the library), `kd_display/config.json` (the layout; it must match the avatar),
  `kd_display/generated/` (font atlas + character map).
- **Requirements:** Python 3.8+ standard library only. Pillow is needed only for image files and `preview()`.
- **One-way:** the client only sends; it never needs to know who is watching.
- **Numbers below** come from the shipped `config.json`; the code reads every size and limit from it.
- **The avatar:** [Klaude on VRChat](https://vrchat.com/home/avatar/avtr_a89b23ff-8a4b-427b-b3b6-c166f2a35136).
- **What you need in VRChat:** wear the Klaude avatar with OSC enabled (Action Menu > Options > OSC > Enabled).
  Turn the display on from the avatar's Expression Menu, or call `d.set(on=True)` from your program.

---

## Contents

1. [Quick start](#1-quick-start)
2. [Concepts](#2-concepts)
3. [The `Display` API](#3-the-display-api)
4. [Limits](#4-limits)
5. [Sync, late joiners and the status bar](#5-sync-late-joiners-and-the-status-bar)
6. [Recipes](#6-recipes)
7. [Lower-level modules](#7-lower-level-modules)
8. [Wire protocol and memory map](#8-wire-protocol-and-memory-map)
9. [Known limitations](#9-known-limitations)

---

## 1. Quick start

```bash
git clone https://github.com/kurashizu/kdchat
cd kdchat
python3 examples/hello_kd.py            # sends to VRChat on 127.0.0.1:9000
python3 examples/hello_kd.py --dry      # no VRChat: writes preview.png instead (needs Pillow)
```

The core of it:

```python
import sys
sys.path.insert(0, "kd_display")                  # the library lives in kd_display/kd
from kd.display import Display

d = Display()                                     # OSC to config.json "osc" (default 127.0.0.1:9000)
d.set(on=True)                                    # show the screen (it pops up with an animation)
d.gfx.rect(0, 0, 64, 64, 4)                       # graphics plane: 1 canvas pixel = 1 screen pixel
d.text("Hello, Klaude", 4, 4)                     # text layer: screen coordinates, any pixel position
d.present()                                       # encode into memory, work out which pages changed
d.run(until_idle=True)                            # send at 3 Hz; returns when everything (and the checksum) is sent
```

A program that keeps running (chat, clock, animation) does not call `run()`; it calls `tick()` from its own loop:

```python
import time
while True:
    ...                     # change the content
    d.present()             # after a change
    d.tick()                # one frame: new content, a refresh, or nothing
    time.sleep(1 / d.cfg.rate_hz)
```

Without VRChat: `Display(dry=True)` and `d.preview("out.png")` render the memory exactly as the shader would.

---

## 2. Concepts

### The screen and its layers

| Layer | Resolution | Coordinates | Content |
|---|---|---|---|
| Graphics `d.gfx` | the screen size (176 × 96 at the default size) | canvas | pixel art, pictures, photos |
| Shapes `d.shapes` | vector, drawn per pixel | screen | 24 hardware lines / rectangles / circles / arcs / polygons / curves |
| Sprites | 4, each 16 × 16 | screen, may be partly off-screen | small images over the graphics, below or above the text |
| Text | the screen size | screen | any number of runs (up to the limits), each with its own position, colour, size |

Stacking, bottom to top: background, graphics, shapes, sprites (below text), text, `above` shapes, sprites (above text).

### Screen sizes (switchable at run time)

`config.json` `screen.sizes` has 6 sizes, each about as many pixels as 128 × 128:
176 × 96 (default, chat), 128 × 128, 208 × 80 (ultra-wide), 160 × 112, 112 × 144 (portrait), 96 × 176 (tall).

`d.set_size(i)` switches to size `i` for every viewer (register `screen`). The graphics canvas is recreated empty at
the new size; `d.cfg.W / H` follow. `d.set_size(i, lowres=True)` also halves the graphics resolution: each graphics
pixel is 2 × 2 screen pixels, the canvas becomes `d.cfg.GW × GH` = `W/2 × H/2`, a quarter of the data (a picture in
about 20 s instead of 60 s). `lowres=False` switches back; omitted = unchanged. Text is not affected.

Pixels keep their physical size, so wide sizes are wider and portrait sizes taller. Memory and run headers are sized for
the largest size, which is why a text background colour can only be palette 0..3.

### Colours

Everything uses palette indices 0..15. The default palette:

| Index | Colour | Index | Colour |
|---|---|---|---|
| 0 | black | 8 | cyan |
| 1 | white | 9 | blue |
| 2 | light grey | 10 | purple |
| 3 | dark grey | 11 | pink |
| 4 | Claude orange | 12 | brown |
| 5 | red | 13 | navy |
| 6 | yellow | 14 | dark green |
| 7 | green | 15 | cream |

`d.palette(colors)` replaces it (16 `(r, g, b)` tuples, 0..255; stored as RGB565, so 65,536 possible colours).
Graphics: each 8 × 8 tile can use at most 4 of the 16 colours (like the NES). With more, the encoder keeps the 4 with the
least error and maps the other pixels to the nearest of them. Shapes and sprites are not bound by tiles.

### Memory, pages and sending

- The memory is 7,230 bytes in 241 pages of 30 bytes. Each frame sends one page: the page id (`KD_P`) plus 30 data
  bytes (`KD_B0..KD_B29`), 248 bits of synced parameters. Default rate 3 frames per second.
- KuraDot avatars come in three **sync tiers** with the same memory: `full` (one frame per page, as above; Klaude),
  `standard` (a page in 2 chunks of 16 bytes, chunk index in the Bool `KD_S0`, 137 bits) and `lite` (3 chunks of 10 bytes,
  `KD_S0`/`KD_S1`, 90 bits; pictures only in low resolution, one side screen). Only the chunks that changed are sent.
  Pick it with `Display(tier=...)` (or env `KD_TIER`, else `config.json` `sync.tier`) or switch with `d.set_tier(t)`
  (everything goes out again). `Config.tier_of(parameter_names)` tells the tier from an avatar's parameters.
- `present()` only encodes. Frames go out from `tick()` or `run()`.
- Only changed pages are sent. A full screen takes a few dozen frames; changing one line of text usually 1 or 2.
- All screen commands (scroll offsets, zoom, transitions, ...) live in one register page: changing one costs 1 frame.

### State versus time

Every command is a **state** ("the offset is now 37 px"), never an action ("move left by 1"). Resending a page any number
of times has no side effect, and a late joiner ends up seeing exactly what everyone else sees.

- **State:** offsets, zoom, mirroring, window, on/off, sprite positions, the end state of a transition. Identical for
  every viewer.
- **Time:** auto-scroll, palette cycling, blinking, a transition while it plays, shape animations. Each viewer runs them
  on their own clock, so the phase differs between viewers: use them for decorative loops only.

---

## 3. The `Display` API

### Creating

```python
Display(cfg=None, sender=None, dry=False, log=None, host=None, port=None,
        feedback=False, listen_host=None, listen_port=None, tier=None)
```

| Argument | Meaning |
|---|---|
| `cfg` | a `kd.config.Config` (default: `kd_display/config.json`) |
| `host`, `port` | VRChat's OSC input. Precedence: argument > env `KD_OSC_HOST` / `KD_OSC_PORT` > `config.json` `osc` |
| `sender` | your own sender object with `send([(address, int), ...])` (default: `kd.osc.Sender`, UDP bundles) |
| `dry` | do not send; encode only (previews, tests) |
| `log` | callback `f(page_id, payload)`, called for every frame sent |
| `feedback` | listen to VRChat's OSC output (default 127.0.0.1:9001) and resend any frame whose parameters did not come back. Optional; it can only check your own client, not other viewers |
| `listen_host`, `listen_port` | where to listen with `feedback` |
| `tier` | the avatar's sync tier: `full` / `standard` / `lite` (default env `KD_TIER`, else `config.json` `sync.tier`) |

On start the client does not know what the avatar still holds (maybe a previous run's content), so the first pass sends
every page: empty graphics pages are replaced by one clear command, all other pages are sent one by one.

Useful attributes: `d.cfg` (layout; `W`, `H`, `GW`, `GH`, `rate_hz` can be changed at run time), `d.gfx` (canvas),
`d.shapes` (shape layer), `d.mem` (the memory image), `d.link` (the sender state), `d.state` (screen registers).

### Text

```python
id = d.text(s, x=0, y=0, width=None, align="left", scale=1, color=1, bg=0, box=False,
            invert=False, wrap=True, line_h=None, id=None, clip=True, move=False, page=False, pages=None,
            screen="main")
```

`screen="left"` / `"right"` puts the text on a side screen (see [Side screens](#side-screens-wings)); `compose()`
takes `screen=` too.

| Argument | Meaning |
|---|---|
| `s` | the text, may contain `\n`. ASCII, all GB2312 hanzi, Japanese (JIS X 0208: kana and both kanji levels), traditional Chinese (Big5 level 1), Korean (KS X 1001), every Latin / Greek / Cyrillic letter incl. Vietnamese (half width), Hebrew and Arabic / Persian / Urdu (right to left, Arabic joined), Thai (consonant + marks clusters), common symbols; a letter the font lacks is drawn without its marks, anything else as □ (Indic scripts: not drawable) |
| `x`, `y` | top-left corner in screen pixels, any position (off-screen too with `clip=False`, e.g. long marquee lines) |
| `width` | layout width, default up to the right edge; longer lines wrap (`wrap=True`) |
| `align` | `left` / `center` / `right` within `width` |
| `scale` | `1`, `2`, `"small"` (5×7 ASCII + 33 common accented letters, other marks dropped; 6×9 px per character, 21 per line) or `"tiny"` (3×5 ASCII, 4×6 px, 32 per line). Standard: latin 7 px, CJK 13 px wide (6 / 12 + 1 px spacing; 13 hanzi per line), glyph height 12, line height 14; doubled at `2`. Small fonts are ASCII only; `"small"` has no background box |
| `color`, `bg` | foreground and background (palette index; background 0..3 only) |
| `box` | draw the background box |
| `invert` | swap foreground and background and draw the box |
| `line_h` | line height, default glyph height + 2 (small fonts 9 / 6) |
| `id` | a key: calling again with the same `id` replaces that text. Default: a new id |
| `clip` | drop lines and characters outside the screen (counted in `present()`'s `clipped`) |
| `move` | this text moves with `text_x` / `text_y` (and their speeds), wraps at `text_wrap` and only shows within `text_clip`. As soon as one text has `move=True`, only those texts move; the others stay put (title bars, clocks) |
| `page` | this text gets whole memory pages to itself: its pages can arrive in any order without garbling, and changing it never blanks other text (a chat line) |
| `pages` | a fixed number of pages: growing or shrinking never shifts what follows; what does not fit is cut |

Returns the text's `id`.

| Call | Meaning |
|---|---|
| `d.remove(id)` / `d.clear_text()` | remove one text / all text |
| `d.measure(s, width=None, scale=1)` | `(w, h)` in pixels |
| `d.compose(parts, id=None, move=False, page=False, pages=None)` | several texts as one item (e.g. a chat line with its time stamp). `parts` is a list of dicts with `text()`'s arguments (`s`, `x`, `y`, `scale`, `color`, ...) |
| `d.fits_pages(parts, pages)` | whether `parts` as one item fit in `pages` pages |
| `d.pages_needed(s, scale=1, x=0, width=None)` | pages this text takes as a page item |
| `d.marquee(s, y0, y1, direction="left", speed=40, scale=1, color=1, x=0, width=None, align="left", gap=None, id="marquee")` | a marquee within rows `y0..y1`, moved per pixel by the shader (no bandwidth). `left`: one line right to left; `up`: wrapped text rising. The wrap period is the text's own length, so the different phase per viewer does not matter. One marquee at a time |

Line breaking: latin by word, CJK by character; no closing punctuation (`，。」`) at a line start and no opening
punctuation (`（「`) at a line end (when unavoidable, latin words are kept whole first); leading spaces are kept.

### Graphics

| Call | Meaning |
|---|---|
| `d.gfx.set(x, y, v)` / `get(x, y)` | one canvas pixel; `v` = palette index |
| `d.gfx.line(x0, y0, x1, y1, v)` | line |
| `d.gfx.rect(x, y, w, h, v, fill=False)` | rectangle |
| `d.gfx.circle(cx, cy, r, v, fill=False)` | circle |
| `d.gfx.blit(bitmap, x, y, transparent=True)` | a 0/1 bitmap (rows of 0/1) |
| `d.gfx.image(path, x, y, w, h, threshold=None)` | a black-and-white picture (error diffusion; `threshold` = hard threshold) |
| `d.gfx.image_palette(path, palette, dither, x, y, w, h)` | a picture mapped to the given palette indices |
| `d.gfx.clear(v=0)` | clear the canvas |
| `d.image(path, dither=True)` | a colour picture, 4 colours per 8×8 tile: the palette is chosen for the picture (median cut) |
| `d.photo(path_or_pixels)` | photo mode: sent in 8×8 tiles, each tile complete in full quality when it arrives, colours blending between tiles. A path, or `GH` rows × `GW` columns of grey 0..1 or `(r, g, b)` 0..1 |
| `d.raw()` | back from photo mode to normal graphics |
| `d.palette(colors)` | replace the palette (16 `(r, g, b)`, 0..255) |

Photo mode and normal graphics share the graphics memory; on a switch the client sends a clear command first, so viewers
never decode old data in the new mode.

### Shapes (hardware drawing)

24 shapes drawn by the shader every frame from a formula (`d.shapes`). Each shape is 10 bytes of memory (3 per page),
so **moving, recolouring or resizing a shape costs 1 frame**: no bitmap is redrawn and the 4-colours-per-tile limit does
not apply. Shapes are kept by number: calling again with the same `i` changes that shape. Coordinates are screen pixels
(-32..223, may be partly off-screen); angles in degrees, 0 = 12 o'clock, clockwise.

| Call (`S = d.shapes`) | Meaning |
|---|---|
| `S.line(i, x0, y0, x1, y1, color, width=1, round_caps=False)` | a line, 1-7 px wide, square or round ends |
| `S.rect(i, x, y, w, h, color, fill=None, width=1, radius=0, angle=0)` | rectangle (`radius` > 0: rounded), may be rotated |
| `S.ellipse(i, cx, cy, rx, ry=None, color, fill=None, width=1, angle=0)` / `S.circle(...)` | ellipse / circle |
| `S.arc(i, cx, cy, r, start=0, sweep=360, color, thickness=1)` | arc or ring (`r` = middle radius): progress rings, spinners |
| `S.pie(i, cx, cy, r, start=0, sweep=90, color, fill=None, width=1)` | pie slice (charts, countdowns) |
| `S.tri(i, p0, p1, p2, color, fill=None, width=1)` | triangle; points are `(x, y)` |
| `S.poly(i, cx, cy, r, sides=6, star=0, angle=0, color, fill=None, width=1)` | regular polygon (3-12 sides); `star` = inner / outer radius (0..1) makes a star |
| `S.bezier(i, p0, p1, p2, color, width=1)` | quadratic curve from `p0` to `p2`, pulled by `p1` |
| `S.hide(i)` / `S.clear()` / `S.free()` | remove one / all; the first free number |

- With `fill` the inside is filled and `width` is the outline (0 = none); without `fill` only the outline is drawn in
  `color`. Lines, arcs and curves only use `color`.
- Options for every call:
  - `pattern`: `"solid"`, `"checker"`, `"hstripes"`, `"vstripes"`, `"diagonal"`, `"dots"` (skipped pixels are
    transparent), or `"hgradient"` / `"vgradient"` (a dithered gradient between the fill and the outline colour).
  - `above=True`: above the text (default: below text and sprites).
  - `xor=True`: invert what is below (cursors, selections); text and sprites on top are not affected.
  - `follow=True`: move and zoom with the graphics layer (map markers, objects in a side-scroller).
  - `anim` (time-based, phase differs per viewer): `("rotate", turns/s)` (-1.9..1.9), `("pulse", Hz)` (size ±20%),
    `("blink", Hz)`, `("sweep", turns/s)` (the start of an arc / pie keeps turning: spinners).
- Whole layer: `d.set(shape_x=..., shape_y=...)` moves all shapes, `shape_vx` / `shape_vy` auto-scroll (-128..127
  px/s), like the text layer. Shapes wrap at the screen edges by their anchor (first point or centre).
- Higher numbers draw over lower ones.
- The byte format is in `kd/shapes.py` (`encode()`, `Shape`); `shapes.paint()` is the reference rasteriser the
  simulator uses, and the shader follows the same rules.

### Sprites

```python
d.sprite(i, x=None, y=None, pattern=None, colors=None, visible=None,
         flip_x=None, flip_y=None, double=None, above_text=None, screen=None)
```

- `i`: 0..3. Arguments left at `None` keep their value.
- `x`, `y`: top-left in screen pixels, -32..223 (partly off-screen is fine).
- `pattern`: 16 rows of 16 values 0..3, or strings (`.` or space = 0). 0 is transparent. Setting a pattern for the
  first time makes the sprite visible.
- `colors`: palette indices for pixel values 1, 2, 3.
- `double`: twice the size (2×2 screen pixels per sprite pixel). `above_text`: draw over the text.
- Moving a sprite changes 1 page, i.e. 1 frame; the background is not resent.

### Screen state: `d.set(**kw)`

| Key | Values | Kind | Meaning |
|---|---|---|---|
| `on` | bool | state | show / hide the screen (with the pop-up animation, below) |
| `gfx`, `text`, `sprites` | bool | state | layers on / off |
| `invert` | bool | state | invert the whole screen |
| `mono`, `mono_fg`, `mono_bg` | bool, colour, colour | state | monochrome: brightness mapped between two colours |
| `dither` | bool | state | retro dithering in photo mode |
| `gfx_x`, `gfx_y` | px | state | move the graphics layer; it wraps around the edges |
| `text_x`, `text_y` | px | state | move the (moving) text; wraps too |
| `shape_x`, `shape_y` | px | state | move the shape layer |
| `gfx_vx`, `gfx_vy`, `text_vx`, `text_vy`, `shape_vx`, `shape_vy` | -128..127 px/s | time | auto-scroll, smooth, no bandwidth |
| `zoom` | 1 / 2 / 4 | state | graphics magnification |
| `mirror_x`, `mirror_y` | bool | state | mirror the screen (not the frame) |
| `window` | `(x0, y0, x1, y1)` or `None` | state | show the graphics only inside this rectangle (aligned to 16 px cells, clamped to the screen) |
| `cycle` | `(first, count, steps/s)` or `None` | time | palette cycling over these colours |
| `blink` | `(colour, Hz)` or `None` | time | this colour blinks (alternating with colour 0), 0.5 Hz steps, up to 7.5 |
| `text_wrap` | `(w, h)` or `None` | state | wrap period of moving text (w in 8 px, h in 2 px steps, max 2040 / 510); `None` = screen size |
| `text_clip` | `(y0, y1)` or `None` | state | moving text only shows in these rows (pixel-exact); `y0 == y1` hides it |
| `size_m` | 0.20 .. 0.60 | state | width of the screen in metres (for a 128 px wide screen) |
| `wings` | bool, `"left"`, `"right"` | state | unfold both side screens, or only one (see below) |
| `wing_text_y` | `(left, right)` | state | a side screen's own vertical offset for its moving text (`None`: it moves with `text_y`) |
| `wing_shape_y` | `(left, right)` | state | a side screen's shape offset (like `shape_y`; its `follow=True` shapes stay put) |
| `wing_pages` | `(left, right)` | state | text pages of the side screens' regions (default from `config.json`, 4 + 4) |

### Side screens (wings)

Two more screens of the main screen's size, folded behind it like a satellite's solar arrays. `d.set(wings=True)`
unfolds them (about 1.4 s: the inner panel swings out around its hinge, the outer one unfolds, then the screens power
on); `wings=False` folds them, `wings="left"` / `"right"` unfolds only that one (the other folds). With one side screen
open the device turns around the seam between it and the main screen. At the left / right positions the avatar moves the display outward while they open, so
they never reach into it. They have no title bar and no status bar.

Everything that can go on the main screen can go on a side screen, in the side screen's own coordinates (0..W,
0..H, the same size as the main screen):

```python
d.set(wings=True)
d.text("今日はいい天気ですね", 4, 4, width=168, screen="left")
d.shapes.rect(3, 4, 70, 168, 20, color=3, fill=13, screen="right")
d.sprite(2, x=10, y=10, pattern=pat, screen="right")
d.set_size(0, lowres=True)                       # pictures on side screens need the low resolution
d.wing_picture("left", rows)                     # rows of palette indices, cfg.GW x cfg.GH
d.present()
```

**No extra memory: the content is routed.** Registers in the same page as `show` (a late joiner gets them together
with the device, and they only change when the split changes) say which part of the memory belongs to which screen:

- **Text:** the side screens' text sits in regions at the END of the text area (`wing_pages` pages each, default 4 + 4),
  the main screen's text before them. The main screen has that much less text memory while a side screen has text.
  Moving side-screen text (`move=True`) moves with the main screen's text registers (`text_x/y`, speeds, `text_wrap`,
  `text_clip`): a side screen's still items fill the first pages of its region, its moving ones start on the next page
  (register `wing_mv`). Three chat logs scroll in step with one register write, or each on its own with
  `wing_text_y` (registers `wing_ly` / `wing_ry`).
- **Shapes:** the driver stores the main screen's shapes first, then the left's, then the right's (it renumbers the
  slots in memory; you keep using your own slot numbers).
- **Sprites:** 2 bits per sprite.
- **Pictures:** a side screen's picture uses its own range of graphics tiles (`config.json` wings.tiles), so pictures
  on side screens need the low-resolution mode (2×2 px dots): up to three pictures, all low resolution, sharing the
  16-colour palette. Photo mode and the graphics registers (scrolling, zoom, window, mirror) are the main screen's.

Transitions, scrolling and the status bar belong to the main screen.

### Appearing, leaving and the chime

- `d.set(on=True / False)` also writes register `show`: the whole screen pops up with an overshoot and the picture
  opens from a line like an old CRT; leaving plays it backwards. A screen that was never turned on is not shown.
- `d.chime()`: plays a chime on the avatar (a command frame, page id 255; it uses the avatar's shared one-shot audio
  source). People nearby hear it; late joiners do not. Two chimes in a row get an idle frame in between.

### Transitions

```python
d.transition(effect="fade", show=True, duration=0.5)
```

- `effect`: `cut`, `fade`, `wipe_right`, `wipe_down`, `slide_left`, `slide_up`, `dissolve`, `iris`.
- `show=False` hides the content, `True` shows it. `duration`: the nearest of 0.25 / 0.5 / 1 / 2 s.
- Timing (several transitions queue in call order): a **hide** takes effect as soon as the previous transition has been
  sent; a **show** waits until the content still pending at the next `present()` has been sent (at most 10 s), so the
  fade-in shows the new content. Typical: `transition(..., show=False)`, change the content, `transition(..., show=True)`.
- Each viewer plays it once when the register arrives; a late joiner plays it once on joining and ends in the same state.

### Scrolling helpers

| Call | Meaning |
|---|---|
| `d.scroll(dx, dy, layer="gfx", clear=True)` | move a layer by `(dx, dy)` px with one register change (1 frame). For the graphics, the strip that wrapped in from the other side is cleared; returns that strip as screen rectangles `[(x, y, w, h)]` to draw into (side-scrollers, chat) |
| `d.gfx_xy(sx, sy)` | screen position -> canvas position under the current offset and zoom |
| `d.text_xy(sx, sy)` | screen position -> text position (where to put a moving text so it shows at that spot) |

### Encoding and sending

| Call | Meaning |
|---|---|
| `info = d.present()` | encode the current content. Returns a dict: `runs`, `glyphs`, `text_bytes`, `pages` (pending), `eta_s` (seconds until sent), `missing` (characters not in the font), `clipped` (characters outside the screen), `dropped` (characters that did not fit the text memory) |
| `d.tick()` | send one frame; returns `(page_id, payload)` or `None` when there was nothing to send |
| `d.run(until_idle=False, stop=None)` | send at `rate_hz` until `stop()` returns true; `until_idle=True` returns once everything (checksums and queued transitions included) has been sent |
| `d.settled()` | everything sent |
| `d.checksums(buf)` | renderer name -> the 16-bit checksum of a memory image (what each viewer's shader computes) |
| `d.synced(buf)` | whether a memory image matches its checksums (what the status bar would show) |
| `d.preview(path, scale=4)` | render the current memory to a PNG (Pillow) |
| `d.cfg.rate_hz` | frames per second; may be changed at run time |

---

## 4. Limits

| What | Limit | Beyond it |
|---|---|---|
| Text memory | 1,530 bytes for all screens (100 hanzi on a full screen take about 190); side screens take `wing_pages` × 30 bytes each from it | from the first text that does not fit on, nothing shows; counted in `dropped` |
| Text runs | 128 (a line break or a latin / CJK switch starts a new run) | as above |
| Characters on screen | 480 | as above |
| One run | 31 characters (split automatically) | - |
| Text coordinates | a run's position fields are 0..127; farther runs continue from the previous one (same line or a few lines down), so long lines and columns work | negative positions, or more than 127 from the previous run, do not fit (`dropped`); with `clip=True` the off-screen part is cut (`clipped`) |
| Sprites | 4, 16×16, 4 colours each (incl. transparent) | - |
| Shapes | 16; coordinates -32..223, radius 0..255, line width 0..7 | values are clamped |
| Graphics | 4 colours per 8×8 tile (full resolution) | the best 4 are chosen, light dithering in the tile |

---

## 5. Sync, late joiners and the status bar

- **Send order:** palette, registers, sprite registers, text, tile colours, bitmap, sprite patterns. The palette first:
  without it everything is black.
- **Fairness:** the longer a page waits, the earlier it goes, so content that changes all the time (clocks, animation)
  never starves the rest.
- **Text consistency:** text is a chain of runs.
  - Same structure, new characters (a clock's digits): sent as is.
  - Page items (`page=True`): every page stands alone, sent as is.
  - Appending at the end: the new pages go first, the page with the old end last.
  - Other structural changes: the chain is cut before the first changed run first; the text before it stays, the text
    after it disappears until the remaining pages have arrived. Never garbled.
  - A run header never crosses a page, so a page's structure is defined by that page alone.
- **Refresh:** the client keeps resending every non-empty page in turn; late joiners and anyone who lost a frame catch up
  from it: 3 pages per second when idle; while new content keeps coming, at least every 4th frame is a refresh, a third
  of them for the core pages (palette, registers, text). A page that was just cleared is refreshed for 2 more minutes.
- **How long a late joiner waits** (3 Hz, static screen): about 5 s for the text and the screen state, about 20 s for
  everything. With the screen changing constantly about 20 s and 85 s.
- **Status bar** (bottom edge of the frame): steady green = this viewer's copy is complete; an orange light running back
  and forth = still arriving (just joined, a frame lost, being updated). The client writes position-weighted checksums
  of the memory into the registers once everything else has been sent; each viewer's shader computes the same sums over
  its own copy and compares. While the screen keeps changing, the bar keeps running.

---

## 6. Recipes

### Chat log with hardware scrolling

Each line gets two fixed pages (`move=True, pages=2`) in a 128 px ring; `text_y` scrolls the whole log up:

- A new line sends only its two pages plus one register frame; the other lines are not resent.
- The new line is written below the visible area first, then the register scrolls it in.
- A line that scrolled out at the top is cleared before it wraps back into view.

The complete implementation, with dividers, time stamps, live typing updates and pictures, is `kd_chat.py`.

### Clock (one page per second, no flicker)

```python
import time, datetime
d.text("Klaude", 0, 12, d.cfg.W, "center", scale=2, id="title")
last = None
while True:
    now = datetime.datetime.now().strftime("%H:%M:%S")
    if now != last:
        last = now
        d.text(now, 0, 50, d.cfg.W, "center", scale=2, id="clock")
        d.present()
    d.tick(); time.sleep(1 / d.cfg.rate_hz)
```

### Marquee

```python
d.text("12:34", 2, 2, scale="tiny")                                # the fixed part
d.marquee("Welcome to Klaude's room - this line can be much longer than the screen", 56, 72, "left", speed=40)
d.present()                 # no more frames needed: the shader scrolls it pixel by pixel
```

### Progress ring and spinner with shapes

```python
S = d.shapes
S.circle(0, 88, 48, 30, color=3, width=2)                               # track
S.arc(1, 88, 48, 30, start=0, sweep=0, color=4, thickness=4)            # progress
S.arc(2, 88, 48, 20, sweep=90, color=1, thickness=2, anim=("sweep", 1)) # spinner, no bandwidth
for p in range(0, 101, 5):
    S.arc(1, 88, 48, 30, start=0, sweep=360 * p / 100, color=4, thickness=4)   # 1 frame per update
    d.present(); d.tick(); time.sleep(1 / d.cfg.rate_hz)
```

### Sprite animation

```python
d.sprite(0, x=10, y=80, pattern=["....3333....", "..33111133..", ...], colors=(6, 5, 12))
for x in range(10, 110, 4):
    d.sprite(0, x=x)
    d.present(); d.tick(); time.sleep(1 / d.cfg.rate_hz)
```

### Changing screens with a transition

```python
d.transition("wipe_down", show=False, duration=0.5)
d.present(); d.run(until_idle=True)
d.clear_text(); d.gfx.clear(); d.text("Next page", 4, 4)
d.transition("wipe_down", show=True, duration=0.5)
d.present(); d.run(until_idle=True)
```

### Side-scroller

```python
for step in range(30):
    for (x, y, w, h) in d.scroll(-4, 0):           # move everything 4 px left; returns the strip that opened up
        for sx in range(x, x + w, 2):
            cx, cy = d.gfx_xy(sx, 0)
            d.gfx.line(cx, 40, cx, 63, 7)           # draw new terrain into it
    d.present(); d.tick(); time.sleep(1 / d.cfg.rate_hz)
```

### Running inside kdchat

kdchat owns the display while its "Klaude display" output is on. To run your own program, turn that output off in
kdchat's settings (or stop kdchat): two clients sending at once overwrite each other's pages.

---

## 7. Lower-level modules

Most programs only need `Display`. These are the layers underneath, for tools and unusual uses.

| Module | What it is |
|---|---|
| `kd.config.Config(path=None)` | `config.json` plus the derived memory layout, shared with the avatar build so both always agree. `W`, `H`, `GW`, `GH`, `P` (bytes per page), `mem_bytes`, `regions` (name -> `(offset, length)`), `rate_hz`, `renderers`; `param_page()`, `param_byte(k)`, `osc_target(host, port)`, `osc_listen(port, host)`, `set_size(i, gscale)`, `summary()` |
| `kd.memory.Memory(cfg)` | the memory image `buf` (bytearray) and its encoders: `reg(name, value)`, `set_palette`, `set_gfx(pixels)`, `set_photo`, `clear_gfx`, `set_runs(runs)`, `set_sprite`, `set_sprite_colors`, `set_sprite_pattern`, `set_shape(i, data)`, `page(p)` -> 30 bytes |
| `kd.link.Link(cfg, send_frame)` | keeps the remote copy in step: `update(buf)` marks changed pages, `tick()` sends the next frame (new content, refresh or nothing), `command(cid)` queues a command frame, `pending()`, `eta()`, `forget()` (assume the avatar lost everything: resend all) |
| `kd.layout.Layout(cfg, charmap, fallback)` | text layout: `lines(text, max_w, scale, wrap)`, `runs(...)`, `glyph(ch, scale)`, `width(...)` |
| `kd.canvas.Canvas(w, h)` | the graphics canvas (`d.gfx`) |
| `kd.shapes` | `encode(kind, fill, stroke, coords, ...)` -> the 10 shape bytes; `Shape(bytes)` decodes; `paint()` is the reference rasteriser |
| `kd.osc` | `Sender(host, port, use_bundle=True).send([(addr, value), ...])`, `Listener(port, on_message, host)`, `message()`, `bundle()`, `parse()`: minimal OSC over UDP |
| `kd.sim` | the reference decoder: `render(mem, font_png=None, t=0.0, fx_time=None)` -> rows of `(r, g, b)` exactly as the shader draws; `to_png(img, path, scale)` |
| `kd.tiny` | the two small ASCII fonts |

Example: write raw graphics memory yourself and still use the link layer:

```python
d.gfx_manual = True                  # present() leaves the bitmap and tile colours alone
a, n = d.cfg.regions["bitmap"]
d.mem.buf[a:a + n] = my_bitmap_bytes
d.present()
```

---

## 8. Wire protocol and memory map

**Frames.** One OSC bundle per frame to `/avatar/parameters/...`:

| Parameter | Type | Meaning |
|---|---|---|
| `KD_P` | int 0..255 | page id; the page's bytes are `KD_B0..KD_B29` of the same frame |
| `KD_S0`, `KD_S1` | bool | (standard / lite tiers only) the chunk index s: which part of the page the bytes are |
| `KD_B0` .. `KD_B29` | int 0..255 | the 30 bytes of the page (standard: `KD_B0..15` = page bytes 16 s .. 16 s + 15; lite: `KD_B0..9` = page bytes 10 s .. 10 s + 9) |

Page ids: 0 = idle, 1..239 = memory pages; 254 = clear graphics and 255 = chime (commands, allocated downwards from
255, so the memory can grow upwards); 240..253 are free. While `KD_P` holds a page id, the avatar's animator
writes `KD_B0..KD_B29` into its copy of that page; the words stay when the id changes. A frame must stay for at least
2 of the viewer's animator frames, which 3 Hz easily is.

**Memory map** (default `config.json`; read `d.cfg.regions` instead of hard-coding):

| Region | Offset | Bytes | Content |
|---|---|---|---|
| `bitmap` | 0 | 4480 | graphics, 2 bits per pixel (or photo coefficients) |
| `tilecol` | 4480 | 560 | the 4 palette indices of every 8×8 tile |
| `palette` | 5040 | 32 | 16 colours, RGB565 |
| `text` | 5100 | 1530 | the run chain (headers + 7 / 12 / 14-bit glyph codes) |
| `regs` | 6630 | 52 | screen registers: `flags`, `gfx_mode`, offsets, speeds, `fx`, `cycle`, `timing`, `blink_view`, window, checksums, text wrap / clip, `screen`, `show` (bit 0 shown, bit 1 left side screen open, bit 2 right), `size`, shape offsets, side-screen routes `wing_tl` / `wing_tr` (first text page of each region), `wing_gl` / `wing_gr` (first tile of each picture), `wing_shp` (first shape slot left << 4 \| right), `wing_spr` (2 bits per sprite), `wing_mv` (first moving page of each wing's region, left << 4 \| right), `wing_ly` / `wing_ry` (a wing's own text offset + 1, 0 = follows `text_y`), `wing_lsy` / `wing_rsy` (a wing's shape offset) |
| `sprites` | 6690 | 276 | 4 sprites: registers, colours, 16×16 2-bit patterns |
| `shapes` | 6990 | 240 | 24 shapes × 10 bytes |

Glyph codes: ASCII 7 bits, the common page (kana + 3,755 hanzi) 12 bits, everything else 14 bits; a stretch that mixes
common and extended full-width glyphs is written in the extended mode alone when that is shorter (Japanese).
An extended run's pitch is the block of its first code (charmap `half_range`: 6 px + 1, Latin / Greek / Cyrillic /
symbols, ASCII copies first; `narrow_range`: 8 px + 1, Hebrew, Arabic presentation forms, Thai clusters, ASCII copies
first; else 12 px + 1), so a run never mixes blocks. The layout (`kd/scripts.py`) orders right-to-left lines for
drawing, shapes Arabic, clusters Thai, and takes ASCII letters next to accented ones from the half-width block when
that saves run headers. Characters the font has in both widths (é, Greek, “ …) follow their neighbours: full width
next to CJK, half width otherwise. Thai clusters are private-use code points in the charmap table (`clusters`).

**Checksums.** The memory is held as 16-bit words split over several renderers. For each renderer the client sends
`sum((2 * i + 1) * word_i) mod 65536` over that renderer's words (`i` = the word's index in the renderer, the checksum
words left out) in the `sum*` registers, after everything else. Odd weights are invertible mod 65536, so any single
wrong word changes the sum and swapped words are caught. `d.checksums(buf)` computes them.

**Changing `config.json`.** The layout is compiled into the avatar (shader and animator). Only use the `config.json`
that matches the avatar version you are driving; a different layout needs a matching avatar build.

---

## 9. Known limitations

- **Strangers may not see it:** VRChat hides custom shaders from strangers by default; they need to "Show Avatar" for
  you. The Quest / Android and iOS versions of the avatar have no display.
- **Transitions may replay for remote viewers** if the network splits a frame (not observed, a guess).
- **The status bar keeps running while the screen keeps changing:** the checksums are only written once nothing else is
  pending.
- **Frequent structural text changes blank the text after the change** until all its pages arrive. For text that
  changes often use `page=True` / `pages=N`.
- **A line spanning two pages** can show its first half new and second half old for a frame when the pages arrive apart.
- **A text starting above the screen is dropped whole** (positions cannot be negative); characters beyond the left edge
  are cut individually.
- **Rate:** 3 Hz is a conservative default.
