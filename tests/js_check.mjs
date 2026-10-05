// JS sanity check (plain node, no packages): syntax of ui/*.js, both languages have the same keys, every key the
// UI uses exists, and placeholders match. Run: node tests/js_check.mjs
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import vm from "node:vm";

const ui = new URL("../ui/", import.meta.url);
const read = (f) => readFileSync(new URL(f, ui), "utf8");
let bad = 0;
const fail = (m) => { console.error("FAIL", m); bad++; };

for (const f of ["i18n.js", "app.js"]) {
  try { execFileSync(process.execPath, ["--check", new URL(f, ui).pathname], { stdio: "pipe" }); }
  catch (e) { fail(`${f}: ${e.stderr}`); }
}

const ctx = {};
vm.runInNewContext(read("i18n.js") + "\nthis.I18N = I18N; this.t = t; this.setLang = (l) => { LANG = l; };", ctx);
const { I18N } = ctx;
const en = Object.keys(I18N.en), zh = Object.keys(I18N.zh);
for (const k of en) if (!(k in I18N.zh)) fail(`zh is missing "${k}"`);
for (const k of zh) if (!(k in I18N.en)) fail(`en is missing "${k}"`);
for (const k of en) {
  const vars = (s) => JSON.stringify((String(s).match(/\{\w+\}/g) || []).sort());
  if (vars(I18N.en[k]) !== vars(I18N.zh[k])) fail(`placeholders differ in "${k}"`);
}

const used = new Set();
const js = read("app.js"), html = read("index.html");
for (const m of js.matchAll(/\bt\(\s*"([\w.]+)"/g)) used.add(m[1]);
for (const m of html.matchAll(/data-i18n(?:-\w+)?="([\w.]+)"/g)) used.add(m[1]);
for (const k of used) if (!k.endsWith(".") && !(k in I18N.en)) fail(`used but not defined: "${k}"`);
// keys built at run time (prefix + value) are checked by pattern
for (const p of ["osc.src.", "chip.", "color.", "screen.", "layout.", "scale.", "long.", "speed."])
  if (!en.some((k) => k.startsWith(p))) fail(`no keys for ${p}*`);

ctx.setLang("zh");
if (vm.runInNewContext('t("composer.count", {n: 1, max: 2, l: 3, maxl: 4})', ctx) !== "1 / 2 · 3 / 4 行") fail("t() vars");
if (vm.runInNewContext('t("no.such.key")', ctx) !== "no.such.key") fail("t() fallback");

console.log(bad ? `${bad} problem(s)` : `ok: ${en.length} keys x 2 languages, ${used.size} used statically`);
process.exit(bad ? 1 : 0);
