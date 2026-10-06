// VRChat Chatbox console. One page for both outputs: the game's chatbox (OSC /chatbox/*) and the Klaude display
// (kd: /api/v1/kd/*). Talks only to the REST API; the browser re-sends the Basic Auth login.
// Every user-visible string comes from i18n.js (t(key) / data-i18n attributes).
"use strict";

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const phone = () => matchMedia("(max-width: 720px)").matches;

const store = {
  get: (k, d) => { try { const v = localStorage.getItem("kdchat." + k) ?? localStorage.getItem("vcb." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },   // vcb.: before 1.3.0
  set: (k, v) => { try { localStorage.setItem("kdchat." + k, JSON.stringify(v)); } catch { } },
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
  document.querySelectorAll("#langSeg button").forEach((b) => {
    const on = b.dataset.lang === l; b.classList.toggle("on", on); b.setAttribute("aria-pressed", on);
  });
  paintPlaceholder(); paintOutputs(); paintTargets(); paintStatus(); paintConn();
  if (S.kd) renderSettings();
  if (typeof TR !== "undefined" && TR && TR.data) paintTr();
  if (S.kdStat) paintKdStat();
  if (S.cfg) paintSettings();
  refreshHistory();
}
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
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg || JSON.stringify(d)).join("; ");   // (validation errors)
    const err = new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    err.status = r.status;
    throw err;
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
  layoutSide();
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
  // the label says what happens; where it goes is shown by the 🎮 / 🖥 targets next to it (both outputs on)
  const label = t(edit ? "send.save" : "send.send");
  const where = t(!both ? "send.send" : tg.length === 2 ? "send.both" : tg[0] === "kd" ? "send.kd" : "send.chatbox");
  $("sendLbl").textContent = label;
  $("send").setAttribute("aria-label", edit ? label : where); $("send").title = edit ? label : where;
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
  // the line count only matters once there is more than one line
  c.textContent = phone() || lines < 2 ? t("composer.countShort", { n: v.length, max: S.maxChars })
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
function openSheet(focusId) {
  loadSettings();
  loadTr();
  $("sheet").hidden = false;
  requestAnimationFrame(() => $("sheet").classList.add("open"));
  document.body.classList.add("sheet-open");
  $("openSettings").setAttribute("aria-expanded", "true");
  setTimeout(() => {
    if (focusId) { $(focusId).scrollIntoView({ block: "start", behavior: "smooth" }); }
    else $("closeSettings").focus({ preventScroll: true });
  }, 60);
}
function closeSheet() {
  if ($("sheet").hidden) return;
  $("sheet").classList.remove("open");
  document.body.classList.remove("sheet-open");
  $("openSettings").setAttribute("aria-expanded", "false");
  setTimeout(() => { $("sheet").hidden = true; }, 220);
  $("openSettings").focus({ preventScroll: true });
}
$("openSettings").onclick = () => openSheet();
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
  $("clearHist").hidden = !items.length;
  if (!items.length) { ul.appendChild(el("li", "empty", t("hist.empty"))); return; }
  const mixed = new Set(items.map((m) => m.output)).size > 1;     // where it went: only worth showing when it differs
  for (const m of items) {
    const li = el("li", S.cur && S.cur.id === m.id ? "cur" : null);
    const body = el("div", "body");
    body.appendChild(el("div", "t" + (m.reverted ? " reverted" : ""), m.reverted ? t("hist.reverted") + m.text : m.text));
    const meta = el("div", "m");
    meta.appendChild(el("span", "time", hhmm(m.created_at)));
    const where = { chatbox: t("hist.game"), kd: t("hist.kd"), "chatbox+kd": t("hist.both") }[m.output] || m.output;
    if (mixed) meta.appendChild(el("span", "badge", where));
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
  ["wings", "set.wings", "wings"],
  ["long", "set.long", "long", "single"], ["speed", "set.speed", "speed", "single"],
];
const SEG_DEFAULTS = { screen: ["208x80", "176x96", "160x112", "128x128", "112x144", "96x176"], layout: ["chat", "single"],
                       scale: [1, 2], long: ["left", "up", "cut"], speed: ["slow", "normal", "fast"], wings: ["auto", "on", "off"] };
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
  if (s.wings) parts.push(t("kd.wingsOpen"));
  if ((s.images || []).length > 1) parts.push(t("kd.lowres"));
  st.appendChild(document.createTextNode(" · " + parts.join(" · ")));
}

