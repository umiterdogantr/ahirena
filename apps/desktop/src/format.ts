import type { Metrics } from "./types";

export function bytes(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(0)} MB`;
  return `${(n / 1024).toFixed(0)} KB`;
}

export function ms(n: number | null | undefined): string {
  if (n == null) return "—";
  return n >= 1000 ? `${(n / 1000).toFixed(1)} sn` : `${Math.round(n)} ms`;
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" });
}

export function shortDigest(d: string | null | undefined): string {
  if (!d) return "—";
  return d.replace(/^sha256:/, "").slice(0, 12);
}

export function metricsLine(m: Metrics | null | undefined): string {
  if (!m) return "";
  const parts: string[] = [];
  if (m.ttft_ms != null) parts.push(`ilk token ${ms(m.ttft_ms)}`);
  if (m.tokens_per_s != null) parts.push(`${m.tokens_per_s.toFixed(1)} token/sn`);
  if (m.output_tokens != null) parts.push(`${m.output_tokens} token`);
  if (m.load_ms) parts.push(`yükleme ${ms(m.load_ms)}`);
  if (m.gpu_percent != null) parts.push(m.gpu_percent >= 100 ? "tamamen GPU" : m.gpu_percent <= 0 ? "tamamen CPU" : `%${m.gpu_percent} GPU`);
  if (m.cancel_latency_ms != null) parts.push(`durdurma ${ms(m.cancel_latency_ms)}`);
  return parts.join(" · ");
}
