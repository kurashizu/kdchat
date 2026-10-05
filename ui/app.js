// VRChat Chatbox console. One page for both outputs: the game's chatbox (OSC /chatbox/*) and the Klaude display
// (kd: /api/v1/kd/*). Talks only to the REST API; the browser re-sends the Basic Auth login.
// Every user-visible string comes from i18n.js (t(key) / data-i18n attributes).
"use strict";

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const phone = () => matchMedia("(max-width: 720px)").matches;

const store = {
  get: (k, d) => { try { const v = localStorage.getItem("vcb." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem("vcb." + k, JSON.stringify(v)); } catch { } },
};

const S = {
  out: { chatbox: true, kd: false }, kdAvailable: true, maxChars: 144, maxLines: 9,
  sfx: store.get("sfx", true), typingHint: store.get("typingHint", true), live: store.get("live", true),
  enterSends: store.get("enterSends", true),
  typingOn: false, busy: 0, conn: null,
  to: { chatbox: true, kd: true }, toManual: false,      // where new messages go (within the outputs that are on)
  cur: null,                                             // the current message (see below)
  kd: null,                    // {settings, choices}
  kdStat: null,                // the last /kd/status (re-rendered on a language switch)
  palette: [], dims: null, image: false,
};

// ---------------------------------------------------------------- language
// First visit: from the browser (Chinese if it starts with "zh", else English); a switch in the UI is remembered.
LANG = store.get("lang", null) || ((navigator.language || "").toLowerCase().startsWith("zh") ? "zh" : "en");

function setLang(l, remember) {
  if (!I18N[l]) l = "en";
  LANG = l;
  if (remember) store.set("lang", l);
  document.documentElement.lang = l === "zh" ? "zh-CN" : "en";
  applyI18n();
  $("langBtn").textContent = l === "zh" ? "中" : "EN";
  document.querySelectorAll("#langSeg button").forEach((b) => {
    const on = b.dataset.lang === l; b.classList.toggle("on", on); b.setAttribute("aria-pressed", on);
  });
  paintPlaceholder(); paintOutputs(); paintTargets(); paintStatus(); paintConn();
  if (S.kd) renderSettings();
  if (S.kdStat) paintKdStat();
  refreshHistory();
}
$("langBtn").onclick = () => setLang(LANG === "zh" ? "en" : "zh", true);
document.querySelectorAll("#langSeg button").forEach((b) => b.onclick = () => setLang(b.dataset.lang, true));

// ---------------------------------------------------------------- API
async function api(path, method = "GET", body, raw) {
  const opt = { method, headers: {} };
  if (raw) { opt.body = raw; opt.headers["Content-Type"] = raw.type || "application/octet-stream"; }
  else if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers["Content-Type"] = "application/json"; }
  const r = await fetch("/api/v1" + path, opt);
  if (!r.ok) {
    let msg = r.status + "";
    try { const j = await r.json(); msg = j.detail || msg; } catch { }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.status === 204 ? null : r.json();
}

function toast(msg, kind) {
  const n = el("div", "toast" + (kind === "err" ? " err" : ""), msg);
  if (kind === "err") n.setAttribute("role", "alert");
  $("toasts").appendChild(n);
  setTimeout(() => n.classList.add("hide"), kind === "err" ? 3500 : 1800);
  setTimeout(() => n.remove(), kind === "err" ? 3800 : 2100);
}

// ---------------------------------------------------------------- outputs (both can be on at the same time)
function paintOutputs() {
  document.querySelectorAll(".outputs button").forEach((b) => {
    const k = b.dataset.mode, on = !!S.out[k];
    b.classList.toggle("on", on); b.setAttribute("aria-pressed", on);
    b.title = k === "kd" && !S.kdAvailable ? t("out.unavailable") : t("out.title");
  });
  document.querySelector('.outputs [data-mode="kd"]').disabled = !S.kdAvailable;
}

async function setOutputs(part) {
  try {
    const r = part ? await api("/outputs", "PUT", part) : await api("/outputs");
    S.out = { chatbox: r.chatbox, kd: r.kd };
    S.kdAvailable = !!r.kd_available;
  } catch (e) { toast(t("out.failed", { msg: e.message }), "err"); }
  paintOutputs();
  const kd = S.out.kd;
  $("kdCol").hidden = !kd;
  $("settings").hidden = !kd; $("kdOffHint").hidden = kd || !S.kdAvailable;
  $("kdSec").hidden = !S.kdAvailable;
  $("grid").classList.toggle("two", kd);
  paintTargets();
  if (kd) { if (!S.kd) await loadKd(); refreshKd(true); }
}
document.querySelectorAll(".outputs button").forEach((b) => b.onclick = () => {
  const k = b.dataset.mode, on = !S.out[k];
  if (!on && k === "kd" && !confirm(t("out.confirmKdOff"))) return;
  const name = t(k === "kd" ? "out.kdLong" : "out.chatboxLong");
  setOutputs({ [k]: on }).then(() => { if (S.out[k] === on) toast(t(on ? "out.on" : "out.off", { name })); });
});

// ---------------------------------------------------------------- the current message
// The input box is always "the current message": a new one, or a sent one being edited. With live typing on it is live on
// the outputs while it is typed (it exists on the server from the first sync on: one id for its whole life); Enter
// finishes it (the next keystroke starts a new one), Esc gives it up (a new one disappears, an edit goes back to the
// text it had). Where it goes is decided when it starts (🎮 / 🖥) and does not change afterwards.
//   S.cur = null | {id, mode: "new" | "edit", original, targets, lastSent}
let syncTimer = null, chain = Promise.resolve();
const queue = (fn) => (chain = chain.then(fn).catch((e) => toast(t("toast.failed", { msg: e.message }), "err")));

function targetsNow() {                                    // for a message that starts now
  const tg = ["chatbox", "kd"].filter((k) => S.out[k] && S.to[k]);
  return tg.length ? tg : ["chatbox", "kd"].filter((k) => S.out[k]);
}
const curTargets = () => (S.cur ? S.cur.targets : targetsNow());

function paintTargets() {
  const both = S.out.chatbox && S.out.kd, tg = curTargets(), edit = S.cur && S.cur.mode === "edit";
  $("targets").hidden = !both;
  document.querySelectorAll("#targets button").forEach((b) => {
    const on = tg.includes(b.dataset.to);
    b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); b.disabled = !!S.cur;
  });
  $("targets").title = t(S.cur ? "to.locked" : "to.title");
  const label = t(edit ? "send.save" : !both ? "send.send" : tg.length === 2 ? "send.both" : tg[0] === "kd" ? "send.kd" : "send.chatbox");
  $("sendLbl").textContent = label;
  $("send").setAttribute("aria-label", label); $("send").title = label;
  $("send").classList.toggle("save", !!edit);
  $("send").querySelector(".ico").textContent = edit ? "✓" : "➤";
  $("kbFill").hidden = !S.out.chatbox || !!edit;
  $("cancel").hidden = !S.cur || !!edit;                       // (an edit has its own cancel in the banner)
  $("editing").hidden = !edit;
  $("composer").classList.toggle("editing-mode", !!edit);
  if (edit) $("editWhat").textContent = S.cur.original;
  const chat = tg.includes("chatbox");
  S.maxChars = chat ? 144 : 400; S.maxLines = chat ? 9 : 20;
  updateCount(); paintStatus();
}
document.querySelectorAll("#targets button").forEach((b) => b.onclick = () => {
  if (S.cur) return;
  const k = b.dataset.to, other = k === "kd" ? "chatbox" : "kd";
  S.to[k] = !S.to[k];
  if (!S.to[k] && !S.to[other]) S.to[other] = true;               // never none
  if (k === "kd") S.toManual = true;
  paintTargets();
});

