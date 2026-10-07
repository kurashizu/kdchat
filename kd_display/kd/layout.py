"""Text layout -> runs. Any pixel position, wrapping (words for latin, per character for CJK, simple kinsoku),
alignment, x2 scale, inverse video. A line is split into runs wherever the code page changes."""
import unicodedata

from .config import MODE_ASCII, MODE_COMMON, MODE_EXT, MODE_TINY, MODE_SMALL, SMALL_FONTS
from .tiny import SMALL_CODES, fold
from . import scripts

NO_START = set("，。、；：？！）」』】》〉…—～·,.;:?!)]}%")
def hangul(ch):
    """a Korean syllable / jamo: Korean breaks lines at spaces, like latin words"""
    return "\uac00" <= ch <= "\ud7a3" or "\u3131" <= ch <= "\u318e"


NO_END = set("（「『【《〈([{")


def wide(ch):
    """a full-width character (CJK, kana, Hangul, full-width forms): punctuation next to it is drawn full width too"""
    o = ord(ch[0]) if ch else 0
    return 0x1100 <= o <= 0x11FF or 0x2E80 <= o <= 0xA4CF or 0xAC00 <= o <= 0xD7A3 or 0xF900 <= o <= 0xFAFF \
        or 0xFE30 <= o <= 0xFE4F or 0xFF00 <= o <= 0xFF60 or 0xFFE0 <= o <= 0xFFE6 or o >= 0x20000


class Line(list):
    """a laid out line (its cells in reading order) + rtl: its paragraph reads right to left"""
    rtl = False


