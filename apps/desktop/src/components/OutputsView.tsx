import { useCallback, useEffect, useState } from "react";
import { api, copyText, errorText, revealPath } from "../api";

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
  const [kind, setKind] = useState("");
  const [previewText, setPreviewText] = useState<string | null>(null);
  const [versions, setVersions] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const q = kind ? `?kind=${encodeURIComponent(kind)}` : "";
    setItems(await api<Artifact[]>("GET", `/api/artifacts${q}`));
  }, [kind]);

  useEffect(() => {
    reload().catch((e) => setError(errorText(e)));
  }, [reload]);

  return (
    <section className="page">
      <header className="page-header">
        <h2>Çıktılar</h2>
      </header>
      <p className="muted">
        Yalnızca gerçekten üretilmiş dosyalar listelenir. Diskte olmayan kayıt için indirme üretilmez. Listeden
        çıkarmak dosyayı silmez; dosya silme açıkça istenmelidir.
      </p>
      <div className="row">
        <button onClick={() => reload().catch((e) => setError(errorText(e)))}>Yenile</button>
        <label>
          Tür
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">Tümü</option>
            <option value="backup">Yedek</option>
            <option value="export">Dışa aktarım</option>
            <option value="file_write">Dosya yazımı</option>
          </select>
        </label>
      </div>
      {items.length === 0 && <p className="muted">Bu filtrede çıktı yok.</p>}
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
            <button disabled={!a.exists} onClick={() => revealPath(a.path).catch((e) => setError(errorText(e)))}>
              Klasörde aç
            </button>
            <button
              type="button"
              onClick={async () => {
                try {
                  await copyText(a.path);
                  setNote("Yol panoya kopyalandı.");
                  setError(null);
                } catch (e) {
                  setError(errorText(e));
                }
              }}
            >
              Yolu kopyala
            </button>
            <button
              type="button"
              onClick={async () => {
                try {
                  const r = await api<{ note: string }>("DELETE", `/api/artifacts/${a.id}`, { delete_file: false });
                  setNote(r.note);
                  setPreviewText(null);
                  setVersions(null);
                  setError(null);
                  await reload();
                } catch (e) {
                  setError(errorText(e));
                }
              }}
            >
              Listeden çıkar
            </button>
            <button
              type="button"
              disabled={!a.exists}
              title="Yalnızca uygulama veri klasöründeki dosya silinir"
              onClick={async () => {
                try {
                  const r = await api<{ note: string; file_deleted: boolean }>("DELETE", `/api/artifacts/${a.id}`, {
                    delete_file: true,
                  });
                  setNote(r.note);
                  setPreviewText(null);
                  setVersions(null);
                  setError(null);
                  await reload();
                } catch (e) {
                  setError(errorText(e));
                }
              }}
            >
              Dosyayı da sil
            </button>
          </div>
        </article>
      ))}
      {note && <p className="muted">{note}</p>}
      {previewText && <pre className="facts">{previewText}</pre>}
      {versions && <pre className="facts">{versions}</pre>}
      {error && <p className="error-inline">{error}</p>}
    </section>
  );
}
