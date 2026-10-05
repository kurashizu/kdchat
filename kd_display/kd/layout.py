"""Text layout -> runs. Any pixel position, wrapping (words for latin, per character for CJK, simple kinsoku),
alignment, x2 scale, inverse video. A line is split into runs wherever the code page changes."""
from .config import MODE_ASCII, MODE_TINY, MODE_SMALL, SMALL_FONTS

NO_START = set("，。、；：？！）」』】》〉…—～·,.;:?!)]}%")
NO_END = set("（「『【《〈([{")


class Layout:
    def __init__(self, cfg, charmap, fallback="□"):
        self.cfg, self.cm, self.fallback = cfg, charmap, fallback
        self.missing = set()
        self.clipped = 0                     # glyphs left out because they fall outside the screen

    def glyph(self, ch, scale=1):
        if scale in SMALL_FONTS:                      # the small fonts: ASCII only
            cp = ord(ch)
            if not 0x20 <= cp < 0x7F:
                self.missing.add(ch)
                cp = ord("?")
            return SMALL_FONTS[scale][0], cp - 0x20
        m = self.cm.mode_of(ch)
        if m is None:
            self.missing.add(ch)
            m = self.cm.mode_of(self.fallback)
        return m

    def width(self, mode, scale=1):
        return self.cfg.adv(mode, scale)

    def slack(self, scale=1):
        """a line may be this much wider than its box: the gap after the last glyph and the glyph's own empty last
        column do not show (10 CJK at 12 + 1 px fill exactly 128 px)"""
        return 1 if scale in SMALL_FONTS else (self.cfg.gap + 1) * scale

    def lines(self, text, max_w, scale=1, wrap=True):
        """-> list of lines, each a list of (mode, code, advance, char). Latin words stay whole unless longer than a line
        (then they are split); CJK breaks anywhere; a line never starts with closing punctuation or ends with opening
        punctuation when that can be avoided without overflowing; no line is wider than max_w and none is empty (except
        for empty paragraphs)."""
        out = []
        wrap = bool(wrap and max_w and max_w > 0)
        if wrap:
            max_w += self.slack(scale)
        for para in text.split("\n"):
            cells = [self.glyph(ch, scale) + (self.width(self.glyph(ch, scale)[0], scale), ch) for ch in para]
            LATIN = (MODE_ASCII, MODE_TINY, MODE_SMALL)
            units, i = [], 0
            while i < len(cells):                     # a latin word is one unit; everything else one character
                j = i + 1
                if cells[i][3] != " " and cells[i][0] in LATIN:
                    while j < len(cells) and cells[j][0] in LATIN and cells[j][3] != " ":
                        j += 1
                units.append(cells[i:j]); i = j
            line, w, lines = [], 0, []
            width = lambda cs: sum(c[2] for c in cs)

            def flush(strip=True):
                nonlocal line, w
                while strip and line and line[-1][3] == " ":
                    line.pop()                        # spaces at a wrap break disappear
                if line:
                    lines.append(line)
                line, w = [], 0

            for unit in units:
                uw = width(unit)
                if not wrap:
                    line += unit; w += uw; continue
                if unit[0][3] == " ":
                    if w + uw <= max_w and (line or not lines):
                        line += unit; w += uw         # kept, also at the start of the paragraph (indent, box padding)
                    elif line:
                        flush()                       # a space at the break disappears
                    continue
                if uw > max_w:                        # longer than a whole line: split it
                    for c in unit:
                        if line and w + c[2] > max_w:
                            flush()
                        line.append(c); w += c[2]
                    continue
                if line and w + uw > max_w and all(c[3] in NO_END for c in line if c[3] != " "):
                    # only opening punctuation on this line: fill it with the start of the word instead of leaving it alone
                    for c in unit:
                        if w + c[2] > max_w:
                            flush()
                        line.append(c); w += c[2]
                    continue
                if line and w + uw > max_w:
                    carry = []
                    # closing punctuation never starts a line: take the previous (non-latin) character down with it
                    if unit[0][3] in NO_START and len(line) > 1 and line[-1][3] != " " and line[-1][0] not in LATIN \
                            and width([line[-1]]) + uw <= max_w:
                        carry.insert(0, line.pop())
                    # opening punctuation never ends a line (but never move the whole line)
                    while len(line) > 1 and line[-1][3] in NO_END and width([line[-1]] + carry) + uw <= max_w:
                        carry.insert(0, line.pop())
                    flush()
                    line, w = carry, width(carry)
                line += unit; w += uw
            flush(strip=False)
            out.extend(lines if lines else [[]])
        return out

    def runs(self, text, x=0, y=0, width=None, align="left", scale=1, fg=1, bg=0, box=False, wrap=True, line_h=None,
             clip=True):
        """clip: leave out lines below / above the screen and glyphs past its right edge (the text space wraps around,
        so they would land on top of other text); clip=False keeps everything (e.g. invisible padding)"""
        from .memory import Run
        W, H = self.cfg.W, self.cfg.H
        max_w = width if width is not None else W - x
        lh = line_h or self.cfg.line_h(scale)
        runs, ln = [], 0
        for ln, line in enumerate(self.lines(text, max_w, scale, wrap)):
            lw = sum(c[2] for c in line)
            if not box:                                   # trailing spaces do not count for alignment (box: they do)
                k = len(line)
                while k and line[k - 1][3] == " ":
                    k -= 1
                lw = sum(c[2] for c in line[:k])
            if line:
                lw = max(0, lw - self.slack(scale))       # centre / right-align the ink, not the trailing gap
            lx = x + max(0, (max_w - lw if align == "right" else (max_w - lw) // 2 if align == "center" else 0))
            ly = y + ln * lh
            if clip and (ly < 0 or ly >= H or lx >= W):   # whole line outside (a run cannot start above the screen)
                self.clipped += len(line)
                continue
            cx, cur = lx, None
            for mode, code, adv, ch in line:
                if clip and (cx >= W or cx < 0):            # glyphs left / right of the screen
                    self.clipped += 1
                    cx += adv
                    continue
                if cur is None or cur.mode != mode or len(cur.codes) >= self.cfg.max_run_len:
                    cur = Run(cx, ly, mode, [], fg, bg, box, scale)
                    runs.append(cur)
                cur.codes.append(code)
                cx += adv
        runs = [r for r in runs if r.codes]
        bbox = (x, y, max_w, (ln + 1) * lh)
        return runs, bbox
