import React, { useMemo, useState } from "react";

type TraceEvent = {
  id?: number | string;
  step_index: number;
  state: TraceState | string;
  tool_name?: string | null;
  created_at?: string;
};

type TraceViewerProps = {
  events?: TraceEvent[];
};

const stateStyles = {
  INIT: "state-init",
  PLANNING: "state-planning",
  TOOL_EXEC: "state-tool",
  EXEC_TOOL: "state-tool",
  RESPOND: "state-respond",
  DONE: "state-done",
  ERROR: "state-error",
  FALLBACK: "state-fallback"
} as const;

type TraceState = keyof typeof stateStyles;

const getStateClass = (state: TraceState | string) =>
  stateStyles[state as TraceState] || "";

export default function TraceViewer({ events = [] }: TraceViewerProps) {
  const [expanded, setExpanded] = useState(false);
  const displayEvents = useMemo(() => {
    if (!Array.isArray(events)) {
      return [];
    }
    if (expanded) {
      return events;
    }
    return events.slice(0, 5);
  }, [events, expanded]);

  return (
    <div className="trace-viewer">
      <div className="trace-list">
        {displayEvents.length === 0 ? (
          <div className="empty-state small">
            <p>暂无事件。</p>
          </div>
        ) : null}
        {displayEvents.map((event, index) => (
          <div key={`${event.id || index}`} className="trace-item">
            <div className="trace-dot" />
            <div className="trace-content">
              <div className="trace-header">
                <span className={`state-pill ${getStateClass(event.state)}`}>
                  {event.state}
                </span>
                <span className="trace-step">步骤 {event.step_index}</span>
              </div>
              <div className="trace-meta">
                <span>工具：{event.tool_name || "暂无"}</span>
                <span>{event.created_at || ""}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
      {Array.isArray(events) && events.length > 5 ? (
        <button
          className="ghost-button"
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
        >
          {expanded ? "收起" : "展开全部"}
        </button>
      ) : null}
    </div>
  );
}
