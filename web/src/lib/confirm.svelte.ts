// A confirmation dialog (instead of the browser's confirm()): await ask({title, desc, action}) -> true / false.
export const confirmState = $state({
  open: false,
  title: "",
  desc: "",
  action: "",
  destructive: true,
  resolve: null as null | ((ok: boolean) => void),
});

export function ask(o: { title: string; desc: string; action: string; destructive?: boolean }): Promise<boolean> {
  return new Promise((resolve) => {
    Object.assign(confirmState, { ...o, destructive: o.destructive ?? true, open: true, resolve });
  });
}
