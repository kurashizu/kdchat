# kdchat console (web/)

The browser console of kdchat: a static [SvelteKit](https://svelte.dev/docs/kit) app with
[shadcn-svelte](https://shadcn-svelte.com/) components and [Lucide](https://lucide.dev/) icons. `npm run build` writes
it to `../ui`, which is committed: the Python server (`app.py`) serves it, so neither the server nor the Windows `.exe`
needs Node.

```bash
npm ci
npm run build        # -> ../ui (the same sources always give the same files; CI checks ui/ is up to date)
npm run dev          # live development against a kdchat on 127.0.0.1:5599 (/api is forwarded there)
npm run check        # types
```

- `src/lib/app.svelte.ts`: the state and every API call; `src/lib/i18n.svelte.ts`: all text (`en`, `zh`).
- `src/lib/components/`: the screens; `src/lib/components/ui/`: shadcn-svelte components (added with
  `npx shadcn-svelte@latest add <name>`).
- `src/lib/decode.ts`: pictures of any common format (HEIC / TIFF decoders load on demand), sent as raw RGB.
- No emoji in the UI: icons are SVG.
