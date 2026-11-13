import { useCallback, useEffect, useState } from "react";
import { api, errorText, pickFolder, revealPath } from "../api";

interface Cap {
  status: string;
  runner: string;
  note: string;
  min_vram_mib_hint: number;
  methods: string[];
}

interface Phase6 {
  stage: number;
  product_closed: boolean;
  training_runner: string;
  evaluation_runs: number;
  acceptance_reports: number;
  note: string;
}

interface Run {
  id: string;
  base_model: string;
  goal: string;
  status: string;
  activated: boolean;
  data_version: string;
}

interface Adapter {
  id: string;
  base_model: string;
  path: string;
  status: string;
  exists: boolean;
  loaded_in_runtime: boolean;
  note?: string;
}

interface EvalSet {
  id: string;
  name: string;
  data_version: string;
  items: { prompt: string; expect_contains?: string | null }[];
}

interface EvalRun {
  id: string;
  model_id: string;
  summary: { checked: number; passed: number; failed: number; note: string };
  created_at: string;
}

interface AccReport {
  id: string;
  summary: { passed: number; failed: number; skipped: number; phase6_closed: boolean; note: string };
  path?: string;
  created_at: string;
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
  const [phase6, setPhase6] = useState<Phase6 | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [adapters, setAdapters] = useState<Adapter[]>([]);
  const [evalSets, setEvalSets] = useState<EvalSet[]>([]);
  const [evalRuns, setEvalRuns] = useState<EvalRun[]>([]);
  const [acceptance, setAcceptance] = useState<AccReport[]>([]);
  const [feedback, setFeedback] = useState<FeedbackItem[]>([]);
  const [filter, setFilter] = useState("");
  const [base, setBase] = useState("");
  const [goal, setGoal] = useState("");
  const [why, setWhy] = useState("");
  const [evalPrompt, setEvalPrompt] = useState("İstanbul'un kısa bir cümleyle tanımı");
  const [evalExpect, setEvalExpect] = useState("İstanbul");
  const [evalModel, setEvalModel] = useState("fake-model");
  const [adapterPath, setAdapterPath] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [exportPath, setExportPath] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const q = filter ? `?status=${encodeURIComponent(filter)}` : "";
    const r = await api<{
      capability: Cap;
      runs: Run[];
      adapters: Adapter[];
      feedback: FeedbackItem[];
      evaluation_sets: EvalSet[];
      evaluation_runs: EvalRun[];
      acceptance_reports: AccReport[];
      phase6: Phase6;
    }>("GET", `/api/training`);
    setCap(r.capability);
    setPhase6(r.phase6);
    setRuns(r.runs);
    setAdapters(r.adapters ?? []);
    setEvalSets(r.evaluation_sets ?? []);
    setEvalRuns(r.evaluation_runs ?? []);
    setAcceptance(r.acceptance_reports ?? []);
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
        Aşama 6 ürün kapanışı holdout değerlendirme + kabul matrisi ile yapılır. Konuşmalar ağırlık güncellemez.
      </p>
      {phase6 && (
        <article className="facts">
          <p>
            Aşama 6 ürün: <strong>{phase6.product_closed ? "kapandı" : "açık"}</strong> · LoRA{" "}
            {phase6.training_runner}
          </p>
          <p className="muted small">
            Değerlendirme {phase6.evaluation_runs} · kabul raporu {phase6.acceptance_reports}
          </p>
          <p className="muted small">{phase6.note}</p>
        </article>
      )}
      {cap && (
        <article className="facts">
          <p>
            Eğitim çalıştırıcı: <strong>{cap.status}</strong> · {cap.runner}
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

      <h3>Holdout değerlendirme</h3>
      <p className="muted small">Uydurma doğruluk yüzdesi yok. İsteğe bağlı alt metin denetimi + süre/token.</p>
      <label>
        Soru
        <textarea rows={2} value={evalPrompt} onChange={(e) => setEvalPrompt(e.target.value)} />
      </label>
      <label>
        Beklenen alt metin (isteğe bağlı)
        <input value={evalExpect} onChange={(e) => setEvalExpect(e.target.value)} />
      </label>
      <label>
        Model
        <input value={evalModel} onChange={(e) => setEvalModel(e.target.value)} />
      </label>
      <div className="row">
        <button
          className="primary"
          type="button"
          onClick={async () => {
            try {
              const set = await api<EvalSet>("POST", "/api/evaluation/sets", {
                name: `Holdout ${new Date().toISOString().slice(0, 16)}`,
                data_version: "holdout-v1",
                items: [{ prompt: evalPrompt, expect_contains: evalExpect || null }],
              });
              const run = await api<EvalRun>("POST", "/api/evaluation/runs", {
                set_id: set.id,
                model_id: evalModel,
                provider_id: evalModel === "fake-model" ? "fake" : "ollama",
              });
              setNote(
                `Değerlendirme: checked ${run.summary.checked}, passed ${run.summary.passed}, failed ${run.summary.failed}`,
              );
              setError(null);
              await reload();
            } catch (e) {
              setError(errorText(e));
            }
          }}
        >
          Küme oluştur ve koş
        </button>
      </div>
      {evalSets.slice(0, 5).map((s) => (
        <article key={s.id} className="facts">
          <h3>
            {s.name} · {s.items.length} madde
          </h3>
          <p className="muted small">veri {s.data_version}</p>
        </article>
      ))}
      {evalRuns.slice(0, 5).map((r) => (
        <article key={r.id} className="facts">
          <h3>
            {r.model_id} · {r.summary.passed}/{r.summary.checked} geçti
          </h3>
          <p className="muted small">
            {r.created_at} · {r.summary.note}
          </p>
        </article>
      ))}

      <h3>Kabul matrisi</h3>
      <div className="row">
        <button
          className="primary"
          type="button"
          onClick={async () => {
            try {
              const r = await api<AccReport>("POST", "/api/acceptance/run");
              setNote(
                `Kabul: pass ${r.summary.passed}, fail ${r.summary.failed}, skip ${r.summary.skipped} · Aşama6 ${
                  r.summary.phase6_closed ? "kapandı" : "açık"
                }`,
              );
              setError(null);
              await reload();
              if (r.path) setExportPath(r.path);
            } catch (e) {
              setError(errorText(e));
            }
          }}
        >
          Matrisi çalıştır
        </button>
      </div>
      {acceptance.slice(0, 3).map((r) => (
        <article key={r.id} className="facts">
          <h3>
            {r.summary.phase6_closed ? "kapandı" : "açık"} · {r.summary.passed} pass / {r.summary.failed} fail
          </h3>
          <p className="muted small">{r.summary.note}</p>
        </article>
      ))}

      <h3>Adaptör kaydı</h3>
      <p className="muted small">Dosya veri klasöründe olmalı. Etkinleştirme Ollama’ya PEFT yüklemez.</p>
      <div className="row">
        <input value={adapterPath} onChange={(e) => setAdapterPath(e.target.value)} placeholder="D:\\...\\adapter" />
        <button
          type="button"
          onClick={async () => {
            try {
              const p = await pickFolder("Adaptör klasörü");
              if (p) setAdapterPath(p);
            } catch (e) {
              setError(errorText(e));
            }
          }}
        >
          Klasör seç…
        </button>
        <button
          type="button"
          disabled={!adapterPath.trim() || !base.trim()}
          onClick={async () => {
            try {
              await api("POST", "/api/training/adapters", { path: adapterPath, base_model: base });
              setNote("Adaptör aday olarak kaydedildi.");
              setError(null);
              await reload();
            } catch (e) {
              setError(errorText(e));
            }
          }}
        >
          Kaydet
        </button>
      </div>
      {adapters.map((a) => (
        <article key={a.id} className="facts">
          <h3>
            {a.base_model} · {a.status} {a.exists ? "" : "· dosya yok"}
          </h3>
          <p className="muted small">
            {a.path} · runtime yükleme: {a.loaded_in_runtime ? "evet" : "hayır"}
          </p>
          <div className="row">
            {a.status !== "active" && (
              <button
                type="button"
                disabled={!a.exists}
                onClick={async () => {
                  try {
                    const out = await api<Adapter>("POST", `/api/training/adapters/${a.id}/activate`);
                    setNote(out.note || "Etkinleştirildi.");
                    await reload();
                  } catch (e) {
                    setError(errorText(e));
                  }
                }}
              >
                Etkinleştir
              </button>
            )}
            {a.status === "active" && (
              <button
                type="button"
                onClick={async () => {
                  try {
                    const out = await api<Adapter>("POST", `/api/training/adapters/${a.id}/rollback`);
                    setNote(out.note || "Geri alındı.");
                    await reload();
                  } catch (e) {
                    setError(errorText(e));
                  }
                }}
              >
                Geri al
              </button>
            )}
          </div>
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
