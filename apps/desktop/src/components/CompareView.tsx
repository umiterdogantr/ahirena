import { useEffect, useRef, useState } from "react";
import { cancelRun, errorText, stream } from "../api";
import { metricsLine } from "../format";
import type { AppSettings, Metrics, MessageStatus, ModelInfo } from "../types";
import Markdown from "./Markdown";

interface Props {
  models: ModelInfo[];
  settings: AppSettings;
  onRunning: (running: boolean) => void;
}

interface Column {
  model_id: string;
  content: string;
  status: MessageStatus | "waiting";
  error: string | null;
  metrics: Metrics | null;
}

/** Aynı soruyu seçilen modellere sırayla sorar. Sonuçlar kaydedilmez. */
export default function CompareView({ models, settings, onRunning }: Props) {
  const [prompt, setPrompt] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [columns, setColumns] = useState<Column[]>([]);
  const [running, setRunning] = useState(false);
  const [stopping, setStopping] = useState(false);
  const runId = useRef<string | null>(null);
  const stopAll = useRef(false);

  useEffect(() => onRunning(running), [running, onRunning]);

  const toggle = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  const patch = (i: number, fn: (c: Column) => Column) => setColumns((cs) => cs.map((c, j) => (j === i ? fn(c) : c)));

  const start = async () => {
    if (!prompt.trim() || selected.length === 0) return;
    stopAll.current = false;
    setStopping(false);
    setRunning(true);
    const order = models.map((m) => m.model_id).filter((id) => selected.includes(id));
    setColumns(order.map((model_id) => ({ model_id, content: "", status: "waiting", error: null, metrics: null })));
    for (let i = 0; i < order.length; i++) {
      if (stopAll.current) {
        patch(i, (c) => ({ ...c, status: "cancelled" }));
        continue;
      }
      patch(i, (c) => ({ ...c, status: "streaming" }));
      try {
        await stream("/api/compare", { prompt, model_id: order[i], provider_id: "ollama", think: false }, (e) => {
          if (e.event === "run") runId.current = e.data.run_id;
          if (e.event === "token") patch(i, (c) => ({ ...c, content: c.content + e.data.delta }));
          if (e.event === "done") patch(i, (c) => ({ ...c, status: e.data.status, error: e.data.error, metrics: e.data.metrics }));
          if (e.event === "transport_error") patch(i, (c) => ({ ...c, status: "error", error: e.data.message }));
        });
      } catch (e) {
        patch(i, (c) => ({ ...c, status: "error", error: errorText(e) }));
      }
      runId.current = null;
    }
    setRunning(false);
  };

  const stop = () => {
    stopAll.current = true;
    setStopping(true);
    if (runId.current) cancelRun(runId.current).catch(() => undefined);
  };

  return (
    <section className="page compare">
      <header className="page-header">
        <h2>Model karşılaştırma</h2>
      </header>
      <p className="muted small">
        Aynı soru seçilen modellere sırayla sorulur; modeller aynı anda belleğe yüklenmez. Sonuçlar kaydedilmez. Sistem talimatı ve bağlam sınırı ({settings.context_length}) ayarlardan gelir.
      </p>
      <div className="model-checks">
        {models.map((m) => (
          <label key={m.model_id} className="check">
            <input type="checkbox" checked={selected.includes(m.model_id)} onChange={() => toggle(m.model_id)} disabled={running} /> {m.model_id}
          </label>
        ))}
      </div>
      <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={4} placeholder="Tüm modellere sorulacak soru" disabled={running} />
      <div className="row">
        {running ? (
          <button className="danger" onClick={stop} disabled={stopping}>
            {stopping ? "Durduruluyor…" : "Durdur"}
          </button>
        ) : (
          <button className="primary" onClick={start} disabled={!prompt.trim() || selected.length === 0}>
            Karşılaştır
          </button>
        )}
      </div>
      <div className="columns">
        {columns.map((c) => (
          <div key={c.model_id} className="column">
            <h4>{c.model_id}</h4>
            {c.status === "waiting" && <p className="muted">Sırada</p>}
            {c.status === "streaming" && !c.content && <p className="muted">Model hazırlanıyor…</p>}
            {c.content && <Markdown text={c.content} />}
            {c.status === "cancelled" && <div className="badge">Durduruldu</div>}
            {c.error && <div className="error-inline">{c.error}</div>}
            {c.metrics && <footer className="msg-meta">{metricsLine(c.metrics)}</footer>}
          </div>
        ))}
      </div>
    </section>
  );
}