const text = $("text");

function paintPlaceholder() {
  text.placeholder = phone() ? t("composer.ph") : t(S.enterSends ? "composer.phDesk" : "composer.phDeskNl");
  text.setAttribute("enterkeyhint", S.enterSends ? "send" : "enter");
}

function updateCount() {
  const v = text.value, lines = v ? v.split("\n").length : 0;
  const over = v.length > S.maxChars || lines > S.maxLines;
  const c = $("count");
  c.textContent = phone() ? t("composer.countShort", { n: v.length, max: S.maxChars })
                          : t("composer.count", { n: v.length, max: S.maxChars, l: lines, maxl: S.maxLines });
  c.title = t("composer.count", { n: v.length, max: S.maxChars, l: lines, maxl: S.maxLines });
  c.classList.toggle("over", over);
  // phones: the counter only near the limit
  c.classList.toggle("near", v.length > S.maxChars * 0.8 || lines > S.maxLines - 2);
  $("send").disabled = !v.trim() || over;
  $("composer").classList.toggle("over", over);
  const cap = phone() ? (document.body.classList.contains("kb") ? 120 : 160) : 260;
  text.style.height = "auto";
  text.style.height = Math.min(cap, Math.max(phone() ? 44 : 84, text.scrollHeight + 2)) + "px";
}

