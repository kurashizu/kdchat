"""Live web preview for kd_test (standard library only): a small HTTP server in a background thread.

    GET /            the page
    GET /frame?v=N   JSON with everything of ONE moment: version, test, expectation, load state, log, and both pictures
                     as base64 RGB (W x H x 3): "now" = what the avatar should show at this moment (the pages sent so
                     far), "target" = the screen once everything has arrived. Empty {"v": N} when nothing changed.

One atomic response per poll and a new URL every time: with separate requests for state and pictures, Safari mixed
pictures of different moments (or reused a cached one) and the preview flickered."""
import base64, json, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler


def rgb_bytes(img):
    return bytes(min(255, max(0, int(round(v * 255)))) for row in img for p in row for v in p)


class WebView:
    def __init__(self, w, h, host="127.0.0.1", port=8765, frame=None):
        self.w, self.h = w, h
        self.lock = threading.Lock()
        self.state = {"v": 0, "w": w, "h": h, "test": "", "expect": "", "status": "", "pending": 0, "total": 0,
                      "log": [], "done": False, "frame": frame or {}}
        self.now = bytes(w * h * 3)
        self.target = bytes(w * h * 3)
        view = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, body, ctype):
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = self.path.split("?")[0]
                with view.lock:
                    if path == "/":
                        return self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
                    if path == "/frame":
                        from urllib.parse import urlparse, parse_qs
                        q = parse_qs(urlparse(self.path).query).get("v", [""])[0]
                        if q.lstrip("-").isdigit() and int(q) == view.state["v"]:
                            body = {"v": view.state["v"]}
                        else:
                            body = dict(view.state, now=base64.b64encode(view.now).decode(),
                                        target=base64.b64encode(view.target).decode())
                        return self._send(json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json")
                self.send_error(404)

        self.server = ThreadingHTTPServer((host, port), H)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}/"

    def set(self, now=None, target=None, **kw):
        """now / target: rows of (r, g, b) floats; kw: state fields. Bumps the version the page polls for."""
        with self.lock:
            if now is not None:
                self.now = rgb_bytes(now)
            if target is not None:
                self.target = rgb_bytes(target)
            self.state.update(kw)
            self.state["v"] += 1

    def log(self, line):
        with self.lock:
            self.state["log"] = (self.state["log"] + [line])[-400:]
            self.state["v"] += 1


