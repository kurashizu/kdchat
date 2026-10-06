import adapter from "@sveltejs/adapter-static";
import { sveltekit } from "@sveltejs/kit/vite";
import tailwindcss from "@tailwindcss/vite";
import { readFileSync } from "node:fs";
import { defineConfig } from "vite";

// the app version from ../version.py (not a build time stamp): the same sources always build the same files
const VERSION = /__version__\s*=\s*"([^"]+)"/.exec(readFileSync("../version.py", "utf8"))![1];

// The console is a static SvelteKit app (one page, rendered in the browser): `npm run build` writes it to ../ui, which
// the Python server (app.py) serves together with the REST API. No Node at run time.
export default defineConfig({
  plugins: [
    tailwindcss(),
    sveltekit({
      adapter: adapter({ pages: "../ui", assets: "../ui", precompress: false, strict: true }),
      alias: { $lib: "./src/lib" }, // (shadcn-svelte components import $lib/...)
      output: { bundleStrategy: "single" },
      version: { name: VERSION, pollInterval: 0 },
      // (/favicon.ico, /docs, /api: served by the Python side, not part of the static build)
      prerender: { handleHttpError: "warn", crawl: false, entries: ["/"] },
    }),
  ],
  build: { assetsInlineLimit: 100000 },
  server: { proxy: { "/api": "http://127.0.0.1:5599" } }, // npm run dev against a local kdchat
});
