import type {
  FilesResponse,
  ForecastAlert,
  MasterEvent,
  Metrics,
  RunStatus,
} from "./types";

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => getJSON<{ ok: boolean; version: string }>("/api/health"),
  runStatus: () => getJSON<RunStatus>("/api/run-status"),
  metrics: () => getJSON<Metrics>("/api/metrics"),
  catalogue: () =>
    getJSON<{ master: MasterEvent[]; sxr: unknown[]; hxr: unknown[] }>("/api/catalogue"),
  alerts: () => getJSON<{ alerts: ForecastAlert[] }>("/api/alerts"),
  files: () => getJSON<FilesResponse>("/api/files"),

  async summary(): Promise<string> {
    const res = await fetch("/api/summary");
    if (!res.ok) throw new Error("No pipeline summary yet");
    return res.text();
  },

  async run(source: "real" | "synthetic"): Promise<void> {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source }),
    });
    if (!res.ok) {
      const detail = (await res.json().catch(() => ({}))).detail ?? res.statusText;
      throw new Error(detail);
    }
  },

  async upload(payload: "solexs" | "hel1os", file: File): Promise<void> {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`/api/upload/${payload}`, { method: "POST", body: form });
    if (!res.ok) {
      const detail = (await res.json().catch(() => ({}))).detail ?? res.statusText;
      throw new Error(detail);
    }
  },
};

export function liveSocketUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/live`;
}
