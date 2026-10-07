"""Text preparation for scripts the display cannot draw letter by letter in logical order: right-to-left text (Hebrew,
Arabic, Persian, Urdu: the bidi order), Arabic joining (presentation forms), Thai (consonant + marks clusters: the
font has no zero-width marks). Pure python, standard library only.

tokens(text)          -> the text's drawing units (a character, a Thai cluster, a lam-alef pair)
shape(tokens)         -> per token the character to look the glyph up by (Arabic: its presentation form)
paragraph_rtl(tokens) -> does the paragraph read right to left (its first strong character)
visual(tokens, rtl)   -> the order to draw a line's tokens in, left to right (mirrored brackets: mirror())
"""
import unicodedata

# characters that draw nothing: dropped (soft hyphen, zero-width space, direction marks / embeddings, BOM)
_DROP = set("­​‎‏‪‫‬‭‮⁠⁦⁧⁨⁩﻿")
ZWNJ, ZWJ = "‌", "‍"


def _is_mark(ch):
    """vowel / cantillation marks of Hebrew and Arabic (machine translations rarely have them; the display drops them)"""
    o = ord(ch)
    return unicodedata.category(ch) == "Mn" and (0x591 <= o <= 0x5C7 or 0x610 <= o <= 0x61A or 0x64B <= o <= 0x65F
                                                or o == 0x670 or 0x6D6 <= o <= 0x6ED)


THAI_MARKS = set("ัิีึืฺุู็่้๊๋์ํ๎")
THAI_TONES = set("่้๊๋์")


def clean(text):
    """NFC, invisible characters and Hebrew / Arabic vowel marks out, Thai sara am in one piece"""
    text = unicodedata.normalize("NFC", text)
    text = "".join(ch for ch in text if ch not in _DROP and not _is_mark(ch))
    return text.replace("ํา", "ำ")


# ------------------------------------------------------------------ Arabic joining
def _forms():
    single, liga = {}, {}
    for cp in list(range(0xFB50, 0xFC00)) + list(range(0xFE70, 0xFF00)):
        d = unicodedata.decomposition(chr(cp))
        if not d.startswith("<"):
            continue
        tag, *bases = d.split()
        if tag not in ("<isolated>", "<final>", "<initial>", "<medial>"):
            continue
        base = "".join(chr(int(b, 16)) for b in bases)
        (single if len(base) == 1 else liga).setdefault(base, {}).setdefault(tag[1:-1], chr(cp))
    return single, liga


FORMS, LIGATURES = _forms()
LAM_ALEF = {k: v for k, v in LIGATURES.items() if k[0] == "ل" and k[1] in "آأإا"}


_REV = {ch: (base, form) for base, f in list(FORMS.items()) + list(LAM_ALEF.items()) for form, ch in f.items()}


def unjoin(ch, before=False, after=False):
    """a presentation form without its join to the letter before (before=True) / after it (a line break there)
    -> the form to use instead, or None when nothing changes"""
    if ch not in _REV:
        return None
    base, form = _REV[ch]
    f = FORMS.get(base) or LAM_ALEF.get(base)
    to_prev = form in ("final", "medial") and not before
    to_next = form in ("initial", "medial") and not after
    want = "medial" if to_prev and to_next else "final" if to_prev else "initial" if to_next else "isolated"
    if want == form:
        return None
    return f.get(want) or f.get("isolated")


def joining(tok):
    """D (joins both sides), R (only the letter before it), C (tatweel / ZWJ: causes joining), U (none)"""
    if tok in (ZWJ, "ـ"):
        return "C"
    f = FORMS.get(tok) or LAM_ALEF.get(tok)
    if not f:
        return "U"
    return "D" if "initial" in f or "medial" in f else "R"


def shape(toks, ok=lambda ch: True):
    """-> per token the character to draw (Arabic letters: the presentation form for their joining with the letters
    before / after; ok(ch): does the font have it - otherwise the next simpler form)"""
    jt = [joining(t) for t in toks]
    out = list(toks)
    for i, t in enumerate(toks):
        f = FORMS.get(t) or LAM_ALEF.get(t)
        if not f:
            continue
        prev = jt[i - 1] if i else "U"
        nxt = jt[i + 1] if i + 1 < len(toks) else "U"
        to_prev = prev in ("D", "C")                              # the letter before joins on to this one
        to_next = jt[i] == "D" and nxt in ("D", "R", "C")
        want = ["medial", "final", "initial", "isolated"] if to_prev and to_next else \
            ["final", "isolated"] if to_prev else ["initial", "isolated"] if to_next else ["isolated"]
        for w in want:
            if w in f and ok(f[w]):
                out[i] = f[w]
                break
    return out


