import { useCallback, useEffect, useState } from "react";
import { api, errorText, revealPath } from "../api";

interface Artifact {
  id: string;
  kind: string;
  title: string;
  path: string;
  byte_size: number;
  content_hash: string;
  version: number;
  exists: boolean;
  created_at: string;
  task_id: string | null;
}

export default function OutputsView() {
  const [items, setItems] = useState<Artifact[]>([]);
  const [previewText, setPreviewText] = useState<string | null>(null);
  const [versions, setVersions] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setItems(await api<Artifact[]>("GET", "/api/artifacts"));
  }, []);

  useEffect(() => {
    reload().catch((e) => setError(errorText(e)));
  }, [reload]);

  return (
    <section className="page">
      <header className="page-header">
        <h2>Çıktılar</h2>
      </header>
      <p className="muted">
        Yalnızca gerçekten üretilmiş dosyalar listelenir. Diskte olmayan kayıt için indirme üretilmez.
      </p>
      <button onClick={() => reload().catch((e) => setError(errorText(e)))}>Yenile</button>
      {items.length === 0 && <p className="muted">Henüz çıktı yok. Yedek, dışa aktarım veya onaylı dosya yazımı burada görünür.</p>}
      {items.map((a) => (
        <article key={a.id} className="facts">
          <h3>
            {a.title} · v{a.version} {a.exists ? "" : "· dosya yok"}
          </h3>
          <p className="muted small">
            {a.kind} · {a.byte_size} bayt · özet {a.content_hash.slice(0, 12)}
            <br />
            {a.path}
          </p>
          <div className="row">
            <button
              disabled={!a.exists}
              onClick={async () => {
                try {
                  const r = await api<{ preview: string; preview_truncated: boolean }>("GET", `/api/artifacts/${a.id}/preview`);
                  setPreviewText(r.preview + (r.preview_truncated ? "\n…" : ""));
                  setVersions(null);
                  setError(null);
                } catch (e) {
                  setError(errorText(e));
                }
              }}
            >
              Önizle
            </button>
            <button
              onClick={async () => {
                try {
                  const r = await api<{ versions: { version: number; content_hash: string; byte_size: number }[] }>(
                    "GET",
                    `/api/artifacts/${a.id}/versions`,
                  );
                  setVersions(r.versions.map((v) => `v${v.version} · ${v.byte_size} bayt · ${v.content_hash.slice(0, 12)}`).join("\n"));
                  setPreviewText(null);
                  setError(null);
                } catch (e) {
                  setError(errorText(e));
                }
              }}
            >
              Sürümler
            </button>
            <button
              disabled={!a.exists}
              onClick={() => revealPath(a.path).catch((e) => setError(errorText(e)))}
            >
              Klasörde aç
            </button>
          </div>
        </article>
      ))}
      {previewText && <pre className="facts">{previewText}</pre>}
      {versions && <pre className="facts">{versions}</pre>}
      {error && <p className="error-inline">{error}</p>}
    </section>
  );
}
