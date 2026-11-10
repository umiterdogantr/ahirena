import { useEffect, useRef, useState } from "react";
import { api, cancelRun, errorText, pickFile, revealPath, stream } from "../api";
import { metricsLine, shortDigest } from "../format";
import type { AppSettings, Conversation, Message, MessageSource, ModelInfo, StreamEvent } from "../types";
import Markdown from "./Markdown";
import ModelPicker from "./ModelPicker";

interface Props {
  conversationId: string | null;
  models: ModelInfo[];
  ollamaOk: boolean;
  runtimeError: string | null;
  settings: AppSettings;
  onCreated: (id: string) => void;
  onUpdated: () => void;
  onRunning: (running: boolean) => void;
  onSelect?: (id: string) => void;
}

interface RunState {
  runId: string | null;
  stopping: boolean;
}

function placeholder(role: "user" | "assistant", content: string, model: string | null): Message {
  const now = new Date().toISOString();
  return {
    id: `tmp-${role}-${now}`,
    conversation_id: "",
    role,
    content,
    thinking: null,
    status: role === "user" ? "complete" : "streaming",
    error: null,
    provider_id: null,
    model_id: model,
    model_digest: null,
    metrics: null,
    sources: [],
    created_at: now,
    updated_at: now,
  };
}

export default function ChatView({ conversationId, models, ollamaOk, runtimeError, settings, onCreated, onUpdated, onRunning, onSelect }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [model, setModel] = useState<string | null>(null);
  const [think, setThink] = useState(false);
  const [input, setInput] = useState("");
  const [imagePath, setImagePath] = useState("");
  const [feedbackFor, setFeedbackFor] = useState<string | null>(null);
  const [feedbackIssue, setFeedbackIssue] = useState("missing_source");
  const [feedbackNote, setFeedbackNote] = useState("");
  const [feedbackFix, setFeedbackFix] = useState("");
  const [feedbackOk, setFeedbackOk] = useState<string | null>(null);
  const [run, setRun] = useState<RunState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [workspaces, setWorkspaces] = useState<{ id: string; name: string }[]>([]);
  const [workspaceId, setWorkspaceId] = useState("genel");
  const skipReload = useRef<string | null>(null);
  const pendingCancel = useRef(false);
  const listRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  const caps = models.find((m) => m.model_id === model)?.capabilities ?? [];
  const canThink = caps.includes("thinking");

  useEffect(() => {
    api<{ id: string; name: string }[]>("GET", "/api/workspaces")
      .then(setWorkspaces)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (conversationId && skipReload.current === conversationId) return;
    setError(null);
    setNotice(null);
    if (!conversationId) {
      setMessages([]);
      setModel((m) => m ?? settings.default_model ?? models[0]?.model_id ?? null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const [conv, msgs] = await Promise.all([
          api<Conversation>("GET", `/api/conversations/${conversationId}`),
          api<Message[]>("GET", `/api/conversations/${conversationId}/messages`),
        ]);
        if (cancelled) return;
        setMessages(msgs);
        setWorkspaceId(conv.workspace_id || "genel");
        setModel(conv.model_id ?? settings.default_model ?? models[0]?.model_id ?? null);
        stickToBottom.current = true;
      } catch (e) {
        if (!cancelled) setError(errorText(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  useEffect(() => {
    if (!model && models.length) setModel(settings.default_model ?? models[0].model_id);
  }, [models, model, settings.default_model]);

  useEffect(() => {
    const el = listRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  useEffect(() => onRunning(run !== null), [run, onRunning]);

  const patchAssistant = (fn: (m: Message) => Message) =>
    setMessages((ms) => {
      const i = ms.length - 1;
      if (i < 0 || ms[i].role !== "assistant") return ms;
      const copy = ms.slice();
      copy[i] = fn(copy[i]);
      return copy;
    });

  const send = async () => {
    const content = input.trim();
    if (!content || run || !model) return;
    setError(null);
    setNotice(null);
    let cid = conversationId;
    try {
      if (!cid) {
        const c = await api<Conversation>("POST", "/api/conversations", { model_id: model, workspace_id: workspaceId });
        cid = c.id;
        skipReload.current = cid;
        onCreated(cid);
      } else {
        skipReload.current = cid;
      }
    } catch (e) {
      setError(errorText(e));
      return;
    }

    setInput("");
    stickToBottom.current = true;
    pendingCancel.current = false;
    setRun({ runId: null, stopping: false });
    setMessages((ms) => [...ms, placeholder("user", content, null), placeholder("assistant", "", model)]);

    const onEvent = (e: StreamEvent) => {
      switch (e.event) {
        case "run":
          setRun((r) => (r ? { ...r, runId: e.data.run_id } : r));
          if (pendingCancel.current) cancelRun(e.data.run_id).catch(() => undefined);
          setMessages((ms) => {
            const copy = ms.slice();
            if (e.data.user_message) copy[copy.length - 2] = e.data.user_message;
            if (e.data.assistant_message_id)
              copy[copy.length - 1] = {
                ...copy[copy.length - 1],
                id: e.data.assistant_message_id,
                sources: e.data.sources ?? copy[copy.length - 1].sources,
              };
            return copy;
          });
          if (e.data.context_dropped_messages)
            setNotice(`Bağlam sınırı (${settings.context_length} token) nedeniyle en eski ${e.data.context_dropped_messages} mesaj modele gönderilmedi.`);
          break;
        case "thinking":
          patchAssistant((m) => ({ ...m, thinking: (m.thinking ?? "") + e.data.delta }));
          break;
        case "token":
          patchAssistant((m) => ({ ...m, content: m.content + e.data.delta }));
          break;
        case "done":
          patchAssistant((m) => ({ ...m, status: e.data.status, error: e.data.error, metrics: e.data.metrics }));
          break;
        case "transport_error":
          patchAssistant((m) => ({ ...m, status: "error", error: e.data.message }));
          break;
      }
    };

    try {
      await stream(
        `/api/conversations/${cid}/chat`,
        {
          content,
          model_id: model,
          provider_id: "ollama",
          think: canThink && think,
          image_path: imagePath.trim() || null,
        },
        onEvent,
      );
      setImagePath("");
    } catch (e) {
      patchAssistant((m) => (m.status === "streaming" ? { ...m, status: "error", error: errorText(e) } : m));
    } finally {
      setRun(null);
      onUpdated();
      try {
        setMessages(await api<Message[]>("GET", `/api/conversations/${cid}/messages`));
      } catch {
        /* ekrandaki geçici sürüm kalır */
      }
      skipReload.current = null;
    }
  };

  const stop = () => {
    if (!run || run.stopping) return;
    setRun({ ...run, stopping: true });
    if (run.runId) cancelRun(run.runId).catch((e) => setError(errorText(e)));
    else pendingCancel.current = true;
  };

  return (
    <section className="chat">
      <header className="chat-header">
        <ModelPicker models={models} value={model} onChange={setModel} disabled={!!run} />
        <label className="check">
          Çalışma alanı
          <select
            value={workspaceId}
            disabled={!!run}
            onChange={async (e) => {
              const id = e.target.value;
              setWorkspaceId(id);
              if (conversationId) {
                try {
                  await api("PATCH", `/api/conversations/${conversationId}`, { workspace_id: id });
                } catch (err) {
                  setError(errorText(err));
                }
              }
            }}
          >
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </label>
        {canThink && (
          <label className="check" title="Model düşünme çıktısı üretir; yanıt süresi uzar.">
            <input type="checkbox" checked={think} onChange={(e) => setThink(e.target.checked)} disabled={!!run} /> Düşünme
          </label>
        )}
        {conversationId && (
          <button
            disabled={!!run}
            title="Bu oturumdan yeni dal açar; önceki mesajları kopyalar"
            onClick={async () => {
              try {
                const c = await api<Conversation>("POST", `/api/conversations/${conversationId}/branch`, {});
                onSelect?.(c.id);
                onUpdated();
              } catch (e) {
                setError(errorText(e));
              }
            }}
          >
            Dal aç
          </button>
        )}
      </header>

      <div
        className="messages"
        ref={listRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}
      >
        {models.length === 0 && (
          <div className="empty-state">
            {runtimeError ? (
              <>
                <p>Ollama başlatılamadı.</p>
                <p className="muted">{runtimeError}</p>
              </>
            ) : !ollamaOk ? (
              <p className="muted">Yerel model sunucusu başlatılıyor…</p>
            ) : (
              <>
                <p>Yüklü yerel model bulunamadı.</p>
                <p className="muted">
                  Depo klasöründe örneğin <code>scripts\ollama.cmd pull gemma4:e2b-it-qat</code> çalıştırın, sonra Modeller ekranında yenileyin.
                </p>
              </>
            )}
          </div>
        )}
        {models.length > 0 && messages.length === 0 && (
          <div className="empty-state">
            <p>Yeni bir konuşma başlatın.</p>
            <p className="muted">Yanıtlar bu bilgisayardaki modelle üretilir; konuşmalar yerel veritabanında saklanır.</p>
          </div>
        )}
        {messages.map((m) => (
          <article key={m.id} className={`msg ${m.role}`}>
            {m.role === "assistant" && m.thinking && (
              <details className="thinking">
                <summary>Model düşünme çıktısı</summary>
                <pre>{m.thinking}</pre>
              </details>
            )}
            {m.role === "assistant" ? (
              m.content ? (
                <Markdown text={m.content} />
              ) : m.status === "streaming" ? (
                <p className="muted">{m.thinking ? "Düşünüyor…" : "Model hazırlanıyor…"}</p>
              ) : null
            ) : (
              <p className="user-text">{m.content}</p>
            )}
            {m.status === "cancelled" && <div className="badge">Durduruldu{m.content ? " — yanıt yarım" : ""}</div>}
            {m.status === "error" && <div className="error-inline">{m.error ?? "Hata"}</div>}
            {m.role === "assistant" && (m.sources?.length ?? 0) > 0 && (
              <details className="sources">
                <summary>Kaynaklar ({m.sources!.length})</summary>
                <ul>
                  {m.sources!.map((s: MessageSource, i) => (
                    <li key={`${s.kind}-${s.id}-${i}`}>
                      <strong>{s.kind === "document" ? "Belge" : "Hafıza"}</strong> · {s.title}
                      {s.path ? (
                        <div className="row">
                          <span className="muted small">{s.path}</span>
                          <button
                            type="button"
                            className="linkish"
                            onClick={() => revealPath(s.path!).catch((e) => setError(errorText(e)))}
                          >
                            Klasörde aç
                          </button>
                        </div>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {m.role === "assistant" && m.status !== "streaming" && !m.id.startsWith("tmp-") && (
              <div className="row">
                <button
                  type="button"
                  onClick={() => {
                    setFeedbackFor(m.id);
                    setFeedbackNote("");
                    setFeedbackFix("");
                    setFeedbackOk(null);
                  }}
                >
                  Düzeltme kaydet
                </button>
              </div>
            )}
            {m.role === "assistant" && m.status !== "streaming" && (
              <footer className="msg-meta" title={m.model_digest ? `digest: ${m.model_digest}` : undefined}>
                {m.model_id} {m.model_digest ? `(${shortDigest(m.model_digest)})` : ""} {metricsLine(m.metrics) && `· ${metricsLine(m.metrics)}`}
              </footer>
            )}
          </article>
        ))}
      </div>

      {feedbackFor && (
        <div className="facts">
          <h3>Düzeltme adayı</h3>
          <p className="muted small">Model ağırlığını değiştirmez. Önce sorun türü kaydedilir; eğitim ayrı ve onaylıdır.</p>
          <label>
            Sorun türü
            <select value={feedbackIssue} onChange={(e) => setFeedbackIssue(e.target.value)}>
              <option value="missing_source">Kaynak eksikliği</option>
              <option value="bad_instruction">Hatalı talimat</option>
              <option value="tool_failure">Başarısız araç</option>
              <option value="wrong_model">Yanlış model</option>
              <option value="needs_training">Eğitim ihtiyacı</option>
              <option value="other">Diğer</option>
            </select>
          </label>
          <label>
            Ne yanlıştı?
            <textarea rows={3} value={feedbackNote} onChange={(e) => setFeedbackNote(e.target.value)} />
          </label>
          <label>
            Önerilen doğru yanıt (isteğe bağlı)
            <textarea rows={3} value={feedbackFix} onChange={(e) => setFeedbackFix(e.target.value)} />
          </label>
          <div className="row">
            <button
              className="primary"
              onClick={async () => {
                try {
                  await api("POST", "/api/feedback", {
                    issue_type: feedbackIssue,
                    note: feedbackNote,
                    suggested_fix: feedbackFix,
                    message_id: feedbackFor,
                    conversation_id: conversationId,
                  });
                  setFeedbackOk("Düzeltme kaydedildi (eğitim başlamadı).");
                  setFeedbackFor(null);
                  setError(null);
                } catch (e) {
                  setError(errorText(e));
                }
              }}
            >
              Kaydet
            </button>
            <button type="button" onClick={() => setFeedbackFor(null)}>
              Vazgeç
            </button>
          </div>
        </div>
      )}

      {feedbackOk && <div className="notice">{feedbackOk}</div>}
      {notice && <div className="notice">{notice}</div>}
      {error && <div className="error-inline">{error}</div>}

      <div className="composer">
        <textarea
          value={input}
          placeholder={model ? "Mesajınızı yazın (Enter gönderir, Shift+Enter yeni satır)" : "Önce bir model seçin"}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          disabled={!model}
          rows={3}
        />
        <label className="check">
          Görüntü yolu
          <input
            value={imagePath}
            onChange={(e) => setImagePath(e.target.value)}
            placeholder="vision modeli yoksa reddedilir; OCR değildir"
            disabled={!!run}
          />
          <button
            type="button"
            disabled={!!run}
            onClick={async () => {
              try {
                const p = await pickFile("Görüntü seç", ["png", "jpg", "jpeg", "webp", "gif"]);
                if (p) setImagePath(p);
              } catch (e) {
                setError(errorText(e));
              }
            }}
          >
            Seç…
          </button>
        </label>
        {run ? (
          <button className="danger" onClick={stop} disabled={run.stopping}>
            {run.stopping ? "Durduruluyor…" : "Durdur"}
          </button>
        ) : (
          <button className="primary" onClick={send} disabled={!input.trim() || !model}>
            Gönder
          </button>
        )}
      </div>
    </section>
  );
}
