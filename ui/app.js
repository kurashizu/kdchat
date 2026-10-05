// VRChat Chatbox console. One page for both outputs: the game's chatbox (OSC /chatbox/*) and the Klaude display
// (kd: /api/v1/kd/*). Talks only to the REST API; the browser re-sends the Basic Auth login.
"use strict";

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

const store = {
  get: (k, d) => { try { const v = localStorage.getItem("vcb." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem("vcb." + k, JSON.stringify(v)); } catch { } },
};

const S = {
  out: { chatbox: true, kd: false }, maxChars: 144, maxLines: 9,
  sfx: store.get("sfx", true), typingHint: store.get("typingHint", true), live: store.get("live", true),
  typingOn: false,
  to: { chatbox: true, kd: true }, toManual: false,      // where new messages go (within the outputs that are on)
  cur: null,                                             // the current message (see below)
  kd: null,                    // {settings, choices}
  palette: [], dims: null, image: false,
};

// ---------------------------------------------------------------- API
async function api(path, method = "GET", body, raw) {
  const opt = { method, headers: {} };
  if (raw) { opt.body = raw; opt.headers["Content-Type"] = raw.type || "application/octet-stream"; }
  else if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers["Content-Type"] = "application/json"; }
  const r = await fetch("/api/v1" + path, opt);
  if (!r.ok) {
    let msg = r.status + "";
    try { const j = await r.json(); msg = j.detail || msg; } catch { }
    throw new Error(msg);
  }
  return r.status === 204 ? null : r.json();
}

function toast(msg, kind) {
  const t = el("div", "toast" + (kind === "err" ? " err" : ""), msg);
  $("toasts").appendChild(t);
  setTimeout(() => t.classList.add("hide"), kind === "err" ? 3500 : 1800);
  setTimeout(() => t.remove(), kind === "err" ? 3800 : 2100);
}

// ---------------------------------------------------------------- outputs (both can be on at the same time)
async function setOutputs(part) {
  try {
    const r = part ? await api("/outputs", "PUT", part) : await api("/outputs");
    S.out = { chatbox: r.chatbox, kd: r.kd };
    document.querySelector('.outputs [data-mode="kd"]').disabled = !r.kd_available;
  } catch (e) { toast("切换失败：" + e.message, "err"); }
  document.querySelectorAll(".outputs button").forEach((b) => {
    const on = !!S.out[b.dataset.mode];
    b.classList.toggle("on", on); b.setAttribute("aria-pressed", on);
  });
  const kd = S.out.kd;
  $("kdCol").hidden = !kd;
  document.querySelector(".grid").classList.toggle("two", kd);
  paintTargets();
  if (kd) { if (!S.kd) await loadKd(); refreshKd(true); }
}
document.querySelectorAll(".outputs button").forEach((b) => b.onclick = () => {
  const k = b.dataset.mode, on = !S.out[k];
  if (!on && k === "kd" && !confirm("关闭 Klaude 显示屏？屏幕会退场，游戏聊天框不受影响。")) return;
  setOutputs({ [k]: on }).then(() => toast((k === "kd" ? "Klaude 显示屏" : "游戏聊天框") + (on ? " 已打开" : " 已关闭")));
});

// ---------------------------------------------------------------- the current message
// The input box is always "the current message": a new one, or a sent one being edited. With 边打边发 on it is live on
// the outputs while it is typed (it exists on the server from the first sync on: one id for its whole life); Enter
// finishes it (the next keystroke starts a new one), Esc gives it up (a new one disappears, an edit goes back to the
// text it had). Where it goes is decided when it starts (🎮 / 🖥) and does not change afterwards.
//   S.cur = null | {id, mode: "new" | "edit", original, targets, lastSent}
let syncTimer = null, chain = Promise.resolve();
const queue = (fn) => (chain = chain.then(fn).catch((e) => toast("失败：" + e.message, "err")));

function targetsNow() {                                    // for a message that starts now
  const t = ["chatbox", "kd"].filter((k) => S.out[k] && S.to[k]);
  return t.length ? t : ["chatbox", "kd"].filter((k) => S.out[k]);
}
const curTargets = () => (S.cur ? S.cur.targets : targetsNow());