// the line next to the counter: what is happening with the current message
function paintStatus() {
  const s = $("status"), c = S.cur;
  let key = null, cls = "";
  if (S.busy) { key = "status.sending"; cls = "busy"; }
  else if (c && S.live && c.id != null && c.mode === "new") { key = "status.live"; cls = "live"; }
  else if (S.typingOn) { key = "status.typing"; cls = "live"; }
  s.textContent = key ? t(key) : "";
  s.className = "status " + cls;
  $("tLive").classList.toggle("active", cls === "live" && key === "status.live");
  $("composer").classList.toggle("busy", !!S.busy);
}

async function typing(on) {
  on = !!on && S.typingHint;
  if (S.typingOn === on) return;
  S.typingOn = on; paintStatus();
  try { await api("/typing", "PUT", { typing: on, targets: curTargets() }); } catch { }
}

function overLimit(v) { return v.length > S.maxChars || v.split("\n").length > S.maxLines; }

function onInput() {
  layoutViewport(); updateCount();
  const v = text.value;
  if (!S.cur && v.trim()) { S.cur = { id: null, mode: "new", original: "", targets: targetsNow() }; paintTargets(); }
  if (S.cur && S.cur.mode === "new" && !v.trim()) { cancelCurrent(true); return; }   // emptied: give the new one up
  if (S.cur && S.cur.mode === "new") typing(!!v.trim());     // the typing indicator, live or not, until Enter / cancel
  if (S.live) { clearTimeout(syncTimer); syncTimer = setTimeout(() => queue(syncLive), 450); }
}

async function syncLive() {                                  // (queued) the live text of the current message
  const c = S.cur, v = text.value;
  if (!c || !v.trim() || overLimit(v) || v === c.lastSent) return;
  if (c.id == null) {
    const m = await api("/messages", "POST", { text: v, final: false, sfx: S.sfx, targets: c.targets });
    c.id = m.id;
    paintStatus();
    refreshHistory();
  } else {
    await api(`/messages/${c.id}`, "PATCH", { text: v, final: false });
  }
  c.lastSent = v;
}

async function commit() {                                   // Enter: the current message is done
  const v = text.value;
  if (!v.trim() || overLimit(v)) return;
  clearTimeout(syncTimer);
  const c = S.cur || { id: null, mode: "new", targets: targetsNow() };
  S.cur = null; text.value = ""; updateCount(); paintTargets(); typing(false);
  S.busy++; paintStatus();
  await queue(async () => {                                 // (after any sync still on its way: it may have made the id)
    if (c.id == null) await api("/messages", "POST", { text: v, final: true, sfx: S.sfx, targets: c.targets });
    else await api(`/messages/${c.id}`, "PATCH", { text: v, final: true });
    toast(t(c.mode === "edit" ? "toast.edited" : "toast.sent"));
  });
  S.busy--; paintStatus();
  refreshHistory();
}

