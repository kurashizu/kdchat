// The console's state: outputs, the current message, history, the Klaude display, translation, server settings.
// Components read the reactive fields and call the methods; every change goes through the REST API.
import { toast } from "svelte-sonner";
import { api, store, ApiError } from "./api";
import { decodePicture, isPicture } from "./decode";
import { t } from "./i18n.svelte";

export type Target = "chatbox" | "kd";

export interface Message {
  id: number;
  text: string;
  output: string;
  created_at: string;
  edited: boolean;
  reverted: boolean;
  kd_id: number | null;
  final: boolean;
  targets: Target[];
  source_lang: string | null;
  translations: Record<string, string>;
}

export interface Language {
  code: string;
  name: string;
  native: string;
  state: "ready" | "absent" | "downloading" | "error";
  size?: number;
  done?: number;
  total?: number;
  error?: string;
}

export interface TrSettings {
  enabled: boolean;
  source: string;
  latin: string;
  targets: string[];
  chatbox: number;
  kd: boolean;
  small: string[];
}

export interface KdStatus {
  active: boolean;
  pending_pages: number;
  eta_s: number;
  synced: boolean;
  messages: number;
  image: boolean;
  images: string[];
  wings: string[];
  lowres: boolean;
  palette: string[];
  width: number;
  height: number;
}

// the current message: a new one (from its first keystroke on, one id for its whole life with live typing on), or a
// sent one being edited. Where a new one goes is fixed when it starts.
interface Current {
  id: number | null;
  mode: "new" | "edit";
  original: string;
  targets: Target[];
  lastSent: string;
}

// a picture -> the display's raw format: "KDRGB1", width, height (u16, big endian), RGB bytes. The browser decodes it
// (upright by its EXIF orientation), scales it to at most 512 px and puts transparency on black: the server needs no
// image library.
async function toRawRGB(file: Blob): Promise<Blob> {
  const bmp = await decodePicture(file);
  const k = Math.min(1, 512 / Math.max(bmp.width, bmp.height));
  const w = Math.max(1, Math.round(bmp.width * k)), h = Math.max(1, Math.round(bmp.height * k));
  const cv = document.createElement("canvas");
  cv.width = w;
  cv.height = h;
  const g = cv.getContext("2d")!;
  g.fillStyle = "#000";
  g.fillRect(0, 0, w, h);
  g.imageSmoothingQuality = "high";
  g.drawImage(bmp, 0, 0, w, h);
  bmp.close();
  const rgba = g.getImageData(0, 0, w, h).data;
  const out = new Uint8Array(10 + w * h * 3);
  out.set([0x4b, 0x44, 0x52, 0x47, 0x42, 0x31, w >> 8, w & 255, h >> 8, h & 255]); // "KDRGB1"
  for (let i = 0, j = 10; i < rgba.length; i += 4, j += 3) {
    out[j] = rgba[i];
    out[j + 1] = rgba[i + 1];
    out[j + 2] = rgba[i + 2];
  }
  return new Blob([out], { type: "application/octet-stream" });
}

const failed = (e: unknown) => toast.error(t("common.failed", { msg: (e as Error).message }));

class App {
  // outputs (both can be on)
  out = $state({ chatbox: true, kd: false });
  kdAvailable = $state(true);
  conn = $state<"connecting" | "ok" | "warn" | "bad">("connecting");

  // sending preferences (this browser)
  sfx = $state(store.get("sfx", true));
  typingHint = $state(store.get("typingHint", true));
  live = $state(store.get("live", true));
  enterSends = $state(store.get("enterSends", true));
  sendTo = $state<Target[]>(store.get("sendTo", ["chatbox", "kd"]));

  // the composer
  text = $state("");
  cur = $state<Current | null>(null);
  busy = $state(0);
  typingOn = $state(false);

  history = $state<Message[]>([]);

  kd = $state<{ settings: Record<string, any>; choices: Record<string, any[]> } | null>(null);
  kdStat = $state<KdStatus | null>(null);
  kdError = $state<string | null>(null);
  previewUrl = $state("");

