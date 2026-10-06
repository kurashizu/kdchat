// REST client for /api/v1 (the browser re-sends the Basic Auth login / the desktop app's session cookie by itself).

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function api<T = any>(path: string, method = "GET", body?: unknown, raw?: Blob): Promise<T> {
  const opt: RequestInit = { method, headers: {} };
  if (raw) {
    opt.body = raw;
    (opt.headers as Record<string, string>)["Content-Type"] = raw.type || "application/octet-stream";
  } else if (body !== undefined) {
    opt.body = JSON.stringify(body);
    (opt.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const r = await fetch("/api/v1" + path, opt);
  if (!r.ok) {
    let msg: unknown = String(r.status);
    try {
      const j = await r.json();
      msg = j.detail ?? msg;
    } catch {
      /* not JSON */
    }
    if (Array.isArray(msg)) msg = msg.map((d: any) => d.msg || JSON.stringify(d)).join("; "); // (validation errors)
    throw new ApiError(typeof msg === "string" ? msg : JSON.stringify(msg), r.status);
  }
  return (r.status === 204 ? null : await r.json()) as T;
}

// small persistent preferences of this browser (kdchat.* keys; vcb.* = the name before 1.3.0)
export const store = {
  get<T>(k: string, d: T): T {
    try {
      const v = localStorage.getItem("kdchat." + k) ?? localStorage.getItem("vcb." + k);
      return v == null ? d : (JSON.parse(v) as T);
    } catch {
      return d;
    }
  },
  set(k: string, v: unknown) {
    try {
      localStorage.setItem("kdchat." + k, JSON.stringify(v));
    } catch {
      /* private mode */
    }
  },
};