PAGE = r"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>Klaude display test</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; font: 14px/1.45 -apple-system, "PingFang SC", "Segoe UI", sans-serif; background: #17181c; color: #e8e6e3; }
  header { padding: 14px 22px 10px; border-bottom: 1px solid #2a2c33; }
  #test { font-size: 22px; font-weight: 600; }
  #expect { color: #c9c4bb; margin-top: 4px; max-width: 1100px; }
  #bar { height: 6px; background: #2a2c33; border-radius: 3px; margin-top: 10px; max-width: 1100px; overflow: hidden; }
  #fill { height: 100%; width: 0; background: #d97757; transition: width .15s; }
  #status { margin-top: 6px; color: #9a968f; font-variant-numeric: tabular-nums; }
  main { display: flex; gap: 28px; padding: 20px 22px; align-items: flex-start; flex-wrap: wrap; }
  .panel h2 { font-size: 13px; font-weight: 600; color: #9a968f; margin: 0 0 8px; letter-spacing: .03em; }
  .device { padding: var(--bt) var(--b) var(--b); border-radius: var(--r); background: linear-gradient(#f3ede2, #ddd3c3);
            box-shadow: 0 0 0 2px #6b5c50, 0 8px 30px rgba(0,0,0,.45); position: relative; }
  .device .label { position: absolute; left: 0; right: 0; top: 0; height: var(--bt); display: flex; align-items: center;
                   justify-content: center; font: 600 calc(var(--bt) * 0.62) ui-monospace, Menlo, monospace;
                   letter-spacing: .04em; color: #5c4d42; }
  .device .clawd { display: inline-block; width: calc(var(--bt) * 1.125); height: calc(var(--bt) * 0.625); margin-right: .5em;
                   background: #d97757; -webkit-mask: var(--clawd) center / contain no-repeat; mask: var(--clawd) center / contain no-repeat; }
  .device[data-led="green"]::after { background: #4cd966 !important; box-shadow: 0 0 6px #4cd966 !important; }
  .device[data-led="amber"]::after { background: #fba826 !important; box-shadow: 0 0 6px #fba826 !important;
                                     animation: blink 1s steps(2, start) infinite; }
  @keyframes blink { to { visibility: hidden; } }
  .device::after { content: ""; position: absolute; left: 50%; bottom: calc(var(--b) / 2 - 4px); width: 8px; height: 8px;
                   margin-left: -4px; border-radius: 50%; background: #d97757; box-shadow: 0 0 6px #d97757; }
  canvas { display: block; image-rendering: pixelated; image-rendering: crisp-edges; background: #050506; box-shadow: 0 0 0 2px #1a1a1c; }
  .screen { position: relative; }
  .gaps { position: absolute; inset: 0; pointer-events: none; display: none;
          background-image: linear-gradient(to right, rgba(0,0,0,.3) 1px, transparent 1px),
                            linear-gradient(to bottom, rgba(0,0,0,.3) 1px, transparent 1px); }
  #log { flex: 1 1 340px; min-width: 300px; max-height: 76vh; overflow: auto; font: 12px/1.5 ui-monospace, Menlo, monospace;
         background: #111215; border: 1px solid #2a2c33; border-radius: 8px; padding: 10px 12px; white-space: pre-wrap; }
  #log .t { color: #d97757; font-weight: 600; margin-top: 6px; }
  #conn { position: fixed; right: 14px; top: 12px; font-size: 12px; color: #9a968f; }
  label { font-size: 12px; color: #9a968f; user-select: none; }
</style></head>
<body>
<div id="conn">connecting…</div>
<header><div id="test">waiting for the test…</div><div id="expect"></div>
  <div id="bar"><div id="fill"></div></div><div id="status"></div></header>
<main>
  <div class="panel"><h2>AVATAR NOW · 现在头上应该显示的画面</h2>
    <div class="device" id="dev"><div class="label"><span class="clawd"></span>Klaude Display</div><div class="screen"><canvas id="now"></canvas><div class="gaps" id="gaps"></div></div></div>
    <div style="margin-top:8px"><label><input type="checkbox" id="grid"> pixel gaps</label></div></div>
  <div class="panel"><h2>TARGET · 加载完成后</h2><canvas id="target"></canvas></div>
  <div id="log"></div>
</main>
<script>
let v = -1, W = 128, H = 128, logLen = 0, built = false;
// Both canvases hold the picture at its real resolution (W x H) and are only scaled by CSS. Writing the pixels straight
// into each canvas: Safari's accelerated canvas defers drawImage() from another canvas, so a shared off-screen canvas
// made "now" show "target" now and then (flicker).
const now = document.getElementById('now'), tgt = document.getElementById('target');
function clawd(rows) {                       // pixel art from config -> SVG mask for the frame label
  const w = Math.max(...rows.map(r => r.length)), h = rows.length;
  let r = '';
  rows.forEach((row, y) => [...row].forEach((ch, x) => { if (ch === 'o') r += `<rect x="${x}" y="${y}" width="1.02" height="1.02"/>`; }));
  return `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 ${w} ${h}' shape-rendering='crispEdges'>${r}</svg>")`;
}
function build(st) {
  W = st.w; H = st.h;
  const big = Math.max(2, Math.floor(Math.min(innerHeight * 0.72, innerWidth * 0.55) / W));
  for (const [c, k] of [[now, big], [tgt, 2]]) { c.width = W; c.height = H; c.style.width = W * k + 'px'; c.style.height = H * k + 'px'; }
  const g = document.getElementById('gaps');
  g.style.backgroundSize = big + 'px ' + big + 'px';
  const f = st.frame || {}, bez = (f.bezel_px || 8) * big, bt = (f.bezel_top_px || f.bezel_px || 8) * big, rad = (f.radius_px || 9) * big;
  const d = document.getElementById('dev'); d.style.setProperty('--b', bez + 'px'); d.style.setProperty('--bt', bt + 'px'); d.style.setProperty('--r', rad + 'px');
  if (f.mascot) d.style.setProperty('--clawd', clawd(f.mascot));
  built = true;
}
function paint(canvas, b64) {
  const bin = atob(b64), img = new ImageData(W, H), px = img.data;
  for (let i = 0, j = 0; i < W * H; i++, j += 3) { px[i*4] = bin.charCodeAt(j); px[i*4+1] = bin.charCodeAt(j+1); px[i*4+2] = bin.charCodeAt(j+2); px[i*4+3] = 255; }
  canvas.getContext('2d').putImageData(img, 0, 0);
}
let seq = 0;
async function poll() {
  try {
    // one request = one moment (state + both pictures), a fresh URL every time (no cache can answer it)
    const st = await (await fetch('/frame?v=' + v + '&n=' + (seq++), {cache: 'no-store'})).json();
    if (st.now !== undefined && st.v !== v) {
      if (!built) build(st);
      v = st.v;
      document.getElementById('conn').textContent = st.done ? 'test finished' : 'live';
      document.getElementById('test').textContent = st.test || '…';
      document.getElementById('expect').textContent = st.expect || '';
      document.getElementById('status').textContent = st.status || '';
      document.getElementById('dev').dataset.led = st.led || 'green';
      document.getElementById('fill').style.width = st.total ? (100 * (1 - st.pending / st.total)) + '%' : '100%';
      paint(now, st.now);
      paint(tgt, st.target);
      if (st.log.length !== logLen) {
        const el = document.getElementById('log'), stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 20;
        el.innerHTML = '';
        for (const l of st.log) { const d = document.createElement('div'); if (l.startsWith('[')) d.className = 't'; d.textContent = l; el.appendChild(d); }
        logLen = st.log.length; if (stick) el.scrollTop = el.scrollHeight;
      }
    } else if (st.now === undefined) {
      document.getElementById('conn').textContent = 'live';
    }
  } catch (e) { document.getElementById('conn').textContent = 'disconnected (test not running)'; }
  setTimeout(poll, 120);
}
document.getElementById('grid').onchange = e => { document.getElementById('gaps').style.display = e.target.checked ? 'block' : 'none'; };
addEventListener('resize', () => { built = false; v = -1; });
poll();
</script></body></html>
"""