async function cancelCurrent(keepText) {                    // Esc: a new one disappears, an edit gets its text back
  clearTimeout(syncTimer);
  const c = S.cur;
  S.cur = null;
  if (!keepText || (c && c.mode === "edit")) text.value = "";
  updateCount(); paintTargets(); typing(false);
  if (!c) return;
  await queue(async () => {
    if (c.mode === "new" && c.id != null) await api(`/messages/${c.id}`, "DELETE");
    if (c.mode === "edit" && c.lastSent !== c.original) await api(`/messages/${c.id}`, "PATCH", { text: c.original, cancel: true });
  });
  refreshHistory();
}

function startEdit(m) {
  if (S.cur && text.value.trim() && !(S.cur.mode === "edit" && S.cur.id === m.id)) {
    toast(t("toast.finishFirst"), "err"); return;
  }
  S.cur = { id: m.id, mode: "edit", original: m.text, targets: m.targets || [], lastSent: m.text };
  text.value = m.text; paintTargets(); text.focus();
  text.setSelectionRange(text.value.length, text.value.length);
  refreshHistory();
}

text.addEventListener("input", onInput);
text.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.isComposing && e.keyCode !== 229) {
    // Enter sends (Shift+Enter = new line); with "Enter sends" off, Enter is a new line and Ctrl/⌘+Enter sends
    const send = S.enterSends ? !e.shiftKey : (e.ctrlKey || e.metaKey);
    if (send) { e.preventDefault(); commit(); }
  } else if (e.key === "Escape") { e.preventDefault(); cancelCurrent(false); }
});
// the send button must not take the focus away from the input (phones: the keyboard stays open)
$("send").addEventListener("pointerdown", (e) => { if (document.activeElement === text) e.preventDefault(); });
$("send").onclick = () => commit();
$("cancel").onclick = () => cancelCurrent(false);
$("editCancel").onclick = () => cancelCurrent(false);
$("kbFill").onclick = async () => {                          // into the game's keyboard, not sent
  const v = text.value;
  if (!v.trim()) return;
  try { await api("/messages", "POST", { text: v, immediate: false, targets: ["chatbox"] }); toast(t("kbFill.done")); }
  catch (e) { toast(t("toast.failed", { msg: e.message }), "err"); }
};

// ---------------------------------------------------------------- sending options (settings sheet; live also in the composer)
const OPTS = [["sSfx", "sfx"], ["sTyping", "typingHint"], ["sLive", "live"], ["sEnter", "enterSends"]];
function paintOpts() {
  for (const [id, key] of OPTS) $(id).setAttribute("aria-checked", !!S[key]);
  $("tLive").classList.toggle("on", S.live); $("tLive").setAttribute("aria-pressed", S.live);
}
function toggleOpt(key) {
  S[key] = !S[key]; store.set(key, S[key]); paintOpts();
  if (key === "typingHint" && !S.typingHint) typing(false);
  if (key === "enterSends") { paintPlaceholder(); paintStatus(); }
  if (key === "live") {
    toast(t(S.live ? "toast.liveOn" : "toast.liveOff"));
    if (S.live && S.cur && text.value.trim()) queue(syncLive);
    paintStatus();
  }
}
for (const [id, key] of OPTS) $(id).onclick = () => toggleOpt(key);
$("tLive").onclick = () => toggleOpt("live");
$("tLive").addEventListener("pointerdown", (e) => { if (document.activeElement === text) e.preventDefault(); });

// ---------------------------------------------------------------- settings sheet
function openSheet() {
  $("sheet").hidden = false;
  requestAnimationFrame(() => $("sheet").classList.add("open"));
  document.body.classList.add("sheet-open");
  $("openSettings").setAttribute("aria-expanded", "true");
  setTimeout(() => $("closeSettings").focus({ preventScroll: true }), 50);
}
function closeSheet() {
  if ($("sheet").hidden) return;
  $("sheet").classList.remove("open");
  document.body.classList.remove("sheet-open");
  $("openSettings").setAttribute("aria-expanded", "false");
  setTimeout(() => { $("sheet").hidden = true; }, 220);
  $("openSettings").focus({ preventScroll: true });
}
$("openSettings").onclick = openSheet;
$("closeSettings").onclick = closeSheet;
$("sheetBackdrop").onclick = closeSheet;
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("sheet").hidden) { e.preventDefault(); closeSheet(); } });