# ------------------------------------------------------------------ tokens
def tokens(text):
    """-> drawing units: Thai consonant + its marks, lam + alef, otherwise single characters (ZWJ / ZWNJ stay as
    tokens: shaping reads them; the layout draws nothing for them)"""
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if "ก" <= ch <= "ฮ" or ch in "ะาำเแโใไ":
            j = i + 1
            while j < n and text[j] in THAI_MARKS:
                j += 1
            out.append(text[i:j]); i = j
            continue
        if ch == "ل" and i + 1 < n and ch + text[i + 1] in LAM_ALEF:
            out.append(text[i:i + 2]); i += 2
            continue
        out.append(ch); i += 1
    return out


def thai_fallbacks(tok):
    """a Thai cluster the font lacks -> simpler ones to try (the tone mark dropped, then the marks after the first)"""
    if len(tok) < 2:
        return []
    out = []
    t = "".join(c for c in tok if c not in THAI_TONES)
    if t != tok and len(t) > 1:
        out.append(t)
    out += [tok[:2], tok[0]]
    return out


# ------------------------------------------------------------------ bidi
def _cls(tok):
    if not tok:
        return "ON"
    c = unicodedata.bidirectional(tok[0])
    return {"AL": "R", "NSM": "ON", "BN": "ON", "LRE": "ON", "RLE": "ON", "PDF": "ON", "LRO": "ON", "RLO": "ON",
            "B": "WS", "S": "WS"}.get(c, c)


def is_rtl(tok):
    return _cls(tok) == "R"


def paragraph_rtl(toks):
    for t in toks:
        c = _cls(t)
        if c in ("L", "R"):
            return c == "R"
    return False


def levels(toks, rtl):
    """embedding levels of a line (a simplified Unicode bidi algorithm: strong types, numbers, neutrals)"""
    base = 1 if rtl else 0
    cls = [_cls(t) for t in toks]
    n = len(cls)
    # numbers: separators between digits and terminators next to them join the number (W4 / W5), AN = EN
    for i, c in enumerate(cls):
        if c == "AN":
            cls[i] = "EN"
    for i, c in enumerate(cls):
        if c in ("ES", "CS") and 0 < i < n - 1 and cls[i - 1] == "EN" and cls[i + 1] == "EN":
            cls[i] = "EN"
    for i, c in enumerate(cls):
        if c == "ET":
            j = i
            while j < n and cls[j] == "ET":
                j += 1
            if (i and cls[i - 1] == "EN") or (j < n and cls[j] == "EN"):
                for k in range(i, j):
                    cls[k] = "EN"
    # the direction each number takes: R after an R (or at the start of an RTL paragraph), else L (W7)
    strong = "R" if rtl else "L"
    num_r = []
    for c in cls:
        if c in ("L", "R"):
            strong = c
        num_r.append(strong == "R")
    # resolved direction of every token; neutrals take the direction of the types around them when both agree
    # (numbers count as their own direction), else the paragraph's (N1 / N2)
    d = ["R" if c == "R" or c == "EN" and num_r[i] else "L" if c in ("L", "EN") else None for i, c in enumerate(cls)]
    i = 0
    while i < n:
        if d[i] is not None:
            i += 1
            continue
        j = i
        while j < n and d[j] is None:
            j += 1
        before = d[i - 1] if i > 0 else ("R" if rtl else "L")
        after = d[j] if j < n else ("R" if rtl else "L")
        for k in range(i, j):
            d[k] = before if before == after else ("R" if rtl else "L")
        i = j
    # levels (I1 / I2): R is odd; L and numbers even, numbers above R text two levels up
    lv = []
    for i, x in enumerate(d):
        if x == "R" and not (cls[i] == "EN"):
            lv.append(1)
        elif cls[i] == "EN" and num_r[i]:
            lv.append(2)
        else:
            lv.append(2 if base else 0)
    k = n
    while k and cls[k - 1] == "WS":                       # trailing white space: the paragraph level (L1)
        k -= 1
        lv[k] = base
    return lv


def visual(toks, rtl):
    """-> (the indices of the tokens in drawing order, left to right; their levels)"""
    lv = levels(toks, rtl)
    order = list(range(len(toks)))
    if not lv:
        return order, lv
    hi = max(lv)
    lo = min(x for x in lv if x % 2) if any(x % 2 for x in lv) else hi + 1
    for level in range(hi, lo - 1, -1):
        i = 0
        while i < len(order):
            if lv[order[i]] >= level:
                j = i
                while j < len(order) and lv[order[j]] >= level:
                    j += 1
                order[i:j] = order[i:j][::-1]
                i = j
            else:
                i += 1
    return order, lv


_MIRROR = dict(zip("()<>[]{}«»‹›", ")(><][}{»«›‹"))


def mirror(tok, level):
    """a bracket in right-to-left text faces the other way"""
    return _MIRROR.get(tok, tok) if level % 2 else tok
