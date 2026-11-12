import { useCallback, useEffect, useState } from "react";
import { api, errorText, revealPath } from "../api";

function looksLikePath(s: string): boolean {
  return /^[A-Za-z]:[\\/]/.test(s.trim()) || s.trim().startsWith("\\\\");
}

interface Workspace {
  id: string;
  name: string;
}

interface MemoryItem {
  id: string;
  body: string;
  source_ref: string;
  status: string;
  verified: number;
}

interface SearchHit {
  id: string;
  body: string;
  source_ref: string;
}

export default function MemoryView() {
  const [spaces, setSpaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState("genel");
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [body, setBody] = useState("");
  const [source, setSource] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [spaceName, setSpaceName] = useState("");
  const [similar, setSimilar] = useState<SearchHit[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async (ws: string) => {
    setItems(await api<MemoryItem[]>("GET", `/api/memory?workspace_id=${encodeURIComponent(ws)}`));
  }, []);

  useEffect(() => {
    api<Workspace[]>("GET", "/api/workspaces")
      .then((rows) => {
        setSpaces(rows);
        setError(null);
      })
      .catch((e) => setError(errorText(e)));
  }, []);

  useEffect(() => {
    reload(workspaceId).catch((e) => setError(errorText(e)));
    setSimilar([]);
    setNote(null);
  }, [workspaceId, reload]);

  const save = async () => {
    setError(null);
    setNote(null);
    try {
      if (editing) {
        await api("PATCH", `/api/memory/${editing}`, { body, source_ref: source });
        setSimilar([]);
      } else {
        const r = await api<{ similar?: SearchHit[]; note?: string | null }>("POST", "/api/memory", {
          workspace_id: workspaceId,
          body,
          source_ref: source,
        });
        setSimilar(r.similar ?? []);
        setNote(r.note ?? "Kayıt eklendi.");
      }
      setBody("");
      setSource("");
      setEditing(null);
      setHits(null);
      await reload(workspaceId);
    } catch (e) {
      setError(errorText(e));
    }
  };

  return (
    <section className="page">
      <header className="page-header">
        <h2>Hafıza</h2>
      </header>
      <p className="muted">
        Buraya yalnızca sizin yazdığınız bilgi girer. Konuşma ve model cevabı kendiliğinden kaydolmaz. Yeni kayıt eskisinin üstüne yazılmaz.
      </p>
      <div className="row">
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
          Yeni alan
          <input value={spaceName} onChange={(e) => setSpaceName(e.target.value)} />
        </label>
        <button
          onClick={async () => {
            try {
              const created = await api<Workspace>("POST", "/api/workspaces", { name: spaceName });
              setSpaces(await api<Workspace[]>("GET", "/api/workspaces"));
              setWorkspaceId(created.id);
              setSpaceName("");
            } catch (e) {
              setError(errorText(e));
            }
          }}
        >
          Alan aç
        </button>
      </div>
      <label>
        Bilgi
        <textarea rows={3} value={body} onChange={(e) => setBody(e.target.value)} />
      </label>
      <label>
        Kaynak
        <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="kim söyledi, hangi not" />
      </label>
      <div className="row">
        <button className="primary" onClick={save}>
          {editing ? "Düzeltmeyi kaydet" : "Kaydet"}
        </button>
        {!editing && (
          <button
            type="button"
            onClick={async () => {
              try {
                const r = await api<{ similar: SearchHit[]; note: string }>(
                  "GET",
                  `/api/memory/similar?workspace_id=${encodeURIComponent(workspaceId)}&q=${encodeURIComponent(body)}`,
                );
                setSimilar(r.similar);
                setNote(r.similar.length ? r.note : "Benzer aktif kayıt bulunamadı.");
                setError(null);
              } catch (e) {
                setError(errorText(e));
              }
            }}
          >
            Benzerleri kontrol et
          </button>
        )}
      </div>
      {note && <p className="muted">{note}</p>}
      {similar.length > 0 && (
        <article className="facts">
          <h3>Benzer kayıtlar (üzerine yazılmadı)</h3>
          <ul>
            {similar.map((s) => (
              <li key={s.id}>
                {s.body}
                <div className="muted small">Kaynak: {s.source_ref}</div>
              </li>
            ))}
          </ul>
        </article>
      )}
      {items.map((item) => (
        <article key={item.id} className="facts">
          <p>{item.body}</p>
          <p className="muted small">
            Kaynak: {item.source_ref} · {item.status === "active" ? "geçerli" : "geçersiz"} · doğrulanmış
          </p>
          <div className="row">
            {looksLikePath(item.source_ref) && (
              <button type="button" onClick={() => revealPath(item.source_ref).catch((e) => setError(errorText(e)))}>
                Kaynağı klasörde aç
              </button>
            )}
            <button
              onClick={() => {
                setEditing(item.id);
                setBody(item.body);
                setSource(item.source_ref);
              }}
            >
              Düzelt
            </button>
            <button
              onClick={async () => {
                await api("POST", `/api/memory/${item.id}/supersede`);
                await reload(workspaceId);
              }}
            >
              Geçersiz say
            </button>
            <button
              onClick={async () => {
                await api("DELETE", `/api/memory/${item.id}`);
                await reload(workspaceId);
              }}
            >
              Sil
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
            const r = await api<{ hits: SearchHit[]; vector: string }>(
              "GET",
              `/api/memory/search?workspace_id=${encodeURIComponent(workspaceId)}&q=${encodeURIComponent(q)}`,
            );
            setHits(r.hits);
            setError(null);
          } catch (e) {
            setError(errorText(e));
          }
        }}
      >
        Ara
      </button>
      {hits && hits.length === 0 && <p className="muted">Sonuç yok.</p>}
      {hits?.map((h) => (
        <article key={h.id} className="facts">
          <p>{h.body}</p>
          <p className="muted small">Kaynak: {h.source_ref}</p>
        </article>
      ))}
      {error && <p className="error-inline">{error}</p>}
    </section>
  );
}