function paintTargets() {
  const both = S.out.chatbox && S.out.kd, t = curTargets(), edit = S.cur && S.cur.mode === "edit";
  $("targets").hidden = !both;
  document.querySelectorAll("#targets button").forEach((b) => {
    b.classList.toggle("on", t.includes(b.dataset.to)); b.disabled = !!S.cur;
  });
  $("targets").title = S.cur ? "这条发到哪里在开始打字时就定了" : "这条发到哪里（只影响发送，不关闭输出）";
  $("send").textContent = edit ? "保存修改" : !both ? "发送" : t.length === 2 ? "发送到两边" : t[0] === "kd" ? "发到显示屏" : "发到游戏";
  $("kbFill").hidden = !S.out.chatbox || !!edit;
  $("editing").hidden = !edit;
  if (edit) $("editWhat").textContent = S.cur.original;
  const chat = t.includes("chatbox");
  S.maxChars = chat ? 144 : 400; S.maxLines = chat ? 9 : 20;
  updateCount();
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

function updateCount() {
  const v = text.value, lines = v ? v.split("\n").length : 0;
  const over = v.length > S.maxChars || lines > S.maxLines;
  $("count").textContent = `${v.length} / ${S.maxChars} · ${lines} / ${S.maxLines} 行`;
  $("count").classList.toggle("over", over);
  // phones: the counter only near the limit (the option chips need the row)
  $("count").classList.toggle("near", v.length > S.maxChars * 0.8 || lines > S.maxLines - 2);
  $("send").disabled = !v.trim() || over;
  const phone = matchMedia("(max-width: 720px)").matches;
  const cap = phone ? (document.body.classList.contains("kb") ? 96 : 140) : 260;
  text.style.height = "auto";
  text.style.height = Math.min(cap, Math.max(phone ? 42 : 84, text.scrollHeight + 2)) + "px";
}

async function typing(on) {
  on = !!on && S.typingHint;
  if (S.typingOn === on) return;
  S.typingOn = on;
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
  await queue(async () => {                                 // (after any sync still on its way: it may have made the id)
    if (c.id == null) await api("/messages", "POST", { text: v, final: true, sfx: S.sfx, targets: c.targets });
    else await api(`/messages/${c.id}`, "PATCH", { text: v, final: true });
    toast(c.mode === "edit" ? "已修改" : "已发送");
  });
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
    toast("先发送（Enter）或取消（Esc）正在打的这条", "err"); return;
  }
  S.cur = { id: m.id, mode: "edit", original: m.text, targets: m.targets || [], lastSent: m.text };
  text.value = m.text; paintTargets(); text.focus();
  text.setSelectionRange(text.value.length, text.value.length);
}

text.addEventListener("input", onInput);
text.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); commit(); }
  else if (e.key === "Escape") { e.preventDefault(); cancelCurrent(false); }
});
$("send").onclick = () => commit();
$("cancel").onclick = () => cancelCurrent(false);
$("editCancel").onclick = () => cancelCurrent(false);
$("kbFill").onclick = async () => {                          // into the game's keyboard, not sent
  const v = text.value;
  if (!v.trim()) return;
  try { await api("/messages", "POST", { text: v, immediate: false, targets: ["chatbox"] }); toast("已填进游戏键盘"); }
  catch (e) { toast("失败：" + e.message, "err"); }
};

function chip(id, key) {
  const b = $(id);
  const paint = () => b.classList.toggle("on", !!S[key]);
  b.onclick = () => {
    S[key] = !S[key]; store.set(key, S[key]); paint();
    if (key === "typingHint" && !S.typingHint) typing(false);
    if (key === "live") {
      toast(S.live ? "边打边发：打字时就实时显示，Enter 定稿" : "边打边发已关闭：Enter 才发出");
      if (S.live && S.cur && text.value.trim()) queue(syncLive);
    }
  };
  paint();
}
chip("tSfx", "sfx"); chip("tTyping", "typingHint"); chip("tAuto", "live");

// ---------------------------------------------------------------- history (newest first; click = edit)
function hhmm(iso) { const d = new Date(iso); return isNaN(d) ? "" : d.toTimeString().slice(0, 5); }
const editable = (m, items) => !m.reverted && m.final !== false &&
  (m.kd_id != null || items.find((x) => (x.targets || []).includes("chatbox")) === m);

