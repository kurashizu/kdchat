"""Link layer: keeps the remote copy of the memory in step with the wanted image, one page per sync tick.

Every tick sends exactly one frame = page id + payload bytes (page id first: if a sync slices the frame, viewers
briefly write stale bytes into the NEW page, which the next tick repairs -- never new bytes into the old page).
Order: palette, registers, sprite registers, text, tile colours, bitmap (low addresses first = progressive photo), sprite
patterns -- everything is black until the palette has arrived, so it goes first.

Refresh (late joiners, dropped frames): every non-zero page is sent again in the same order, one after the other (a cursor
over the page order, so changing content never makes it skip pages), at refresh_rate_hz. While new content keeps coming,
the refresh still gets every 1/refresh_busy_share-th frame, so a static part (palette, background) can never starve
behind an animation or a clock. refresh_core_share of the refresh frames walk the core pages (palette, registers, sprite
registers, text: what a late joiner needs to see anything), the others walk the rest; each group has its own cursor.

Fairness of new content: pages are taken in the order above, but every frame a page waits moves it AGE_STEP places
forward, so a page that changes all the time (a moving sprite, a clock) can never starve the others: any changed page
goes out within about len(order) / AGE_STEP frames.

Pages that became all zero are refreshed too for zero_refresh_s (a viewer that missed the frame or the clear command
would otherwise keep the old content forever); after that every viewer holds zeros there anyway. At start the client
does not know what the avatar holds (an earlier session may have left content), so every page is sent once.

Text is a list of runs walked from the first byte, so a half-sent text area can decode old bytes as headers = garbage
glyphs. That only happens when the run STRUCTURE changes (where runs start, their lengths and code pages): content-only
edits (a clock) and appends after the old end are safe in any order and go out normally. When the structure changes
over two or more pages (or the avatar's text is unknown: startup, a lost frame), the first text page is first sent
with an empty list (the text disappears), then the other pages; the real first page goes out as soon as it, together
with what is already on the air, walks exactly like the wanted text. A graphics mode switch (raw <-> photo) starts with
one clear command, so old bytes are never decoded in the new mode. Pages that became zero are refreshed in every 4th
refresh frame only, so they do not slow late joiners down.

Feedback (optional): `check()` returns what the avatar holds now (page id, payload) from VRChat's OSC output. Before
each new frame the previous one is compared with it; a frame that did not arrive is queued again at once."""
import time

AGE_STEP = 2


