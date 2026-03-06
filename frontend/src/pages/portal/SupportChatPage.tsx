import { useEffect, useMemo, useRef, useState } from "react";

import { getOllamaModels, postChat, warmupOllamaModel } from "../../lib/api";
import type { ChatRouting, PortalRagConfig } from "../../lib/api";
import {
  activatePortalLlmProfile,
  clearPortalChatHistory,
  createPortalLlmProfile,
  deletePortalLlmProfile,
  emitPortalDataUpdated,
  emitPortalNotificationRefresh,
  fetchPortalLlmModels,
  listPortalChatHistory,
  listPortalLlmProfiles,
  updatePortalLlmProfile,
  validatePortalLlmProfile,
} from "../../lib/portalApi";
import type { PortalLlmModelOption, PortalLlmProfile } from "../../lib/portalApi";
import { QUICK_QUESTIONS } from "./portalData";

type PortalMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  runId?: string;
  latencyMs?: number;
};

type PendingActionPayload = Record<string, unknown>;

type FeedbackOrderPick = {
  order_id?: number;
  order_no?: string;
  label?: string;
};

type StageTimings = {
  ruleMs: number | null;
  toolMs: number | null;
  answerMs: number | null;
  toolCount: number;
  totalMs: number;
};

const LANE_LABELS: Record<string, string> = {
  action: "操作通道",
  rag: "RAG 问答",
  smalltalk: "通用对话",
  safety: "安全应急",
  fallback_readonly: "只读兜底",
};

const CHAT_MENU = [
  { label: "安燃助手", prompt: "你好，介绍一下你可以帮我做什么" },
  { label: "下单服务", prompt: "我要下单 15kg 瓶装配送" },
  { label: "订单查询", prompt: "帮我查一下最近订单" },
  { label: "订单改址", prompt: "我要修改订单地址" },
  { label: "投诉建议", prompt: "我要投诉今天的服务" }
] as const;

const OLLAMA_MODEL_KEY = "portal_ollama_model";
const FALLBACK_MODEL = "deepseek-r1:8b";
const RAG_CONFIG_KEY = "portal_rag_config";
const CHAT_HISTORY_BASE_VISIBLE = 20;
const CHAT_HISTORY_EXPAND_STEP = 5;
const CHAT_BOTTOM_STICKY_GAP = 120;
const CHAT_CONTEXT_EXPIRE_MS = 30 * 60 * 1000;
const CHAT_CACHE_PREFIX = "portal_chat_cache_v2";
const CHAT_DRAFT_PREFIX = "portal_chat_draft_v1";
const PROFILE_SELECTED_KEY = "portal_selected_llm_profile_id";
const CONFIRM_WORD_RE = /^(确认|取消|是|否|好的|好|继续|算了|不用了|先这样)$/;
const SLOW_THRESHOLD_MS = 6000;
const STARTER_GUIDE_MESSAGE =
  "您好，我可以帮您办理下单、查订单、改地址、查地址、投诉等。请直接说您的具体目的，例如“下单一瓶15kg”或“帮我查最近订单”。";
const TOOL_DOMAIN_MAP: Record<string, string[]> = {
  portal_create_order: ["orders", "notifications"],
  portal_pay_order: ["orders", "notifications"],
  portal_cancel_order: ["orders", "notifications"],
  portal_modify_order_address: ["orders", "addresses", "notifications"],
  portal_create_address: ["addresses", "profile", "notifications"],
  portal_update_address: ["addresses", "profile", "notifications"],
  portal_set_default_address: ["addresses", "profile", "orders", "notifications"],
  portal_delete_address: ["addresses", "profile", "notifications"],
  portal_update_profile: ["profile", "notifications"],
  portal_change_password: ["profile", "notifications"],
  portal_create_feedback: ["profile", "notifications"],
  portal_request_refund: ["profile", "notifications"],
  portal_cart_add: ["cart"],
  portal_cart_remove: ["cart"],
  portal_cart_clear: ["cart"],
  portal_cart_checkout: ["cart", "orders", "notifications"],
  portal_read_notification: ["notifications"],
  portal_read_all_notifications: ["notifications"],
};

type LlmProfileForm = {
  id?: number;
  name: string;
  api_base_url: string;
  api_key: string;
  model_name: string;
  is_active: boolean;
};

const DEFAULT_RAG_CONFIG: PortalRagConfig = {
  top_k: 4,
  min_score: 0.32,
  min_hits: 1,
  max_bullets: 4,
  enable_rewrite: true
};

function nowIso() {
  return new Date().toISOString();
}

function normalizeRagConfig(input: unknown): PortalRagConfig {
  if (!input || typeof input !== "object") return DEFAULT_RAG_CONFIG;
  const raw = input as Partial<PortalRagConfig>;
  const topK = Number(raw.top_k);
  const minScore = Number(raw.min_score);
  const minHits = Number(raw.min_hits);
  const maxBullets = Number(raw.max_bullets);
  return {
    top_k: Number.isFinite(topK) ? Math.max(1, Math.min(8, Math.round(topK))) : DEFAULT_RAG_CONFIG.top_k,
    min_score: Number.isFinite(minScore) ? Math.max(0, Math.min(1, minScore)) : DEFAULT_RAG_CONFIG.min_score,
    min_hits: Number.isFinite(minHits) ? Math.max(1, Math.min(5, Math.round(minHits))) : DEFAULT_RAG_CONFIG.min_hits,
    max_bullets: Number.isFinite(maxBullets) ? Math.max(1, Math.min(8, Math.round(maxBullets))) : DEFAULT_RAG_CONFIG.max_bullets,
    enable_rewrite: typeof raw.enable_rewrite === "boolean" ? raw.enable_rewrite : DEFAULT_RAG_CONFIG.enable_rewrite
  };
}

function resolveOwnerKey() {
  const uid = (localStorage.getItem("portal_profile_id") || "").trim();
  if (uid) return `uid:${uid}`;
  const phone = (localStorage.getItem("portal_profile_phone") || "").trim();
  if (phone) return `phone:${phone.replace(/[^0-9]/g, "")}`;
  const token = localStorage.getItem("portal_token") || "";
  if (token) return `token:${token.replace(/[^a-zA-Z0-9]/g, "").slice(-16)}`;
  return "anonymous";
}

function cacheKey(owner: string) {
  return `${CHAT_CACHE_PREFIX}_${owner.replace(/[^0-9a-zA-Z:_-]/g, "_")}`;
}

function draftCacheKey(owner: string) {
  return `${CHAT_DRAFT_PREFIX}_${owner.replace(/[^0-9a-zA-Z:_-]/g, "_")}`;
}

function normalizeTime(value: unknown) {
  if (typeof value !== "string" || !value.trim()) return nowIso();
  const ts = Date.parse(value);
  if (!Number.isNaN(ts)) return new Date(ts).toISOString();
  return nowIso();
}

function parseStoredProfileId(raw: string | null): number | null {
  if (!raw) return null;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed <= 0) return null;
  return Math.trunc(parsed);
}