async function refreshHistory() {
  let items = [];
  try { items = (await api("/messages?limit=15")).items || []; } catch { }
  const ul = $("history"); ul.innerHTML = "";
  if (!items.length) { ul.appendChild(el("li", "empty", "还没有消息")); return; }
  for (const m of items) {
    const li = el("li" , S.cur && S.cur.id === m.id ? "cur" : null);
    li.appendChild(el("div", "t" + (m.reverted ? " reverted" : ""), m.reverted ? "（已撤回）" + m.text : m.text));
    const meta = el("div", "m", hhmm(m.created_at));
    const where = { chatbox: "游戏", kd: "显示屏", "chatbox+kd": "两边" }[m.output] || m.output;
    meta.appendChild(el("span", "badge", where));
    if (m.final === false) meta.appendChild(el("span", "badge edit", "正在打"));
    else if (m.edited && !m.reverted) meta.appendChild(el("span", "badge edit", "已编辑"));
    li.appendChild(meta);
    const act = el("div", "act");
    if (m.kd_id != null && !m.reverted && m.final !== false) {
      const rv = el("button", "again", "↶"); rv.title = "撤回（显示屏上显示 message reverted；游戏聊天框撤回不了）";
      rv.onclick = async (e) => {
        e.stopPropagation();
        if (!confirm("撤回这条消息？显示屏上会显示 message reverted。")) return;
        try { await api(`/messages/${m.id}/revert`, "POST"); toast("已撤回"); refreshHistory(); }
        catch (err) { toast("撤回失败：" + err.message, "err"); }
      };
      act.appendChild(rv);
    }
    const again = el("button", "again", "↻"); again.title = "作为新消息再发一次";
    again.onclick = async (e) => {
      e.stopPropagation();
      try { await api("/messages", "POST", { text: m.text, final: true, sfx: S.sfx, targets: targetsNow() }); toast("已重新发送"); refreshHistory(); }
      catch (err) { toast("发送失败：" + err.message, "err"); }
    };
    act.appendChild(again);
    li.appendChild(act);
    if (editable(m, items)) { li.title = "点一下编辑这条"; li.onclick = () => startEdit(m); }
    else li.classList.add("ro");
    ul.appendChild(li);
  }
}
$("clearHist").onclick = async () => {
  if (!confirm("清空服务端的消息历史？（不影响显示屏和游戏）")) return;
  try { await api("/messages", "DELETE"); refreshHistory(); } catch (e) { toast("失败：" + e.message, "err"); }
};

// ---------------------------------------------------------------- Klaude display: settings
const COLOR_NAMES = ["黑", "白", "浅灰", "深灰", "橙", "红", "黄", "绿", "青", "蓝", "紫", "粉", "棕", "深蓝", "深绿", "米色"];
const SEGS = [
  ["screen", "屏幕尺寸", { "208x80": "208×80 超宽", "176x96": "176×96 宽", "160x112": "160×112", "128x128": "128×128 方",
                         "112x144": "112×144 竖", "96x176": "96×176 长竖" }],
  ["layout", "布局", { chat: "聊天记录", single: "单条大字" }],
  ["scale", "字号", { 1: "标准", 2: "大字" }],
  ["long", "太长时", { left: "向左跑马灯", up: "向上滚动", cut: "截断" }, "single"],
  ["speed", "跑马灯速度", { slow: "慢", normal: "中", fast: "快" }, "single"],
];
const CHIPS = [["clock", "时钟"], ["date", "日期"], ["show_time", "消息时间"], ["divider", "分隔线"], ["highlight", "最新一条高亮"],
               ["invert", "反色"], ["image_full", "图片全屏"]];
const COLORS = [["color", "文字"], ["alt", "交替"], ["accent", "最新"], ["meta", "时间/草稿"]];

async function loadKd() {
  try { S.kd = await api("/kd/settings"); renderSettings(); }
  catch (e) { $("settings").textContent = "显示屏不可用：" + e.message; }
}

async function setKd(part) {
  const before = { ...S.kd.settings };
  Object.assign(S.kd.settings, part); renderSettings();            // optimistic
  try { S.kd.settings = (await api("/kd/settings", "PUT", part)).settings; renderSettings(); refreshKd(true); }
  catch (e) { S.kd.settings = before; renderSettings(); toast("设置失败：" + e.message, "err"); }
}

