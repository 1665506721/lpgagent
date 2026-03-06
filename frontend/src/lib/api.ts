export type ChatResponse = {
  run_id?: string;
  final_response: string;
  state?: string;
  intent?: string;
  risk_level?: string;
  need_human?: boolean;
  confirm_required?: boolean;
  pending_action?: Record<string, unknown>;
  ui_action?: string;
  form?: FormPayload;
  events_preview?: Array<Record<string, unknown>>;
  routing?: ChatRouting;
};

export type ChatRouting = {
  mode?: "v2" | "legacy";
  lane?: "action" | "rag" | "smalltalk" | "safety" | "fallback_readonly";
  model_source?: "cloud" | "local" | "none";
  write_allowed?: boolean;
  degraded_reason?: string | null;
  ui_theme?: "light" | "eye" | "dark";
  manual_handoff?: boolean;
  manual_queue?: {
    status?: "WAITING" | "CONNECTING" | "CANCELED";
    ahead_count?: number;
    eta_minutes?: number;
    source?: "session_estimate" | string;
    can_collect_issue?: boolean;
  };
};

export type FormPayload = {
  form_id: string;
  title: string;
  description: string;
  schema: JsonSchema;
  prefill?: Record<string, unknown>;
  submit_intent?: string;
  confirm_required?: boolean;
  cta_label?: string;
};

export type JsonSchema = {
  type?: string;
  properties?: Record<string, SchemaProperty>;
  required?: string[];
};

export type SchemaProperty = {
  type?: string;
  enum?: string[];
  minimum?: number;
  maximum?: number;
  minLength?: number;
  pattern?: string;
  default?: unknown;
};

export type RunDetail = {
  run_id: string;
  created_at?: string;
  model_provider?: string;
  events?: AgentEvent[];
};

export type OllamaModelsResponse = {
  provider: "OLLAMA";
  base_url: string;
  models: string[];
  reachable: boolean;
  error?: string | null;
};

export type OllamaWarmupResponse = {
  ok: boolean;
  provider: "OLLAMA";
  base_url: string;
  model: string;
  response?: string;
  error?: string;
};

export type AgentEvent = {
  id?: number | string;
  step_index: number;
  state: string;
  tool_name?: string | null;
  created_at?: string;
  input_json?: Record<string, unknown> | null;
  output_json?: Record<string, unknown> | null;
  tool_input?: Record<string, unknown> | null;
  tool_output?: Record<string, unknown> | null;
  policy_result?: Record<string, unknown> | null;
};

export type PortalRagConfig = {
  top_k: number;
  min_score: number;
  min_hits: number;
  max_bullets?: number;
  enable_rewrite: boolean;
};

const API_BASE = import.meta.env?.VITE_API_BASE || "http://localhost:8000";

async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    const errorPayload = await response.json().catch(() => ({}));
    const code = String(errorPayload?.code || "");
    let message = errorPayload?.error || errorPayload?.message || "网络异常，请稍后重试";
    if (code === "MODEL_UNAVAILABLE") {
      message = "当前大模型未连接，请先点击“启动模型”后再试。";
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export async function postChat(params: {
  message: string;
  runId?: string;
  forceNewRun?: boolean;
  userId?: string;
  modelProvider: string;
  portalMode?: boolean;
  authToken?: string;
  openaiApiKey?: string;
  anthropicApiKey?: string;
  providerType?: string;
  providerName?: string;
  providerModel?: string;
  providerBaseUrl?: string;
  providerApiKey?: string;
  providerProfileId?: number;
  portalRagConfig?: PortalRagConfig;
}): Promise<ChatResponse> {
  const payload = {
    message: params.message,
    run_id: params.runId || undefined,
    force_new_run: Boolean(params.forceNewRun) || undefined,
    user_id: params.userId ? Number(params.userId) : null,
    model_provider: params.modelProvider,
    portal_mode: params.portalMode || undefined,
    openai_api_key: params.openaiApiKey || undefined,
    anthropic_api_key: params.anthropicApiKey || undefined,
    provider_type: params.providerType || undefined,
    provider_name: params.providerName || undefined,
    provider_model: params.providerModel || undefined,
    provider_base_url: params.providerBaseUrl || undefined,
    provider_api_key: params.providerApiKey || undefined,
    provider_profile_id:
      typeof params.providerProfileId === "number" ? params.providerProfileId : undefined,
    portal_rag_config: params.portalRagConfig || undefined
  };
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (params.authToken) {
    headers.Authorization = `Token ${params.authToken}`;
  }
  return requestJson<ChatResponse>("/api/chat", {
    method: "POST",
    headers,
    body: JSON.stringify(payload)
  });
}

export async function getRunDetail(runId: string): Promise<RunDetail> {
  const data = await requestJson<RunDetail>(`/api/runs/${runId}`);
  const events = Array.isArray(data.events) ? [...data.events] : [];
  events.sort((a, b) => (a.step_index || 0) - (b.step_index || 0));
  return { ...data, events };
}

export async function getOllamaModels(baseUrl?: string): Promise<OllamaModelsResponse> {
  const query = baseUrl ? `?base_url=${encodeURIComponent(baseUrl)}` : "";
  return requestJson<OllamaModelsResponse>(`/api/ollama/models${query}`);
}

export async function warmupOllamaModel(model: string, baseUrl?: string): Promise<OllamaWarmupResponse> {
  const payload = {
    model,
    base_url: baseUrl || undefined
  };
  return requestJson<OllamaWarmupResponse>("/api/ollama/warmup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}