async function refreshKd(force) {
  if (!S.out.kd || (document.hidden && !force)) return;
  try {
    const s = await api("/kd/status");
    S.kdStat = s;
    if (!S.palette.length && s.palette) { S.palette = s.palette; if (S.kd) renderSettings(); }
    const pw = s.wings ? 3 * s.width + 12 : s.width;              // open side screens: the preview shows all three
    if (s.width && (!S.dims || S.dims[0] !== pw || S.dims[1] !== s.height)) {
      S.dims = [pw, s.height];
      const k = Math.min((s.wings ? 1056 : 352) / pw, 240 / s.height);
      $("prev").style.width = Math.round(pw * k) + "px"; $("prev").style.height = Math.round(s.height * k) + "px";
      $("prev").style.aspectRatio = `${pw} / ${s.height}`;
      $("prev").closest(".device").classList.toggle("wide", !!s.wings);
    }
    paintImgScreen();
    $("led").className = s.synced ? "ok" : "";
    paintKdStat();
    $("closeImg").hidden = !(s.images || []).length && !s.image;
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
  const scr = S.imgScreen || "main";
  try { const r = await api("/kd/image?screen=" + scr, "POST", undefined, file); toast(t("kd.imgShown", { s: Math.round(r.eta_s) })); refreshKd(true); }
  catch (e) { toast(t("kd.imgFailed", { msg: e.message }), "err"); }
}
// where the next picture goes (main screen or a side screen; side screens: up to 3 pictures, low resolution)
function paintImgScreen() {
  const box = $("imgScreen");
  const can = S.kd && S.kd.settings && S.kd.settings.wings !== "off";
  box.hidden = !can;
  if (!can) { S.imgScreen = "main"; return; }
  box.innerHTML = "";
  box.appendChild(el("span", "lab", t("img.to")));
  box.appendChild(segOf(["main", "left", "right"].map((v) => [v, t("scr." + v)]), S.imgScreen || "main",
                        (v) => { S.imgScreen = v; paintImgScreen(); }));
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

// ---------------------------------------------------------------- server settings: phone access, OSC target, password, address
// S.cfg = GET /settings: {version, osc, server, password, network, warning}
const qrUrl = (u) => "/api/v1/network/qr.svg?url=" + encodeURIComponent(u);
const IPV4_RE = /^((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$/;
const NAME_RE = /^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.?$/;
const validHost = (h) => (/^[\d.]+$/.test(h) ? IPV4_RE.test(h) : NAME_RE.test(h));   // (same rules as the server)
const validPort = (p) => /^\d+$/.test(String(p)) && +p >= 1 && +p <= 65535;
let lanPick = 0;

async function loadSettings() {
  try { S.cfg = await api("/settings"); paintSettings(); } catch { }
}

function fieldErr(id, msg) { const e = $(id); e.textContent = msg || ""; e.hidden = !msg; }

function paintSettings() {
  const c = S.cfg;
  if (!c) return;
  document.querySelectorAll(".ver").forEach((e) => { e.textContent = "v" + c.version; });
  // phone access
  const n = c.network, urls = n.urls || [];
  if (lanPick >= urls.length) lanPick = 0;
  $("lanNone").hidden = urls.length > 0;
  $("lanNone").textContent = t("lan.none", { host: n.listen_host });
  $("lanBox").hidden = !urls.length;
  const list = $("lanList"); list.innerHTML = "";
  if (urls.length) {
    list.appendChild(el("p", "hint", t("lan.scan")));
    urls.forEach((u, i) => {
      const b = el("button", "lan-url" + (i === lanPick ? " on" : ""), u.replace(/\/$/, ""));
      b.type = "button"; b.setAttribute("aria-pressed", i === lanPick);
      b.onclick = () => { lanPick = i; paintSettings(); };
      list.appendChild(b);
    });
    const u = urls[lanPick];
    if ($("lanQr").dataset.url !== u) { $("lanQr").src = qrUrl(u); $("lanQr").dataset.url = u; }
    $("lanQr").alt = t("lan.qrAlt", { url: u });
  }
  // the desktop card + the "open on the LAN" notice
  $("phoneCard").hidden = !urls.length || store.get("phoneHidden", false);
  layoutSide();
  if (urls.length) {
    if ($("phoneQr").dataset.url !== urls[0]) { $("phoneQr").src = qrUrl(urls[0]); $("phoneQr").dataset.url = urls[0]; }
    $("phoneQr").alt = t("lan.qrAlt", { url: urls[0] });
    $("phoneUrl").href = urls[0]; $("phoneUrl").textContent = urls[0].replace(/\/$/, "");
  }
  $("lanNotice").hidden = !n.open_on_lan || store.get("lanNoticeOff", false);
  // OSC target
  const o = c.osc;
  $("oscNow").textContent = `${o.host}:${o.port}`;
  $("oscSrc").textContent = t("osc.src." + (o.source || "default"));
  if (document.activeElement !== $("oscHost") && document.activeElement !== $("oscPort")) {
    $("oscHost").value = o.host; $("oscPort").value = o.port;
  }
  $("oscReset").title = `${o.default.host}:${o.default.port}`;
  if (o.error) fieldErr("oscErr", t("osc.unresolved", { msg: o.error })); 
  // password
  const pw = c.password;
  $("pwState").textContent = t(!pw.enabled ? "pw.off" : pw.source === "env" ? "pw.onEnv" : "pw.onSettings");
  $("pwCurWrap").hidden = !pw.enabled;
  $("pwRemove").hidden = !pw.enabled;
  $("pwSave").textContent = t(pw.enabled ? "pw.change" : "pw.set");
  // server address
  const sv = c.server;
  if (!$("srvForm").contains(document.activeElement)) { $("srvHost").value = sv.listen_host; $("srvPort").value = sv.listen_port; }
  $("srvRestart").hidden = !sv.restart_needed;
}

$("oscForm").onsubmit = async (e) => {
  e.preventDefault();
  const host = $("oscHost").value.trim(), port = $("oscPort").value.trim();
  if (!validHost(host)) return fieldErr("oscErr", t("osc.badHost"));
  if (!validPort(port)) return fieldErr("oscErr", t("osc.badPort"));
  fieldErr("oscErr");
  try {
    S.cfg.osc = await api("/osc", "PUT", { host, port: Number(port) });
    paintSettings(); health(); toast(t("osc.saved", { target: `${host}:${port}` }));
  } catch (err) { fieldErr("oscErr", err.status === 400 ? err.message : t("toast.failed", { msg: err.message })); }
};
$("oscReset").onclick = async () => {
  fieldErr("oscErr");
  try {
    S.cfg.osc = await api("/osc", "DELETE");
    $("oscHost").value = S.cfg.osc.host; $("oscPort").value = S.cfg.osc.port;
    paintSettings(); health(); toast(t("osc.resetDone", { target: `${S.cfg.osc.host}:${S.cfg.osc.port}` }));
  } catch (err) { fieldErr("oscErr", t("toast.failed", { msg: err.message })); }
};

$("pwForm").onsubmit = async (e) => {
  e.preventDefault();
  const nw = $("pwNew").value;
  if (nw.length < 4) return fieldErr("pwErr", t("pw.short"));
  fieldErr("pwErr");
  try {
    await api("/settings/password", "PUT", { current_password: $("pwCur").value || null, new_password: nw });
    $("pwCur").value = $("pwNew").value = "";
    toast(t("pw.setDone"));
    setTimeout(() => location.reload(), 1500);              // the browser asks for the new password
  } catch (err) { fieldErr("pwErr", err.status === 403 ? t("pw.wrong") : err.message); }
};
$("pwRemove").onclick = async () => {
  if (!confirm(t("pw.confirmRemove"))) return;
  try {
    S.cfg.password = await api("/settings/password", "PUT", { current_password: $("pwCur").value || null, new_password: null });
    $("pwCur").value = ""; fieldErr("pwErr"); toast(t("pw.removed")); loadSettings();
  } catch (err) { fieldErr("pwErr", err.status === 403 ? t("pw.wrong") : err.message); }
};

$("srvForm").onsubmit = async (e) => {
  e.preventDefault();
  const host = $("srvHost").value.trim(), port = $("srvPort").value.trim();
  if (!validHost(host)) return fieldErr("srvErr", t("srv.badHost"));
  if (!validPort(port)) return fieldErr("srvErr", t("osc.badPort"));
  fieldErr("srvErr");
  try { S.cfg.server = await api("/settings/server", "PUT", { listen_host: host, listen_port: Number(port) }); paintSettings(); toast(t("srv.saved")); }
  catch (err) { fieldErr("srvErr", err.message); }
};
$("srvReset").onclick = async () => {
  try { S.cfg.server = await api("/settings/server", "DELETE"); $("srvHost").value = ""; paintSettings(); toast(t("srv.saved")); }
  catch (err) { fieldErr("srvErr", err.message); }
};

$("lanSetPw").onclick = () => { openSheet("pwSec"); setTimeout(() => $("pwNew").focus({ preventScroll: true }), 400); };
$("lanDismiss").onclick = () => { store.set("lanNoticeOff", true); $("lanNotice").hidden = true; };
$("phoneHide").onclick = () => { store.set("phoneHidden", true); $("phoneCard").hidden = true; layoutSide(); };

// two columns when the side column has something to show (the display, or the phone card on a computer)
function layoutSide() {
  const any = !$("kdCol").hidden || (!$("phoneCard").hidden && !phone());
  $("side").hidden = !any;
  $("grid").classList.toggle("two", any);
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
matchMedia("(max-width: 720px)").addEventListener("change", () => { paintPlaceholder(); updateCount(); paintStatus(); layoutSide(); });

// ---------------------------------------------------------------- start
(async () => {
  setLang(LANG, false);
  paintOpts();
  updateCount();
  layoutViewport();
  await setOutputs(null);
  health(); loadSettings();
  setInterval(() => refreshKd(false), 1000);
  setInterval(health, 10000);
  setInterval(refreshHistory, 15000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { refreshKd(true); refreshHistory(); health(); } });
  if (!phone()) text.focus();      // (phones: no keyboard popping up on load)
})();


// ---------------------------------------------------------------- translation (local models, translate.py)
var TR = { data: null, poll: null };      // (var: setLang may run before this line)

async function loadTr() {
  try { TR.data = await api("/translate"); paintTr(); }
  catch (e) { $("trBox").textContent = t("tr.failed", { msg: e.message }); }
  const busy = TR.data && TR.data.languages.some((l) => l.state === "downloading");
  clearTimeout(TR.poll);
  if (busy) TR.poll = setTimeout(loadTr, 1000);
}

async function setTr(part) {
  try { TR.data.settings = (await api("/translate", "PUT", part)).settings; paintTr(); refreshKd(true); }
  catch (e) { toast(t("tr.failed", { msg: e.message }), "err"); loadTr(); }
}

function langLabel(l) { return l.native === l.name ? l.native : `${l.native} · ${l.name}`; }

function selectOf(options, cur, onPick) {          // options: [[value, label]]
  const sel = el("select");
  for (const [v, n] of options) { const o = el("option", null, n); o.value = v; if (String(v) === String(cur)) o.selected = true; sel.appendChild(o); }
  sel.onchange = () => onPick(sel.value);
  return sel;
}

function paintTr() {
  const d = TR.data;
  if (!d) return;
  const s = d.settings, langs = d.languages;
  const ready = langs.filter((l) => l.state === "ready");
  const sw = $("trOn"); sw.setAttribute("aria-checked", !!s.enabled);
  sw.onclick = () => setTr({ enabled: !s.enabled });
  const box = $("trBox"); box.innerHTML = "";
  const all = langs.map((l) => [l.code, langLabel(l)]);
  const pickTarget = (i) => (v) => {
    const tg = [...s.targets]; tg[i] = v; const out = tg.filter((x, k) => x && x !== "-" && tg.indexOf(x) === k);
    const l = langs.find((x) => x.code === v);
    if (l && l.state !== "ready") toast(t("tr.needModel", { name: l.native }), "err");
    setTr({ targets: out });
  };
  box.appendChild(optRow(t("tr.source"), selectOf([["auto", t("tr.auto")], ...all], s.source, (v) => setTr({ source: v }))));
  if (s.source === "auto")
    box.appendChild(optRow(t("tr.latin"), selectOf(all.filter(([c]) => !["zh", "zh_hant", "ja", "ko", "ru", "uk", "bg", "ar", "fa", "ur", "he", "th", "el", "hi", "mr", "bn", "ta", "te", "kn", "ml", "gu", "sr"].includes(c)), s.latin, (v) => setTr({ latin: v }))));
  box.appendChild(optRow(t("tr.target1"), selectOf([["-", t("tr.none")], ...all], s.targets[0] || "-", pickTarget(0))));
  box.appendChild(optRow(t("tr.target2"), selectOf([["-", t("tr.none")], ...all], s.targets[1] || "-", pickTarget(1))));
  box.appendChild(optRow(t("tr.chatbox"), segOf([[0, t("tr.cb0")], [1, t("tr.cb1")], [2, t("tr.cb2")]], s.chatbox, (v) => setTr({ chatbox: Number(v) }))));
  const kd = el("button", "pill" + (s.kd ? " on" : "")); kd.type = "button"; kd.setAttribute("aria-pressed", !!s.kd);
  kd.appendChild(el("i", "dot")); kd.appendChild(el("span", null, t("tr.kd"))); kd.onclick = () => setTr({ kd: !s.kd });
  box.appendChild(optRow("", kd));
  // the language list: the selected / downloaded ones first
  const m = $("trModels"); m.innerHTML = "";
  const want = new Set([s.source, s.latin, ...s.targets]);
  const order = [...langs].filter((l) => l.code !== "en").sort((a, b) =>
    (b.state === "ready") - (a.state === "ready") || want.has(b.code) - want.has(a.code) || a.name.localeCompare(b.name));
  for (const l of order) {
    const row = el("div", "tr-row" + (l.state === "ready" ? " ready" : ""));
    row.appendChild(el("span", "lab", langLabel(l)));
    const mb = Math.round((l.size || 0) / 1e6);
    if (l.state === "downloading") {
      const pct = l.total ? Math.floor(100 * l.done / l.total) : 0;
      const bar = el("span", "bar"); const fill = el("i"); fill.style.width = pct + "%"; bar.appendChild(fill);
      row.appendChild(bar); row.appendChild(el("em", null, pct + "%"));
    } else if (l.state === "ready") {
      row.appendChild(el("em", "ok", t("tr.ready")));
      const del = el("button", "btn sm ghost", t("tr.delete")); del.type = "button";
      del.onclick = async () => { try { await api("/translate/models/" + l.code, "DELETE"); loadTr(); } catch (e) { toast(t("toast.failed", { msg: e.message }), "err"); } };
      row.appendChild(del);
    } else {
      row.appendChild(el("em", l.state === "error" ? "err" : null, l.state === "error" ? (l.error || "error") : mb + " MB"));
      const dl = el("button", "btn sm", t(l.state === "error" ? "tr.retry" : "tr.download")); dl.type = "button";
      dl.onclick = async () => { try { await api("/translate/models/" + l.code, "POST"); loadTr(); } catch (e) { toast(t("toast.failed", { msg: e.message }), "err"); } };
      row.appendChild(dl);
    }
    m.appendChild(row);
  }
}