  tr = $state<{ settings: TrSettings; languages: Language[]; small_ok: string[] } | null>(null);

  cfg = $state<any>(null);

  // the settings dialog (open + tab), opened from anywhere
  settingsOpen = $state(false);
  settingsTab = $state("general");

  private syncTimer: ReturnType<typeof setTimeout> | undefined;
  private chain: Promise<unknown> = Promise.resolve();
  private trPoll: ReturnType<typeof setTimeout> | undefined;

  // ------------------------------------------------------------ derived
  get both() {
    return this.out.chatbox && this.out.kd;
  }

  // where a message that starts now goes: the picked targets among the outputs that are on (never none)
  targetsNow(): Target[] {
    const on = (["chatbox", "kd"] as Target[]).filter((k) => this.out[k]);
    const tg = on.filter((k) => this.sendTo.includes(k));
    return tg.length ? tg : on;
  }

  get curTargets(): Target[] {
    return this.cur ? this.cur.targets : this.targetsNow();
  }

  get limits() {
    const chat = this.curTargets.includes("chatbox");
    return { chars: chat ? 144 : 400, lines: chat ? 9 : 20 };
  }

  get over() {
    const v = this.text;
    return v.length > this.limits.chars || v.split("\n").length > this.limits.lines;
  }

  openSettings(tab = "general") {
    this.settingsTab = tab;
    this.settingsOpen = true;
    this.loadSettings();
    this.loadTr();
  }

  // ------------------------------------------------------------ preferences
  setPref(key: "sfx" | "typingHint" | "live" | "enterSends", v: boolean) {
    this[key] = v;
    store.set(key, v);
    if (key === "typingHint" && !v) this.typing(false);
    if (key === "live") {
      toast(t(v ? "toast.liveOn" : "toast.liveOff"));
      if (v && this.cur && this.text.trim()) this.queue(() => this.syncLive());
    }
  }

  setSendTo(v: Target[]) {
    if (!v.length) return; // never none
    this.sendTo = v;
    store.set("sendTo", v);
  }

  // ------------------------------------------------------------ outputs + connection
  async loadOutputs(part?: Partial<Record<Target, boolean>>) {
    try {
      const r = part ? await api("/outputs", "PUT", part) : await api("/outputs");
      this.out = { chatbox: r.chatbox, kd: r.kd };
      this.kdAvailable = !!r.kd_available;
    } catch (e) {
      toast.error(t("out.failed", { msg: (e as Error).message }));
    }
    if (this.out.kd) {
      if (!this.kd) await this.loadKd();
      this.refreshKd(true);
    }
  }

  async setOutput(k: Target, on: boolean) {
    await this.loadOutputs({ [k]: on });
    if (this.out[k] === on) toast(t(on ? "out.on" : "out.off", { name: t(k === "kd" ? "out.kd" : "out.chatbox") }));
  }

  async health() {
    try {
      const h = await api("/health");
      this.conn = h.ok === false ? "warn" : "ok";
    } catch {
      this.conn = "bad";
    }
  }

  // ------------------------------------------------------------ the current message
  queue(fn: () => Promise<unknown>) {
    this.chain = this.chain.then(fn).catch(failed);
    return this.chain;
  }

  private typingRenew: ReturnType<typeof setInterval> | undefined;

  async typing(on: boolean) {
    on = on && this.typingHint;
    if (this.typingOn === on) return;
    this.typingOn = on;
    // the server turns it off after 15 s without news (a closed page never leaves it on): renew while typing
    clearInterval(this.typingRenew);
    if (on) this.typingRenew = setInterval(() => this.sendTyping(true), 5000);
    await this.sendTyping(on);
  }

  private async sendTyping(on: boolean) {
    try {
      await api("/typing", "PUT", { typing: on, targets: this.curTargets });
    } catch {
      /* best effort */
    }
  }