function buildProfileForm(profile?: PortalLlmProfile | null): LlmProfileForm {
  return {
    id: profile?.id,
    name: profile?.name || "",
    api_base_url: profile?.api_base_url || "",
    api_key: "",
    model_name: profile?.model_name || "",
    is_active: Boolean(profile?.is_active),
  };
}

function formatMessageTimestamp(createdAt: string) {
  const ts = Date.parse(createdAt);
  if (Number.isNaN(ts)) return "";
  const target = new Date(ts);
  const now = new Date();
  const timePart = target.toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit"
  });
  const isSameDay = target.toDateString() === now.toDateString();
  if (isSameDay) return timePart;
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (target.toDateString() === yesterday.toDateString()) {
    return `昨天 ${timePart}`;
  }
  if (target.getFullYear() === now.getFullYear()) {
    const datePart = target.toLocaleDateString("zh-CN", {
      month: "2-digit",
      day: "2-digit"
    });
    return `${datePart} ${timePart}`;
  }
  const datePart = target.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  });
  return `${datePart} ${timePart}`;
}

function extractFeedbackOrderPicks(pendingAction: PendingActionPayload | null) {
  if (!pendingAction) return [] as FeedbackOrderPick[];
  if (pendingAction.type !== "CREATE_FEEDBACK" || pendingAction.status !== "COLLECTING") return [] as FeedbackOrderPick[];
  const picksRaw = Array.isArray(pendingAction.picks) ? pendingAction.picks : [];
  return picksRaw
    .map((item) => (item && typeof item === "object" ? (item as FeedbackOrderPick) : null))
    .filter((item): item is FeedbackOrderPick => Boolean(item));
}

function formatFeedbackPickLabel(item: FeedbackOrderPick, index: number) {
  if (item.label && item.label.trim()) return item.label.trim();
  if (item.order_no) return item.order_no;
  return `第${index + 1}个订单`;
}

function asEventTime(value: unknown) {
  if (typeof value !== "string") return null;
  const ts = Date.parse(value);
  return Number.isNaN(ts) ? null : ts;
}

function computeStageTimings(
  eventsPreview: Array<Record<string, unknown>> | undefined,
  totalMs: number
): StageTimings {
  const events = Array.isArray(eventsPreview) ? eventsPreview : [];
  const lastInitIndex = (() => {
    for (let i = events.length - 1; i >= 0; i -= 1) {
      if (events[i]?.state === "INIT") return i;
    }
    return -1;
  })();
  const turnEvents = lastInitIndex >= 0 ? events.slice(lastInitIndex) : events;
  const firstInit = turnEvents.find((item) => item.state === "INIT");
  const firstPlanning = turnEvents.find((item) => item.state === "PLANNING");
  const firstRespond = turnEvents.find((item) => item.state === "RESPOND");
  const toolEvents = turnEvents.filter((item) => item.state === "TOOL_EXEC");

  const initTs = asEventTime(firstInit?.created_at);
  const planningTs = asEventTime(firstPlanning?.created_at);
  const respondTs = asEventTime(firstRespond?.created_at);
  const toolTimes = toolEvents.map((item) => asEventTime(item.created_at)).filter((v): v is number => v !== null);

  const firstToolTs = toolTimes.length ? Math.min(...toolTimes) : null;
  const lastToolTs = toolTimes.length ? Math.max(...toolTimes) : null;

  const ruleMs =
    initTs !== null && planningTs !== null && planningTs >= initTs ? planningTs - initTs : null;
  const toolMs =
    firstToolTs !== null && lastToolTs !== null && lastToolTs >= firstToolTs
      ? lastToolTs - firstToolTs
      : toolTimes.length
      ? 0
      : null;
  const answerStartTs = lastToolTs ?? planningTs ?? initTs;
  const answerMs =
    answerStartTs !== null && respondTs !== null && respondTs >= answerStartTs
      ? respondTs - answerStartTs
      : null;

  return {
    ruleMs,
    toolMs,
    answerMs,
    toolCount: toolEvents.length,
    totalMs: Math.max(0, Math.round(totalMs)),
  };
}

function collectDomainsFromEvents(eventsPreview: Array<Record<string, unknown>> | undefined): string[] {
  const events = Array.isArray(eventsPreview) ? eventsPreview : [];
  const domains = new Set<string>();
  events
    .filter((item) => item?.state === "TOOL_EXEC")
    .forEach((item) => {
      const toolName = String(item?.tool_name || "");
      const mapped = TOOL_DOMAIN_MAP[toolName] || [];
      mapped.forEach((domain) => domains.add(domain));
    });
  return Array.from(domains);
}

function emitPortalThemeChange(theme: "light" | "eye" | "dark") {
  window.dispatchEvent(new CustomEvent("portal:theme-change", { detail: { theme } }));
}

function detectThemeFromText(text: string): "light" | "eye" | "dark" | null {
  const value = String(text || "");
  if (value.includes("护眼模式")) return "eye";
  if (value.includes("黑夜模式") || value.includes("夜间模式") || value.includes("深色模式")) return "dark";
  if (value.includes("白天模式") || value.includes("白天主题") || value.includes("标准模式") || value.includes("浅色模式")) return "light";
  return null;
}