// ---------------------------------------------------------------- history (newest first; click = edit)
function hhmm(iso) { const d = new Date(iso); return isNaN(d) ? "" : d.toTimeString().slice(0, 5); }
const editable = (m, items) => !m.reverted && m.final !== false &&
  (m.kd_id != null || items.find((x) => (x.targets || []).includes("chatbox")) === m);

function iconBtn(sym, title, fn) {
  const b = el("button", "icon-btn sm", sym); b.type = "button"; b.title = title; b.setAttribute("aria-label", title);
  b.onclick = (e) => { e.stopPropagation(); fn(); };
  return b;
}

async function refreshHistory() {
  let items = [];
  try { items = (await api("/messages?limit=15")).items || []; } catch { }
  const ul = $("history"); ul.innerHTML = "";
  if (!items.length) { ul.appendChild(el("li", "empty", t("hist.empty"))); return; }
  for (const m of items) {
    const li = el("li", S.cur && S.cur.id === m.id ? "cur" : null);
    const body = el("div", "body");
    body.appendChild(el("div", "t" + (m.reverted ? " reverted" : ""), m.reverted ? t("hist.reverted") + m.text : m.text));
    const meta = el("div", "m");
    meta.appendChild(el("span", "time", hhmm(m.created_at)));
    const where = { chatbox: t("hist.game"), kd: t("hist.kd"), "chatbox+kd": t("hist.both") }[m.output] || m.output;
    meta.appendChild(el("span", "badge", where));
    if (m.final === false) meta.appendChild(el("span", "badge edit", t("hist.typing")));
    else if (m.edited && !m.reverted) meta.appendChild(el("span", "badge edit", t("hist.edited")));
    body.appendChild(meta);
    li.appendChild(body);
    const act = el("div", "act");
    if (m.kd_id != null && !m.reverted && m.final !== false) {
      act.appendChild(iconBtn("↶", t("hist.revert"), async () => {
        if (!confirm(t("hist.confirmRevert"))) return;
        try { await api(`/messages/${m.id}/revert`, "POST"); toast(t("hist.revertedToast")); refreshHistory(); }
        catch (err) { toast(t("hist.revertFailed", { msg: err.message }), "err"); }
      }));
    }
    act.appendChild(iconBtn("↻", t("hist.again"), async () => {
      try { await api("/messages", "POST", { text: m.text, final: true, sfx: S.sfx, targets: targetsNow() }); toast(t("hist.resent")); refreshHistory(); }
      catch (err) { toast(t("hist.sendFailed", { msg: err.message }), "err"); }
    }));
    li.appendChild(act);
    if (editable(m, items)) {
      li.title = t("hist.editHint"); li.classList.add("can-edit");
      body.tabIndex = 0; body.setAttribute("role", "button"); body.setAttribute("aria-label", t("hist.editHint") + ": " + m.text);
      li.onclick = () => startEdit(m);
      body.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); startEdit(m); } };
    }
    else li.classList.add("ro");
    ul.appendChild(li);
  }
}
$("clearHist").onclick = async () => {
  if (!confirm(t("hist.confirmClear"))) return;
  try { await api("/messages", "DELETE"); refreshHistory(); } catch (e) { toast(t("toast.failed", { msg: e.message }), "err"); }
};

// ---------------------------------------------------------------- Klaude display: settings
const SEGS = [     // [key, label key, option-key prefix, only in layout]
  ["screen", "set.screen", "screen"], ["layout", "set.layout", "layout"], ["scale", "set.scale", "scale"],
  ["long", "set.long", "long", "single"], ["speed", "set.speed", "speed", "single"],
];
const SEG_DEFAULTS = { screen: ["208x80", "176x96", "160x112", "128x128", "112x144", "96x176"], layout: ["chat", "single"],
                       scale: [1, 2], long: ["left", "up", "cut"], speed: ["slow", "normal", "fast"] };
