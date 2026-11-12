import { useCallback, useEffect, useState } from "react";
import { api, coreStatus, errorText } from "./api";
import type { AppSettings, CoreStatus, Health, LoadedModel, ModelInfo } from "./types";
import Sidebar from "./components/Sidebar";
import ChatView from "./components/ChatView";
import ModelsView from "./components/ModelsView";
import CompareView from "./components/CompareView";
import SettingsView from "./components/SettingsView";
import SkillsView from "./components/SkillsView";
import MemoryView from "./components/MemoryView";
import DocumentsView from "./components/DocumentsView";
import TasksView from "./components/TasksView";
import TrainingView from "./components/TrainingView";
import OutputsView from "./components/OutputsView";
import StatusBar from "./components/StatusBar";

export type View =
  | "chat"
  | "models"
  | "compare"
  | "skills"
  | "memory"
  | "documents"
  | "tasks"
  | "outputs"
  | "training"
  | "settings";

export default function App() {
  const [core, setCore] = useState<CoreStatus>({ state: "starting", error: null, log_hint: null });
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelErrors, setModelErrors] = useState<string[]>([]);
  const [loaded, setLoaded] = useState<LoadedModel[]>([]);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [view, setView] = useState<View>("chat");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [listVersion, setListVersion] = useState(0);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    let stop = false;
    if (!("__TAURI_INTERNALS__" in window)) {
      setCore({ state: "failed", error: "Bu arayüz yalnızca Ahirena masaüstü penceresinde çalışır; tarayıcıda açılamaz.", log_hint: null });
      return;
    }
    const poll = async () => {
      while (!stop) {
        try {
          const s = await coreStatus();
          setCore(s);
          if (s.state !== "starting") return;
        } catch (e) {
          setCore({ state: "failed", error: errorText(e), log_hint: null });
          return;
        }
        await new Promise((r) => setTimeout(r, 300));
      }
    };
    poll();
    return () => {
      stop = true;
    };
  }, []);

  const refreshModels = useCallback(async () => {
    try {
      const r = await api<{ models: ModelInfo[]; errors: { provider_id: string; error: string }[] }>("GET", "/api/models");
      setModels(r.models);
      setModelErrors(r.errors.map((e) => e.error));
    } catch (e) {
      setModelErrors([errorText(e)]);
    }
  }, []);

  useEffect(() => {
    if (core.state !== "ready") return;
    api<AppSettings>("GET", "/api/settings").then(setSettings).catch(() => undefined);
    refreshModels();
    let stop = false;
    const tick = async () => {
      try {
        setHealth(await api<Health>("GET", "/api/health"));
        setHealthError(null);
        const l = await api<{ models: LoadedModel[] }>("GET", "/api/models/loaded");
        setLoaded(l.models);
      } catch (e) {
        setHealthError(errorText(e));
      }
    };
    tick();
    const id = setInterval(() => !stop && tick(), 4000);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [core.state, refreshModels]);

  const ollamaOk = health?.providers.find((p) => p.provider_id === "ollama")?.ok ?? false;
  useEffect(() => {
    if (ollamaOk) refreshModels();
  }, [ollamaOk, refreshModels]);

  useEffect(() => {
    const theme = settings?.theme ?? "system";
    const apply = () => {
      const dark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
      document.documentElement.dataset.theme = dark ? "dark" : "light";
    };
    apply();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [settings?.theme]);

  if (core.state !== "ready") {
    return (
      <div className="boot">
        <h1>Ahirena</h1>
        {core.state === "starting" ? (
          <p>Yerel çekirdek başlatılıyor…</p>
        ) : (
          <div className="error-box">
            <strong>Çekirdek başlatılamadı.</strong>
            <p>{core.error}</p>
            {core.log_hint && <p className="muted">Ayrıntı: {core.log_hint}</p>}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="app">
      <Sidebar
        view={view}
        onView={setView}
        activeId={activeId}
        onSelect={(id) => {
          setActiveId(id);
          setView("chat");
        }}
        version={listVersion}
        onChanged={() => setListVersion((v) => v + 1)}
        defaultModel={settings?.default_model ?? null}
      />
      <main className="main">
        {view === "chat" && settings && (
          <ChatView
            conversationId={activeId}
            models={models}
            ollamaOk={ollamaOk}
            runtimeError={health?.ollama_runtime?.error ?? null}
            settings={settings}
            onCreated={(id) => {
              setActiveId(id);
              setListVersion((v) => v + 1);
            }}
            onUpdated={() => setListVersion((v) => v + 1)}
            onRunning={setRunning}
            onSelect={(id) => {
              setActiveId(id);
              setView("chat");
            }}
          />
        )}
        {view === "models" && <ModelsView models={models} loaded={loaded} errors={modelErrors} onRefresh={refreshModels} />}
        {view === "compare" && settings && <CompareView models={models} settings={settings} onRunning={setRunning} />}
        {view === "skills" && <SkillsView />}
        {view === "memory" && <MemoryView />}
        {view === "documents" && <DocumentsView />}
        {view === "tasks" && <TasksView />}
        {view === "outputs" && <OutputsView />}
        {view === "training" && (
          <TrainingView
            onOpenConversation={(id) => {
              setActiveId(id);
              setView("chat");
              setListVersion((v) => v + 1);
            }}
            onOpenSkills={() => setView("skills")}
            onOpenCompare={() => setView("compare")}
          />
        )}
        {view === "settings" && settings && <SettingsView settings={settings} models={models} health={health} onSaved={setSettings} />}
      </main>
      <StatusBar health={health} error={healthError} loaded={loaded} running={running} />
    </div>
  );
}
