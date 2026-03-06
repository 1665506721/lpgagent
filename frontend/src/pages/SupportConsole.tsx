import { useEffect, useMemo, useState } from "react";
import ChatPanel from "../components/ChatPanel";
import FormDialog from "../components/FormDialog";
import RunInspector from "../components/RunInspector";
import type { FormPayload, RunDetail } from "../lib/api";
import { getRunDetail, postChat } from "../lib/api";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  meta?: {
    note?: string;
  };
};

type ProviderProfile = {
  id: string;
  name: string;
  providerType: "OLLAMA" | "OPENAI" | "ANTHROPIC" | "OPENAI_COMPAT";
  modelName: string;
  apiBase?: string;
  apiKey?: string;
};

type ProviderDraft = Omit<ProviderProfile, "id">;

const DEFAULT_PROFILE: ProviderProfile = {
  id: "ollama-default",
  name: "本地 Ollama",
  providerType: "OLLAMA",
  modelName: "deepseek-r1:8b",
  apiBase: "http://localhost:11434",
  apiKey: ""
};

const PROVIDER_OPTIONS: Array<{ value: ProviderProfile["providerType"]; label: string }> = [
  { value: "OLLAMA", label: "本地 Ollama" },
  { value: "OPENAI", label: "OpenAI" },
  { value: "ANTHROPIC", label: "Anthropic" },
  { value: "OPENAI_COMPAT", label: "OpenAI 兼容" }
];

function nowLabel() {
  const now = new Date();
  return `${now.getHours().toString().padStart(2, "0")}:${now
    .getMinutes()
    .toString()
    .padStart(2, "0")}`;
}

function ensureProfiles(raw: unknown): ProviderProfile[] {
  if (!Array.isArray(raw)) {
    return [DEFAULT_PROFILE];
  }
  const list = raw
    .filter((item) => item && typeof item === "object")
    .map((item) => {
      const data = item as Partial<ProviderProfile>;
      return {
        id: data.id || `profile-${Math.random()}`,
        name: data.name || "未命名模型",
        providerType: (data.providerType as ProviderProfile["providerType"]) || "OLLAMA",
        modelName: data.modelName || DEFAULT_PROFILE.modelName,
        apiBase: data.apiBase || "",
        apiKey: data.apiKey || ""
      };
    });
  const hasDefault = list.some((profile) => profile.id === DEFAULT_PROFILE.id);
  return hasDefault ? list : [DEFAULT_PROFILE, ...list];
}

function providerHint(profile?: ProviderProfile) {
  if (!profile) {
    return "当前使用：未选择";
  }
  if (profile.providerType === "OLLAMA") {
    return `当前使用：${profile.name}（${profile.modelName}）`;
  }
  if (profile.providerType === "OPENAI") {
    return `当前使用：${profile.name}（${profile.modelName || "OpenAI"}）`;
  }
  if (profile.providerType === "ANTHROPIC") {
    return `当前使用：${profile.name}（${profile.modelName || "Anthropic"}）`;
  }
  return `当前使用：${profile.name}（兼容接口 / ${profile.modelName}）`;
}