  // the page goes away: the indicator off at once (keepalive: the request outlives the page)
  leaving() {
    if (!this.typingOn) return;
    clearInterval(this.typingRenew);
    fetch("/api/v1/typing", { method: "PUT", keepalive: true, headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ typing: false }) }).catch(() => {});
  }

  onInput() {
    const v = this.text;
    if (!this.cur && v.trim()) this.cur = { id: null, mode: "new", original: "", targets: this.targetsNow(), lastSent: "" };
    if (this.cur && this.cur.mode === "new" && !v.trim()) {
      this.cancel(true); // emptied: give the new one up
      return;
    }
    if (this.cur && this.cur.mode === "new") this.typing(!!v.trim());
    this.syncSoon();
  }

  // live typing: show the current text soon (after a change of where it goes, too)
  syncSoon(delay = 450) {
    if (!this.live || !this.cur) return;
    clearTimeout(this.syncTimer);
    this.syncTimer = setTimeout(() => this.queue(() => this.syncLive()), delay);
  }

  private async syncLive() {
    const c = this.cur, v = this.text;
    if (!c || !v.trim() || this.over || v === c.lastSent) return;
    if (c.id == null) {
      const m = await api("/messages", "POST", { text: v, final: false, sfx: this.sfx, targets: c.targets });
      c.id = m.id;
      this.refreshHistory();
    } else {
      await api(`/messages/${c.id}`, "PATCH", { text: v, final: false });
    }
    c.lastSent = v;
  }

  async commit() {
    const v = this.text;
    if (!v.trim() || this.over) return;
    clearTimeout(this.syncTimer);
    const c: Current = this.cur ?? { id: null, mode: "new", original: "", targets: this.targetsNow(), lastSent: "" };
    this.cur = null;
    this.text = "";
    this.typing(false);
    this.busy++;
    await this.queue(async () => {
      if (c.id == null) await api("/messages", "POST", { text: v, final: true, sfx: this.sfx, targets: c.targets });
      else await api(`/messages/${c.id}`, "PATCH", { text: v, final: true });
      toast.success(t(c.mode === "edit" ? "toast.edited" : "toast.sent"));
    });
    this.busy--;
    this.refreshHistory();
  }

  async cancel(keepText = false) {
    clearTimeout(this.syncTimer);
    const c = this.cur;
    this.cur = null;
    if (!keepText || (c && c.mode === "edit")) this.text = "";
    this.typing(false);
    if (!c) return;
    await this.queue(async () => {
      if (c.mode === "new" && c.id != null) await api(`/messages/${c.id}`, "DELETE");
      if (c.mode === "edit" && c.lastSent !== c.original)
        await api(`/messages/${c.id}`, "PATCH", { text: c.original, cancel: true });
    });
    this.refreshHistory();
  }

  focusComposer: (() => void) | null = null;   // (set by the composer)

  startEdit(m: Message) {
    const c = this.cur;
    // another message is being typed / changed: finish it first; an edit with nothing changed yet just switches
    const untouched = c && c.mode === "edit" && this.text === c.original && c.lastSent === c.original;
    if (c && this.text.trim() && !(c.mode === "edit" && c.id === m.id) && !untouched) {
      toast.error(t("toast.finishFirst"));
      return false;
    }
    this.cur = { id: m.id, mode: "edit", original: m.text, targets: m.targets || [], lastSent: m.text };
    this.text = m.text;
    setTimeout(() => this.focusComposer?.(), 0);   // (after the click: the list keeps the focus otherwise)
    return true;
  }

  async fillKeyboard() {
    const v = this.text;
    if (!v.trim()) return;
    try {
      await api("/messages", "POST", { text: v, immediate: false, targets: ["chatbox"] });
      toast(t("composer.kbFillDone"));
    } catch (e) {
      failed(e);
    }
  }

  // ------------------------------------------------------------ history
  async refreshHistory() {
    try {
      this.history = (await api("/messages?limit=30")).items || [];
    } catch {
      /* keep the last list */
    }
  }

  editable(m: Message) {
    return !m.reverted && m.final !== false &&
      (m.kd_id != null || this.history.find((x) => (x.targets || []).includes("chatbox")) === m);
  }

  async revert(m: Message) {
    try {
      await api(`/messages/${m.id}/revert`, "POST");
      toast(t("hist.revertedToast"));
      this.refreshHistory();
    } catch (e) {
      failed(e);
    }
  }

  async again(m: Message) {
    try {
      await api("/messages", "POST", { text: m.text, final: true, sfx: this.sfx, targets: this.targetsNow() });
      toast.success(t("hist.resent"));
      this.refreshHistory();
    } catch (e) {
      failed(e);
    }
  }

  async clearHistory() {
    try {
      await api("/messages", "DELETE");
      this.refreshHistory();
    } catch (e) {
      failed(e);
    }
  }

  // ------------------------------------------------------------ Klaude display
  async loadKd() {
    try {
      this.kd = await api("/kd/settings");
      this.kdError = null;
    } catch (e) {
      this.kdError = (e as Error).message;
    }
  }

  async setKd(part: Record<string, unknown>) {
    if (!this.kd) return;
    const before = { ...this.kd.settings };
    Object.assign(this.kd.settings, part); // optimistic
    try {
      this.kd.settings = (await api("/kd/settings", "PUT", part)).settings;
      this.refreshKd(true);
    } catch (e) {
      this.kd.settings = before;
      toast.error(t("kd.setFailed", { msg: (e as Error).message }));
    }
  }

  async refreshKd(force = false) {
    if (!this.out.kd || (document.hidden && !force)) return;
    try {
      this.kdStat = await api("/kd/status");
      this.kdError = null;
      this.previewUrl = "/api/v1/kd/preview.png?t=" + Date.now();
    } catch (e) {
      this.kdError = (e as Error).message;
    }
  }

  async kdAction(path: string, okKey?: "kd.chimed" | "kd.cleared", method = "POST") {
    try {
      await api(path, method);
      if (okKey) toast(t(okKey));
      this.refreshKd(true);
    } catch (e) {
      failed(e);
    }
  }

  async sendImage(file: File | null | undefined) {
    if (!file || !isPicture(file)) return;
    if (!this.out.kd) {
      toast.error(t("kd.needKd"));
      return;
    }
    const id = toast.loading(t("kd.imgWorking"));
    try {
      const raw = await toRawRGB(file);
      const r = await api("/kd/image", "POST", undefined, raw);
      toast.success(t("kd.imgShown", { s: Math.round(r.eta_s) }), { id });
      this.refreshKd(true);
    } catch (e) {
      toast.error(t("kd.imgFailed", { msg: (e as Error).message }), { id });
    }
  }

  // ------------------------------------------------------------ translation
  async loadTr() {
    try {
      this.tr = await api("/translate");
    } catch (e) {
      toast.error(t("tr.failed", { msg: (e as Error).message }));
    }
    clearTimeout(this.trPoll);
    if (this.tr?.languages.some((l) => l.state === "downloading")) this.trPoll = setTimeout(() => this.loadTr(), 1000);
  }

  async setTr(part: Partial<TrSettings>) {
    if (!this.tr) return;
    const before = { ...this.tr.settings };
    Object.assign(this.tr.settings, part);
    try {
      this.tr.settings = (await api("/translate", "PUT", part)).settings;
      this.refreshKd(true);
    } catch (e) {
      this.tr.settings = before;
      toast.error(t("tr.failed", { msg: (e as Error).message }));
    }
  }

  lang(code: string): Language | undefined {
    return this.tr?.languages.find((l) => l.code === code);
  }

  langName(code: string) {
    const l = this.lang(code);
    return l ? l.native : code;
  }

  async download(code: string) {
    try {
      await api("/translate/models/" + code, "POST");
      toast(t("tr.downloadStarted", { name: this.langName(code) }));
      this.loadTr();
    } catch (e) {
      failed(e);
    }
  }

  async deleteModel(code: string) {
    try {
      await api("/translate/models/" + code, "DELETE");
      this.loadTr();
    } catch (e) {
      failed(e);
    }
  }

  // ------------------------------------------------------------ server settings
  async loadSettings() {
    try {
      this.cfg = await api("/settings");
    } catch {
      /* the dialog shows what it has */
    }
  }

  async put(path: string, body: unknown, method = "PUT") {
    return api(path, method, body);
  }
}

export const app = new App();
export { ApiError };
