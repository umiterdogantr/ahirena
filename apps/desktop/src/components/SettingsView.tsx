import { useState } from "react";
import { api, errorText } from "../api";
import type { AppSettings, Health, ModelInfo, Theme } from "../types";
import ModelPicker from "./ModelPicker";

const RUNTIME_STATE: Record<NonNullable<Health["ollama_runtime"]>["state"], string> = {
  pending: "bekliyor",
  starting: "başlatılıyor…",
  managed: "Ahirena tarafından başlatıldı",
  external: "Ahirena dışında çalışan sunucu kullanılıyor",
  unavailable: "ulaşılamıyor",
  error: "başlatılamadı",
};

interface Props {
  settings: AppSettings;
  models: ModelInfo[];
  health: Health | null;
  onSaved: (s: AppSettings) => void;
}

export default function SettingsView({ settings, models, health, onSaved }: Props) {
  const [draft, setDraft] = useState<AppSettings>(settings);
  const [state, setState] = useState<{ saving: boolean; message: string | null; error: string | null }>({ saving: false, message: null, error: null });

  const save = async () => {
    setState({ saving: true, message: null, error: null });
    try {
      const s = await api<AppSettings>("PATCH", "/api/settings", draft);
      onSaved(s);
      setDraft(s);
      setState({ saving: false, message: "Kaydedildi.", error: null });
    } catch (e) {
      setState({ saving: false, message: null, error: errorText(e) });
    }
  };

  return (
    <section className="page settings">
      <header className="page-header">
        <h2>Ayarlar</h2>
      </header>

      <label>
        Varsayılan model
        <ModelPicker models={models} value={draft.default_model} onChange={(v) => setDraft({ ...draft, default_model: v || null })} />
      </label>

      <label>
        Sistem talimatı
        <textarea rows={5} value={draft.system_prompt} onChange={(e) => setDraft({ ...draft, system_prompt: e.target.value })} />
      </label>

      <label>
        Bağlam sınırı (token)
        <input
          type="number"
          min={1024}
          max={262144}
          step={1024}
          value={draft.context_length}
          onChange={(e) => setDraft({ ...draft, context_length: Number(e.target.value) })}
        />
        <span className="muted small">Büyük değer daha fazla ekran kartı belleği kullanır; 4 GB VRAM için 4096–8192 önerilir.</span>
      </label>

      <label>
        Tema
        <select value={draft.theme} onChange={(e) => setDraft({ ...draft, theme: e.target.value as Theme })}>
          <option value="system">Sistem</option>
          <option value="light">Açık</option>
          <option value="dark">Koyu</option>
        </select>
      </label>

      <div className="row">
        <button className="primary" onClick={save} disabled={state.saving}>
          {state.saving ? "Kaydediliyor…" : "Kaydet"}
        </button>
        {state.message && <span className="ok">{state.message}</span>}
        {state.error && <span className="error-inline">{state.error}</span>}
      </div>

      <h3>Gizlilik ve konum</h3>
      {health ? (
        <ul className="facts">
          <li>Model konumu: yalnızca yerel ({health.providers.map((p) => `${p.provider_id} ${p.version ?? ""}`).join(", ")})</li>
          <li>Uzak model sağlayıcıları: {health.privacy.remote_providers_enabled ? "etkin" : "kapalı"}</li>
          <li>
            Ollama bulut özellikleri:{" "}
            {health.privacy.ollama_cloud_disabled === true
              ? "kapalı (Ahirena sunucuyu OLLAMA_NO_CLOUD=1 ile başlattı)"
              : "bilinmiyor — sunucu Ahirena dışında başlatılmış"}
          </li>
          <li>Konuşmaların saklandığı yer: yerel SQLite — {health.data_dir}</li>
          <li className="muted small">Bunlar uygulama ayarlarıdır; işletim sistemi düzeyinde ağ engeli değildir.</li>
        </ul>
      ) : (
        <p className="muted">Durum bilgisi alınamadı.</p>
      )}

      {health?.ollama_runtime && (
        <>
          <h3>Ollama sunucusu</h3>
          <ul className="facts">
            <li>Durum: {RUNTIME_STATE[health.ollama_runtime.state]}</li>
            <li>Adres: {health.ollama_runtime.url}</li>
            <li>GPU arka ucu: {health.ollama_runtime.backend === "vulkan" ? "Vulkan" : "otomatik (Ollama seçer)"}</li>
            <li>Model klasörü: {health.ollama_runtime.models_dir ?? "Ollama varsayılanı"}</li>
            {health.ollama_runtime.log && <li>Günlük: {health.ollama_runtime.log}</li>}
            {health.ollama_runtime.error && <li className="error-inline">{health.ollama_runtime.error}</li>}
            <li className="muted small">Bu ayarlar {health.config_path} dosyasındadır; değişiklik uygulama yeniden açılınca geçerli olur.</li>
          </ul>
        </>
      )}
    </section>
  );
}
