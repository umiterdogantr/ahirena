import { useCallback, useEffect, useState } from "react";
import { api, errorText, pickFile, revealPath } from "../api";

interface Workspace {
  id: string;
  name: string;
}

interface DocumentRow {
  id: string;
  title: string;
  path: string;
  version: number;
  content_hash: string;
  index_version: string;
  vector: string;
  index_state?: string;
  index_error?: string | null;
}

interface IndexJob {
  id: string;
  document_id: string;
  title: string;
  path: string;
  state: string;
  error: string | null;
  kind: string;
}

interface Hit {
  document_id: string;
  title: string;
  path: string;
  version: number;
  start_char: number;
  end_char: number;
  text: string;
}

export default function DocumentsView() {
  const [spaces, setSpaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState("genel");
  const [docs, setDocs] = useState<DocumentRow[]>([]);
  const [path, setPath] = useState("");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [indexNote, setIndexNote] = useState("fts-1 · vektör yok");
  const [jobs, setJobs] = useState<IndexJob[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async (ws: string) => {
    setDocs(await api<DocumentRow[]>("GET", `/api/documents?workspace_id=${encodeURIComponent(ws)}`));
    setJobs(await api<IndexJob[]>("GET", `/api/documents/jobs?workspace_id=${encodeURIComponent(ws)}`));
  }, []);

  useEffect(() => {
    api<Workspace[]>("GET", "/api/workspaces")
      .then(setSpaces)
      .catch((e) => setError(errorText(e)));
  }, []);

  useEffect(() => {
    reload(workspaceId).catch((e) => setError(errorText(e)));
  }, [workspaceId, reload]);

  return (
    <section className="page">
      <header className="page-header">
        <h2>Belgeler</h2>
      </header>
      <p className="muted">
        Düz metin ve Markdown indekslenir. PDF, ofis ve görüntü bu sürümde ayrıştırılmaz. Vektör indeksi yok; arama sözcük indeksidir.
        Silmek kaydı ve indeksi kaldırır, diskteki dosyaya dokunmaz.
      </p>
      <label>
        Çalışma alanı
        <select value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)}>
          {spaces.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Dosya yolu
        <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="D:\notlar\toplanti.txt" />
      </label>
      <div className="row">
        <button
          type="button"
          onClick={async () => {
            try {
              const p = await pickFile("Belge seç", ["txt", "md", "markdown"]);
              if (p) setPath(p);
            } catch (e) {
              setError(errorText(e));
            }
          }}
        >
          Dosya seç…
        </button>
        <button
          className="primary"
          onClick={async () => {
            setError(null);
            try {
              await api("POST", "/api/documents/import", { workspace_id: workspaceId, path });
              await reload(workspaceId);
            } catch (e) {
              setError(errorText(e));
            }
          }}
        >
          İçe aktar
        </button>
      </div>
      {jobs.length > 0 && (
        <article className="facts">
          <h3>Açık indeks işleri ({jobs.length})</h3>
          {jobs.map((j) => (
            <p key={j.id} className="muted small">
              {j.title} · {j.state}
              {j.error ? ` · ${j.error}` : ""}
            </p>
          ))}
          <button
            type="button"
            onClick={async () => {
              try {
                await api("POST", `/api/documents/jobs/retry?workspace_id=${encodeURIComponent(workspaceId)}`);
                await reload(workspaceId);
                setError(null);
              } catch (e) {
                setError(errorText(e));
              }
            }}
          >
            Başarısızları yeniden dene
          </button>
        </article>
      )}
      {docs.map((doc) => (
        <article key={doc.id} className="facts">
          <h3>
            {doc.title} · sürüm {doc.version}
          </h3>
          <p className="muted small">
            {doc.path}
            <br />
            özet {doc.content_hash.slice(0, 12)} · indeks {doc.index_version} · durum {doc.index_state ?? "—"} · vektör {doc.vector}
          </p>
          {doc.index_error && <p className="error-inline">{doc.index_error}</p>}
          <div className="row">
            <button type="button" onClick={() => revealPath(doc.path).catch((e) => setError(errorText(e)))}>
              Klasörde aç
            </button>
            <button
              onClick={async () => {
                await api("DELETE", `/api/documents/${doc.id}`);
                setHits(null);
                await reload(workspaceId);
              }}
            >
              İndeksten sil
            </button>
          </div>
        </article>
      ))}
      <label>
        Bu alanda ara
        <input value={q} onChange={(e) => setQ(e.target.value)} />
      </label>
      <button
        onClick={async () => {
          try {
            const r = await api<{ hits: Hit[]; index: string; vector: string }>(
              "GET",
              `/api/documents/search?workspace_id=${encodeURIComponent(workspaceId)}&q=${encodeURIComponent(q)}`,
            );
            setHits(r.hits);
            setIndexNote(`${r.index} · vektör ${r.vector}`);
            setError(null);
          } catch (e) {
            setError(errorText(e));
          }
        }}
      >
        Ara
      </button>
      <p className="muted small">{indexNote}</p>
      {hits && hits.length === 0 && <p className="muted">Sonuç yok.</p>}
      {hits?.map((h, i) => (
        <article key={`${h.document_id}-${i}`} className="facts">
          <p>{h.text}</p>
          <p className="muted small">
            {h.title} · sürüm {h.version} · karakter {h.start_char}–{h.end_char}
            <br />
            {h.path}
          </p>
          <button type="button" onClick={() => revealPath(h.path).catch((e) => setError(errorText(e)))}>
            Klasörde aç
          </button>
        </article>
      ))}
      {error && <p className="error-inline">{error}</p>}
    </section>
  );
}
