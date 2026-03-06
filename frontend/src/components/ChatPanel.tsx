import type { KeyboardEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  meta?: {
    note?: string;
  };
};

type ChatPanelProps = {
  messages: ChatMessage[];
  onSend: (message: string) => Promise<void>;
  loading: boolean;
};

type AssistantMessageType = "guide" | "progress" | "result" | "normal";

type ResultInfo = {
  orderId?: string;
  status?: string;
  eta?: string;
  ticketId?: string;
};

type OrderListInfo = {
  header: string;
  orders: string[];
};

const STATUS_RULES = [
  { rule: /已出库|已安排配送/, label: "已出库（已安排配送）" },
  { rule: /配送中/, label: "配送中" },
  { rule: /已送达|送达/, label: "已送达" },
  { rule: /已取消/, label: "已取消" },
  { rule: /已确认/, label: "已确认" },
  { rule: /已创建/, label: "已创建" }
];

const GUIDE_RULE = /(欢迎|可以为您|我可以|我能|服务范围|随时告诉我)/;
const PROGRESS_RULE = /(正在|处理中|查询中|请稍候|为您查询)/;
const RESULT_RULE =
  /(订单号|工单号|当前状态|预计|已出库|配送中|已送达|已取消|已确认|已创建)/;

function classifyAssistantMessage(content: string): AssistantMessageType {
  if (PROGRESS_RULE.test(content)) {
    return "progress";
  }
  if (RESULT_RULE.test(content)) {
    return "result";
  }
  if (GUIDE_RULE.test(content)) {
    return "guide";
  }
  return "normal";
}

function extractResultInfo(content: string): ResultInfo | null {
  const orderMatch = content.match(/订单号[:：]?\s*(\d{6,10})/);
  const ticketMatch = content.match(/工单号[:：]?\s*(\d{4,10})/);
  const etaMatch = content.match(
    /(\d{1,2}月\d{1,2}日\s*\d{1,2}:\d{2}|今天\s*\d{1,2}:\d{2}|明天\s*\d{1,2}:\d{2})/
  );
  const statusMatch = STATUS_RULES.find(({ rule }) => rule.test(content));
  const result: ResultInfo = {
    orderId: orderMatch?.[1],
    ticketId: ticketMatch?.[1],
    status: statusMatch?.label,
    eta: etaMatch?.[1]
  };
  if (!result.orderId && !result.ticketId && !result.status) {
    return null;
  }
  return result;
}

function extractOrderList(content: string): OrderListInfo | null {
  const marker = "订单列表：";
  if (!content.includes(marker)) {
    return null;
  }
  const [header, listText] = content.split(marker);
  const lines = (listText || "")
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && /^\d+\./.test(line));
  if (!lines.length) {
    return null;
  }
  return { header: header.trim(), orders: lines };
}

