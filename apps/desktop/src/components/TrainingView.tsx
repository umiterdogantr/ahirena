import { useCallback, useEffect, useState } from "react";
import { api, errorText, revealPath } from "../api";

interface Cap {
  status: string;
  runner: string;
  note: string;
  min_vram_mib_hint: number;
  methods: string[];
}

interface Run {
  id: string;
  base_model: string;
  goal: string;
  status: string;
  activated: boolean;
  data_version: string;
}

interface FeedbackItem {
  id: string;
  issue_type: string;
  issue_label: string;
  note: string;
  suggested_fix: string | null;
  status: string;
  trains_model: boolean;
  created_at: string;
  conversation_id: string | null;
  message_id: string | null;
}

interface Props {
  onOpenConversation?: (id: string) => void;
  onOpenSkills?: () => void;
  onOpenCompare?: () => void;
}

const SKILL_DRAFT_TYPES = new Set(["bad_instruction", "tool_failure", "other"]);

export default function TrainingView({ onOpenConversation, onOpenSkills, onOpenCompare }: Props) {
  const [cap, setCap] = useState<Cap | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [feedback, setFeedback] = useState<FeedbackItem[]>([]);
  const [filter, setFilter] = useState("");
  const [base, setBase] = useState("");
  const [goal, setGoal] = useState("");
  const [why, setWhy] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [exportPath, setExportPath] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const q = filter ? `?status=${encodeURIComponent(filter)}` : "";
    const r = await api<{ capability: Cap; runs: Run[]; feedback: FeedbackItem[] }>("GET", `/api/training`);
    setCap(r.capability);
    setRuns(r.runs);
    if (filter) {
      const fb = await api<{ items: FeedbackItem[] }>("GET", `/api/feedback${q}`);
      setFeedback(fb.items);
    } else {
      setFeedback(r.feedback ?? []);
    }
  }, [filter]);

  useEffect(() => {
    reload().catch((e) => setError(errorText(e)));
  }, [reload]);

  return (
    <section className="page">
      <header className="page-header">
        <h2>Eğitim</h2>
      </header>
      <p className="muted">
        LoRA/QLoRA hattı ayrı çalıştırıcı ister. Bu cihazda doğrulanmadan eğitim başlamaz; kayıtlar planlandı olarak kalır.
        Konuşmalar ağırlık güncellemez.
      </p>
      {cap && (
        <article className="facts">
          <p>
            Durum: <strong>{cap.status}</strong> · çalıştırıcı {cap.runner}
          </p>
          <p className="muted small">
            Yöntemler: {cap.methods.join(", ")} · önerilen VRAM ≥ {cap.min_vram_mib_hint} MiB
          </p>
          <p className="muted small">{cap.note}</p>
        </article>
      )}
      <label>
        Temel model
        <input value={base} onChange={(e) => setBase(e.target.value)} placeholder="gemma4:e2b-it-qat" />
      </label>
      <label>
        Hedef davranış
        <textarea rows={2} value={goal} onChange={(e) => setGoal(e.target.value)} />
      </label>
      <label>
        Neden RAG/talimat yetmiyor?
        <textarea rows={2} value={why} onChange={(e) => setWhy(e.target.value)} />
      </label>
      <button
        className="primary"
        onClick={async () => {
          setError(null);
          setNote(null);
          try {
            const out = await api<Run>("POST", "/api/training/runs", {
              base_model: base,
              goal,
              why_not_rag: why,
              start: false,
            });
            setNote(`Kayıt alındı: ${out.status}`);
            await reload();
          } catch (e) {
            setError(errorText(e));
          }
        }}
      >
        Plan kaydı oluştur
      </button>
      <button
        onClick={async () => {
          setError(null);
          try {
            await api("POST", "/api/training/runs", { base_model: base || "x", goal: goal || "y", start: true });
          } catch (e) {
            setError(errorText(e));
          }
        }}
      >
        Eğitimi başlat (reddedilir)
      </button>
      {runs.map((r) => (
        <article key={r.id} className="facts">
          <h3>
            {r.base_model} · {r.status}
          </h3>
          <p>{r.goal}</p>
          <p className="muted small">
            veri {r.data_version} · etkin {r.activated ? "evet" : "hayır"}
          </p>
        </article>
      ))}
      <h3>Düzeltme adayları</h3>
      <p className="muted small">Sohbetten kaydedilir. Fine-tuning otomatik başlamaz.</p>
      <div className="row">
        <label>
          Durum
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">Tümü</option>
            <option value="open">Açık</option>
            <option value="reviewed">İncelendi</option>
            <option value="dismissed">Kapatıldı</option>
          </select>
        </label>
        <button
          type="button"
          onClick={async () => {
            try {
              const q = filter ? `?status=${encodeURIComponent(filter)}` : "";
              const r = await api<{ path: string; count: number }>("POST", `/api/feedback/export${q}`);
              setExportPath(r.path);
              setNote(`${r.count} düzeltme dışa aktarıldı.`);
              setError(null);
            } catch (e) {
              setError(errorText(e));
            }
          }}
        >
          Listeyi dışa aktar
        </button>
        {exportPath && (
          <button type="button" onClick={() => revealPath(exportPath).catch((e) => setError(errorText(e)))}>
            Dosyayı klasörde aç
          </button>
        )}
      </div>
      {feedback.length === 0 && <p className="muted">Henüz düzeltme yok.</p>}
      {feedback.map((f) => (
        <article key={f.id} className="facts">
          <h3>
            {f.issue_label} · {f.status}
          </h3>
          <p>{f.note}</p>
          {f.suggested_fix && (
            <p className="muted small">
              Önerilen düzeltme: {f.suggested_fix}
            </p>
          )}
          <p className="muted small">
            {f.created_at} · modeli eğitir: {f.trains_model ? "evet" : "hayır"}
          </p>
          <div className="row">
            {f.conversation_id && onOpenConversation && (
              <button type="button" onClick={() => onOpenConversation(f.conversation_id!)}>
                Oturuma git
              </button>
            )}
            {f.issue_type === "wrong_model" && onOpenCompare && (
              <button type="button" onClick={() => onOpenCompare()}>
                Model karşılaştır
              </button>
            )}
            {SKILL_DRAFT_TYPES.has(f.issue_type) && f.status === "open" && (
              <button
                type="button"
                onClick={async () => {
                  try {
                    const r = await api<{ note: string; candidate: { name: string } }>(
                      "POST",
                      `/api/feedback/${f.id}/skill-draft`,
                    );
                    setNote(`${r.note} (${r.candidate.name})`);
                    setError(null);
                    await reload();
                    onOpenSkills?.();
                  } catch (e) {
                    setError(errorText(e));
                  }
                }}
              >
                Yetenek taslağına çevir
              </button>
            )}
            {f.status === "open" && (
              <>
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      await api("PATCH", `/api/feedback/${f.id}`, { status: "reviewed" });
                      await reload();
                    } catch (e) {
                      setError(errorText(e));
                    }
                  }}
                >
                  İncelendi
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      await api("PATCH", `/api/feedback/${f.id}`, { status: "dismissed" });
                      await reload();
                    } catch (e) {
                      setError(errorText(e));
                    }
                  }}
                >
                  Kapat
                </button>
              </>
            )}
          </div>
        </article>
      ))}
      {note && <p className="muted">{note}</p>}
      {error && <p className="error-inline">{error}</p>}
    </section>
  );
}