function renderSettings() {
  const box = $("settings"), s = S.kd.settings, ch = S.kd.choices || {};
  box.innerHTML = "";
  const set = el("div", "set"); box.appendChild(set);
  set.appendChild(el("h3", null, "显示"));
  for (const [key, label, names, only] of SEGS) {
    if (!(key in s)) continue;
    const row = el("div", "opt" + (only && s.layout !== only ? " off" : "")); row.appendChild(el("span", null, label));
    if (only && s.layout !== only) row.title = "只在“单条大字”布局里生效";
    const seg = el("div", "seg");
    for (const v of ch[key] || Object.keys(names)) {
      const b = el("button", String(s[key]) === String(v) ? "on" : null, names[v] || v);
      b.onclick = () => setKd({ [key]: key === "scale" ? Number(v) : v });
      seg.appendChild(b);
    }
    row.appendChild(seg); set.appendChild(row);
  }
  if ("size" in s) {                       // the device's width in VRChat (register size; was the menu's radial)
    const row = el("div", "opt"); row.appendChild(el("span", null, "大小"));
    const wrap = el("div", "range");
    const r = el("input"); r.type = "range"; r.min = "0.20"; r.max = "0.60"; r.step = "0.01"; r.value = s.size;
    const out = el("em", null, Math.round(s.size * 100) + " cm");
    r.oninput = () => { out.textContent = Math.round(r.value * 100) + " cm"; };
    r.onchange = () => setKd({ size: Number(r.value) });
    wrap.appendChild(r); wrap.appendChild(out); row.appendChild(wrap); set.appendChild(row);
  }
  set.appendChild(el("h3", null, "开关"));
  const chips = el("div", "chips");
  for (const [key, label] of CHIPS) {
    if (!(key in s)) continue;
    const b = el("button", "chip" + (s[key] ? " on" : ""), label);
    b.onclick = () => setKd({ [key]: !s[key] });
    chips.appendChild(b);
  }
  set.appendChild(chips);
  set.appendChild(el("h3", null, "颜色"));
  for (const [key, label] of COLORS) {
    if (!(key in s)) continue;
    const row = el("div", "opt"); row.appendChild(el("span", null, label));
    const sw = el("div", "swatches");
    if (key === "alt") {                                           // alternating colour: can be off
      const off = el("button", s.alt === 0 ? "on" : null, "关");
      off.style.cssText = "width:auto;padding:0 7px;background:transparent;color:var(--dim);font-size:12px";
      off.onclick = () => setKd({ alt: 0 }); sw.appendChild(off);
    }
    for (let i = 1; i <= 14; i++) {
      const b = el("button", s[key] === i ? "on" : null);
      b.style.background = S.palette[i] || "#888"; b.title = COLOR_NAMES[i];
      b.onclick = () => setKd({ [key]: i });
      sw.appendChild(b);
    }
    sw.appendChild(el("em", null, s[key] ? COLOR_NAMES[s[key]] : "关"));
    row.appendChild(sw); set.appendChild(row);
  }
  if (key_in(s, "image_fit")) {
    set.appendChild(el("h3", null, "图片"));
    const row = el("div", "opt"); row.appendChild(el("span", null, "图片"));
    const seg = el("div", "seg");
    for (const [v, n] of [["cover", "填满（裁切）"], ["contain", "完整显示"]]) {
      const b = el("button", s.image_fit === v ? "on" : null, n);
      b.onclick = () => setKd({ image_fit: v }); seg.appendChild(b);
    }
    row.appendChild(seg); set.appendChild(row);
    if ("image_screen" in s) {
      const r2 = el("div", "opt"); r2.appendChild(el("span", null, "屏幕"));
      const g2 = el("div", "seg");
      for (const [v, n] of [["auto", "按图片比例自动换尺寸"], ["keep", "保持当前尺寸"]]) {
        const b = el("button", s.image_screen === v ? "on" : null, n);
        b.onclick = () => setKd({ image_screen: v }); g2.appendChild(b);
      }
      r2.appendChild(g2); set.appendChild(r2);
    }
    if ("image_res" in s) {
      const r3 = el("div", "opt"); r3.appendChild(el("span", null, "清晰度"));
      const g3 = el("div", "seg");
      for (const [v, n] of [["high", "高（清楚，约 70 秒）"], ["low", "低（快，约 20 秒）"]]) {
        const b = el("button", s.image_res === v ? "on" : null, n);
        b.onclick = () => setKd({ image_res: v }); g3.appendChild(b);
      }
      r3.appendChild(g3); set.appendChild(r3);
    }
  }
}
const key_in = (o, k) => o && k in o;

