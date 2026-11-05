import type { Health, LoadedModel } from "../types";

interface Props {
  health: Health | null;
  error: string | null;
  loaded: LoadedModel[];
  running: boolean;
}

export default function StatusBar({ health, error, loaded, running }: Props) {
  const ollama = health?.providers.find((p) => p.provider_id === "ollama");
  const runtime = health?.ollama_runtime;
  const starting = !ollama?.ok && (runtime?.state === "starting" || runtime?.state === "pending");
  return (
    <footer className="statusbar">
      <span className={error ? "dot bad" : "dot ok"}>Çekirdek {error ? "yanıt vermiyor" : health ? `v${health.core.version}` : "…"}</span>
      <span className={ollama?.ok ? "dot ok" : starting ? "dot" : "dot bad"} title={runtime?.error ?? ollama?.error ?? undefined}>
        Ollama {ollama?.ok ? `${ollama.version}${runtime?.backend === "vulkan" ? " · Vulkan" : ""}` : starting ? "başlatılıyor…" : "çalışmıyor"}
      </span>
      <span>Model konumu: yerel</span>
      <span>Uzak sağlayıcı: {health?.privacy.remote_providers_enabled ? "açık" : "kapalı"}</span>
      <span>
        {loaded.length
          ? loaded.map((m) => `${m.model_id} (${m.gpu_percent >= 100 ? "GPU" : m.gpu_percent <= 0 ? "CPU" : `%${m.gpu_percent} GPU`})`).join(", ")
          : "Bellekte model yok"}
      </span>
      <span className="grow" />
      <span>{running ? "Yanıt üretiliyor…" : "Hazır"}</span>
    </footer>
  );
}
