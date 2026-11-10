import { useEffect, useState } from "react";
import { api, errorText } from "../api";
import { dateTime } from "../format";
import type { Conversation } from "../types";
import type { View } from "../App";

interface Props {
  view: View;
  onView: (v: View) => void;
  activeId: string | null;
  onSelect: (id: string | null) => void;
  version: number;
  onChanged: () => void;
  defaultModel: string | null;
}

const NAV: { id: View; label: string }[] = [
  { id: "chat", label: "Sohbet" },
  { id: "models", label: "Modeller" },
  { id: "compare", label: "Karşılaştır" },
  { id: "skills", label: "Yetenekler" },
  { id: "memory", label: "Hafıza" },
  { id: "documents", label: "Belgeler" },
  { id: "tasks", label: "Görevler" },
  { id: "outputs", label: "Çıktılar" },
  { id: "training", label: "Eğitim" },
  { id: "settings", label: "Ayarlar" },
];

export default function Sidebar({ view, onView, activeId, onSelect, version, onChanged, defaultModel }: Props) {
  const [items, setItems] = useState<Conversation[]>([]);
  const [q, setQ] = useState("");
  const [archived, setArchived] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(async () => {
      try {
        const params = new URLSearchParams();
        if (q.trim()) params.set("q", q.trim());
        if (archived) params.set("archived", "true");
        setItems(await api<Conversation[]>("GET", `/api/conversations?${params}`));
        setError(null);
      } catch (e) {
        setError(errorText(e));
      }
    }, 200);
    return () => clearTimeout(t);
  }, [q, archived, version]);

  const create = async () => {
    try {
      const c = await api<Conversation>("POST", "/api/conversations", { model_id: defaultModel });
      onChanged();
      onSelect(c.id);
    } catch (e) {
      setError(errorText(e));
    }
  };

  const rename = async (id: string) => {
    const title = editTitle.trim();
    setEditing(null);
    if (!title) return;
    try {
      await api("PATCH", `/api/conversations/${id}`, { title });
      onChanged();
    } catch (e) {
      setError(errorText(e));
    }
  };

  const toggleArchive = async (c: Conversation) => {
    try {
      await api("PATCH", `/api/conversations/${c.id}`, { archived: !c.archived });
      if (activeId === c.id) onSelect(null);
      onChanged();
    } catch (e) {
      setError(errorText(e));
    }
  };

  const remove = async (id: string) => {
    setConfirmDelete(null);
    try {
      await api("DELETE", `/api/conversations/${id}`);
      if (activeId === id) onSelect(null);
      onChanged();
    } catch (e) {
      setError(errorText(e));
    }
  };

  return (
    <aside className="sidebar">
      <div className="brand">Ahirena</div>
      <nav className="nav">
        {NAV.map((n) => (
          <button key={n.id} className={view === n.id ? "active" : ""} onClick={() => onView(n.id)}>
            {n.label}
          </button>
        ))}
      </nav>
      <button className="primary new-session" onClick={create}>
        + Yeni oturum
      </button>
      <input className="search" placeholder="Oturumlarda ara…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Oturumlarda ara" />
      <label className="check">
        <input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Arşivi göster
      </label>
      {error && <div className="error-inline">{error}</div>}
      <ul className="sessions">
        {items.length === 0 && <li className="muted empty">{q ? "Eşleşen oturum yok." : archived ? "Arşiv boş." : "Henüz oturum yok."}</li>}
        {items.map((c) => (
          <li key={c.id} className={c.id === activeId ? "active" : ""}>
            {editing === c.id ? (
              <input
                autoFocus
                className="rename"
                value={editTitle}
                maxLength={200}
                onChange={(e) => setEditTitle(e.target.value)}
                onBlur={() => rename(c.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") rename(c.id);
                  if (e.key === "Escape") setEditing(null);
                }}
              />
            ) : (
              <button className="session-title" onClick={() => onSelect(c.id)} title={c.title}>
                <span>{c.title}</span>
                <small className="muted">{c.match_snippet ?? dateTime(c.updated_at)}</small>
              </button>
            )}
            <div className="session-actions">
              <button
                title="Yeniden adlandır"
                onClick={() => {
                  setEditing(c.id);
                  setEditTitle(c.title);
                }}
              >
                ✎
              </button>
              <button title={c.archived ? "Arşivden çıkar" : "Arşivle"} onClick={() => toggleArchive(c)}>
                {c.archived ? "↺" : "▣"}
              </button>
              {confirmDelete === c.id ? (
                <button className="danger" title="Silmeyi onayla" onClick={() => remove(c.id)} onBlur={() => setConfirmDelete(null)}>
                  Sil?
                </button>
              ) : (
                <button title="Sil" onClick={() => setConfirmDelete(c.id)}>
                  ✕
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </aside>
  );
}