const CHIPS = ["clock", "date", "show_time", "divider", "highlight", "invert", "image_full"];
const COLORS = ["color", "alt", "accent", "meta"];
const IMG_SEGS = [["image_fit", "img.fit", [["cover", "img.cover"], ["contain", "img.contain"]]],
                  ["image_screen", "img.screen", [["auto", "img.auto"], ["keep", "img.keep"]]],
                  ["image_res", "img.res", [["high", "img.high"], ["low", "img.low"]]]];
const colorName = (i) => t("colors")[i] || String(i);
const optName = (prefix, v) => { const k = prefix + "." + v, s = t(k); return s === k ? String(v) : s; };

async function loadKd() {
  try { S.kd = await api("/kd/settings"); renderSettings(); }
  catch (e) { $("settings").textContent = t("kd.unavailable", { msg: e.message }); }
}

async function setKd(part) {
  const before = { ...S.kd.settings };
  Object.assign(S.kd.settings, part); renderSettings();            // optimistic
  try { S.kd.settings = (await api("/kd/settings", "PUT", part)).settings; renderSettings(); refreshKd(true); }
  catch (e) { S.kd.settings = before; renderSettings(); toast(t("kd.setFailed", { msg: e.message }), "err"); }
}

function optRow(label, control, off) {
  const row = el("div", "opt" + (off ? " off" : ""));
  row.appendChild(el("span", "lab", label)); row.appendChild(control);
  if (off) row.title = t("set.onlySingle");
  return row;
}
function segOf(pairs, cur, onPick) {                 // pairs: [[value, label]]
  const seg = el("div", "seg");
  for (const [v, n] of pairs) {
    const on = String(cur) === String(v);
    const b = el("button", on ? "on" : null, n); b.type = "button"; b.setAttribute("aria-pressed", on);
    b.onclick = () => onPick(v);
    seg.appendChild(b);
  }
  return seg;
}

function renderSettings() {
  if (!S.kd) return;
  const box = $("settings"), s = S.kd.settings, ch = S.kd.choices || {};
  const scroll = $("sheet").querySelector(".panel-body").scrollTop;
  box.innerHTML = "";
  const set = el("div", "set"); box.appendChild(set);
  set.appendChild(el("h4", null, t("set.display")));
  for (const [key, label, prefix, only] of SEGS) {
    if (!(key in s)) continue;
    const vals = ch[key] || SEG_DEFAULTS[key];
    const seg = segOf(vals.map((v) => [v, optName(prefix, v)]), s[key], (v) => setKd({ [key]: key === "scale" ? Number(v) : v }));
    set.appendChild(optRow(t(label), seg, only && s.layout !== only));
  }
  if ("size" in s) {                       // the device's width in VRChat (register size; was the menu's radial)
    const wrap = el("div", "range");
    const r = el("input"); r.type = "range"; r.min = "0.20"; r.max = "0.60"; r.step = "0.01"; r.value = s.size;
    r.setAttribute("aria-label", t("set.size"));
    const out = el("em", null, Math.round(s.size * 100) + " cm");
    r.oninput = () => { out.textContent = Math.round(r.value * 100) + " cm"; };
    r.onchange = () => setKd({ size: Number(r.value) });
    wrap.appendChild(r); wrap.appendChild(out);
    set.appendChild(optRow(t("set.size"), wrap));
  }
  set.appendChild(el("h4", null, t("set.toggles")));
  const chips = el("div", "chips");
  for (const key of CHIPS) {
    if (!(key in s)) continue;
    const b = el("button", "pill" + (s[key] ? " on" : ""));
    b.type = "button"; b.setAttribute("aria-pressed", !!s[key]);
    b.appendChild(el("i", "dot")); b.appendChild(el("span", null, t("chip." + key)));
    b.onclick = () => setKd({ [key]: !s[key] });
    chips.appendChild(b);
  }
  set.appendChild(chips);
  set.appendChild(el("h4", null, t("set.colors")));
  for (const key of COLORS) {
    if (!(key in s)) continue;
    const sw = el("div", "swatches");
    if (key === "alt") {                                           // alternating colour: can be off
      const off = el("button", "none" + (s.alt === 0 ? " on" : ""), t("set.off"));
      off.type = "button"; off.setAttribute("aria-pressed", s.alt === 0);
      off.onclick = () => setKd({ alt: 0 }); sw.appendChild(off);
    }
    for (let i = 1; i <= 14; i++) {
      const b = el("button", s[key] === i ? "on" : null);
      b.type = "button"; b.style.background = S.palette[i] || "#888";
      b.title = colorName(i); b.setAttribute("aria-label", colorName(i)); b.setAttribute("aria-pressed", s[key] === i);
      b.onclick = () => setKd({ [key]: i });
      sw.appendChild(b);
    }
    sw.appendChild(el("em", null, s[key] ? colorName(s[key]) : t("set.off")));
    set.appendChild(optRow(t("color." + key), sw));
  }
  if ("image_fit" in s) {
    set.appendChild(el("h4", null, t("set.image")));
    for (const [key, label, opts] of IMG_SEGS) {
      if (!(key in s)) continue;
      set.appendChild(optRow(t(label), segOf(opts.map(([v, k]) => [v, t(k)]), s[key], (v) => setKd({ [key]: v }))));
    }
  }
  $("sheet").querySelector(".panel-body").scrollTop = scroll;
}