function ResultCard({ result }: { result: ResultInfo }) {
  return (
    <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
      <div className="flex flex-wrap items-center gap-4">
        {result.orderId ? (
          <div>
            <div className="text-xs text-emerald-700">订单号</div>
            <div className="font-semibold">{result.orderId}</div>
          </div>
        ) : null}
        {result.ticketId ? (
          <div>
            <div className="text-xs text-emerald-700">工单号</div>
            <div className="font-semibold">{result.ticketId}</div>
          </div>
        ) : null}
        {result.status ? (
          <div>
            <div className="text-xs text-emerald-700">当前状态</div>
            <div className="font-semibold">{result.status}</div>
          </div>
        ) : null}
        {result.eta ? (
          <div>
            <div className="text-xs text-emerald-700">预计送达</div>
            <div className="font-semibold">{result.eta}</div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function OrderListCard({
  info,
  expanded,
  onToggle
}: {
  info: OrderListInfo;
  expanded: boolean;
  onToggle: () => void;
}) {
  const visibleOrders = expanded ? info.orders : info.orders.slice(0, 3);
  return (
    <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
      <div className="flex items-center justify-between">
        <div className="text-xs text-slate-500">订单列表（共 {info.orders.length} 条）</div>
        <button
          type="button"
          onClick={onToggle}
          className="text-xs font-semibold text-slate-600 hover:text-slate-800"
        >
          {expanded ? "收起" : "展开全部"}
        </button>
      </div>
      <div className="mt-2 space-y-1 text-sm text-slate-700">
        {visibleOrders.map((line) => (
          <div key={line} className="rounded-lg bg-white px-3 py-2 text-xs text-slate-600">
            {line}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ChatPanel({ messages, onSend, loading }: ChatPanelProps) {
  const [draft, setDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const [expandedOrders, setExpandedOrders] = useState<Record<string, boolean>>({});

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const canSend = useMemo(() => draft.trim().length > 0 && !loading, [draft, loading]);

  const handleSubmit = async () => {
    if (!canSend) {
      return;
    }
    const message = draft.trim();
    setDraft("");
    await onSend(message);
  };

  const handleKeyDown = async (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      await handleSubmit();
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto pb-6 pr-2 scrollbar-thin">
        {messages.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">
            暂无对话记录。
          </div>
        ) : null}
        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex items-start gap-3 ${
              message.role === "user" ? "flex-row-reverse" : ""
            }`}
          >
            <div
              className={`flex h-10 w-10 items-center justify-center rounded-full text-sm font-semibold ${
                message.role === "user"
                  ? "bg-amber-500 text-white"
                  : "bg-slate-900 text-white"
              }`}
            >
              {message.role === "user" ? "我" : "助"}
            </div>
            {message.role === "assistant" ? (
              (() => {
                const messageType = classifyAssistantMessage(message.content);
                const resultInfo = extractResultInfo(message.content);
                const orderList = extractOrderList(message.content);
                if (messageType === "progress") {
                  return (
                    <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-400 border-t-transparent" />
                      <span>{message.content}</span>
                    </div>
                  );
                }
                const cardStyle =
                  messageType === "guide"
                    ? "bg-slate-50 text-slate-700 ring-1 ring-slate-200"
                    : messageType === "result"
                      ? "bg-white text-slate-700 ring-1 ring-emerald-200"
                      : "bg-white text-slate-700 ring-1 ring-slate-200";
                const label =
                  messageType === "guide"
                    ? "引导提示"
                    : messageType === "result"
                      ? "处理结果"
                      : "客服回复";
                const contentText = orderList ? orderList.header : message.content;
                return (
                  <div className={`max-w-[72%] rounded-2xl px-4 py-3 text-sm leading-6 ${cardStyle}`}>
                    <div className="mb-2 inline-flex items-center rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500">
                      {label}
                    </div>
                    <div className="whitespace-pre-wrap">{contentText}</div>
                    {resultInfo ? <ResultCard result={resultInfo} /> : null}
                    {orderList ? (
                      <OrderListCard
                        info={orderList}
                        expanded={Boolean(expandedOrders[message.id])}
                        onToggle={() =>
                          setExpandedOrders((prev) => ({
                            ...prev,
                            [message.id]: !prev[message.id]
                          }))
                        }
                      />
                    ) : null}
                    <div className="mt-2 text-xs text-slate-400">{message.createdAt}</div>
                  </div>
                );
              })()
            ) : (
              <div className="max-w-[72%] rounded-2xl bg-amber-50 px-4 py-3 text-sm leading-6 text-slate-800">
                <div className="whitespace-pre-wrap">{message.content}</div>
                {message.meta?.note ? (
                  <div className="mt-1 text-xs text-slate-500">{message.meta.note}</div>
                ) : null}
                <div className="mt-2 text-xs text-slate-400">{message.createdAt}</div>
              </div>
            )}
          </div>
        ))}
        {loading ? (
          <div className="flex items-center gap-3 text-sm text-slate-500">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-400 border-t-transparent" />
            正在生成回复...
          </div>
        ) : null}
        <div ref={bottomRef} />
      </div>
      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          rows={3}
          placeholder=""
          aria-label="输入消息"
          className="w-full resize-none rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-700 focus:border-slate-400 focus:outline-none"
        />
        <div className="mt-3 flex items-center justify-between">
          <span className="text-xs text-slate-400">Enter 发送 / Shift+Enter 换行</span>
          <button
            type="button"
            disabled={!canSend}
            onClick={handleSubmit}
            className="flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {loading ? (
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
            ) : null}
            发送
          </button>
        </div>
      </div>
    </div>
  );
}