class Link:
    def __init__(self, cfg, send_frame, now=time.monotonic):
        self.cfg = cfg
        self.send_frame = send_frame                 # f(page_id, bytes)
        self.now = now
        self.want = bytearray(cfg.pages * cfg.P)
        self.sent = bytearray(cfg.pages * cfg.P)      # what the viewers should hold
        self.refresh_on = cfg.raw["sync"]["refresh"]
        self.refresh_rate = cfg.raw["sync"]["refresh_rate_hz"]
        self.busy_every = max(2, round(1 / cfg.raw["sync"].get("refresh_busy_share", 0.2)))
        self.credit = 0.0                             # refresh frames earned (refresh_rate_hz / rate_hz per tick)
        self._busy = 0                                # new-content frames since the last refresh
        self.core_share = cfg.raw["sync"].get("refresh_core_share", 0.5)
        self._cursor = {"core": 0, "rest": 0}          # next refresh position in each group
        self.refreshed = self.refreshed_core = 0
        self._ticks = 0
        self.frames = 0
        self.cmds = []                               # command frames to send (page ids, config "commands")
        self.check = None                            # f() -> (page_id, bytes) seen on the avatar, or None
        self.last = None                             # last frame sent (page_id, payload)
        self.force = set()                           # pages to send again (lost on the way)
        self.ok = self.lost = 0
        self.waiting = {}                            # dirty page -> tick it was first seen dirty
        self.zeroed = {}                             # page -> tick it was last sent as all zero (refreshed for a while)
        self.zero_window = cfg.raw["sync"].get("zero_refresh_s", 120)
        self.text_head = cfg.text_base // cfg.P
        self.mode_at = cfg.regs["gfx_mode"]
        self._mode_cleared = False                   # the clear for the current mode switch has gone out
        self.sent_tick = {}                          # page -> tick it was last sent
        c = cfg
        self.gfx_pages = range(c.gfx_base // c.P, (c.gfx_base + c.gfx_bytes + c.P - 1) // c.P)
        self.text_pages = range(c.text_base // c.P, (c.text_base + c.text_bytes + c.P - 1) // c.P)
        self.pal_pages = range(c.pal_base // c.P, (c.pal_base + c.pal_bytes + c.P - 1) // c.P)
        self.reg_pages = range(c.reg_base // c.P, c.reg_base // c.P + c.reg_npages)
        self.spr_head = c.spr_base // c.P                                                     # sprite registers + colours
        self.spr_pages = range(c.spr_base // c.P, c.pages)
        first = list(self.pal_pages) + list(self.reg_pages) + [self.spr_head]
        tc_pages = list(range(c.tc_base // c.P, (c.tc_base + c.tc_bytes + c.P - 1) // c.P))   # tile colours before the
        rest = list(self.text_pages) + tc_pages + list(self.gfx_pages) + list(self.spr_pages)  # bitmap: right colours at once
        self.order = []
        for p in first + rest:
            if p not in self.order:
                self.order.append(p)
        self.pos = {p: i for i, p in enumerate(self.order)}
        core = set(first) | set(self.text_pages)
        self.force = set(range(c.pages))              # unknown avatar state: send every page once
        if 0 < self.core_share < 1:
            self.groups = {"core": [p for p in self.order if p in core], "rest": [p for p in self.order if p not in core]}
        else:                                         # no split: one cursor over the whole order
            self.groups = {"core": list(self.order), "rest": []}
            self.core_share = 1

    def update(self, memory_buf):
        self.want[:] = memory_buf

    def forget(self):
        """viewers lost their copy (avatar reloaded): everything non-zero is dirty again"""
        self.sent[:] = bytes(len(self.sent))

    def _page(self, buf, p):
        return buf[p * self.cfg.P:(p + 1) * self.cfg.P]

    def dirty(self, p):
        return p in self.force or self._page(self.want, p) != self._page(self.sent, p)

    def _verify(self):
        if not (self.check and self.last):
            return
        seen, (pid, payload) = self.check(), self.last
        self.last = None
        if seen is None:
            return
        if seen == (pid, bytes(payload)):
            self.ok += 1
            return
        self.lost += 1
        if self.ok == 0 and self.lost >= 8:          # never one confirmed frame: the reports are not ours to trust
            print("feedback: no frame confirmed after 8 tries -> feedback off, sending without it")
            self.check = None
            return
        c = self.cfg
        if pid == c.id_clear_gfx:                  # the clear did not arrive: send every graphics page instead
            self.force.update(self.gfx_pages)
        elif 1 <= pid <= c.pages:
            self.force.add(pid - 1)

    def command(self, cid):
        """queue a command frame: the avatar acts while that page id is on the wire (one frame, payload ignored)"""
        self.cmds.append(cid)

    def pending(self):
        return [p for p in self.order if self.dirty(p)]

    def eta(self):
        return len(self.pending()) / self.cfg.rate_hz

    def _clear_pays(self):
        cleared = range(self.cfg.clear_bytes // self.cfg.P)      # the pages the clear command zeroes (not the palette's)
        to_zero = sum(1 for p in cleared if self.dirty(p) and not any(self._page(self.want, p)))
        kept = sum(1 for p in cleared if not self.dirty(p) and any(self._page(self.want, p)))
        return to_zero >= 2 and to_zero > kept + 1              # a tie gains nothing and blinks the kept pages

    def tick(self):
        """send one frame; returns (page_id, payload) or None when idle"""
        self._ticks += 1
        self._verify()
        if self.cmds:
            cid = self.cmds[0]
            if self.last and self.last[0] == cid:
                return self._emit(0, bytes(self.cfg.P))      # the same command again: an idle frame between (an edge)
            self.cmds.pop(0)
            return self._emit(cid, bytes(self.cfg.P))
        pend = self.pending()
        if self.refresh_on:
            self.credit = min(1.0, self.credit + self.refresh_rate / self.cfg.rate_hz)
            if self.credit >= 1.0 and (not pend or self._busy >= self.busy_every - 1):
                p = self._next_refresh(pend)
                if p is not None:
                    self.credit -= 1.0
                    self._busy = 0
                    self.refreshed += 1
                    self.refreshed_core += p in self.groups["core"]
                    return self._send_page(p)
        if pend:
            for p in pend:
                self.waiting.setdefault(p, self._ticks)
            for p in [p for p in self.waiting if p not in pend]:
                del self.waiting[p]
            c = self.cfg
            if self.want[self.mode_at] == self.sent[self.mode_at]:
                self._mode_cleared = False
            mode_switch = (self.want[self.mode_at] != self.sent[self.mode_at] and not self._mode_cleared
                           and any(self.sent[0:c.clear_bytes]))
            if mode_switch or (any(p in self.gfx_pages for p in pend) and self._clear_pays()):
                self._mode_cleared = self._mode_cleared or mode_switch
                return self._clear()
            self._busy += 1
            pend = self._text_guard(pend)
            if isinstance(pend, tuple):
                return pend                          # the blank first page went out
            if not pend:
                return None
            p = min(pend, key=lambda p: self.pos[p] - AGE_STEP * (self._ticks - self.waiting.get(p, self._ticks)))
            return self._send_page(p)
        if self.last and self.last[0] > self.cfg.id_clear_gfx:
            return self._emit(0, bytes(self.cfg.P))          # never leave a command on the wire (a late joiner would act)
        return None

    # ---------------- text consistency
    def _walk(self, buf):
        """the run list as the shader walks it: [(offset, length, mode), ...]"""
        c = self.cfg
        off, end, out = c.text_base, c.text_base + c.text_bytes, []
        for _ in range(c.max_runs):
            if off + c.hdr_bytes > end:
                break
            h = int.from_bytes(bytes(buf[off:off + c.hdr_bytes]), "big")
            n = (h >> c.o_len) & ((1 << c.lenb) - 1)
            if n == 0:
                break
            mode = (h >> c.o_mode) & 3
            if mode == 3 and (h >> c.o_scale) & 1:
                mode = 4                                  # 3x5 font (mode 3 + scale bit), 7-bit codes
            elif mode == 3 and h & 1:
                mode = 5                                  # 5x7 font (mode 3 + box bit), 7-bit codes
            out.append((off, n, mode))
            off = self._run_end(off, n, mode)
        return out

    def _run_end(self, off, n, mode):
        c = self.cfg
        cb = c.code_bits[0] if mode in (4, 5) else c.code_bits.get(mode, c.code_bits[2])
        return off + c.hdr_bytes + (n if mode == 3 else (n * cb + 7) // 8)

    def _text_guard(self, pend):
        """-> the pages that may go out now, or the emitted cut page (a tuple).
        Text pages can arrive in any order, so a run list whose structure changes (run offsets / lengths / modes) could
        be walked half old, half new = garbage. Then the list is first cut in front of the first run that changes (a
        zeroed header there: the runs before it stay on the screen, the rest blanks for a moment), the other pages go
        out, and the page with the cut goes last, once the whole list walks like the wanted one."""
        c = self.cfg
        text = [p for p in pend if p in self.text_pages]
        if not text:
            return pend
        unknown = self.text_head in self.force            # startup / lost frame: the avatar may hold anything
        on_air, wanted = self._walk(self.sent), self._walk(self.want)
        len_last = c.hdr_bytes - 1 - c.o_len // 8          # the last header byte holding length bits (big endian)
        if not unknown and self._independent(on_air, wanted, text):
            return pend                                   # every changed page is a whole segment of its own
        if not unknown and on_air and on_air[:len(wanted)] == wanted:
            return pend                                   # a cut at the end: the walk stops at the new end marker
        if not unknown and wanted[:len(on_air)] == on_air:
            # an append after the end on the air (also the rest of the list after a cut): the page with that end marker
            # (a zero length) goes out last, once everything after it is there
            end = self._run_end(*on_air[-1]) if on_air else c.text_base
            if end + c.hdr_bytes > c.text_base + c.text_bytes or len(on_air) >= c.max_runs:
                return pend
            bp = (end + len_last) // c.P
            hyp = bytearray(self.sent); hyp[bp * c.P:(bp + 1) * c.P] = self._page(self.want, bp)
            if self._walk(hyp) != wanted:
                return [p for p in pend if p != bp]
            return pend
        if len(text) < 2:
            return pend                                   # one page: old or new
        i = 0
        if not unknown:
            while i < len(on_air) and i < len(wanted) and on_air[i] == wanted[i]:
                i += 1
        # the length bits of the cut header must lie in one page (a header may straddle two): else cut one run earlier
        while i > 0 and wanted[i][0] % c.P + len_last >= c.P:
            i -= 1
        off = wanted[i][0] if i else c.text_base
        bp, rel = off // c.P, off % c.P
        cut = bytearray(self._page(self.want, bp))
        cut[rel:min(c.P, rel + c.hdr_bytes)] = bytes(min(c.P, rel + c.hdr_bytes) - rel)
        self.sent[bp * c.P:(bp + 1) * c.P] = cut
        self.force.discard(bp)
        self.waiting.pop(bp, None)
        return self._emit(bp + 1, bytes(cut))

    def _independent(self, on_air, wanted, text):
        """True if the pending text pages can go out in any order: the page boundaries where both run lists start a run
        (and the area start) cut the text into segments, and no segment holds more than one pending page. Walking any
        mix enters each segment at a boundary both lists share and leaves it at the next one, through either all old
        or all new bytes of that segment."""
        c = self.cfg
        a = {o for o, _, _ in on_air if o % c.P == 0} & {o for o, _, _ in wanted if o % c.P == 0}
        a.add(c.text_base)
        ends = [self._run_end(*on_air[-1]) if on_air else c.text_base, self._run_end(*wanted[-1]) if wanted else c.text_base]
        # beyond the end of both lists nothing is walked: one segment from the later end on
        bounds = sorted(b for b in a if b <= max(ends))
        seg = {}
        for p in text:
            b = max((x for x in bounds if x <= p * c.P), default=c.text_base)
            seg[b] = seg.get(b, 0) + 1
            if seg[b] > 1:
                return False
        return True                                       # (pages that are not pending hold the same bytes in both)

    def _clear(self):
        c = self.cfg
        self.sent[0:c.clear_bytes] = bytes(c.clear_bytes)          # bitmap + tile colours; the palette stays
        for p in range(c.clear_bytes // c.P):                       # pages wholly inside the cleared range
            self.force.discard(p)
            self.zeroed[p] = self._ticks
            if not any(self._page(self.want, p)):
                self.sent_tick[p] = self._ticks              # final after the clear (others still have to go out)
        return self._emit(c.id_clear_gfx, bytes(c.P))

    def _send_page(self, p):
        self.force.discard(p)
        self.waiting.pop(p, None)
        self.sent_tick[p] = self._ticks
        self.sent[p * self.cfg.P:(p + 1) * self.cfg.P] = self._page(self.want, p)
        if any(self._page(self.want, p)):
            self.zeroed.pop(p, None)
        elif p not in self.zeroed:
            self.zeroed[p] = self._ticks
        return self._emit(p + 1, bytes(self._page(self.want, p)))

    def _next_refresh(self, pend):
        """next page of the group whose turn it is (core vs rest by refresh_core_share), after that group's cursor, that
        holds something and is not about to be sent anyway; the other group if this one has nothing"""
        skip = set(pend)
        live = lambda p: p in self.reg_pages or p == self.spr_head or any(self._page(self.want, p))
        zero = lambda p: (not live(p) and self._ticks - self.zeroed.get(p, -10 ** 9) < self.zero_window * self.cfg.rate_hz)
        core_turn = self.refreshed_core < self.core_share * (self.refreshed + 1)
        groups = ("core", "rest") if core_turn else ("rest", "core")
        # pages that recently became zero only get every 4th refresh frame (or what is left when nothing else is due)
        tries = [("zero", zero), ("live", live)] if self.refreshed % 4 == 3 else [("live", live), ("zero", zero)]
        for kind, want_kind in tries:
            for g in groups:
                pages = self.groups[g]
                key = (kind, g)                       # separate cursors: the zero walk must not reset the live walk
                n = len(pages)
                for k in range(n):
                    i = (self._cursor.get(key, 0) + k) % n
                    p = pages[i]
                    if p not in skip and want_kind(p):
                        self._cursor[key] = i + 1
                        return p
        return None

    def _emit(self, pid, payload):
        self.frames += 1
        self.last = (pid, bytes(payload))
        self.send_frame(pid, payload)
        return pid, payload

    def run(self, until_idle=False, stop=None):
        period = 1.0 / self.cfg.rate_hz
        t = self.now()
        while not (stop and stop()):
            self.tick()
            if until_idle and not self.pending():
                return
            t += period
            d = t - self.now()
            if d > 0:
                time.sleep(d)
            else:
                t = self.now()
