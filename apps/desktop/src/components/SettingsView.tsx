import { useEffect, useState } from "react";
import { api, errorText, pickFile, pickFolder, revealPath } from "../api";
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
  const [lastPath, setLastPath] = useState<string | null>(null);
  const [media, setMedia] = useState<Record<string, { available?: boolean; status?: string; note?: string }> | null>(null);
  const [offline, setOffline] = useState(false);
  const [torSocks, setTorSocks] = useState("127.0.0.1:9050");
  const [torListening, setTorListening] = useState(false);
  const [diag, setDiag] = useState<Record<string, unknown> | null>(null);
  const [pendingRestore, setPendingRestore] = useState<{ source_db?: string; note?: string; error?: string } | null>(null);

  const reloadPending = () =>
    api<{ pending: { source_db?: string; note?: string; error?: string } | null }>("GET", "/api/backup/pending")
      .then((r) => setPendingRestore(r.pending))
      .catch(() => undefined);

  useEffect(() => {
    api<Record<string, { available?: boolean; status?: string; note?: string }>>("GET", "/api/media")
      .then(setMedia)
      .catch(() => undefined);
    api<{ offline: boolean; tor_socks: string; tor_listening: boolean }>("GET", "/api/network")
      .then((n) => {
        setOffline(n.offline);
        setTorSocks(n.tor_socks);
        setTorListening(n.tor_listening);
      })
      .catch(() => undefined);
    reloadPending();
  }, []);

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
      {health && (
        <p className="muted small">
          Ahirena çekirdek v{health.core.version} · veri {health.data_dir}
        </p>
      )}

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

      <h3>Ağ politikası</h3>
      <p className="muted small">
        OS duvarı değildir. Tor SOCKS {torListening ? "açık" : "yok"}. Görevler ekranından da değiştirilebilir.
      </p>
      <label className="check">
        <input type="checkbox" checked={offline} onChange={(e) => setOffline(e.target.checked)} /> Ağ politikası kapalı
      </label>
      <label>
        Tor SOCKS
        <input value={torSocks} onChange={(e) => setTorSocks(e.target.value)} />
      </label>
      <div className="row">
        <button
          onClick={async () => {
            setState({ saving: true, message: null, error: null });
            try {
              const n = await api<{ offline: boolean; tor_socks: string; tor_listening: boolean }>("PUT", "/api/network", {
                offline,
                tor_socks: torSocks,
              });
              setOffline(n.offline);
              setTorSocks(n.tor_socks);
              setTorListening(n.tor_listening);
              setState({ saving: false, message: "Ağ ayarı kaydedildi.", error: null });
            } catch (e) {
              setState({ saving: false, message: null, error: errorText(e) });
            }
          }}
        >
          Ağ ayarını kaydet
        </button>
        <button
          onClick={async () => {
            try {
              const r = await api<{ note: string; tor_listening: boolean }>("POST", "/api/network/tor-probe");
              setTorListening(r.tor_listening);
              setState({ saving: false, message: r.note, error: null });
            } catch (e) {
              setState({ saving: false, message: null, error: errorText(e) });
            }
          }}
        >
          Tor SOCKS denetle
        </button>
      </div>

      <h3>Yedek ve dışa aktarım</h3>
      <p className="muted small">
        Sırlar ve model ağırlıkları pakete girmez. Geri yükleme canlı DB açıkken uygulanmaz; sonraki açılışta mevcut
        veritabanı önce backups/pre-restore-* altına kopyalanır.
      </p>
      <div className="row">
        <button
          onClick={async () => {
            setState({ saving: true, message: null, error: null });
            try {
              const r = await api<{ path: string }>("POST", "/api/backup");
              setLastPath(r.path);
              setState({ saving: false, message: `Yedek: ${r.path}`, error: null });
            } catch (e) {
              setState({ saving: false, message: null, error: errorText(e) });
            }
          }}
        >
          SQLite yedeği al
        </button>
        <button
          onClick={async () => {
            setState({ saving: true, message: null, error: null });
            try {
              const r = await api<{ path: string }>("POST", "/api/export");
              setLastPath(r.path);
              setState({ saving: false, message: `Dışa aktarım: ${r.path}`, error: null });
            } catch (e) {
              setState({ saving: false, message: null, error: errorText(e) });
            }
          }}
        >
          Kişisel veriyi dışa aktar
        </button>
        <button
          type="button"
          onClick={async () => {
            try {
              const folder = await pickFolder("Yedek klasörü seçin");
              const file = folder ? null : await pickFile("ahirena.db seçin", ["db"]);
              const path = folder || file;
              if (!path) return;
              setState({ saving: true, message: null, error: null });
              const r = await api<{ note: string; source_db: string }>("POST", "/api/backup/restore", {
                path,
                confirm: true,
              });
              setState({
                saving: false,
                message: `${r.note} Kaynak: ${r.source_db}. Uygulamayı kapatıp yeniden açın.`,
                error: null,
              });
              await reloadPending();
            } catch (e) {
              setState({ saving: false, message: null, error: errorText(e) });
            }
          }}
        >
          Yedekten geri yükle…
        </button>
        {lastPath && (
          <button
            onClick={() =>
              revealPath(lastPath).catch((e) => setState((s) => ({ ...s, error: errorText(e) })))
            }
          >
            Son dosyayı klasörde aç
          </button>
        )}
      </div>
      {pendingRestore && (
        <div className="row">
          <p className="muted small">
            Bekleyen geri yükleme: {pendingRestore.source_db ?? pendingRestore.error ?? "—"}
            {pendingRestore.note ? ` — ${pendingRestore.note}` : ""}
          </p>
          <button
            type="button"
            onClick={async () => {
              try {
                const r = await api<{ note: string }>("DELETE", "/api/backup/pending");
                setState({ saving: false, message: r.note, error: null });
                await reloadPending();
              } catch (e) {
                setState({ saving: false, message: null, error: errorText(e) });
              }
            }}
          >
            Bekleyen geri yüklemeyi iptal et
          </button>
        </div>
      )}

      {media && (
        <>
          <h3>Medya durumu</h3>
          <ul className="facts">
            {Object.entries(media).map(([k, v]) => (
              <li key={k}>
                {k}: {v.status ?? (v.available ? "açık" : "kapalı")}
                {v.note ? ` — ${v.note}` : ""}
              </li>
            ))}
          </ul>
        </>
      )}

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
          {health.disk && (
            <li>
              Veri diski boş alan: {health.disk.free_mib} MiB {health.disk.ok ? "" : "(yedek/aktarım reddedilir)"}
            </li>
          )}
          <li className="muted small">Bunlar uygulama ayarlarıdır; işletim sistemi düzeyinde ağ engeli değildir.</li>
        </ul>
      ) : (
        <p className="muted">Durum bilgisi alınamadı.</p>
      )}
      {health && (
        <div className="row">
          <button type="button" onClick={() => revealPath(health.data_dir).catch((e) => setState((s) => ({ ...s, error: errorText(e) })))}>
            Veri klasörünü aç
          </button>
          <button
            type="button"
            onClick={() => revealPath(`${health.data_dir}\\logs`).catch((e) => setState((s) => ({ ...s, error: errorText(e) })))}
          >
            Günlük klasörünü aç
          </button>
          <button
            type="button"
            onClick={() => revealPath(health.config_path).catch((e) => setState((s) => ({ ...s, error: errorText(e) })))}
          >
            config.json konumunu aç
          </button>
        </div>
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

      <h3>Dürüst durum özeti</h3>
      <p className="muted small">Sahte yeşil ışık yok; planlanan özellik planlandı görünür.</p>
      <div className="row">
        <button
          type="button"
          onClick={async () => {
            try {
              setDiag(await api("GET", "/api/diagnostics"));
              setState((s) => ({ ...s, error: null }));
            } catch (e) {
              setState((s) => ({ ...s, error: errorText(e) }));
            }
          }}
        >
          Özeti yenile
        </button>
        <button
          type="button"
          onClick={async () => {
            try {
              const r = await api<{ path: string; diagnostics: Record<string, unknown> }>("POST", "/api/diagnostics/save");
              setDiag(r.diagnostics);
              setLastPath(r.path);
              setState({ saving: false, message: `Tanılama kaydedildi: ${r.path}`, error: null });
            } catch (e) {
              setState((s) => ({ ...s, error: errorText(e) }));
            }
          }}
        >
          Özeti dosyaya kaydet
        </button>
      </div>
      {diag && (
        <ul className="facts">
          <li>Yerel öncelik: {String(diag.local_first)} · uzak sağlayıcı: {String(diag.remote_providers)}</li>
          <li>
            Medya — OCR: {String((diag.media as { ocr?: string })?.ocr)} · ses çıkış:{" "}
            {String((diag.media as { speech_output?: string })?.speech_output)} · ekran izleme:{" "}
            {String((diag.media as { screen_watch?: string })?.screen_watch)}
          </li>
          <li>
            Eğitim: {String((diag.training as { status?: string })?.status)} · çalıştırıcı{" "}
            {String((diag.training as { runner?: string })?.runner)}
          </li>
          <li>
            Ağ OS duvarı: {String((diag.network as { os_firewall?: boolean })?.os_firewall)} · Tor dinliyor:{" "}
            {String((diag.network as { tor_listening?: boolean })?.tor_listening)}
          </li>
          <li>
            Betik: {String(diag.scripts)} · tarayıcı oturumu: {String(diag.browser_sessions)} · açılış hizmeti:{" "}
            {String((diag.tasks as { os_autostart?: boolean })?.os_autostart)}
          </li>
        </ul>
      )}
    </section>
  );
}