// ---------------------------------------------------------------- Klaude display: status, preview, actions
function paintKdStat() {
  const s = S.kdStat;
  if (!s) return;
  const st = $("kdStat"); st.innerHTML = "";
  st.appendChild(el("strong", s.synced ? "ok" : null, t(s.synced ? "kd.synced" : "kd.syncing")));
  const parts = [];
  if (!s.synced) parts.push(t("kd.pending", { p: s.pending_pages, s: Math.ceil(s.eta_s) }));
  parts.push(`${s.width}×${s.height}`, t("kd.msgs", { n: s.messages }));
  if (s.image) parts.push(t("kd.showingImage"));
  st.appendChild(document.createTextNode(" · " + parts.join(" · ")));
}

async function refreshKd(force) {
  if (!S.out.kd || (document.hidden && !force)) return;
  try {
    const s = await api("/kd/status");
    S.kdStat = s;
    if (!S.palette.length && s.palette) { S.palette = s.palette; if (S.kd) renderSettings(); }
    if (s.width && (!S.dims || S.dims[0] !== s.width || S.dims[1] !== s.height)) {
      S.dims = [s.width, s.height];
      const k = Math.min(352 / s.width, 240 / s.height);
      $("prev").style.width = Math.round(s.width * k) + "px"; $("prev").style.height = Math.round(s.height * k) + "px";
      $("prev").style.aspectRatio = `${s.width} / ${s.height}`;
    }
    $("led").className = s.synced ? "ok" : "";
    paintKdStat();
    $("closeImg").hidden = !s.image;
    if (s.image !== S.image) {                                     // a picture appeared / closed
      S.image = s.image;
      if (!S.toManual || !s.image) { S.to.kd = !s.image; S.toManual = false; paintTargets(); }
      if (s.image && S.out.chatbox) toast(t("kd.imageChatOnly"));
    }
    $("prev").src = "/api/v1/kd/preview.png?t=" + Date.now();
  } catch (e) { S.kdStat = null; $("kdStat").textContent = t("kd.unavailable", { msg: e.message }); }
}

$("chime").onclick = async () => { try { await api("/kd/chime", "POST"); toast("🔔"); } catch (e) { toast(t("toast.failed", { msg: e.message }), "err"); } };
$("kdClear").onclick = async () => { try { await api("/kd/clear", "POST"); toast(t("kd.cleared")); refreshKd(true); } catch (e) { toast(t("toast.failed", { msg: e.message }), "err"); } };
$("closeImg").onclick = async () => { try { await api("/kd/image", "DELETE"); refreshKd(true); } catch (e) { toast(t("toast.failed", { msg: e.message }), "err"); } };