// ---------------------------------------------------------------- Klaude display: status, preview, actions
async function refreshKd(force) {
  if (!S.out.kd || (document.hidden && !force)) return;
  try {
    const s = await api("/kd/status");
    if (!S.palette.length && s.palette) { S.palette = s.palette; if (S.kd) renderSettings(); }
    if (s.width && (!S.dims || S.dims[0] !== s.width || S.dims[1] !== s.height)) {
      S.dims = [s.width, s.height];
      const k = Math.min(352 / s.width, 240 / s.height);
      $("prev").style.width = Math.round(s.width * k) + "px"; $("prev").style.height = Math.round(s.height * k) + "px";
      $("prev").style.aspectRatio = `${s.width} / ${s.height}`;
    }
    $("led").className = s.synced ? "ok" : "";
    $("kdStat").innerHTML = (s.synced ? "<strong>已同步</strong>" : `<strong>同步中</strong> · 还有 ${s.pending_pages} 页，约 ${Math.ceil(s.eta_s)} 秒`)
      + ` · ${s.width}×${s.height} · ${s.messages} 条消息${s.image ? " · 正在显示图片" : ""}`;
    $("closeImg").hidden = !s.image;
    if (s.image !== S.image) {                                     // a picture appeared / closed
      S.image = s.image;
      if (!S.toManual || !s.image) { S.to.kd = !s.image; S.toManual = false; paintTargets(); }
      if (s.image && S.out.chatbox) toast("显示屏正在显示图片：消息先只发游戏聊天框（点 🖥 也发到显示屏）");
    }
    $("prev").src = "/api/v1/kd/preview.png?t=" + Date.now();
  } catch (e) { $("kdStat").textContent = "显示屏不可用：" + e.message; }
}

$("chime").onclick = async () => { try { await api("/kd/chime", "POST"); toast("🔔"); } catch (e) { toast("失败：" + e.message, "err"); } };
$("kdClear").onclick = async () => { try { await api("/kd/clear", "POST"); toast("已清屏"); refreshKd(true); } catch (e) { toast("失败：" + e.message, "err"); } };
$("closeImg").onclick = async () => { try { await api("/kd/image", "DELETE"); refreshKd(true); } catch (e) { toast("失败：" + e.message, "err"); } };

async function sendImage(file) {
  if (!file || !file.type.startsWith("image/")) return;
  if (!S.out.kd) { toast("图片只能显示在 Klaude 显示屏上：先打开它", "err"); return; }
  toast("图片处理中…");
  try { const r = await api("/kd/image", "POST", undefined, file); toast(`图片已显示，约 ${Math.round(r.eta_s)} 秒传完`); refreshKd(true); }
  catch (e) { toast("图片失败：" + e.message, "err"); }
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
async function health() {
  const c = $("conn");
  try {
    const h = await api("/health");
    c.className = "conn ok"; c.querySelector("span").textContent = h.status === "ok" || h.ok ? "在线" : "在线";
  } catch { c.className = "conn bad"; c.querySelector("span").textContent = "离线"; }
}

// ---------------------------------------------------------------- phones: keyboard and the fixed composer
// Android Chrome shrinks the page for the keyboard (viewport interactive-widget=resizes-content); iOS Safari and older
// browsers do not: there the visual viewport tells how much of the window the keyboard covers, and the composer moves up.
function layoutViewport() {
  const vv = window.visualViewport;
  const kb = vv ? Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop)) : 0;
  document.documentElement.style.setProperty("--kb", kb + "px");
  const open = kb > 60 || (document.activeElement === text && matchMedia("(max-width: 720px)").matches
                           && vv && vv.height < screen.height * 0.6);
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
  .observe(document.querySelector(".composer"));

// ---------------------------------------------------------------- start
(async () => {
  updateCount();
  layoutViewport();
  if (matchMedia("(max-width: 720px)").matches) {          // phones: settings folded, a short placeholder
    $("settingsFold").open = false;
    text.placeholder = "说点什么…";
  }
  await setOutputs(null);
  refreshHistory(); health();
  setInterval(() => refreshKd(false), 1000);
  setInterval(health, 10000);
  setInterval(refreshHistory, 15000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { refreshKd(true); refreshHistory(); } });
  if (!matchMedia("(max-width: 720px)").matches) text.focus();      // (phones: no keyboard popping up on load)
})();
