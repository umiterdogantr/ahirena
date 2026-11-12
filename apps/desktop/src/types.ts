export type MessageStatus = "complete" | "streaming" | "cancelled" | "error";

export interface Conversation {
  id: string;
  title: string;
  model_id: string | null;
  archived: boolean;
  workspace_id: string;
  parent_id?: string | null;
  created_at: string;
  updated_at: string;
  match_snippet?: string | null;
}

export interface MessageSource {
  kind: "memory" | "document";
  id: string;
  title: string;
  path?: string | null;
  text: string;
}

export interface MessageAttachment {
  id: string;
  path: string;
  media_type: string;
  byte_size: number;
  content_hash: string;
  untrusted: boolean;
  exists: boolean;
}

export interface Metrics {
  ttft_ms?: number;
  wall_ms?: number;
  total_ms?: number;
  load_ms?: number;
  prompt_tokens?: number;
  output_tokens?: number;
  tokens_per_s?: number | null;
  gpu_percent?: number;
  model_memory_bytes?: number;
  model_vram_bytes?: number;
  cancel_latency_ms?: number;
  context_dropped_messages?: number;
  num_ctx?: number;
  done_reason?: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "system" | "user" | "assistant";
  content: string;
  thinking: string | null;
  status: MessageStatus;
  error: string | null;
  provider_id: string | null;
  model_id: string | null;
  model_digest: string | null;
  metrics: Metrics | null;
  sources?: MessageSource[];
  attachments?: MessageAttachment[];
  created_at: string;
  updated_at: string;
}

export interface ModelInfo {
  provider_id: string;
  model_id: string;
  location: "local" | "remote";
  digest: string | null;
  size_bytes: number | null;
  family: string | null;
  parameter_size: string | null;
  quantization: string | null;
  context_length: number | null;
  capabilities: string[];
  license_name: string | null;
  modified_at: string | null;
}

export interface LoadedModel {
  provider_id: string;
  model_id: string;
  size_bytes: number;
  vram_bytes: number;
  gpu_percent: number;
  expires_at: string | null;
}

export interface OllamaRuntime {
  state: "pending" | "starting" | "managed" | "external" | "unavailable" | "error";
  error: string | null;
  url: string;
  managed: boolean;
  backend: string;
  models_dir: string | null;
  exe: string | null;
  pid: number | null;
  log: string | null;
}

export interface Health {
  core: { ok: boolean; version: string };
  providers: { provider_id: string; location: string; ok: boolean; version: string | null; error: string | null }[];
  ollama_runtime: OllamaRuntime | null;
  privacy: { remote_providers_enabled: boolean; ollama_cloud_disabled: boolean | null; conversation_storage: string };
  config_path: string;
  data_dir: string;
  active_runs: string[];
  network?: { offline: boolean; tor_socks: string };
  disk?: { free_mib: number; free_bytes: number; ok: boolean; min_free_bytes: number; path: string };
  tasks?: {
    worker: string;
    os_autostart: boolean;
    queued: number;
    running: number;
    waiting_approval: number;
    needs_reconciliation: number;
    attention: number;
  };
}

export type Theme = "system" | "light" | "dark";

export interface AppSettings {
  default_model: string | null;
  system_prompt: string;
  context_length: number;
  theme: Theme;
}

export interface CoreStatus {
  state: "starting" | "ready" | "failed";
  error: string | null;
  log_hint: string | null;
}

export type StreamEvent =
  | {
      event: "run";
      data: {
        run_id: string;
        model_id: string;
        user_message?: Message;
        assistant_message_id?: string;
        context_dropped_messages?: number;
        sources?: MessageSource[];
        num_ctx?: number;
        boost?: { boost?: boolean; context_length?: number; base_context?: number; remote?: boolean };
      };
    }
  | { event: "thinking"; data: { delta: string } }
  | { event: "token"; data: { delta: string } }
  | { event: "done"; data: { run_id: string; status: MessageStatus; error: string | null; metrics: Metrics } }
  | { event: "transport_error"; data: { message: string } };

export interface BenchReport {
  created_at: string;
  machine: Record<string, unknown>;
  prompts_version: string;
  results: {
    model_id: string;
    digest: string | null;
    phase: "cold" | "warm";
    prompt_id: string;
    ttft_ms: number | null;
    tokens_per_s: number | null;
    total_ms: number | null;
    load_ms: number | null;
    output_tokens: number | null;
    gpu_percent: number | null;
    model_memory_bytes: number | null;
    gpu_used_mib_after: number | null;
    error: string | null;
  }[];
}
