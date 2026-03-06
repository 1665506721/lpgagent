import { useCallback, useEffect, useMemo, useState } from "react";

import {
  PortalApiError,
  cancelPortalOrder,
  listPortalOrders,
  payPortalOrder,
  type PortalOrderListData,
  type PortalOrderListItem
} from "../../lib/portalApi";

type StatusTab = {
  key: string;
  label: string;
};

type OrderListPageProps = {
  initialStatus?: string;
  initialKeyword?: string;
};

const STATUS_TABS: StatusTab[] = [
  { key: "ALL", label: "全部" },
  { key: "PENDING_PAYMENT", label: "待付款" },
  { key: "PAID", label: "已支付" },
  { key: "SCHEDULED", label: "已预约" },
  { key: "IN_SERVICE", label: "进行中" },
  { key: "COMPLETED", label: "已完成" },
  { key: "CANCELED", label: "已取消" },
  { key: "EXPIRED", label: "已过期" }
];
const STATUS_KEYS = new Set(STATUS_TABS.map((item) => item.key));

function normalizeStatus(status: string | undefined) {
  if (!status) return "ALL";
  return STATUS_KEYS.has(status) ? status : "ALL";
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function formatAmount(amount: string, currency: string) {
  const number = Number(amount);
  if (Number.isNaN(number)) return `${currency} ${amount}`;
  if (currency === "CNY") return `¥${number.toFixed(2)}`;
  return `${currency} ${number.toFixed(2)}`;
}

function statusClass(status: string) {
  if (status === "COMPLETED") return "portal-status success";
  if (status === "PENDING_PAYMENT") return "portal-status warn";
  if (status === "CANCELED" || status === "EXPIRED") return "portal-status danger";
  return "portal-status";
}

export default function OrderListPage({ initialStatus, initialKeyword }: OrderListPageProps) {
  const [activeStatus, setActiveStatus] = useState(normalizeStatus(initialStatus));
  const [keywordInput, setKeywordInput] = useState((initialKeyword || "").trim());
  const [keyword, setKeyword] = useState((initialKeyword || "").trim());
  const [page, setPage] = useState(1);
  const [data, setData] = useState<PortalOrderListData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string>("");
  const [actingOrderId, setActingOrderId] = useState<number | null>(null);

  const fetchOrders = useCallback(async (silent = false) => {
    if (!silent) {
      setLoading(true);
    }
    setError("");
    try {
      const result = await listPortalOrders({
        status: activeStatus === "ALL" ? undefined : activeStatus,
        keyword: keyword || undefined,
        page,
        page_size: 10
      });
      setData(result);
      setLastUpdatedAt(
        new Date().toLocaleTimeString("zh-CN", { hour12: false, hour: "2-digit", minute: "2-digit" })
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : "订单加载失败";
      setError(message);
      setData(null);
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }, [activeStatus, keyword, page]);

  useEffect(() => {
    void fetchOrders();
  }, [fetchOrders]);

  useEffect(() => {
    const nextStatus = normalizeStatus(initialStatus);
    const nextKeyword = (initialKeyword || "").trim();
    setActiveStatus(nextStatus);
    setKeywordInput(nextKeyword);
    setKeyword(nextKeyword);
    setPage(1);
  }, [initialKeyword, initialStatus]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void fetchOrders(true);
    }, 25000);
    return () => {
      window.clearInterval(timer);
    };
  }, [fetchOrders]);

  useEffect(() => {
    const refreshFromEvent = (event: Event) => {
      const detail = (event as CustomEvent<{ domains?: string[] }>).detail;
      const domains = Array.isArray(detail?.domains) ? detail?.domains : [];
      if (!domains.length || domains.includes("orders")) {
        void fetchOrders(true);
      }
    };
    window.addEventListener("portal:data-updated", refreshFromEvent as EventListener);
    return () => {
      window.removeEventListener("portal:data-updated", refreshFromEvent as EventListener);
    };
  }, [fetchOrders]);

  const items = data?.items || [];
  const totalPages = data?.total_pages || 1;

  const canGoPrev = page > 1;
  const canGoNext = page < totalPages;

  const handleApplyFilter = () => {
    setPage(1);
    setKeyword(keywordInput.trim());
    setFeedback("");
  };

  const handleStatusChange = (status: string) => {
    setActiveStatus(status);
    setPage(1);
    setFeedback("");
  };

  const handlePay = async (order: PortalOrderListItem) => {
    setActingOrderId(order.id);
    setError("");
    setFeedback("");
    try {
      await payPortalOrder(order.id);
      setFeedback(`订单 ${order.order_no} 支付成功`);
      await fetchOrders();
    } catch (err) {
      setError(err instanceof Error ? err.message : "支付失败");
    } finally {
      setActingOrderId(null);
    }
  };

  const handleCancel = async (order: PortalOrderListItem) => {
    const confirmed = window.confirm(`确认取消订单 ${order.order_no} 吗？`);
    if (!confirmed) return;

    setActingOrderId(order.id);
    setError("");
    setFeedback("");
    try {
      await cancelPortalOrder(order.id);
      setFeedback(`订单 ${order.order_no} 已取消`);
      await fetchOrders();
    } catch (err) {
      if (err instanceof PortalApiError && err.code === "ORDER_NOT_CANCELABLE") {
        setError("当前订单不满足取消条件（需在预计开始前 1 小时以上）。");
      } else {
        setError(err instanceof Error ? err.message : "取消失败");
      }
    } finally {
      setActingOrderId(null);
    }
  };

  const hasFilters = useMemo(() => Boolean(keyword || activeStatus !== "ALL"), [keyword, activeStatus]);

  return (
    <div className="portal-page">
      <div className="portal-page-header">
        <div>
          <div className="portal-title">我的订单</div>
          <div className="portal-subtitle">
            服务单与配件单统一管理，支持按状态与关键词查询。
            {lastUpdatedAt ? ` 最近更新 ${lastUpdatedAt}` : ""}
          </div>
        </div>
        <div className="portal-filter">
          {STATUS_TABS.map((tab) => (
            <button
              key={tab.key}
              className={activeStatus === tab.key ? "portal-pill active" : "portal-pill"}
              type="button"
              onClick={() => handleStatusChange(tab.key)}
            >
              {tab.label}
            </button>
          ))}
          <button
            className="portal-pill"
            type="button"
            onClick={() => {
              void fetchOrders(true);
              setFeedback("已刷新订单列表");
            }}
          >
            刷新
          </button>
        </div>
      </div>

      <div className="portal-card filter-bar">
        <div className="portal-search small">
          <span className="portal-search-icon">🔎</span>
          <input
            value={keywordInput}
            onChange={(event) => setKeywordInput(event.target.value)}
            placeholder="输入订单号 / 服务类型 / 备注"
          />
        </div>
        <button className="portal-secondary" type="button" onClick={handleApplyFilter}>
          应用筛选
        </button>
        {hasFilters ? (
          <button
            className="portal-ghost"
            type="button"
            onClick={() => {
              setKeywordInput("");
              setKeyword("");
              setActiveStatus("ALL");
              setPage(1);
              setFeedback("已清空筛选");
            }}
          >
            清空筛选
          </button>
        ) : null}
      </div>

      {feedback ? <div className="auth-hint">{feedback}</div> : null}
      {error ? <div className="auth-error">{error}</div> : null}

      <div className="portal-list">
        {loading ? <div className="portal-card empty-card">订单加载中...</div> : null}
        {!loading && items.length === 0 ? (
          <div className="portal-card empty-card">暂无订单，去下单页创建第一笔订单。</div>
        ) : null}

        {!loading
          ? items.map((order) => {
              const isActing = actingOrderId === order.id;
              const canPay = order.status === "PENDING_PAYMENT";
              const canCancel = ["PENDING_PAYMENT", "PAID", "SCHEDULED"].includes(order.status);

              return (
                <div key={order.id} className="portal-card order-card">
                  <div className="order-card-header">
                    <div>
                      <div className="order-title">{order.service_type_label}</div>
                      <div className="order-meta">订单号：{order.order_no}</div>
                    </div>
                    <span className={statusClass(order.status)}>{order.status_label}</span>
                  </div>

                  <div className="order-card-body">
                    <div>
                      <div className="order-label">下单时间</div>
                      <div className="order-value">{formatDateTime(order.created_at)}</div>
                    </div>
                    <div>
                      <div className="order-label">预计服务时间</div>
                      <div className="order-value">
                        {formatDateTime(order.eta_start)} - {formatDateTime(order.eta_end).slice(-5)}
                      </div>
                    </div>
                    <div>
                      <div className="order-label">订单金额</div>
                      <div className="order-value strong">{formatAmount(order.amount_total, order.currency)}</div>
                    </div>
                    <div>
                      <div className="order-label">操作状态</div>
                      <div className="order-value">
                        {isActing ? "处理中..." : "可操作"}
                        {order.assigned_worker?.name ? (
                          <div className="order-worker">
                            上门人员：{order.assigned_worker.name} {order.assigned_worker.phone || ""}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  </div>

                  <div className="order-card-actions">
                    <button
                      className="portal-secondary"
                      type="button"
                      onClick={() => {
                        window.location.hash = `#/portal/orders/${order.id}`;
                      }}
                    >
                      查看详情
                    </button>

                    <button
                      className="portal-ghost danger"
                      type="button"
                      disabled={!canCancel || isActing}
                      onClick={() => handleCancel(order)}
                    >
                      {isActing && canCancel ? "取消中..." : "取消订单"}
                    </button>

                    {canPay ? (
                      <button
                        className="portal-cta"
                        type="button"
                        disabled={isActing}
                        onClick={() => handlePay(order)}
                      >
                        {isActing ? "支付中..." : "立即付款"}
                      </button>
                    ) : (
                      <button
                        className="portal-cta"
                        type="button"
                        onClick={() => {
                          if (order.service_type === "ACCESSORIES") {
                            window.location.hash = "#/portal/store";
                            return;
                          }
                          window.location.hash = `#/portal/order/new?service=${order.service_type}`;
                        }}
                      >
                        再来一单
                      </button>
                    )}
                  </div>
                </div>
              );
            })
          : null}
      </div>

      <div className="portal-pagination">
        <button
          className="portal-ghost"
          type="button"
          disabled={!canGoPrev}
          onClick={() => setPage((value) => Math.max(1, value - 1))}
        >
          上一页
        </button>
        <button className="portal-pill active" type="button">
          {page}
        </button>
        <button
          className="portal-ghost"
          type="button"
          disabled={!canGoNext}
          onClick={() => setPage((value) => value + 1)}
        >
          下一页
        </button>
      </div>
    </div>
  );
}
