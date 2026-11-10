import { useState } from "react";
import { api, errorText } from "../api";
import type { Health, LoadedModel } from "../types";

interface Props {
  health: Health | null;
  error: string | null;
  loaded: LoadedModel[];
  running: boolean;
}

export default function StatusBar({ health, error, loaded, running }: Props) {
  const [cancelNote, setCancelNote] = useState<string | null>(null);
  const ollama = health?.providers.find((p) => p.provider_id === "ollama");
  const runtime = health?.ollama_runtime;
  const starting = !ollama?.ok && (runtime?.state === "starting" || runtime?.state === "pending");
  const active = health?.active_runs?.length ?? 0;
  return (
    <footer className="statusbar">
      <span className={error ? "dot bad" : "dot ok"}>Çekirdek {error ? "yanıt vermiyor" : health ? `v${health.core.version}` : "…"}</span>
      <span className={ollama?.ok ? "dot ok" : starting ? "dot" : "dot bad"} title={runtime?.error ?? ollama?.error ?? undefined}>
        Ollama {ollama?.ok ? `${ollama.version}${runtime?.backend === "vulkan" ? " · Vulkan" : ""}` : starting ? "başlatılıyor…" : "çalışmıyor"}
      </span>
      <span>Model konumu: yerel</span>
      <span>Uzak sağlayıcı: {health?.privacy.remote_providers_enabled ? "açık" : "kapalı"}</span>
      <span title={health?.network?.tor_socks}>
        Ağ politikası: {health?.network?.offline ? "kapalı" : "açık"}
      </span>
      <span className={health?.disk && !health.disk.ok ? "dot bad" : undefined} title={health?.disk?.path}>
        Disk: {health?.disk ? `${health.disk.free_mib} MiB boş` : "…"}
      </span>
      <span
        className={health?.tasks && health.tasks.attention > 0 ? "dot bad" : undefined}
        title="İşçi yalnızca çekirdek açıkken çalışır"
      >
        Görev:{" "}
        {health?.tasks
          ? `${health.tasks.queued} kuyruk · ${health.tasks.running} çalışıyor · ${health.tasks.waiting_approval} onay · ${health.tasks.needs_reconciliation} uzlaştırma`
          : "…"}
      </span>
      <span>
        {loaded.length
          ? loaded.map((m) => `${m.model_id} (${m.gpu_percent >= 100 ? "GPU" : m.gpu_percent <= 0 ? "CPU" : `%${m.gpu_percent} GPU`})`).join(", ")
          : "Bellekte model yok"}
      </span>
      <span className="grow" />
      {active > 0 && (
        <button
          type="button"
          className="linkish"
          onClick={async () => {
            try {
              const r = await api<{ count: number }>("POST", "/api/runs/cancel-all");
              setCancelNote(`${r.count} çalışma durduruldu`);
            } catch (e) {
              setCancelNote(errorText(e));
            }
          }}
        >
          Tümünü durdur ({active})
        </button>
      )}
      {cancelNote && <span className="muted small">{cancelNote}</span>}
      <span>
        {running
          ? `Yanıt üretiliyor…${active ? ` (${active})` : ""}`
          : "Hazır"}
      </span>
    </footer>
  );
}