function formatMs(ms: number | null) {
  if (ms === null) return "-";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function renderInlineBold(text: string, keyPrefix: string) {
  const segments = String(text || "").split(/(\*\*[^*]+\*\*)/g);
  return segments.map((segment, index) => {
    const key = `${keyPrefix}-${index}`;
    if (segment.startsWith("**") && segment.endsWith("**") && segment.length > 4) {
      return <strong key={key}>{segment.slice(2, -2)}</strong>;
    }
    return <span key={key}>{segment}</span>;
  });
}

function renderMessageContent(content: string, keyPrefix: string) {
  const lines = String(content || "").split(/\r?\n/);
  return lines.map((line, index) => {
    const isBlank = !line.trim();
    return (
      <p key={`${keyPrefix}-line-${index}`} className={`portal-msg-line ${isBlank ? "blank" : ""}`}>
        {isBlank ? "\u00A0" : renderInlineBold(line, `${keyPrefix}-seg-${index}`)}
      </p>
    );
  });
}

export default function SupportChatPage() {
  const ownerRef = useRef(resolveOwnerKey());
  const runIdRef = useRef("");
  const requestStartedAtRef = useRef<number | null>(null);
  const chatStreamRef = useRef<HTMLDivElement | null>(null);
  const [messages, setMessages] = useState<PortalMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [hint, setHint] = useState("");
  const [runId, setRunId] = useState("");
  const [confirmRequired, setConfirmRequired] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingActionPayload | null>(null);
  const [modelName, setModelName] = useState(localStorage.getItem(OLLAMA_MODEL_KEY) || FALLBACK_MODEL);
  const [modelOptions, setModelOptions] = useState<string[]>([FALLBACK_MODEL]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelStarting, setModelStarting] = useState(false);
  const [modelReachable, setModelReachable] = useState(true);
  const [showRagTuning, setShowRagTuning] = useState(false);
  const [lastLatencyMs, setLastLatencyMs] = useState<number | null>(null);
  const [lastStageTimings, setLastStageTimings] = useState<StageTimings | null>(null);
  const [lastRouting, setLastRouting] = useState<ChatRouting | null>(null);
  const [fallbackModalOpen, setFallbackModalOpen] = useState(false);
  const [ragConfig, setRagConfig] = useState<PortalRagConfig>(() => {
    try {
      const raw = localStorage.getItem(RAG_CONFIG_KEY);
      return raw ? normalizeRagConfig(JSON.parse(raw)) : DEFAULT_RAG_CONFIG;
    } catch {
      return DEFAULT_RAG_CONFIG;
    }
  });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [profilesLoading, setProfilesLoading] = useState(false);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileTesting, setProfileTesting] = useState(false);
  const [profileModelsLoading, setProfileModelsLoading] = useState(false);
  const [profiles, setProfiles] = useState<PortalLlmProfile[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState<number | null>(() =>
    parseStoredProfileId(localStorage.getItem(PROFILE_SELECTED_KEY))
  );
  const [profileModels, setProfileModels] = useState<PortalLlmModelOption[]>([]);
  const [editingProfileId, setEditingProfileId] = useState<number | null>(null);
  const [profileForm, setProfileForm] = useState<LlmProfileForm>(() => buildProfileForm(null));
  const [profileModelManual, setProfileModelManual] = useState("");
  const [profileValidateHint, setProfileValidateHint] = useState("");
  const [showAdvancedProfileFields, setShowAdvancedProfileFields] = useState(false);
  const [historyExpanded, setHistoryExpanded] = useState(0);
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);
  const [clearingContext, setClearingContext] = useState(false);
  const [cacheHydrated, setCacheHydrated] = useState(false);

  const feedbackOrderPicks = useMemo(() => extractFeedbackOrderPicks(pendingAction), [pendingAction]);
  const hiddenHistoryCount = useMemo(
    () => Math.max(0, messages.length - (CHAT_HISTORY_BASE_VISIBLE + historyExpanded)),
    [messages.length, historyExpanded]
  );
  const visibleMessages = useMemo(() => {
    const keep = CHAT_HISTORY_BASE_VISIBLE + historyExpanded;
    if (keep <= 0) return messages;
    return messages.slice(Math.max(0, messages.length - keep));
  }, [messages, historyExpanded]);
  const avgLatencyMs = useMemo(() => {
    const assistant = messages.filter((item) => item.role === "assistant" && typeof item.latencyMs === "number");
    if (!assistant.length) return null;
    const sum = assistant.reduce((acc, item) => acc + (item.latencyMs || 0), 0);
    return Math.round(sum / assistant.length);
  }, [messages]);
  const selectedProfile = useMemo(
    () => profiles.find((item) => item.id === selectedProfileId) || null,
    [profiles, selectedProfileId]
  );
  const activeProfile = useMemo(() => profiles.find((item) => item.is_active) || null, [profiles]);
  const preferredProfileSeed = useMemo(
    () => selectedProfile || activeProfile || profiles[0] || null,
    [selectedProfile, activeProfile, profiles]
  );
  const selectedProfileLabel = useMemo(
    () => (selectedProfile?.model_name || "").trim(),
    [selectedProfile]
  );
  const localModelStatusLabel = useMemo(
    () => (modelReachable ? `本地 Ollama：${modelName}` : "本地 Ollama：未连接"),
    [modelReachable, modelName]
  );

  useEffect(() => {
    const maxExpand = Math.max(0, messages.length - CHAT_HISTORY_BASE_VISIBLE);
    setHistoryExpanded((prev) => Math.max(0, Math.min(prev, maxExpand)));
  }, [messages.length]);

  useEffect(() => {
    localStorage.setItem(OLLAMA_MODEL_KEY, modelName);
  }, [modelName]);

  useEffect(() => {
    localStorage.setItem(RAG_CONFIG_KEY, JSON.stringify(ragConfig));
  }, [ragConfig]);

  useEffect(() => {
    if (typeof selectedProfileId === "number" && selectedProfileId > 0) {
      localStorage.setItem(PROFILE_SELECTED_KEY, String(selectedProfileId));
      return;
    }
    localStorage.removeItem(PROFILE_SELECTED_KEY);
  }, [selectedProfileId]);

  useEffect(() => {
    ownerRef.current = resolveOwnerKey();
    const owner = ownerRef.current;
    const raw = localStorage.getItem(cacheKey(owner));
    const fallbackDraft = localStorage.getItem(draftCacheKey(owner));
    if (!raw) {
      if (typeof fallbackDraft === "string") {
        setDraft(fallbackDraft);
      }
      setCacheHydrated(true);
      return;
    }
    try {
      const parsed = JSON.parse(raw) as {
        messages?: PortalMessage[];
        runId?: string;
        draft?: string;
        confirmRequired?: boolean;
        pendingAction?: PendingActionPayload | null;
        lastStageTimings?: StageTimings | null;
        lastRouting?: ChatRouting | null;
        updatedAt?: string;
        historyExpanded?: number;
      };
      const restored = Array.isArray(parsed.messages)
        ? parsed.messages
            .map((msg, idx) => ({
              id: msg.id || `cached-${idx}`,
              role: msg.role === "assistant" ? "assistant" : "user",
              content: String(msg.content || "").trim(),
              createdAt: normalizeTime(msg.createdAt),
              runId: msg.runId || "",
              latencyMs: typeof msg.latencyMs === "number" ? msg.latencyMs : undefined
            }))
            .filter((msg) => msg.content)
        : [];
      if (restored.length) {
        setMessages(restored);
      }
      if (typeof parsed.draft === "string") {
        setDraft(parsed.draft);
      } else if (typeof fallbackDraft === "string") {
        setDraft(fallbackDraft);
      }
      const restoredRunId = String(parsed.runId || "");
      if (restoredRunId) {
        setRunId(restoredRunId);
        runIdRef.current = restoredRunId;
      }
      const latestAssistant = [...restored].reverse().find((item) => item.role === "assistant");
      if (latestAssistant && typeof latestAssistant.latencyMs === "number") {
        setLastLatencyMs(latestAssistant.latencyMs);
      }
      setLastStageTimings(parsed.lastStageTimings || null);
      setLastRouting(parsed.lastRouting || null);
      setConfirmRequired(Boolean(parsed.confirmRequired));
      setPendingAction(parsed.pendingAction || null);
      if (typeof parsed.historyExpanded === "number" && Number.isFinite(parsed.historyExpanded)) {
        setHistoryExpanded(Math.max(0, Math.trunc(parsed.historyExpanded)));
      }
    } catch {
      if (typeof fallbackDraft === "string") {
        setDraft(fallbackDraft);
      }
    } finally {
      setCacheHydrated(true);
    }
  }, []);

  useEffect(() => {
    if (!cacheHydrated) return;
    setMessages((prev) => {
      if (prev.length) return prev;
      return [
        {
          id: `assistant-guide-${Date.now()}`,
          role: "assistant",
          content: STARTER_GUIDE_MESSAGE,
          createdAt: nowIso(),
          runId: ""
        }
      ];
    });
  }, [cacheHydrated]);

  useEffect(() => {
    const token = localStorage.getItem("portal_token") || "";
    if (!token) return;
    let disposed = false;
    const loadCloud = async () => {
      try {
        const payload = await listPortalChatHistory(300);
        if (disposed) return;
        const items = Array.isArray(payload.items) ? payload.items : [];
        if (!items.length) return;
        const cloudMessages: PortalMessage[] = items
          .map((item, idx) => ({
            id: `cloud-${item.id || idx}`,
            role: item.role === "assistant" ? "assistant" : "user",
            content: String(item.content || "").trim(),
            createdAt: normalizeTime(item.created_at),
            runId: item.run_id ? String(item.run_id) : ""
          }))
          .filter((item) => item.content);
        if (!cloudMessages.length) return;
        setMessages((prev) => {
          if (!prev.length) return cloudMessages;
          const prevLatest = Date.parse(prev[prev.length - 1]?.createdAt || "");
          const cloudLatest = Date.parse(cloudMessages[cloudMessages.length - 1]?.createdAt || "");
          if (Number.isNaN(cloudLatest)) return prev;
          if (Number.isNaN(prevLatest)) return cloudMessages;
          if (cloudLatest >= prevLatest || cloudMessages.length > prev.length) {
            return cloudMessages;
          }
          return prev;
        });
        const latestRunId = [...cloudMessages].reverse().find((msg) => msg.runId)?.runId || "";
        if (latestRunId) {
          setRunId(latestRunId);
          runIdRef.current = latestRunId;
        }
        setLastLatencyMs(null);
        setLastStageTimings(null);
        setLastRouting(null);
      } catch {
        // fallback to local cache
      }
    };
    void loadCloud();
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    if (!cacheHydrated) return;
    const payload = {
      messages,
      runId,
      draft,
      confirmRequired,
      pendingAction,
      lastStageTimings,
      lastRouting,
      historyExpanded,
      updatedAt: nowIso()
    };
    localStorage.setItem(cacheKey(ownerRef.current), JSON.stringify(payload));
    localStorage.setItem(draftCacheKey(ownerRef.current), draft);
  }, [cacheHydrated, messages, runId, draft, confirmRequired, pendingAction, lastStageTimings, lastRouting, historyExpanded]);

  useEffect(() => {
    const stream = chatStreamRef.current;
    if (!stream) return;
    const distanceToBottom = stream.scrollHeight - stream.scrollTop - stream.clientHeight;
    if (distanceToBottom <= CHAT_BOTTOM_STICKY_GAP) {
      stream.scrollTop = stream.scrollHeight;
      setShowJumpToLatest(false);
    }
  }, [messages.length, loading]);

  const loadModels = async () => {
    setModelsLoading(true);
    try {
      const payload = await getOllamaModels();
      const options = payload.models?.length ? payload.models : [FALLBACK_MODEL];
      setModelOptions(options);
      setModelReachable(Boolean(payload.reachable));
      if (!options.includes(modelName)) setModelName(options[0]);
    } catch {
      setModelOptions([FALLBACK_MODEL]);
      setModelReachable(false);
      setHint("模型列表获取失败，已切换为手动默认模型。");
    } finally {
      setModelsLoading(false);
    }
  };

  useEffect(() => {
    void loadModels();
  }, []);

  const loadProfiles = async (preferredProfileId?: number | null) => {
    setProfilesLoading(true);
    setProfileValidateHint("");
    try {
      const payload = await listPortalLlmProfiles();
      const items = Array.isArray(payload.items) ? payload.items : [];
      setProfiles(items);

      const validIds = new Set(items.map((item) => item.id));
      let nextSelected: number | null =
        typeof preferredProfileId === "number" ? preferredProfileId : selectedProfileId;
      if (nextSelected !== null && !validIds.has(nextSelected)) {
        nextSelected = null;
      }
      if (nextSelected === null && payload.active_profile_id && validIds.has(payload.active_profile_id)) {
        nextSelected = payload.active_profile_id;
      }
      if (nextSelected === null) {
        nextSelected = null;
      }
      setSelectedProfileId(nextSelected);
    } catch (error) {
      setHint(error instanceof Error ? error.message : "模型配置加载失败");
    } finally {
      setProfilesLoading(false);
    }
  };

  useEffect(() => {
    void loadProfiles();
  }, []);

  useEffect(() => {
    if (!selectedProfileId) return;
    if (profiles.some((item) => item.id === selectedProfileId)) return;
    const fallback = profiles.find((item) => item.is_active) || null;
    setSelectedProfileId(fallback?.id || null);
  }, [profiles, selectedProfileId]);

  const openCreateProfile = () => {
    setSelectedProfileId(null);
    setEditingProfileId(null);
    if (preferredProfileSeed) {
      setProfileForm({
        id: undefined,
        name: "",
        api_base_url: preferredProfileSeed.api_base_url || "",
        api_key: "",
        model_name: "",
        is_active: true,
      });
      setShowAdvancedProfileFields(false);
    } else {
      setProfileForm(buildProfileForm(null));
      setShowAdvancedProfileFields(true);
    }
    setProfileModels([]);
    setProfileModelManual("");
    setProfileValidateHint("");
    setSettingsOpen(true);
  };

  const openEditProfile = (profile: PortalLlmProfile) => {
    setSelectedProfileId(profile.id);
    setEditingProfileId(profile.id);
    setProfileForm(buildProfileForm(profile));
    setShowAdvancedProfileFields(true);
    setProfileModels([]);
    setProfileModelManual(profile.model_name || "");
    setProfileValidateHint("");
    setSettingsOpen(true);
  };

  const handleRefreshProfileModels = async (profileId?: number) => {
    const targetId = profileId || editingProfileId || selectedProfileId || preferredProfileSeed?.id || null;
    if (!targetId) {
      setProfileValidateHint("请先选择或创建一个配置");
      return;
    }
    setProfileModelsLoading(true);
    try {
      const payload = await fetchPortalLlmModels(targetId);
      const items = Array.isArray(payload.items) ? payload.items : [];
      setProfileModels(items);
      if (items.length && !profileForm.model_name) {
        setProfileForm((prev) => ({ ...prev, model_name: items[0].id }));
      }
      setProfileValidateHint(items.length ? `已拉取 ${items.length} 个模型` : "未获取到模型，可手动填写模型名");
    } catch (error) {
      setProfileValidateHint(error instanceof Error ? error.message : "模型列表拉取失败，请手动填写模型名");
    } finally {
      setProfileModelsLoading(false);
    }
  };

  const handleValidateProfile = async (profileId?: number) => {
    const targetId = profileId || editingProfileId || selectedProfileId || preferredProfileSeed?.id || null;
    if (!targetId) {
      setProfileValidateHint("请先选择配置");
      return;
    }
    setProfileTesting(true);
    try {
      const payload = await validatePortalLlmProfile(targetId);
      const count = Number(payload.model_count || 0);
      setProfileValidateHint(`连接成功，可用模型数：${count}`);
    } catch (error) {
      setProfileValidateHint(error instanceof Error ? error.message : "连接校验失败");
    } finally {
      setProfileTesting(false);
    }
  };

  const handleSaveProfile = async () => {
    const isCreate = !editingProfileId;
    const seed = preferredProfileSeed;
    const autoReuseConnection = isCreate && !showAdvancedProfileFields && !!seed;
    const base = (profileForm.api_base_url.trim() || (autoReuseConnection ? seed?.api_base_url : "") || "").trim();
    const model = profileForm.model_name.trim() || profileModelManual.trim();
    const manualName = profileForm.name.trim();
    let name = manualName;
    if (!name && model) {
      const baseName = model.slice(0, 48);
      const existing = new Set((profiles || []).map((item) => item.name));
      if (!existing.has(baseName)) {
        name = baseName;
      } else {
        let cursor = 2;
        while (existing.has(`${baseName}-${cursor}`) && cursor < 1000) cursor += 1;
        name = `${baseName}-${cursor}`;
      }
    }
    if (!name || !base || !model) {
      setProfileValidateHint("请填写模型名（无复用配置时需补充 API 地址与密钥）");
      return;
    }
    setProfileSaving(true);
    setProfileValidateHint("");
    try {
      if (editingProfileId) {
        const payload: {
          name: string;
          provider_type: "OPENAI_COMPAT";
          api_base_url: string;
          model_name: string;
          is_active: boolean;
          api_key?: string;
        } = {
          name,
          provider_type: "OPENAI_COMPAT",
          api_base_url: base,
          model_name: model,
          is_active: Boolean(profileForm.is_active),
        };
        if (profileForm.api_key.trim()) {
          payload.api_key = profileForm.api_key.trim();
        }
        const updated = await updatePortalLlmProfile(editingProfileId, payload);
        await loadProfiles(updated.id);
        setSelectedProfileId(updated.id);
      } else {
        const created = await createPortalLlmProfile({
          name,
          provider_type: "OPENAI_COMPAT",
          api_base_url: base,
          api_key: profileForm.api_key.trim() || undefined,
          model_name: model,
          is_active: Boolean(profileForm.is_active),
        });
        await loadProfiles(created.id);
        setSelectedProfileId(created.id);
      }
      setSettingsOpen(false);
      setHint("模型配置已保存，下一条消息将使用新配置");
    } catch (error) {
      setProfileValidateHint(error instanceof Error ? error.message : "保存失败");
    } finally {
      setProfileSaving(false);
    }
  };

  const handleDeleteProfile = async (profileId: number) => {
    if (!window.confirm("确认删除该模型配置？")) return;
    try {
      await deletePortalLlmProfile(profileId);
      await loadProfiles();
      if (selectedProfileId === profileId) {
        setSelectedProfileId(activeProfile?.id || null);
      }
      setHint("模型配置已删除");
    } catch (error) {
      setHint(error instanceof Error ? error.message : "删除失败");
    }
  };

  const handleActivateProfile = async (profileId: number) => {
    try {
      const activated = await activatePortalLlmProfile(profileId);
      await loadProfiles(activated.id);
      setSelectedProfileId(activated.id);
      setHint(`已切换到配置：${activated.name}`);
    } catch (error) {
      setHint(error instanceof Error ? error.message : "切换配置失败");
    }
  };

  const handleStartModel = async () => {
    setModelStarting(true);
    try {
      await warmupOllamaModel(modelName);
      setModelReachable(true);
      setHint(`模型已启动：${modelName}`);
    } catch (error) {
      setModelReachable(false);
      setHint(error instanceof Error ? error.message : "模型启动失败，请先确认本地 Ollama 服务已运行。");
    } finally {
      setModelStarting(false);
    }
  };

  const appendAssistantMessage = (content: string, latencyMs?: number) => {
    setMessages((prev) => [
      ...prev,
      {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content,
        createdAt: nowIso(),
        runId: runIdRef.current || "",
        latencyMs
      }
    ]);
    if (typeof latencyMs === "number") {
      setLastLatencyMs(latencyMs);
    }
  };

  const handleSend = async (text: string) => {
    const message = (text || "").trim();
    if (!message) return;

    let forceNewRun = false;
    let nextHint = "";
    const lastMessage = messages.length ? messages[messages.length - 1] : null;
    const lastMessageTs = lastMessage ? Date.parse(lastMessage.createdAt) : Number.NaN;
    const isContextExpired =
      Number.isFinite(lastMessageTs) && Date.now() - Number(lastMessageTs) > CHAT_CONTEXT_EXPIRE_MS;
    if (isContextExpired) {
      runIdRef.current = "";
      setRunId("");
      setConfirmRequired(false);
      setPendingAction(null);
      setLastStageTimings(null);
      setLastRouting(null);
      nextHint = "距离上次会话已超过30分钟，已自动开启新会话。";
    } else if (pendingAction && !CONFIRM_WORD_RE.test(message)) {
      nextHint = "当前流程还没结束。您可以回复“确认”继续，或回复“取消”后再办新需求。";
    }

    setLoading(true);
    setHint(nextHint);
    setDraft("");
    localStorage.removeItem(draftCacheKey(ownerRef.current));
    requestStartedAtRef.current = Date.now();

    const userMsg: PortalMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: message,
      createdAt: nowIso(),
      runId: runIdRef.current || ""
    };
    setMessages((prev) => [...prev, userMsg]);

    try {
      const token = localStorage.getItem("portal_token") || "";
      const usingProfile = Boolean(selectedProfile);
      const response = await postChat({
        message,
        runId: runIdRef.current || undefined,
        forceNewRun,
        modelProvider: usingProfile ? "OPENAI_COMPAT" : "OLLAMA",
        providerType: usingProfile ? "OPENAI_COMPAT" : "OLLAMA",
        providerModel: usingProfile ? selectedProfile?.model_name : modelName,
        providerBaseUrl: usingProfile ? selectedProfile?.api_base_url : undefined,
        providerProfileId: usingProfile ? selectedProfile?.id : undefined,
        portalMode: true,
        authToken: token || undefined,
        portalRagConfig: ragConfig
      });
      if (response.run_id) {
        runIdRef.current = response.run_id;
        setRunId(response.run_id);
      }
      setConfirmRequired(Boolean(response.confirm_required));
      setPendingAction(response.pending_action && typeof response.pending_action === "object" ? response.pending_action : null);
      setLastRouting(response.routing || null);
      const latencyMs = requestStartedAtRef.current ? Date.now() - requestStartedAtRef.current : undefined;
      if (typeof latencyMs === "number") {
        setLastStageTimings(computeStageTimings(response.events_preview, latencyMs));
      } else {
        setLastStageTimings(null);
      }
      appendAssistantMessage(response.final_response || "", latencyMs);
      const routingTheme = (response.routing?.ui_theme as "light" | "eye" | "dark" | undefined) || undefined;
      const textTheme = detectThemeFromText(response.final_response || "");
      const nextTheme = routingTheme || textTheme;
      if (nextTheme) {
        emitPortalThemeChange(nextTheme);
      }
      if (response.routing?.lane === "fallback_readonly" || response.routing?.write_allowed === false) {
        setFallbackModalOpen(true);
      }
      const updatedDomains = collectDomainsFromEvents(response.events_preview);
      if (updatedDomains.length) {
        emitPortalDataUpdated(updatedDomains);
        if (updatedDomains.includes("notifications") || updatedDomains.includes("orders") || updatedDomains.includes("profile")) {
          emitPortalNotificationRefresh();
        }
      }
    } catch (error) {
      const latencyMs = requestStartedAtRef.current ? Date.now() - requestStartedAtRef.current : undefined;
      setLastStageTimings(null);
      setLastRouting(null);
      appendAssistantMessage(error instanceof Error ? error.message : "系统繁忙，请稍后再试。", latencyMs);
      setConfirmRequired(false);
      setPendingAction(null);
    } finally {
      requestStartedAtRef.current = null;
      setLoading(false);
    }
  };

  const startNewConversation = () => {
    runIdRef.current = "";
    setRunId("");
    setConfirmRequired(false);
    setPendingAction(null);
    setLastStageTimings(null);
    setLastLatencyMs(null);
    setLastRouting(null);
    setDraft("");
    localStorage.removeItem(draftCacheKey(ownerRef.current));
    setHint("已开启新会话");
  };

  const clearContextAndHistory = async () => {
    const confirmed = window.confirm("确认清除聊天记录并重置上下文吗？");
    if (!confirmed) return;
    setClearingContext(true);
    try {
      const result = await clearPortalChatHistory();
      runIdRef.current = "";
      setRunId("");
      setMessages([]);
      setDraft("");
      setConfirmRequired(false);
      setPendingAction(null);
      setLastStageTimings(null);
      setLastLatencyMs(null);
      setLastRouting(null);
      setHistoryExpanded(0);
      localStorage.removeItem(cacheKey(ownerRef.current));
      localStorage.removeItem(draftCacheKey(ownerRef.current));
      setHint(
        `已清除 ${result.deleted_count || 0} 条聊天记录并重置上下文。`
      );
    } catch (error) {
      setHint(error instanceof Error ? error.message : "清除上下文失败");
    } finally {
      setClearingContext(false);
    }
  };

  const runIdShort = runId ? `${runId.slice(0, 8)}...${runId.slice(-6)}` : "未建立";
  const routingLaneLabel = lastRouting?.lane ? LANE_LABELS[lastRouting.lane] || lastRouting.lane : "";
  const routingModelLabel =
    lastRouting?.model_source === "cloud"
      ? "云模型"
      : lastRouting?.model_source === "local"
      ? "本地模型"
      : "无模型";
  const capabilityLabel = lastRouting?.write_allowed === false ? "只读" : "可执行写操作";
  const manualQueueRaw =
    lastRouting?.manual_queue && typeof lastRouting.manual_queue === "object"
      ? (lastRouting.manual_queue as Record<string, unknown>)
      : null;
  const manualQueueStatus = String(manualQueueRaw?.status || "").toUpperCase();
  const manualQueueAhead =
    typeof manualQueueRaw?.ahead_count === "number" && Number.isFinite(manualQueueRaw.ahead_count)
      ? Math.max(0, Math.trunc(manualQueueRaw.ahead_count))
      : 0;
  const manualQueueEta =
    typeof manualQueueRaw?.eta_minutes === "number" && Number.isFinite(manualQueueRaw.eta_minutes)
      ? Math.max(1, Math.trunc(manualQueueRaw.eta_minutes))
      : 1;
  const showManualQueueCard =
    Boolean(lastRouting?.manual_handoff) && ["WAITING", "CONNECTING"].includes(manualQueueStatus);

  return (
    <div className="portal-page">
      <div className="portal-chat-layout">
        <aside className="portal-chat-side">
          <div className="portal-card">
            <div className="portal-card-title">客服中心</div>
            <div className="portal-chat-menu">
              {CHAT_MENU.map((item) => (
                <button key={item.label} className="portal-ghost" type="button" onClick={() => void handleSend(item.prompt)}>
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          <div className="portal-card hotline">
            <div>紧急热线</div>
            <strong>400-888-0000</strong>
          </div>
        </aside>

        <section className="portal-card portal-chat-main">
          <div className="portal-chat-header">
            <div>
              <div className="portal-card-title">安燃助手 (AnRan Assistant)</div>
              <div className="portal-subtitle">在线客服</div>
            </div>
            <div className="portal-chat-actions">
              <div className="portal-chat-model">
                <span>配置</span>
                <select
                  value={selectedProfileId ? `profile-${selectedProfileId}` : "local"}
                  onChange={(event) => {
                    const value = event.target.value;
                    if (value === "local") {
                      setSelectedProfileId(null);
                      return;
                    }
                    const parsed = Number(value.replace("profile-", ""));
                    if (Number.isFinite(parsed) && parsed > 0) {
                      setSelectedProfileId(Math.trunc(parsed));
                    }
                  }}
                  disabled={profilesLoading}
                >
                  <option value="local">{localModelStatusLabel}</option>
                  {profiles.map((item) => (
                    <option key={item.id} value={`profile-${item.id}`}>
                      {item.model_name}
                    </option>
                  ))}
                </select>
                <button
                  className="portal-ghost"
                  type="button"
                  onClick={() => {
                    if (selectedProfile) {
                      openEditProfile(selectedProfile);
                      return;
                    }
                    openCreateProfile();
                  }}
                >
                  模型设置
                </button>
              </div>
              {!selectedProfile ? (
                <div className="portal-chat-model">
                  <span>模型</span>
                  <select value={modelName} onChange={(event) => setModelName(event.target.value)} disabled={modelsLoading}>
                    {modelOptions.map((item) => (
                      <option key={item} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                  <button className="portal-ghost" type="button" onClick={() => void loadModels()} disabled={modelsLoading}>
                    {modelsLoading ? "刷新中..." : "刷新模型"}
                  </button>
                  <button className="portal-ghost" type="button" onClick={() => void handleStartModel()} disabled={modelStarting}>
                    {modelStarting ? "启动中..." : "启动模型"}
                  </button>
                </div>
              ) : null}
              <button className="portal-ghost" type="button" onClick={startNewConversation}>
                新会话
              </button>
              <button className="portal-ghost" type="button" onClick={() => void clearContextAndHistory()} disabled={clearingContext}>
                {clearingContext ? "清除中..." : "清除上下文"}
              </button>
              <button className="portal-ghost" type="button" onClick={() => setShowRagTuning((prev) => !prev)}>
                {showRagTuning ? "收起调参" : "RAG 调参"}
              </button>
            </div>
          </div>

          <div className="portal-chat-meta">
            <span className="portal-pill">会话ID：{runIdShort}</span>
            <span className="portal-pill">消息数：{messages.length}</span>
            {lastLatencyMs !== null ? (
              <span className="portal-pill">上次响应：{(lastLatencyMs / 1000).toFixed(2)}s</span>
            ) : null}
            {avgLatencyMs !== null ? (
              <span className="portal-pill">会话均值：{(avgLatencyMs / 1000).toFixed(2)}s</span>
            ) : null}
            {selectedProfile ? (
              <span className="portal-pill active">当前云模型：{selectedProfileLabel}</span>
            ) : (
              <span className={`portal-pill ${modelReachable ? "active" : "warn"}`}>{localModelStatusLabel}</span>
            )}
            {selectedProfile ? <span className="portal-pill">{selectedProfile.model_name}</span> : null}
            {confirmRequired ? <span className="portal-pill warn">当前有待确认操作</span> : null}
            {lastRouting ? (
              <>
                <span className={`portal-pill ${lastRouting.mode === "v2" ? "active" : ""}`}>
                  路由：{lastRouting.mode === "v2" ? "V2" : "Legacy"}
                </span>
                <span className="portal-pill">通道：{routingLaneLabel || "-"}</span>
                <span className="portal-pill">来源：{routingModelLabel}</span>
                <span className={`portal-pill ${lastRouting.write_allowed === false ? "warn" : "active"}`}>
                  能力：{capabilityLabel}
                </span>
              </>
            ) : null}
          </div>
          {lastStageTimings ? (
            <div className="portal-chat-meta">
              <span className="portal-pill">规则：{formatMs(lastStageTimings.ruleMs)}</span>
              <span className="portal-pill">
                工具：{formatMs(lastStageTimings.toolMs)}（{lastStageTimings.toolCount}次）
              </span>
              <span className="portal-pill">生成：{formatMs(lastStageTimings.answerMs)}</span>
            </div>
          ) : null}

          {hint ? <div className="auth-hint">{hint}</div> : null}
          {lastRouting?.write_allowed === false ? (
            <div className="auth-hint">
              当前在只读兜底模式：可查订单/资料/安全问答，写操作需先配置可用云模型。
            </div>
          ) : null}
          {lastLatencyMs !== null && lastLatencyMs > SLOW_THRESHOLD_MS ? (
            <div className="auth-hint">
              当前响应偏慢（{(lastLatencyMs / 1000).toFixed(2)}s）。
              {selectedProfile && !/flash/i.test(selectedProfile.model_name)
                ? " 建议切换到更快模型（如 GLM-4.7-Flash）做客服场景。"
                : " 建议降低模型复杂度或减少长上下文后再试。"}
            </div>
          ) : null}
          {showManualQueueCard ? (
            <div className="portal-card">
              <div className="portal-card-title">人工客服排队中</div>
              <div className="portal-subtitle">
                {manualQueueStatus === "CONNECTING"
                  ? "正在为您接入人工客服，已轮到您。"
                  : `当前前面还有 ${manualQueueAhead} 位，预计约 ${manualQueueEta} 分钟。`}
              </div>
              <div className="portal-subtitle">有问题您可以先问我，我会先帮您整理诉求。</div>
              <div className="portal-chat-quick">
                <button
                  className="portal-pill"
                  type="button"
                  disabled={loading}
                  onClick={() => void handleSend("取消人工排队")}
                >
                  取消人工排队
                </button>
              </div>
            </div>
          ) : null}
          {showRagTuning ? (
            <div className="portal-chat-tuning">
              <div className="portal-chat-tuning-row">
                <label>
                  TopK
                  <input
                    type="number"
                    min={1}
                    max={8}
                    value={ragConfig.top_k}
                    onChange={(event) =>
                      setRagConfig((prev) => normalizeRagConfig({ ...prev, top_k: Number(event.target.value) }))
                    }
                  />
                </label>
                <label>
                  MinScore
                  <input
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={ragConfig.min_score}
                    onChange={(event) =>
                      setRagConfig((prev) => normalizeRagConfig({ ...prev, min_score: Number(event.target.value) }))
                    }
                  />
                </label>
                <label>
                  MinHits
                  <input
                    type="number"
                    min={1}
                    max={5}
                    value={ragConfig.min_hits}
                    onChange={(event) =>
                      setRagConfig((prev) => normalizeRagConfig({ ...prev, min_hits: Number(event.target.value) }))
                    }
                  />
                </label>
                <label className="portal-chat-tuning-check">
                  <input
                    type="checkbox"
                    checked={ragConfig.enable_rewrite}
                    onChange={(event) =>
                      setRagConfig((prev) => normalizeRagConfig({ ...prev, enable_rewrite: event.target.checked }))
                    }
                  />
                  Query 改写
                </label>
              </div>
            </div>
          ) : null}

          <div
            ref={chatStreamRef}
            className="portal-chat-stream scrollbar-thin"
            onScroll={() => {
              const stream = chatStreamRef.current;
              if (!stream) return;
              const distanceToBottom = stream.scrollHeight - stream.scrollTop - stream.clientHeight;
              const shouldStick = distanceToBottom <= CHAT_BOTTOM_STICKY_GAP;
              setShowJumpToLatest(!shouldStick);
            }}
          >
            {hiddenHistoryCount > 0 ? (
              <div className="portal-chat-history-tools">
                <button
                  className="portal-pill"
                  type="button"
                  onClick={() => setHistoryExpanded((prev) => prev + CHAT_HISTORY_EXPAND_STEP)}
                >
                  展开 5 条
                </button>
              </div>
            ) : null}
            {visibleMessages.map((msg) => (
              <div key={msg.id} className={`portal-bubble ${msg.role === "user" ? "user" : "assistant"}`}>
                <div className="portal-bubble-content">{renderMessageContent(msg.content, msg.id)}</div>
                <small>
                  {formatMessageTimestamp(msg.createdAt)}
                  {msg.role === "assistant" && typeof msg.latencyMs === "number"
                    ? ` · ${(msg.latencyMs / 1000).toFixed(2)}s`
                    : ""}
                </small>
              </div>
            ))}
            {loading ? (
              <div className="portal-chat-loading">
                <span className="portal-spinner" />
                <span>正在生成回复...</span>
              </div>
            ) : null}
          </div>
          {showJumpToLatest ? (
            <div className="portal-chat-history-tools">
              <button
                className="portal-pill active"
                type="button"
                onClick={() => {
                  const stream = chatStreamRef.current;
                  if (!stream) return;
                  stream.scrollTo({ top: stream.scrollHeight, behavior: "smooth" });
                  setShowJumpToLatest(false);
                }}
              >
                回到最新消息
              </button>
            </div>
          ) : null}

          {feedbackOrderPicks.length ? (
            <div className="portal-chat-picker">
              <div className="portal-card-title">请选择要投诉的订单</div>
              <div className="portal-chat-picker-list">
                {feedbackOrderPicks.map((item, index) => (
                  <button
                    key={`${item.order_id || item.order_no || index}`}
                    className="portal-pill"
                    type="button"
                    disabled={loading}
                    onClick={() => void handleSend(item.order_no || `第${index + 1}个`)}
                  >
                    {formatFeedbackPickLabel(item, index)}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {confirmRequired ? (
            <div className="portal-chat-quick">
              <button className="portal-pill active" type="button" onClick={() => void handleSend("确认")}>确认执行</button>
              <button className="portal-pill" type="button" onClick={() => void handleSend("取消")}>取消操作</button>
            </div>
          ) : (
            <div className="portal-chat-quick">
              {QUICK_QUESTIONS.map((item) => (
                <button key={item} className="portal-pill" type="button" onClick={() => void handleSend(item)}>
                  {item}
                </button>
              ))}
            </div>
          )}

          <div className="portal-chat-input">
            <input
              value={draft}
              onChange={(event) => {
                const value = event.target.value;
                setDraft(value);
                localStorage.setItem(draftCacheKey(ownerRef.current), value);
              }}
              placeholder="例如：下单一瓶15kg、查订单、查看我的地址"
              onKeyDown={(event) => {
                if (event.key === "Enter") void handleSend(draft);
              }}
            />
            <button className="portal-cta" type="button" onClick={() => void handleSend(draft)} disabled={loading}>
              发送
            </button>
          </div>
        </section>

        <aside className="portal-chat-side">
          <div className="portal-card alert-card">
            <div className="alert-title">安全提醒</div>
            <div className="alert-desc">如发现燃气泄漏，请立即关闭阀门并开窗通风，勿操作电器，及时联系紧急热线。</div>
          </div>
          <div className="portal-card">
            <div className="portal-card-title">猜你想问</div>
            <div className="portal-chat-menu">
              {QUICK_QUESTIONS.map((item) => (
                <button key={item} className="portal-ghost" type="button" onClick={() => void handleSend(item)}>
                  {item}
                </button>
              ))}
            </div>
          </div>
        </aside>
      </div>

      {settingsOpen ? (
        <div className="portal-drawer-mask" onClick={() => setSettingsOpen(false)}>
          <div className="portal-drawer" onClick={(event) => event.stopPropagation()}>
            <div className="portal-drawer-header">
              <div>
                <div className="portal-card-title">模型设置（魔搭/OpenAI 兼容）</div>
                <div className="portal-subtitle">配置保存在账号下，切换后下一条消息立即生效，不重置会话。</div>
              </div>
              <button className="portal-ghost" type="button" onClick={() => setSettingsOpen(false)}>
                关闭
              </button>
            </div>
            <div className="portal-drawer-body">
              <div className="portal-drawer-form">
                <div className="portal-drawer-form-toolbar">
                  <button className="portal-ghost" type="button" onClick={openCreateProfile}>
                    + 新建配置（复用连接）
                  </button>
                  {selectedProfile ? (
                    <>
                      {!selectedProfile.is_active ? (
                        <button className="portal-ghost" type="button" onClick={() => void handleActivateProfile(selectedProfile.id)}>
                          设为默认
                        </button>
                      ) : null}
                      <button className="portal-ghost danger" type="button" onClick={() => void handleDeleteProfile(selectedProfile.id)}>
                        删除当前配置
                      </button>
                    </>
                  ) : null}
                </div>
                {!editingProfileId && preferredProfileSeed ? (
                  <div className="portal-subtitle">
                    新建时将复用连接：{preferredProfileSeed.api_base_url} / {preferredProfileSeed.api_key_masked}
                  </div>
                ) : null}
                <label>
                  模型名（可手填）
                  <input
                    value={profileForm.model_name}
                    onChange={(event) => {
                      const value = event.target.value;
                      setProfileForm((prev) => ({ ...prev, model_name: value }));
                      setProfileModelManual(value);
                    }}
                    placeholder="例如：qwen-plus / qwen2.5-7b-instruct"
                  />
                </label>
                {editingProfileId || showAdvancedProfileFields || !preferredProfileSeed ? (
                  <>
                    <label>
                      配置名（可选）
                      <input
                        value={profileForm.name}
                        onChange={(event) => setProfileForm((prev) => ({ ...prev, name: event.target.value }))}
                        placeholder="留空将自动按模型名生成"
                      />
                    </label>
                    <label>
                      API Base URL
                      <input
                        value={profileForm.api_base_url}
                        onChange={(event) => setProfileForm((prev) => ({ ...prev, api_base_url: event.target.value }))}
                        placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
                      />
                    </label>
                    <label>
                      API Key {editingProfileId ? "（留空表示不修改）" : "（留空则复用已有配置密钥）"}
                      <input
                        type="password"
                        value={profileForm.api_key}
                        onChange={(event) => setProfileForm((prev) => ({ ...prev, api_key: event.target.value }))}
                        placeholder={editingProfileId ? "留空不修改" : "可留空复用已有密钥"}
                      />
                    </label>
                  </>
                ) : null}
                {!editingProfileId && preferredProfileSeed ? (
                  <button
                    className="portal-ghost"
                    type="button"
                    onClick={() => setShowAdvancedProfileFields((prev) => !prev)}
                  >
                    {showAdvancedProfileFields ? "收起高级配置" : "展开高级配置"}
                  </button>
                ) : null}

                <div className="portal-chat-quick">
                  <button className="portal-ghost" type="button" onClick={() => void handleRefreshProfileModels()} disabled={profileModelsLoading}>
                    {profileModelsLoading ? "拉取中..." : "刷新模型列表"}
                  </button>
                  <button className="portal-ghost" type="button" onClick={() => void handleValidateProfile()} disabled={profileTesting}>
                    {profileTesting ? "校验中..." : "测试连接"}
                  </button>
                </div>
                {profileModels.length ? (
                  <div className="portal-profile-model-tags">
                    {profileModels.map((item) => (
                      <button
                        key={item.id}
                        className={`portal-pill ${profileForm.model_name === item.id ? "active" : ""}`}
                        type="button"
                        onClick={() => setProfileForm((prev) => ({ ...prev, model_name: item.id }))}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                ) : null}
                <label className="portal-chat-tuning-check">
                  <input
                    type="checkbox"
                    checked={profileForm.is_active}
                    onChange={(event) => setProfileForm((prev) => ({ ...prev, is_active: event.target.checked }))}
                  />
                  保存后设为默认配置
                </label>
                {profileValidateHint ? <div className="portal-subtitle">{profileValidateHint}</div> : null}
                <div className="portal-chat-quick">
                  <button className="portal-ghost" type="button" onClick={() => setSettingsOpen(false)}>
                    取消
                  </button>
                  <button className="portal-cta" type="button" onClick={() => void handleSaveProfile()} disabled={profileSaving}>
                    {profileSaving ? "保存中..." : editingProfileId ? "更新配置" : "创建配置"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {fallbackModalOpen ? (
        <div className="portal-modal" onClick={() => setFallbackModalOpen(false)}>
          <div className="portal-modal-card" onClick={(event) => event.stopPropagation()}>
            <div className="portal-modal-header">
              <h3>当前为只读兜底模式</h3>
              <button className="portal-ghost" type="button" onClick={() => setFallbackModalOpen(false)}>
                关闭
              </button>
            </div>
            <div className="portal-modal-list">
              <div>目前可继续为您提供：查订单、查资料、价格/年检咨询、安全应急建议。</div>
              <div>如需我直接代您下单、改址、投诉或修改资料，请先在模型设置绑定可用云模型。</div>
            </div>
            <div className="portal-chat-quick">
              <button className="portal-ghost" type="button" onClick={() => setFallbackModalOpen(false)}>
                稍后再说
              </button>
              <button
                className="portal-cta"
                type="button"
                onClick={() => {
                  setFallbackModalOpen(false);
                  setSettingsOpen(true);
                }}
              >
                去模型设置
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
