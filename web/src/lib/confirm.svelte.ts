// A confirmation dialog (instead of the browser's confirm()): await ask({title, desc, action}) -> true / false.
// remember: a key; the dialog offers "Don't ask again" and, once that was ticked and confirmed, ask() answers true
// at once (this browser; Settings > General resets it).
import { store } from "./api";

export const confirmState = $state({
  open: false,
  title: "",
  desc: "",
  action: "",
  destructive: true,
  remember: null as string | null,
  dontAsk: false,
  resolve: null as null | ((ok: boolean) => void),
});

export const skipped = $state({ keys: store.get<string[]>("skipConfirm", []) });

export function ask(o: { title: string; desc: string; action: string; destructive?: boolean; remember?: string }): Promise<boolean> {
  if (o.remember && skipped.keys.includes(o.remember)) return Promise.resolve(true);
  return new Promise((resolve) => {
    Object.assign(confirmState, {
      ...o, destructive: o.destructive ?? true, remember: o.remember ?? null, dontAsk: false, open: true, resolve,
    });
  });
}

export function confirmed() {
  const k = confirmState.remember;
  if (k && confirmState.dontAsk && !skipped.keys.includes(k)) {
    skipped.keys = [...skipped.keys, k];
    store.set("skipConfirm", skipped.keys);
  }
}

export function resetSkipped() {
  skipped.keys = [];
  store.set("skipConfirm", []);
}
