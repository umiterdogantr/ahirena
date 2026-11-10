import { useCallback, useEffect, useState } from "react";
import { api, errorText, pickFolder } from "../api";

interface Task {
  id: string;
  title: string;
  kind: string;
  state: string;
  route: string;
  last_error: string | null;
  schedule_at: string | null;
  interval_seconds: number | null;
  approvals?: { id: string; decision: string; target_summary: string }[];
  steps?: { id: string; tool: string; state: string; result?: unknown }[];
}

interface Net {
  offline: boolean;
  tor_listening: boolean;
  tor_socks: string;
  worker: string;
  os_autostart: boolean;
  browser_sessions: string;
  note: string;
}

export default function TasksView() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [net, setNet] = useState<Net | null>(null);
  const [kind, setKind] = useState("clock.now");
  const [url, setUrl] = useState("");
  const [hosts, setHosts] = useState("");
  const [root, setRoot] = useState("");
  const [relative, setRelative] = useState("");
  const [content, setContent] = useState("");
  const [route, setRoute] = useState("direct");
  const [scheduleAt, setScheduleAt] = useState("");
  const [intervalSec, setIntervalSec] = useState("");
  const [missedPolicy, setMissedPolicy] = useState("skip");
  const [offline, setOffline] = useState(false);
  const [torSocks, setTorSocks] = useState("127.0.0.1:9050");
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const q = filter ? `?state=${encodeURIComponent(filter)}` : "";
    setTasks(await api<Task[]>("GET", `/api/tasks${q}`));
    const n = await api<Net>("GET", "/api/network");
    setNet(n);
    setOffline(n.offline);
    setTorSocks(n.tor_socks);
  }, [filter]);

  useEffect(() => {
    reload().catch((e) => setError(errorText(e)));
  }, [reload]);

  const create = async () => {
    setError(null);
    const body: Record<string, unknown> = { kind, title: kind, route };
    if (scheduleAt.trim()) body.schedule_at = new Date(scheduleAt).toISOString();
    if (intervalSec.trim()) body.interval_seconds = Number(intervalSec);
    body.missed_policy = missedPolicy;
    if (kind === "web.fetch") {
      body.params = { url };
      body.grant = { hosts: hosts.split(/[,\s]+/).filter(Boolean) };
    }
    if (kind === "files.write") {
      body.params = { relative, content };
      body.grant = { roots: [root] };
    }
    try {
      await api("POST", "/api/tasks", body);
      await reload();
    } catch (e) {
      setError(errorText(e));
    }
  };

  const act = async (path: string, payload?: unknown) => {
    setError(null);
    setNote(null);
    try {
      const out = await api("POST", path, payload ?? {});
      if (path.endsWith("/replay")) setNote(JSON.stringify(out, null, 2));
      await reload();
    } catch (e) {
      setError(errorText(e));
    }
  };

  return (
    <section className="page">
      <header className="page-header">
        <h2>Görevler</h2>
      </header>
      <p className="muted">
        Zamanlanmış iş yalnızca çekirdek açıkken yürür; Windows açılış hizmeti kurulmaz. Yazma onay ister. Kesinti sonrası
        dış işlem otomatik tekrarlanmaz. Tarayıcı oturumu bu sürümde kapalıdır.
      </p>
      {net && (
        <p className="muted small">
          İşçi: {net.worker} · Tor SOCKS {net.tor_listening ? "açık" : "yok"} · tarayıcı {net.browser_sessions} · açılış hizmeti yok
        </p>
      )}
      <h3>Ağ politikası</h3>
      <label className="check">
        <input type="checkbox" checked={offline} onChange={(e) => setOffline(e.target.checked)} /> Ağ politikası kapalı (web görevleri reddedilir; OS duvarı değildir)
      </label>
      <label>
        Tor SOCKS
        <input value={torSocks} onChange={(e) => setTorSocks(e.target.value)} />
      </label>
      <div className="row">
        <button
          onClick={async () => {
            try {
              setNet(await api<Net>("PUT", "/api/network", { offline, tor_socks: torSocks }));
              setNote("Ağ ayarı kaydedildi.");
              setError(null);
            } catch (e) {
              setError(errorText(e));
            }
          }}
        >
          Ağ ayarını kaydet
        </button>
        <button
          onClick={async () => {
            try {
              const r = await api<{ ok: boolean; note: string; tor_listening: boolean; external_fetch: boolean }>(
                "POST",
                "/api/network/tor-probe",
              );
              setNote(r.note);
              setNet((n) => (n ? { ...n, tor_listening: r.tor_listening } : n));
              setError(null);
            } catch (e) {
              setError(errorText(e));
            }
          }}
        >
          Tor SOCKS denetle
        </button>
      </div>
      <label>
        Tür
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="clock.now">Saat (onaysız)</option>
          <option value="web.fetch">Web oku</option>
          <option value="files.write">Dosya yaz (onaylı)</option>
        </select>
      </label>
      <label>
        Rota
        <select value={route} onChange={(e) => setRoute(e.target.value)}>
          <option value="direct">Doğrudan</option>
          <option value="tor">Tor (yoksa başarısız)</option>
        </select>
      </label>
      {kind === "web.fetch" && (
        <>
          <label>
            URL
            <input value={url} onChange={(e) => setUrl(e.target.value)} />
          </label>
          <label>
            İzinli alan adları
            <input value={hosts} onChange={(e) => setHosts(e.target.value)} placeholder="example.com" />
          </label>
        </>
      )}
      {kind === "files.write" && (
        <>
          <label>
            Kök klasör
            <input value={root} onChange={(e) => setRoot(e.target.value)} />
            <button
              type="button"
              onClick={async () => {
                try {
                  const p = await pickFolder("Yazma kök klasörü");
                  if (p) setRoot(p);
                } catch (e) {
                  setError(errorText(e));
                }
              }}
            >
              Klasör seç…
            </button>
          </label>
          <label>
            Göreli dosya
            <input value={relative} onChange={(e) => setRelative(e.target.value)} />
          </label>
          <label>
            İçerik
            <textarea rows={3} value={content} onChange={(e) => setContent(e.target.value)} />
          </label>
        </>
      )}
      <label>
        Zaman (yerel, boşsa hemen)
        <input type="datetime-local" value={scheduleAt} onChange={(e) => setScheduleAt(e.target.value)} />
      </label>
      <label>
        Tekrar (saniye, boşsa tek sefer)
        <input type="number" min={30} value={intervalSec} onChange={(e) => setIntervalSec(e.target.value)} placeholder="örn. 3600" />
      </label>
      <label>
        Kaçırılan zaman
        <select value={missedPolicy} onChange={(e) => setMissedPolicy(e.target.value)}>
          <option value="skip">Atla (uyku/kapalıyken kaçanı çalıştırma)</option>
          <option value="run_once">Bir kez çalıştır (çekirdek açılınca)</option>
        </select>
      </label>
      <button className="primary" onClick={create}>
        Görevi kaydet
      </button>
      <div className="row">
        <label>
          Durum filtresi
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">Tümü</option>
            <option value="queued">Kuyruk</option>
            <option value="running">Çalışıyor</option>
            <option value="waiting_approval">Onay bekliyor</option>
            <option value="needs_reconciliation">Uzlaştırma</option>
            <option value="succeeded">Bitti</option>
            <option value="failed">Hata</option>
            <option value="cancelled">İptal</option>
          </select>
        </label>
        <button
          type="button"
          onClick={async () => {
            try {
              const r = await api<{ count: number }>("POST", "/api/tasks/purge-terminal");
              setNote(`${r.count} kapalı görev silindi.`);
              setError(null);
              await reload();
            } catch (e) {
              setError(errorText(e));
            }
          }}
        >
          Kapalıları temizle
        </button>
      </div>
      {tasks.length === 0 && <p className="muted">Bu filtrede görev yok.</p>}
      {tasks.map((t) => (
        <article key={t.id} className="facts">
          <h3>
            {t.title} · {t.state}
          </h3>
          <p className="muted small">
            {t.kind} · rota {t.route}
            {t.schedule_at ? ` · zaman ${t.schedule_at}` : ""}
            {t.interval_seconds ? ` · tekrar ${t.interval_seconds}s` : ""}
          </p>
          {t.last_error && <p className="error-inline">{t.last_error}</p>}
          <div className="row">
            {t.state === "queued" && <button onClick={() => act(`/api/tasks/${t.id}/run`)}>Çalıştır</button>}
            {t.state === "waiting_approval" && t.approvals?.filter((a) => a.decision === "pending").map((a) => (
              <span key={a.id} className="row">
                <button className="primary" onClick={() => act(`/api/tasks/${t.id}/approve`, { approval_id: a.id })}>
                  Onayla
                </button>
                <button onClick={() => act(`/api/tasks/${t.id}/deny`, { approval_id: a.id })}>Reddet</button>
              </span>
            ))}
            {t.state === "needs_reconciliation" && (
              <>
                <button onClick={() => act(`/api/tasks/${t.id}/reconcile`, { decision: "verified" })}>Gerçekleşti say</button>
                <button onClick={() => act(`/api/tasks/${t.id}/reconcile`, { decision: "retry" })}>Yeniden dene</button>
                <button onClick={() => act(`/api/tasks/${t.id}/reconcile`, { decision: "cancel" })}>İptal</button>
              </>
            )}
            {t.state !== "succeeded" && t.state !== "cancelled" && t.state !== "failed" && (
              <button onClick={() => act(`/api/tasks/${t.id}/cancel`)}>Durdur</button>
            )}
            <button onClick={() => act(`/api/tasks/${t.id}/branch`, { title: `${t.title} · dal` })}>Dal aç</button>
            {(t.steps?.length ?? 0) > 0 && (
              <button onClick={() => act(`/api/tasks/${t.id}/replay`)}>Çevrimdışı oynat</button>
            )}
            {(t.state === "succeeded" || t.state === "failed" || t.state === "cancelled") && (
              <button
                type="button"
                onClick={async () => {
                  try {
                    await api("DELETE", `/api/tasks/${t.id}`);
                    setError(null);
                    await reload();
                  } catch (e) {
                    setError(errorText(e));
                  }
                }}
              >
                Sil
              </button>
            )}
          </div>
        </article>
      ))}
      {note && <pre className="facts">{note}</pre>}
      {error && <p className="error-inline">{error}</p>}
    </section>
  );
}
