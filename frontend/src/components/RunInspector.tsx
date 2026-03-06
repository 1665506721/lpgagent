import { useMemo, useState } from "react";
import type { AgentEvent, RunDetail } from "../lib/api";

type RunInspectorProps = {
  runDetail: RunDetail | null;
  loading: boolean;
};

const STATE_STYLES: Record<string, string> = {
  INIT: "bg-blue-50 text-blue-700",
  PLANNING: "bg-amber-50 text-amber-700",
  EXEC_TOOL: "bg-purple-50 text-purple-700",
  TOOL_EXEC: "bg-purple-50 text-purple-700",
  RESPOND: "bg-emerald-50 text-emerald-700",
  DONE: "bg-cyan-50 text-cyan-700",
  ERROR: "bg-rose-50 text-rose-700",
  FALLBACK: "bg-slate-100 text-slate-600"
};

const STATE_LABELS: Record<string, string> = {
  INIT: "接收用户请求",
  PLANNING: "识别用户意图与关键信息",
  EXEC_TOOL: "调用业务系统",
  TOOL_EXEC: "调用业务系统",
  RESPOND: "生成客服回复",
  DONE: "请求完成",
  ERROR: "处理异常",
  FALLBACK: "使用兜底回复"
};

const TECH_LABELS: Record<string, string> = {
  INIT: "INIT",
  PLANNING: "PLANNING",
  EXEC_TOOL: "系统调用",
  TOOL_EXEC: "系统调用",
  RESPOND: "RESPOND",
  DONE: "DONE",
  ERROR: "ERROR",
  FALLBACK: "FALLBACK"
};

const TOOL_LABELS: Record<string, string> = {
  query_order: "订单查询服务",
  external_query_order: "外部订单查询",
  external_query_orders_by_phone: "外部订单列表",
  create_order: "下单服务",
  modify_order_address: "改址服务",
  create_ticket: "工单服务",
  safety_search: "安全知识库",
  kb_search: "知识库检索"
};

const INTENT_LABELS: Record<string, string> = {
  ORDER_QUERY: "订单查询",
  ORDER_URGE: "催单处理",
  ORDER_CREATE: "下单请求",
  ORDER_MODIFY_ADDRESS: "修改地址",
  TICKET_COMPLAINT: "投诉工单",
  SAFETY_HIGH: "安全应急",
  SAFETY_LOW: "安全咨询",
  IDENTITY: "身份说明",
  GREETING: "服务接待",
  UNKNOWN: "其他需求"
};

function formatTime(value?: string) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const month = date.getMonth() + 1;
  const day = date.getDate();
  const hour = date.getHours().toString().padStart(2, "0");
  const minute = date.getMinutes().toString().padStart(2, "0");
  return `${month}月${day}日 ${hour}:${minute}`;
}

function formatJson(value: unknown) {
  if (!value) {
    return "-";
  }
  return JSON.stringify(value, null, 2);
}

function buildSummary(events: AgentEvent[]) {
  const planningEvent = events.find((event) => event.state === "PLANNING");
  const planningPayload =
    (planningEvent?.output_json as Record<string, unknown> | undefined) ||
    (planningEvent?.input_json as Record<string, unknown> | undefined) ||
    {};
  const intent = typeof planningPayload.intent === "string" ? planningPayload.intent : "UNKNOWN";
  const intentLabel = INTENT_LABELS[intent] || "其他需求";
  const slots =
    planningPayload.slots && typeof planningPayload.slots === "object"
      ? (planningPayload.slots as Record<string, unknown>)
      : {};
  const slotParts: string[] = [];
  if (slots.order_id) {
    slotParts.push(`订单号 ${slots.order_id}`);
  }
  if (slots.phone_last4) {
    slotParts.push(`手机号后四位 ${slots.phone_last4}`);
  }
  if (slots.new_address) {
    slotParts.push(`新地址 ${slots.new_address}`);
  }
  if (slots.address) {
    slotParts.push(`地址 ${slots.address}`);
  }
  if (slots.quantity) {
    slotParts.push(`数量 ${slots.quantity}`);
  }
  if (slots.cylinder_type) {
    slotParts.push(`规格 ${slots.cylinder_type}`);
  }
  const slotsLabel = slotParts.length > 0 ? slotParts.join("，") : "未识别到关键信息";

  let methodLabel = "标准流程";
  if (planningPayload.ui_action === "SHOW_FORM" || planningPayload.form_id) {
    methodLabel = "需要补充信息（表单）";
  } else if (Array.isArray(planningPayload.missing_fields)) {
    methodLabel = "需要补充信息（字段未齐）";
  } else if (typeof planningPayload.route === "string" && planningPayload.route.includes("rule")) {
    methodLabel = "规则直达，无需补充信息";
  }

  const systemSet = new Set<string>();
  events.forEach((event) => {
    if (event.tool_name) {
      systemSet.add(TOOL_LABELS[event.tool_name] || "业务系统");
    }
  });
  const systemLabel = systemSet.size > 0 ? Array.from(systemSet).join("、") : "未调用系统";

  return {
    intentLabel,
    slotsLabel,
    methodLabel,
    systemLabel
  };
}