class Layout:
    def __init__(self, cfg, charmap, fallback="□"):
        self.cfg, self.cm, self.fallback = cfg, charmap, fallback
        self.missing = set()
        self.clipped = 0                     # glyphs left out because they fall outside the screen

    def glyph(self, ch, scale=1, full=False):
        """ch: a character or a Thai cluster; full: draw a character the font has in both widths full width"""
        if scale in SMALL_FONTS:                      # the small fonts: ASCII (+ accented letters in "small"; fold())
            from .tiny import small_code
            cp = ord(ch)
            if scale == "small" and not 0x20 <= cp < 0x7F:
                code = small_code(ch)
                if SMALL_CODES[code] != ch:
                    self.missing.add(ch)
                return SMALL_FONTS[scale][0], code
            if not 0x20 <= cp < 0x7F:
                self.missing.add(ch)
                cp = ord("?")
            return SMALL_FONTS[scale][0], cp - 0x20
        m = self.cm.mode_of(ch, full)
        if m is None:
            # what the font lacks: a simpler Thai cluster, the letter without its marks (ǩ -> k, polytonic Greek),
            # else the fallback box
            bare = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))
            for alt in scripts.thai_fallbacks(ch) + [bare]:
                if alt and alt != ch:
                    m = self.cm.mode_of(alt, full)
                    if m is not None:
                        return m
            self.missing.add(ch)
            m = self.cm.mode_of(self.fallback)
        return m

    def width(self, mode, scale=1, code=None):
        return self.cfg.adv(mode, scale, code)

    def cls(self, cell):
        """a cell's width class: half (ASCII, the half-width block), narrow or full"""
        w = self.cfg.width_of(cell[0], cell[1]) if cell[0] in (MODE_ASCII, MODE_COMMON, MODE_EXT) else 0
        return "narrow" if w == self.cfg.narrow and w != self.cfg.half else "full" if w == self.cfg.cell else "half"

    def wordish(self, cell):
        """part of a word (lines break between words): Latin / Greek / Cyrillic letters, Hebrew, Arabic, Korean; Thai and
        CJK break between characters"""
        if cell[0] in (MODE_ASCII, MODE_TINY, MODE_SMALL):
            return True
        if hangul(cell[3]):
            return True
        c = self.cls(cell)
        return c == "half" or c == "narrow" and not "\u0e00" <= cell[3][0] <= "\u0e7f"

    def _cells(self, toks, scale):
        """tokens -> cells (mode, code, advance, token): Arabic letters in their joining forms, characters the font has
        in both widths by their neighbours, ASCII inside Hebrew / Arabic / Thai text at the narrow pitch (one run)"""
        if scale in SMALL_FONTS:
            return [self.glyph(t, scale) + (self.width(self.glyph(t, scale)[0], scale), t) for t in toks]
        cm = self.cm
        shaped = scripts.shape(toks, lambda ch: cm.mode_of(ch) is not None) if any(
            "\u0600" <= t[0] <= "\u06ff" for t in toks if t) else toks
        n = len(toks)
        full = [False] * n
        for i, t in enumerate(toks):
            if cm.both(t):
                # the nearest neighbour that is not itself ambiguous / a space decides (before it, else after it)
                for k in list(range(i - 1, -1, -1)) + list(range(i + 1, n)):
                    u = toks[k]
                    if u.isspace() or cm.both(u):
                        continue
                    full[i] = wide(u)
                    break
        cells = []
        for i, t in enumerate(toks):
            if t in (scripts.ZWJ, scripts.ZWNJ):
                continue
            m = self.glyph(shaped[i], scale, full[i])
            cells.append(m + (self.width(m[0], scale, m[1]), t))
        # ASCII between narrow glyphs (spaces, digits, punctuation in Hebrew / Arabic / Thai): their narrow copies
        k = 0
        while k < len(cells):
            if cells[k][0] != MODE_ASCII:
                k += 1
                continue
            j = k
            while j < len(cells) and cells[j][0] == MODE_ASCII and not cells[j][3].isalpha():
                j += 1
            if j > k and k > 0 and j < len(cells) and self.cls(cells[k - 1]) == "narrow" and self.cls(cells[j]) == "narrow":
                for q in range(k, j):
                    code = cm.ascii_as(cells[q][1], "narrow")
                    cells[q] = (MODE_EXT, code, self.width(MODE_EXT, scale, code), cells[q][3])
            k = max(j, k + 1)
        return cells

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
        base_w = max_w
        if scale in SMALL_FONTS:
            text = fold(text, extra=scale == "small")    # accents the font lacks: dropped (é stays, ș -> s)
        else:
            text = scripts.clean(text)
        for para in text.split("\n"):
            toks = scripts.tokens(para) if scale not in SMALL_FONTS else list(para)
            rtl = scale not in SMALL_FONTS and scripts.paragraph_rtl(toks)
            cells = self._cells(toks, scale)
            para = [c[3] for c in cells]
            if wrap:                                  # (narrow glyphs have ink in their last column: less slack)
                narrow = any(c[0] == MODE_EXT and self.cls(c) == "narrow" for c in cells)
                max_w = base_w + (self.cfg.gap * (scale if scale not in SMALL_FONTS else 1) if narrow else self.slack(scale))
            if scale not in SMALL_FONTS:
                # a space between Korean words: the full-width blank (U+3000), so a Korean line stays in one code mode
                # (every switch to ASCII and back costs two run headers: a line of short words would not fit its memory)
                for k in range(1, len(para) - 1):
                    if para[k] == " " and hangul(para[k - 1]) and hangul(para[k + 1]):
                        g = self.glyph("\u3000", scale)
                        cells[k] = g + (self.width(g[0], scale), " ")
            units, i = [], 0
            while i < len(cells):                     # a latin / Korean word is one unit; everything else one character
                j = i + 1
                if cells[i][3] != " " and self.wordish(cells[i]):
                    kor = hangul(cells[i][3])
                    while j < len(cells) and cells[j][3] != " " and (self.wordish(cells[j])
                                                                     or kor and cells[j][3] in NO_START):
                        kor = kor or hangul(cells[j][3])
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
                    if unit[0][3] in NO_START and len(line) > 1 and line[-1][3] != " " and not self.wordish(line[-1]) \
                            and width([line[-1]]) + uw <= max_w:
                        carry.insert(0, line.pop())
                    # opening punctuation never ends a line (but never move the whole line)
                    while len(line) > 1 and line[-1][3] in NO_END and width([line[-1]] + carry) + uw <= max_w:
                        carry.insert(0, line.pop())
                    flush()
                    line, w = carry, width(carry)
                line += unit; w += uw
            flush(strip=False)
            for ln in lines if lines else [[]]:
                ln = Line(ln)
                ln.rtl = rtl
                out.append(ln)
        return out

    def _unify(self, line):
        """fewer run headers, each a new run of 4 bytes:
        - mixed kana / hanzi + extended kanji (Japanese: 気, 読 ... are extended glyphs) would switch modes all the time:
          a stretch of full-width glyphs that mixes both is written in the extended mode alone when that takes fewer
          bits (an extended code can name any glyph)
        - a Latin word with accented letters (half-width block) would switch ASCII <-> extended at every accent: ASCII
          letters next to them take their copies in the half-width block where that takes fewer bits"""
        cb, hdr = self.cfg.code_bits, 8 * self.cfg.hdr_bytes
        out, i, n = list(line), 0, len(line)
        full = lambda c: c[0] == MODE_COMMON or c[0] == MODE_EXT and self.cls(c) == "full"
        while i < n:
            if not full(out[i]):
                i += 1
                continue
            j = i
            while j < n and full(out[j]):
                j += 1
            seg = out[i:j]
            runs = 1 + sum(1 for a, b in zip(seg, seg[1:]) if a[0] != b[0])
            if runs > 1:
                split = runs * hdr + sum(cb[m] for m, _, _, _ in seg)
                if hdr + len(seg) * cb[MODE_EXT] < split:
                    out[i:j] = [(MODE_EXT, c + self.cm.n_ascii if m == MODE_COMMON else c, a, ch) for m, c, a, ch in seg]
            i = j
        half = lambda c: c[0] == MODE_ASCII or c[0] == MODE_EXT and self.cls(c) == "half"
        i = 0
        while i < n:
            if not half(out[i]):
                i += 1
                continue
            j = i
            while j < n and half(out[j]):
                j += 1
            seg = out[i:j]
            if any(c[0] == MODE_EXT for c in seg) and any(c[0] == MODE_ASCII for c in seg):
                # cheapest assignment: state A (ASCII mode) / E (half-width block), a header at every change
                INF = 1 << 30
                cost = {"A": INF, "E": INF}
                back = []
                for k, c in enumerate(seg):
                    opts = {"E": cb[MODE_EXT]}
                    if c[0] == MODE_ASCII:
                        opts["A"] = cb[MODE_ASCII]
                    new, bk = {}, {}
                    for st, bits in opts.items():
                        if k == 0:
                            new[st], bk[st] = hdr + bits, None
                        else:
                            p = min(cost, key=lambda q: cost[q] + (hdr if q != st else 0))
                            new[st], bk[st] = cost[p] + (hdr if p != st else 0) + bits, p
                    cost = {"A": new.get("A", INF), "E": new.get("E", INF)}
                    back.append(bk)
                st = min(cost, key=cost.get)
                for k in range(len(seg) - 1, -1, -1):
                    m, c, a, ch = seg[k]
                    if st == "E" and m == MODE_ASCII:
                        seg[k] = (MODE_EXT, self.cm.ascii_as(c, "half"), a, ch)
                    st = back[k][st] if k else st
                out[i:j] = seg
            i = j
        return out

    def _visual(self, line, scale, box):
        """a line in drawing order (left to right): right-to-left text reversed (numbers and Latin inside it keep their
        order, brackets mirror), Arabic letters at its ends not joined to what went to the line before / after"""
        if scale in SMALL_FONTS or not line or not (line.rtl or any(scripts.is_rtl(c[3]) for c in line)):
            return list(line)
        cells = list(line)
        if not box:
            while cells and cells[-1][3] == " ":
                cells.pop()                               # (trailing spaces would land at the left edge)
        for k in (0, len(cells) - 1):
            if cells and cells[k][0] == MODE_EXT:
                ch = self.cm.table[cells[k][1]] if cells[k][1] < len(self.cm.table) else 0
                alt = scripts.unjoin(chr(ch), before=k == 0, after=k == len(cells) - 1) if 0 < ch < 0xF0000 else None
                if alt:
                    m = self.glyph(alt, scale)
                    cells[k] = m + (cells[k][2], cells[k][3])
        order, lv = scripts.visual([c[3] for c in cells], line.rtl)
        out = []
        for i in order:
            c = cells[i]
            mt = scripts.mirror(c[3], lv[i])
            if mt != c[3]:
                m = self.glyph(mt, scale)
                if m[0] == MODE_ASCII and self.cls(c) == "narrow":
                    m = (MODE_EXT, self.cm.ascii_as(m[1], "narrow"))
                c = m + (self.width(m[0], scale, m[1]), c[3])
            out.append(c)
        return out

    def runs(self, text, x=0, y=0, width=None, align="left", scale=1, fg=1, bg=0, box=False, wrap=True, line_h=None,
             clip=True):
        """clip: leave out lines below / above the screen and glyphs past its right edge (the text space wraps around,
        so they would land on top of other text); clip=False keeps everything (e.g. invisible padding).
        A right-to-left paragraph aligned "left" is aligned right (its start)."""
        from .memory import Run
        W, H = self.cfg.W, self.cfg.H
        max_w = width if width is not None else W - x
        lh = line_h or self.cfg.line_h(scale)
        runs, ln = [], 0
        for ln, line in enumerate(self.lines(text, max_w, scale, wrap)):
            vis = self._unify(self._visual(line, scale, box))
            k = len(vis)
            if not box:                                   # trailing spaces do not count for alignment (box: they do)
                while k and vis[k - 1][3] == " ":
                    k -= 1
            lw = sum(c[2] for c in vis[:k])
            if k:                                         # centre / right-align the ink, not the trailing gap
                narrow = vis[k - 1][0] == MODE_EXT and self.cls(vis[k - 1]) == "narrow"
                lw = max(0, lw - (self.cfg.gap * scale if narrow else self.slack(scale)))
            al = "right" if align == "left" and getattr(line, "rtl", False) else align
            lx = x + max(0, (max_w - lw if al == "right" else (max_w - lw) // 2 if al == "center" else 0))
            ly = y + ln * lh
            if clip and (ly < 0 or ly >= H or lx >= W):   # whole line outside (a run cannot start above the screen)
                self.clipped += len(line)
                continue
            cx, cur, cur_cls = lx, None, None
            for cell in vis:
                mode, code, adv, ch = cell
                if clip and (cx >= W or cx < 0):            # glyphs left / right of the screen
                    self.clipped += 1
                    cx += adv
                    continue
                cl = self.cls(cell) if mode in (MODE_ASCII, MODE_COMMON, MODE_EXT) else None
                if cur is None or cur.mode != mode or cl != cur_cls or len(cur.codes) >= self.cfg.max_run_len:
                    cur = Run(cx, ly, mode, [], fg, bg, box, scale)
                    cur_cls = cl
                    runs.append(cur)
                cur.codes.append(code)
                cx += adv
        runs = [r for r in runs if r.codes]
        bbox = (x, y, max_w, (ln + 1) * lh)
        return runs, bbox