async function sendImage(file) {
  if (!file || !file.type.startsWith("image/")) return;
  if (!S.out.kd) { toast(t("kd.needKd"), "err"); return; }
  toast(t("kd.imgWorking"));
  try { const r = await api("/kd/image", "POST", undefined, file); toast(t("kd.imgShown", { s: Math.round(r.eta_s) })); refreshKd(true); }
  catch (e) { toast(t("kd.imgFailed", { msg: e.message }), "err"); }
}
$("file").onchange = (e) => { sendImage(e.target.files[0]); e.target.value = ""; };
document.addEventListener("paste", (e) => {
  const item = [...(e.clipboardData?.items || [])].find((i) => i.kind === "file" && i.type.startsWith("image/"));
  if (!item) return;
  e.preventDefault(); sendImage(item.getAsFile());
});
let dragDepth = 0;
document.addEventListener("dragenter", (e) => { if ([...e.dataTransfer.types].includes("Files")) { dragDepth++; $("dropzone").classList.add("on"); } });
document.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; $("dropzone").classList.remove("on"); } });
document.addEventListener("dragover", (e) => e.preventDefault());
document.addEventListener("drop", (e) => {
  e.preventDefault(); dragDepth = 0; $("dropzone").classList.remove("on");
  sendImage([...e.dataTransfer.files].find((f) => f.type.startsWith("image/")));
});

// ---------------------------------------------------------------- connection
// "ok" = the server answers and the VRChat host resolves; "warn" = server ok, host does not resolve; "bad" = no server
function paintConn() {
  const c = $("conn"), st = S.conn;
  c.className = "conn" + (st ? " " + st : "");
  const label = t(st === "ok" ? "conn.online" : st === "warn" ? "conn.noHost" : st === "bad" ? "conn.offline" : "conn.connecting");
  c.querySelector("span").textContent = label;
  c.title = t("conn.title") + ": " + label;
  $("offline").hidden = st !== "bad";
}
async function health() {
  try { const h = await api("/health"); S.conn = h.ok === false ? "warn" : "ok"; }
  catch { S.conn = "bad"; }
  paintConn();
}

// ---------------------------------------------------------------- phones: keyboard and the fixed composer
// Android Chrome shrinks the page for the keyboard (viewport interactive-widget=resizes-content); iOS Safari and older
// browsers do not: there the visual viewport tells how much of the window the keyboard covers, and the composer moves up.
function layoutViewport() {
  const vv = window.visualViewport;
  const kb = vv ? Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop)) : 0;
  document.documentElement.style.setProperty("--kb", kb + "px");
  const open = kb > 60 || (document.activeElement === text && phone() && vv && vv.height < screen.height * 0.6);
  document.body.classList.toggle("kb", !!open);
}
if (window.visualViewport) {
  visualViewport.addEventListener("resize", layoutViewport);
  visualViewport.addEventListener("scroll", layoutViewport);
}
text.addEventListener("focus", () => setTimeout(layoutViewport, 300));
text.addEventListener("click", () => setTimeout(layoutViewport, 300));
text.addEventListener("blur", () => setTimeout(layoutViewport, 300));
new ResizeObserver(([e]) => document.documentElement.style.setProperty("--composer-h", Math.ceil(e.target.offsetHeight) + "px"))
  .observe($("composer"));
matchMedia("(max-width: 720px)").addEventListener("change", () => { paintPlaceholder(); updateCount(); paintStatus(); });

// ---------------------------------------------------------------- start
(async () => {
  setLang(LANG, false);
  paintOpts();
  updateCount();
  layoutViewport();
  await setOutputs(null);
  health();
  setInterval(() => refreshKd(false), 1000);
  setInterval(health, 10000);
  setInterval(refreshHistory, 15000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { refreshKd(true); refreshHistory(); health(); } });
  if (!phone()) text.focus();      // (phones: no keyboard popping up on load)
})();