export default function RunInspector({ runDetail, loading }: RunInspectorProps) {
  const [expandedId, setExpandedId] = useState<string | number | null>(null);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [processOpen, setProcessOpen] = useState(false);

  const events = runDetail?.events || [];
  const lastEvent = useMemo(() => {
    if (!events.length) {
      return null;
    }
    return events[events.length - 1];
  }, [events]);
  const lastStateLabel = lastEvent ? STATE_LABELS[lastEvent.state] || lastEvent.state : "-";

  const summary = useMemo(() => buildSummary(events), [events]);

  const handleCopy = async () => {
    if (!runDetail?.run_id) {
      return;
    }
    await navigator.clipboard.writeText(runDetail.run_id);
  };

  const toggleEvent = (event: AgentEvent) => {
    const key = event.id ?? event.step_index;
    setExpandedId((prev) => (prev === key ? null : key));
  };

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="sticky top-6 z-10">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-slate-400">服务摘要</p>
              <h3 className="mt-2 text-lg font-semibold text-slate-900">最近一次服务</h3>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setSummaryOpen((prev) => !prev)}
                className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-500 hover:border-slate-300 hover:text-slate-700"
              >
                {summaryOpen ? "收起摘要" : "展开摘要"}
              </button>
              <button
                type="button"
                onClick={handleCopy}
                className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-500 hover:border-slate-300 hover:text-slate-700"
              >
                复制服务编号
              </button>
            </div>
          </div>
          {summaryOpen ? (
            <div className="mt-4 grid gap-4">
              <div className="grid gap-3 text-sm text-slate-600">
                <div className="flex items-center justify-between">
                  <span>服务编号</span>
                  <span className="truncate text-slate-900">{runDetail?.run_id || "-"}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>智能引擎</span>
                  <span className="text-slate-900">{runDetail?.model_provider || "-"}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>创建时间</span>
                  <span className="text-slate-900">{formatTime(runDetail?.created_at)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>当前状态</span>
                  <span className="text-slate-900">{lastStateLabel}</span>
                </div>
              </div>
              <div className="rounded-xl border border-slate-100 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                <div className="flex items-center justify-between">
                  <span>用户意图</span>
                  <span className="text-slate-900">{summary.intentLabel}</span>
                </div>
                <div className="mt-2 flex items-start justify-between gap-4">
                  <span>识别信息</span>
                  <span className="text-right text-slate-900">{summary.slotsLabel}</span>
                </div>
                <div className="mt-2 flex items-center justify-between">
                  <span>处理方式</span>
                  <span className="text-slate-900">{summary.methodLabel}</span>
                </div>
                <div className="mt-2 flex items-center justify-between">
                  <span>调用系统</span>
                  <span className="text-slate-900">{summary.systemLabel}</span>
                </div>
              </div>
            </div>
          ) : (
            <p className="mt-3 text-xs text-slate-400">点击展开查看服务编号与处理摘要。</p>
          )}
        </div>
      </div>

      <div className="flex-1 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-slate-900">处理过程</h3>
          <div className="flex items-center gap-2">
            {loading ? <span className="text-xs text-slate-400">更新中...</span> : null}
            <button
              type="button"
              onClick={() => setProcessOpen((prev) => !prev)}
              className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-500 hover:border-slate-300 hover:text-slate-700"
            >
              {processOpen ? "收起过程" : "展开过程"}
            </button>
          </div>
        </div>
        {processOpen ? (
          <div className="mt-4 space-y-3 overflow-y-auto pr-2 scrollbar-thin">
          {events.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
              暂无过程记录。
            </div>
          ) : null}
          {events.map((event) => {
            const key = event.id ?? event.step_index;
            const stateLabel = STATE_LABELS[event.state] || "流程节点";
            const techLabel = TECH_LABELS[event.state] || "-";
            const systemLabel = event.tool_name ? TOOL_LABELS[event.tool_name] || "业务系统" : null;
            return (
              <div key={key} className="rounded-xl border border-slate-200 bg-slate-50">
                <button
                  type="button"
                  onClick={() => toggleEvent(event)}
                  className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left text-sm text-slate-700"
                >
                  <div className="flex items-center gap-3">
                    <span
                      className={`rounded-full px-3 py-1 text-xs font-semibold ${
                        STATE_STYLES[event.state] || "bg-slate-100 text-slate-600"
                      }`}
                    >
                      步骤 {event.step_index}
                    </span>
                    <div>
                      <div className="text-sm font-medium text-slate-800">{stateLabel}</div>
                      <div className="text-xs text-slate-400">
                        系统标记：{techLabel}
                        {systemLabel ? ` · 调用：${systemLabel}` : ""}
                      </div>
                    </div>
                  </div>
                  <span className="text-xs text-slate-400">{formatTime(event.created_at)}</span>
                </button>
                {expandedId === key ? (
                  <div className="border-t border-slate-200 bg-white px-4 py-3 text-xs text-slate-600">
                    <div className="grid gap-3">
                      <div>
                        <p className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">请求明细</p>
                        <pre className="whitespace-pre-wrap rounded-lg bg-slate-100 p-3">
                          {formatJson(event.input_json)}
                        </pre>
                      </div>
                      <div>
                        <p className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">响应明细</p>
                        <pre className="whitespace-pre-wrap rounded-lg bg-slate-100 p-3">
                          {formatJson(event.output_json)}
                        </pre>
                      </div>
                      <div className="grid gap-3 md:grid-cols-2">
                        <div>
                          <p className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">系统请求</p>
                          <pre className="whitespace-pre-wrap rounded-lg bg-slate-100 p-3">
                            {formatJson(event.tool_input)}
                          </pre>
                        </div>
                        <div>
                          <p className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">系统返回</p>
                          <pre className="whitespace-pre-wrap rounded-lg bg-slate-100 p-3">
                            {formatJson(event.tool_output)}
                          </pre>
                        </div>
                      </div>
                      <div>
                        <p className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">规则判定</p>
                        <pre className="whitespace-pre-wrap rounded-lg bg-slate-100 p-3">
                          {formatJson(event.policy_result)}
                        </pre>
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>
            );
          })}
          </div>
        ) : (
          <p className="mt-3 text-xs text-slate-400">展开查看处理过程与事件详情。</p>
        )}
      </div>
    </div>
  );
}
