import { useEffect, useRef, useState } from "react";
import { api, cancelRun, errorText, stream } from "../api";
import { metricsLine, shortDigest } from "../format";
import type { AppSettings, Conversation, Message, ModelInfo, StreamEvent } from "../types";
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
    created_at: now,
    updated_at: now,
  };
}

export default function ChatView({ conversationId, models, ollamaOk, runtimeError, settings, onCreated, onUpdated, onRunning }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [model, setModel] = useState<string | null>(null);
  const [think, setThink] = useState(false);
  const [input, setInput] = useState("");
  const [run, setRun] = useState<RunState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const skipReload = useRef<string | null>(null);
  const pendingCancel = useRef(false);
  const listRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  const caps = models.find((m) => m.model_id === model)?.capabilities ?? [];
  const canThink = caps.includes("thinking");

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
        const c = await api<Conversation>("POST", "/api/conversations", { model_id: model });
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
            if (e.data.assistant_message_id) copy[copy.length - 1] = { ...copy[copy.length - 1], id: e.data.assistant_message_id };
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
      await stream(`/api/conversations/${cid}/chat`, { content, model_id: model, provider_id: "ollama", think: canThink && think }, onEvent);
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
        {canThink && (
          <label className="check" title="Model düşünme çıktısı üretir; yanıt süresi uzar.">
            <input type="checkbox" checked={think} onChange={(e) => setThink(e.target.checked)} disabled={!!run} /> Düşünme
          </label>
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
            {m.role === "assistant" && m.status !== "streaming" && (
              <footer className="msg-meta" title={m.model_digest ? `digest: ${m.model_digest}` : undefined}>
                {m.model_id} {m.model_digest ? `(${shortDigest(m.model_digest)})` : ""} {metricsLine(m.metrics) && `· ${metricsLine(m.metrics)}`}
              </footer>
            )}
          </article>
        ))}
      </div>

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
