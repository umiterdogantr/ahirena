import { Channel, invoke } from "@tauri-apps/api/core";
import type { CoreStatus, StreamEvent } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

interface RawResponse {
  status: number;
  body: unknown;
}

function detail(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => (x && typeof x === "object" && "msg" in x ? String(x.msg) : String(x))).join("; ");
  }
  return `İstek başarısız (HTTP ${status})`;
}

export async function api<T>(method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE", path: string, body?: unknown): Promise<T> {
  const res = await invoke<RawResponse>("api", { method, path, body: body ?? null });
  if (res.status >= 400) throw new ApiError(res.status, detail(res.body, res.status));
  return res.body as T;
}

export function coreStatus(): Promise<CoreStatus> {
  return invoke<CoreStatus>("core_status");
}

/** Sunucudan SSE akışını Rust üzerinden alır; gizli anahtar arayüze hiç gelmez. */
export async function stream(path: string, body: unknown, onEvent: (e: StreamEvent) => void): Promise<void> {
  const channel = new Channel<StreamEvent>();
  channel.onmessage = onEvent;
  await invoke("api_stream", { path, body, onEvent: channel });
}

export function cancelRun(runId: string): Promise<{ cancelled: boolean }> {
  return api("POST", `/api/runs/${encodeURIComponent(runId)}/cancel`);
}

export function errorText(e: unknown): string {
  if (e instanceof Error) return e.message;
  return String(e);
}