export default function SupportConsole() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null);
  const [userId] = useState("1");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeForm, setActiveForm] = useState<FormPayload | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [runLoading, setRunLoading] = useState(false);
  const [showInspector, setShowInspector] = useState(false);

  const [profiles, setProfiles] = useState<ProviderProfile[]>([DEFAULT_PROFILE]);
  const [activeProfileId, setActiveProfileId] = useState<string>(DEFAULT_PROFILE.id);
  const [showProfileEditor, setShowProfileEditor] = useState(false);
  const [profileDraft, setProfileDraft] = useState<ProviderDraft>({
    name: "",
    providerType: "OPENAI",
    modelName: "",
    apiBase: "",
    apiKey: ""
  });

  useEffect(() => {
    const storedProfiles = localStorage.getItem("provider_profiles");
    const storedActive = localStorage.getItem("active_profile_id");
    if (storedProfiles) {
      try {
        const parsed = JSON.parse(storedProfiles);
        const sanitized = ensureProfiles(parsed);
        setProfiles(sanitized);
        if (storedActive && sanitized.some((item) => item.id === storedActive)) {
          setActiveProfileId(storedActive);
        } else {
          setActiveProfileId(sanitized[0]?.id || DEFAULT_PROFILE.id);
        }
        return;
      } catch {
        setProfiles([DEFAULT_PROFILE]);
        setActiveProfileId(DEFAULT_PROFILE.id);
      }
    }
    setProfiles([DEFAULT_PROFILE]);
    setActiveProfileId(DEFAULT_PROFILE.id);
  }, []);

  useEffect(() => {
    localStorage.setItem("provider_profiles", JSON.stringify(profiles));
  }, [profiles]);

  useEffect(() => {
    localStorage.setItem("active_profile_id", activeProfileId);
  }, [activeProfileId]);

  const activeProfile = useMemo(() => {
    return profiles.find((profile) => profile.id === activeProfileId) || profiles[0];
  }, [profiles, activeProfileId]);

  const hintText = useMemo(() => providerHint(activeProfile), [activeProfile]);
  const layoutClass = showInspector
    ? "grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]"
    : "flex flex-col gap-6";

  const canSaveProfile = useMemo(() => {
    if (!profileDraft.name.trim() || !profileDraft.modelName.trim()) {
      return false;
    }
    if (profileDraft.providerType !== "OLLAMA" && !profileDraft.apiKey?.trim()) {
      return false;
    }
    if (profileDraft.providerType === "OPENAI_COMPAT" && !profileDraft.apiBase?.trim()) {
      return false;
    }
    return true;
  }, [profileDraft]);

  const pushMessage = (
    role: "user" | "assistant",
    content: string,
    meta?: ChatMessage["meta"]
  ) => {
    setMessages((prev) => [
      ...prev,
      {
        id: `${role}-${Date.now()}-${Math.random()}`,
        role,
        content,
        createdAt: nowLabel(),
        meta
      }
    ]);
  };

  const handleError = (message: string) => {
    setError(message);
    window.setTimeout(() => setError(null), 4000);
  };

  const refreshRunDetail = async (runId: string) => {
    setRunLoading(true);
    try {
      const data = await getRunDetail(runId);
      setRunDetail({
        run_id: data.run_id || runId,
        created_at: data.created_at,
        model_provider: data.model_provider,
        events: data.events || []
      });
    } finally {
      setRunLoading(false);
    }
  };

  const handleSend = async (
    message: string,
    display?: { content?: string; meta?: ChatMessage["meta"] }
  ) => {
    setLoading(true);
    pushMessage("user", display?.content ?? message, display?.meta);
    try {
      const profile = activeProfile || DEFAULT_PROFILE;
      const response = await postChat({
        message,
        userId,
        modelProvider: profile.providerType,
        providerType: profile.providerType,
        providerName: profile.name,
        providerModel: profile.modelName,
        providerBaseUrl: profile.apiBase,
        providerApiKey: profile.apiKey,
        openaiApiKey:
          profile.providerType === "OPENAI" || profile.providerType === "OPENAI_COMPAT"
            ? profile.apiKey
            : undefined,
        anthropicApiKey: profile.providerType === "ANTHROPIC" ? profile.apiKey : undefined
      });
      pushMessage("assistant", response.final_response);
      if (response.run_id) {
        await refreshRunDetail(response.run_id);
      }
      const uiAction = response.ui_action || (response.form ? "SHOW_FORM" : undefined);
      if (uiAction === "SHOW_FORM" && response.form) {
        setActiveForm(response.form);
        setFormOpen(true);
      }
    } catch (err) {
      handleError(err instanceof Error ? err.message : "网络异常，请稍后重试");
    } finally {
      setLoading(false);
    }
  };

  const handleFormSubmit = async (formId: string, payload: Record<string, unknown>) => {
    const message = `提交表单：${JSON.stringify({ form_id: formId, payload })}`;
    await handleSend(message, {
      content: "已填写表单",
      meta: { note: "表单已提交，正在为您处理" }
    });
  };

  const handleSaveProfile = () => {
    if (!canSaveProfile) {
      handleError("请完善模型配置后再保存");
      return;
    }
    const newProfile: ProviderProfile = {
      id: `profile-${Date.now()}`,
      name: profileDraft.name.trim(),
      providerType: profileDraft.providerType,
      modelName: profileDraft.modelName.trim(),
      apiBase:
        profileDraft.providerType === "OLLAMA"
          ? profileDraft.apiBase?.trim() || DEFAULT_PROFILE.apiBase
          : profileDraft.apiBase?.trim() || "",
      apiKey: profileDraft.apiKey?.trim() || ""
    };
    setProfiles((prev) => [...prev, newProfile]);
    setActiveProfileId(newProfile.id);
    setProfileDraft({
      name: "",
      providerType: "OPENAI",
      modelName: "",
      apiBase: "",
      apiKey: ""
    });
    setShowProfileEditor(false);
  };

  const handleRemoveProfile = () => {
    if (!activeProfile || activeProfile.id === DEFAULT_PROFILE.id) {
      return;
    }
    const nextProfiles = profiles.filter((profile) => profile.id !== activeProfile.id);
    setProfiles(nextProfiles.length ? nextProfiles : [DEFAULT_PROFILE]);
    setActiveProfileId(nextProfiles[0]?.id || DEFAULT_PROFILE.id);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-amber-50/40 to-emerald-50/40">
      <div className="mx-auto max-w-6xl px-6 pb-12 pt-8">
        <div className="flex flex-col gap-6">
          <header className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-slate-400">客服工作台</p>
              <h1 className="mt-2 text-3xl font-semibold text-slate-900">安燃助手客服台</h1>
              <p className="mt-2 text-sm text-slate-500">
                面向客服的对话与处理回放面板，支持表单补齐与服务追踪。
              </p>
            </div>
            <div className="flex w-full max-w-sm flex-col gap-2">
              <label className="text-xs text-slate-500">智能引擎</label>
              <select
                value={activeProfileId}
                onChange={(event) => setActiveProfileId(event.target.value)}
                className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 shadow-sm"
              >
                {profiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {profile.name}
                  </option>
                ))}
              </select>
              <span className="text-xs text-slate-400">{hintText}</span>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setShowProfileEditor((prev) => !prev)}
                  className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-500 hover:border-slate-300 hover:text-slate-700"
                >
                  {showProfileEditor ? "收起配置" : "添加模型"}
                </button>
                <button
                  type="button"
                  onClick={handleRemoveProfile}
                  className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-500 hover:border-slate-300 hover:text-slate-700"
                >
                  删除当前配置
                </button>
                <button
                  type="button"
                  onClick={() => setShowInspector((prev) => !prev)}
                  className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-500 hover:border-slate-300 hover:text-slate-700"
                >
                  {showInspector ? "隐藏回放" : "查看回放"}
                </button>
              </div>
              {showProfileEditor ? (
                <div className="mt-2 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                  <div className="grid gap-3 text-xs text-slate-600">
                    <div>
                      <label className="text-xs text-slate-500">配置名称</label>
                      <input
                        value={profileDraft.name}
                        onChange={(event) =>
                          setProfileDraft((prev) => ({ ...prev, name: event.target.value }))
                        }
                        placeholder="例如：GPT-5.2 个人账号"
                        className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-700"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-slate-500">模型来源</label>
                      <select
                        value={profileDraft.providerType}
                        onChange={(event) =>
                          setProfileDraft((prev) => ({
                            ...prev,
                            providerType: event.target.value as ProviderProfile["providerType"]
                          }))
                        }
                        className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700"
                      >
                        {PROVIDER_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="text-xs text-slate-500">模型名称</label>
                      <input
                        value={profileDraft.modelName}
                        onChange={(event) =>
                          setProfileDraft((prev) => ({
                            ...prev,
                            modelName: event.target.value
                          }))
                        }
                        placeholder="例如：gpt-5.2 / gemini-pro-3 / deepseek-r1:8b"
                        className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-700"
                      />
                    </div>
                    {profileDraft.providerType === "OLLAMA" ||
                    profileDraft.providerType === "OPENAI_COMPAT" ? (
                      <div>
                        <label className="text-xs text-slate-500">API Base URL</label>
                        <input
                          value={profileDraft.apiBase}
                          onChange={(event) =>
                            setProfileDraft((prev) => ({
                              ...prev,
                              apiBase: event.target.value
                            }))
                          }
                          placeholder={
                            profileDraft.providerType === "OLLAMA"
                              ? "http://localhost:11434"
                              : "https://api.your-provider.com/v1"
                          }
                          className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-700"
                        />
                      </div>
                    ) : null}
                    {profileDraft.providerType !== "OLLAMA" ? (
                      <div>
                        <label className="text-xs text-slate-500">API Key</label>
                        <input
                          type="password"
                          value={profileDraft.apiKey}
                          onChange={(event) =>
                            setProfileDraft((prev) => ({
                              ...prev,
                              apiKey: event.target.value
                            }))
                          }
                          placeholder="请输入 API Key"
                          className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-700"
                        />
                      </div>
                    ) : null}
                  </div>
                  <div className="mt-4 flex items-center justify-between">
                    <span className="text-xs text-slate-400">配置仅保存在当前浏览器。</span>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => setShowProfileEditor(false)}
                        className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-500 hover:border-slate-300 hover:text-slate-700"
                      >
                        取消
                      </button>
                      <button
                        type="button"
                        onClick={handleSaveProfile}
                        className="rounded-full bg-slate-900 px-3 py-1 text-xs font-semibold text-white hover:bg-slate-800"
                      >
                        保存配置
                      </button>
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
          </header>

          {error ? (
            <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-600">
              {error}
            </div>
          ) : null}

          <div className={layoutClass}>
            <section className="flex min-h-[640px] flex-col gap-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold text-slate-900">对话区</h2>
                  <p className="text-sm text-slate-500">与客户对话并触发表单补齐流程。</p>
                </div>
                <span className="text-xs text-slate-400">对话仅展示客服相关信息。</span>
              </div>
              <ChatPanel messages={messages} onSend={handleSend} loading={loading} />
            </section>

            {showInspector ? (
              <section className="min-h-[640px]">
                <RunInspector runDetail={runDetail} loading={runLoading} />
              </section>
            ) : null}
          </div>
        </div>
      </div>
      <FormDialog
        open={formOpen}
        form={activeForm}
        onClose={() => {
          setFormOpen(false);
          setActiveForm(null);
        }}
        onSubmit={handleFormSubmit}
      />
    </div>
  );
}
