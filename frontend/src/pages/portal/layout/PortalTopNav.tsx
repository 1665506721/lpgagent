import { useEffect, useMemo, useRef, useState } from "react";

import {
  listPortalNotifications,
  readAllPortalNotifications,
  readPortalNotification,
  type PortalNotificationItem,
} from "../../../lib/portalApi";
import { NAV_LINKS } from "../portalData";

type PortalTopNavProps = {
  activePath: string;
  theme: "light" | "eye" | "dark";
  onThemeChange: (theme: "light" | "eye" | "dark") => void;
};

function formatNotificationTime(value: string) {
  const ts = Date.parse(value);
  if (Number.isNaN(ts)) return "";
  return new Date(ts).toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function notificationLevelClass(level: string) {
  if (level === "SUCCESS") return "success";
  if (level === "WARNING") return "warning";
  if (level === "ERROR") return "error";
  return "info";
}

export default function PortalTopNav({ activePath, theme, onThemeChange }: PortalTopNavProps) {
  const [keyword, setKeyword] = useState("");
  const [notificationOpen, setNotificationOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);
  const [notifications, setNotifications] = useState<PortalNotificationItem[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const panelRef = useRef<HTMLDivElement | null>(null);

  const hasMore = page < totalPages;
  const hasToken = Boolean(localStorage.getItem("portal_token"));

  const handleSearch = () => {
    const normalized = keyword.trim();
    const query = new URLSearchParams();
    if (normalized) {
      query.set("keyword", normalized);
    }
    const suffix = query.toString();
    window.location.hash = `#/portal/orders${suffix ? `?${suffix}` : ""}`;
  };

  const loadNotifications = async (nextPage = 1, append = false, silent = false) => {
    if (!hasToken) {
      setNotifications([]);
      setUnreadCount(0);
      setPage(1);
      setTotalPages(1);
      return;
    }
    if (!silent) setLoading(true);
    try {
      const payload = await listPortalNotifications({ page: nextPage, page_size: 12 });
      setUnreadCount(payload.unread_count || 0);
      setPage(payload.page || 1);
      setTotalPages(payload.total_pages || 1);
      setNotifications((prev) => (append ? [...prev, ...(payload.items || [])] : payload.items || []));
    } catch {
      // keep current state
    } finally {
      if (!silent) setLoading(false);
    }
  };

  useEffect(() => {
    void loadNotifications(1, false, false);
    const timer = window.setInterval(() => {
      void loadNotifications(1, false, true);
    }, 30000);
    const refresh = () => void loadNotifications(1, false, true);
    window.addEventListener("portal:notification-refresh", refresh as EventListener);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("portal:notification-refresh", refresh as EventListener);
    };
  }, [hasToken]);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (!panelRef.current) return;
      if (!panelRef.current.contains(event.target as Node)) {
        setNotificationOpen(false);
      }
    };
    if (notificationOpen) {
      document.addEventListener("mousedown", onClick);
    }
    return () => document.removeEventListener("mousedown", onClick);
  }, [notificationOpen]);

  const handleOpenNotification = async (item: PortalNotificationItem) => {
    try {
      if (!item.is_read) {
        await readPortalNotification(item.id);
      }
    } catch {
      // ignore read error
    } finally {
      setNotifications((prev) => prev.map((row) => (row.id === item.id ? { ...row, is_read: true } : row)));
      setUnreadCount((prev) => Math.max(0, prev - (item.is_read ? 0 : 1)));
    }
    const route = (item.target_route || "").trim();
    if (route) {
      window.location.hash = route;
    }
    setNotificationOpen(false);
  };

  const handleReadAll = async () => {
    if (!notifications.length || unreadCount <= 0) return;
    setMarkingAll(true);
    try {
      await readAllPortalNotifications();
      setNotifications((prev) => prev.map((item) => ({ ...item, is_read: true })));
      setUnreadCount(0);
    } finally {
      setMarkingAll(false);
    }
  };

  const summaryText = useMemo(() => {
    if (!notifications.length) return "暂无系统消息";
    if (unreadCount <= 0) return "暂无未读消息";
    return `未读 ${unreadCount} 条`;
  }, [notifications.length, unreadCount]);

  return (
    <header className="portal-top-nav">
      <div className="portal-top-nav-inner">
        <button
          className="portal-brand clickable"
          type="button"
          onClick={() => {
            window.location.hash = "#/portal/dashboard";
          }}
        >
          <div className="portal-logo">L</div>
          <div>
            <div className="portal-brand-title">LPG 服务平台</div>
            <div className="portal-brand-sub">企业用户服务中心</div>
          </div>
        </button>

        <nav className="portal-top-links">
          {NAV_LINKS.map((link) => {
            const isActive = activePath === link.path || activePath.startsWith(`${link.path}/`);
            return (
              <a
                key={link.path}
                href={`#${link.path}`}
                className={isActive ? "portal-link active" : "portal-link"}
              >
                {link.label}
              </a>
            );
          })}
        </nav>

        <div className="portal-top-actions">
          <div className="portal-search">
            <span className="portal-search-icon">🔎</span>
            <input
              placeholder="搜索订单 / 服务 / 配件"
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  handleSearch();
                }
              }}
            />
          </div>

          <div className="portal-theme-switch">
            <span>主题</span>
            <select
              value={theme}
              onChange={(event) => onThemeChange(event.target.value as "light" | "eye" | "dark")}
              aria-label="主题模式"
            >
              <option value="light">白天</option>
              <option value="eye">护眼</option>
              <option value="dark">黑夜</option>
            </select>
          </div>

          <div className="portal-notify-wrap" ref={panelRef}>
            <button
              className="portal-icon-btn portal-notify-btn"
              type="button"
              aria-label="系统消息"
              onClick={() => {
                setNotificationOpen((prev) => !prev);
                if (!notificationOpen) void loadNotifications(1, false, true);
              }}
            >
              🔔
              {unreadCount > 0 ? <span className="portal-notify-badge">{unreadCount > 99 ? "99+" : unreadCount}</span> : null}
            </button>
            {notificationOpen ? (
              <div className="portal-notify-panel">
                <div className="portal-notify-header">
                  <div>
                    <strong>系统消息</strong>
                    <small>{summaryText}</small>
                  </div>
                  <button className="portal-ghost" type="button" onClick={() => void handleReadAll()} disabled={markingAll || unreadCount <= 0}>
                    {markingAll ? "处理中..." : "一键已读"}
                  </button>
                </div>

                <div className="portal-notify-list">
                  {loading && notifications.length === 0 ? <div className="portal-notify-empty">加载中...</div> : null}
                  {!loading && notifications.length === 0 ? <div className="portal-notify-empty">暂无系统消息</div> : null}
                  {notifications.map((item) => (
                    <button
                      key={item.id}
                      className={`portal-notify-item ${item.is_read ? "read" : "unread"}`}
                      type="button"
                      onClick={() => void handleOpenNotification(item)}
                    >
                      <div className="portal-notify-item-head">
                        <span className={`portal-notify-level ${notificationLevelClass(item.level)}`}>{item.level}</span>
                        <strong>{item.title}</strong>
                      </div>
                      <p>{item.content}</p>
                      <small>{formatNotificationTime(item.created_at)}</small>
                    </button>
                  ))}
                </div>

                {hasMore ? (
                  <button
                    className="portal-ghost portal-notify-more"
                    type="button"
                    onClick={() => void loadNotifications(page + 1, true, false)}
                    disabled={loading}
                  >
                    {loading ? "加载中..." : "加载更多"}
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </header>
  );
}
