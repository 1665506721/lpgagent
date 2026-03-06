import { useCallback, useEffect, useMemo, useState } from "react";

import {
  PortalApiError,
  cancelPortalOrder,
  getPortalOrder,
  listPortalAddresses,
  modifyPortalOrderAddress,
  payPortalOrder,
  type PortalAddress,
  type PortalOrderDetail
} from "../../lib/portalApi";

type OrderDetailPageProps = {
  orderId?: string;
};

const TIMELINE = [
  { key: "PENDING_PAYMENT", label: "待支付" },
  { key: "PAID", label: "已支付" },
  { key: "SCHEDULED", label: "已预约" },
  { key: "IN_SERVICE", label: "服务中" },
  { key: "COMPLETED", label: "已完成" }
];

const ACCESSORY_PRICE_MAP: Record<string, { name: string; price: number }> = {
  HOSE: { name: "耐高温燃气软管", price: 35 },
  REGULATOR: { name: "安全减压阀", price: 80 },
  ALARM: { name: "燃气报警器", price: 120 },
  VALVE: { name: "自闭阀", price: 68 },
  STOVE_1B: { name: "单眼燃气灶", price: 259 },
  STOVE_2B: { name: "双眼燃气灶", price: 499 },
  IGNITER: { name: "点火器", price: 45 },
  SEAL_TAPE: { name: "密封生料带", price: 15 },
  CLAMP_SET: { name: "卡箍套装（4只）", price: 22 }
};

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

function buildServiceRows(order: PortalOrderDetail) {
  const payload = order.service_payload || {};

  if (["LPG_CYLINDER_DELIVERY", "CYLINDER_EXCHANGE"].includes(order.service_type)) {
    return [
      {
        name: order.service_type_label,
        spec: String(payload.cylinder_type || "-") + (payload.return_empty ? "（回收空瓶）" : ""),
        quantity: Number(payload.quantity || 1),
        unitPrice: Number(order.amount_subtotal) / Math.max(Number(payload.quantity || 1), 1)
      }
    ];
  }

  if (order.service_type === "ACCESSORIES") {
    const items = Array.isArray(payload.items) ? payload.items : [];
    return items.map((item) => ({
      name: ACCESSORY_PRICE_MAP[String((item as { sku?: string }).sku || "")]?.name || "配件",
      spec: String((item as { sku?: string }).sku || "-"),
      quantity: Number((item as { quantity?: number }).quantity || 1),
      unitPrice: ACCESSORY_PRICE_MAP[String((item as { sku?: string }).sku || "")]?.price || 0
    }));
  }

  return [
    {
      name: order.service_type_label,
      spec: JSON.stringify(payload),
      quantity: 1,
      unitPrice: Number(order.amount_subtotal)
    }
  ];
}

function statusClass(status: string) {
  if (status === "COMPLETED") return "portal-status success";
  if (status === "PENDING_PAYMENT") return "portal-status warn";
  if (status === "CANCELED" || status === "EXPIRED") return "portal-status danger";
  return "portal-status";
}

export default function OrderDetailPage({ orderId }: OrderDetailPageProps) {
  const parsedOrderId = Number(orderId);
  const isValidOrderId = Number.isFinite(parsedOrderId) && parsedOrderId > 0;

  const [order, setOrder] = useState<PortalOrderDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [showAddressModal, setShowAddressModal] = useState(false);
  const [addresses, setAddresses] = useState<PortalAddress[]>([]);
  const [addressesLoading, setAddressesLoading] = useState(false);

  const loadOrder = useCallback(async () => {
    if (!isValidOrderId) {
      setError("订单编号无效");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const detail = await getPortalOrder(parsedOrderId);
      setOrder(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : "订单详情加载失败");
      setOrder(null);
    } finally {
      setLoading(false);
    }
  }, [isValidOrderId, parsedOrderId]);

  useEffect(() => {
    void loadOrder();
  }, [loadOrder]);

  useEffect(() => {
    const refreshFromEvent = (event: Event) => {
      const detail = (event as CustomEvent<{ domains?: string[] }>).detail;
      const domains = Array.isArray(detail?.domains) ? detail?.domains : [];
      if (!domains.length || domains.includes("orders") || domains.includes("addresses")) {
        void loadOrder();
      }
    };
    window.addEventListener("portal:data-updated", refreshFromEvent as EventListener);
    const timer = window.setInterval(() => {
      void loadOrder();
    }, 25000);
    return () => {
      window.removeEventListener("portal:data-updated", refreshFromEvent as EventListener);
      window.clearInterval(timer);
    };
  }, [loadOrder]);

  const currentStep = useMemo(() => {
    if (!order) return -1;
    if (order.status === "CANCELED" || order.status === "EXPIRED") return -1;
    return TIMELINE.findIndex((item) => item.key === order.status);
  }, [order]);

  const serviceRows = useMemo(() => (order ? buildServiceRows(order) : []), [order]);

  const handlePay = async () => {
    if (!order) return;
    setActing(true);
    setError("");
    setFeedback("");
    try {
      const updated = await payPortalOrder(order.id);
      setOrder(updated);
      setFeedback("支付成功");
    } catch (err) {
      setError(err instanceof Error ? err.message : "支付失败");
    } finally {
      setActing(false);
    }
  };

  const handleCancel = async () => {
    if (!order) return;
    const confirmed = window.confirm(`确认取消订单 ${order.order_no} 吗？`);
    if (!confirmed) return;

    setActing(true);
    setError("");
    setFeedback("");
    try {
      const updated = await cancelPortalOrder(order.id);
      setOrder(updated);
      setFeedback("订单已取消");
    } catch (err) {
      if (err instanceof PortalApiError && err.code === "ORDER_NOT_CANCELABLE") {
        setError("当前订单不满足取消条件（需在预计开始前 1 小时以上）。");
      } else {
        setError(err instanceof Error ? err.message : "取消失败");
      }
    } finally {
      setActing(false);
    }
  };

  const handleOpenModifyAddress = async () => {
    setAddressesLoading(true);
    setError("");
    try {
      const result = await listPortalAddresses();
      setAddresses(result);
      setShowAddressModal(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "地址加载失败");
    } finally {
      setAddressesLoading(false);
    }
  };

  const handleSelectAddress = async (address: PortalAddress) => {
    if (!order) return;
    setActing(true);
    setError("");
    setFeedback("");
    try {
      const updated = await modifyPortalOrderAddress(order.id, { address_id: address.id });
      setOrder(updated);
      setFeedback("地址修改成功");
      setShowAddressModal(false);
    } catch (err) {
      if (err instanceof PortalApiError && err.code === "ORDER_NOT_EDITABLE") {
        setError("当前订单不满足改址条件（需在预计开始前 1 小时以上）。");
      } else {
        setError(err instanceof Error ? err.message : "修改地址失败");
      }
    } finally {
      setActing(false);
    }
  };

  if (!isValidOrderId) {
    return <div className="portal-card auth-error">订单编号无效，请返回订单列表重试。</div>;
  }

  if (loading) {
    return <div className="portal-card empty-card">订单详情加载中...</div>;
  }

  if (!order) {
    return (
      <div className="portal-page">
        {error ? <div className="auth-error">{error}</div> : null}
        <button className="portal-secondary" type="button" onClick={() => (window.location.hash = "#/portal/orders")}> 
          返回订单列表
        </button>
      </div>
    );
  }

  const canPay = order.status === "PENDING_PAYMENT";
  const canCancel = ["PENDING_PAYMENT", "PAID", "SCHEDULED"].includes(order.status);
  const canModifyAddress = ["PENDING_PAYMENT", "PAID", "SCHEDULED"].includes(order.status);

  return (
    <div className="portal-page">
      <div className="portal-page-header">
        <div>
          <div className="portal-title">订单详情</div>
          <div className="portal-subtitle">订单编号：{order.order_no}</div>
        </div>
        <div className="portal-tags">
          <span className="portal-pill">{order.service_type_label}</span>
          <span className={statusClass(order.status)}>{order.status_label}</span>
        </div>
      </div>

      {feedback ? <div className="auth-hint">{feedback}</div> : null}
      {error ? <div className="auth-error">{error}</div> : null}

      <div className="portal-card timeline-card">
        <div className="timeline-row">
          {TIMELINE.map((item, index) => (
            <div key={item.key} className={`timeline-node ${currentStep >= index ? "active" : ""}`}>
              <span />
              <div>{item.label}</div>
              <small>{index === 0 ? formatDateTime(order.created_at) : ""}</small>
            </div>
          ))}
        </div>
      </div>

      <div className="portal-grid two">
        <div className="portal-card">
          <div className="portal-card-title">服务地址</div>
          <div className="address-block">
            <div className="address-map">地图占位</div>
            <div>
              <div className="address-name">
                {order.contact_snapshot.contact_name} {order.contact_snapshot.contact_phone}
              </div>
              <div className="address-detail">{order.address_snapshot.address_full}</div>
              {order.address_snapshot.door_note ? (
                <div className="address-detail">门牌备注：{order.address_snapshot.door_note}</div>
              ) : null}
              {order.assigned_worker?.name ? (
                <div className="address-detail">
                  上门人员：{order.assigned_worker.name} {order.assigned_worker.phone || ""}
                </div>
              ) : null}
            </div>
          </div>
        </div>

        <div className="portal-card">
          <div className="portal-card-title">费用明细</div>
          <div className="fee-list">
            <div>
              <span>服务小计</span>
              <span>{formatAmount(order.amount_subtotal, order.currency)}</span>
            </div>
            <div>
              <span>加急费用</span>
              <span>{formatAmount(order.amount_urgent_fee, order.currency)}</span>
            </div>
            <div className="fee-total">
              <span>应付合计</span>
              <span>{formatAmount(order.amount_total, order.currency)}</span>
            </div>
            <div className="fee-note">
              服务时间：{formatDateTime(order.eta_start)} - {formatDateTime(order.eta_end).slice(-5)}
            </div>
            <div className="fee-note">最晚取消时间：{formatDateTime(order.cancel_deadline)}</div>
            <div className="fee-note">最晚改址时间：{formatDateTime(order.address_edit_deadline)}</div>
          </div>
        </div>
      </div>

      <div className="portal-card">
        <div className="portal-card-title">服务详情</div>
        <div className="portal-table">
          <div className="portal-table-row header">
            <span>项目</span>
            <span>规格</span>
            <span>数量</span>
            <span>单价</span>
          </div>
          {serviceRows.map((row, index) => (
            <div key={`${row.name}-${index}`} className="portal-table-row">
              <span>{row.name}</span>
              <span>{row.spec}</span>
              <span>{row.quantity}</span>
              <span>{Number(row.unitPrice) > 0 ? `¥${Number(row.unitPrice).toFixed(2)}` : "-"}</span>
            </div>
          ))}
        </div>
        {order.notes ? <div className="portal-note">备注：{order.notes}</div> : null}
      </div>

      <div className="portal-card">
        <div className="portal-card-title">事件日志</div>
        <div className="portal-list">
          {order.events.length === 0 ? <div className="empty-card">暂无事件记录</div> : null}
          {order.events.map((event, index) => (
            <div key={`${event.event_type}-${index}`} className="portal-card order-card">
              <div className="order-card-header">
                <div className="order-title">{event.event_type}</div>
                <div className="order-meta">{formatDateTime(event.created_at)}</div>
              </div>
              <div className="portal-note">{JSON.stringify(event.payload)}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="portal-actions">
        <button className="portal-secondary" type="button" onClick={() => (window.location.hash = "#/portal/orders")}>
          返回订单列表
        </button>
        <button className="portal-ghost" type="button" onClick={() => (window.location.hash = "#/portal/chat")}>
          联系客服
        </button>
        <button
          className="portal-secondary"
          type="button"
          disabled={!canModifyAddress || acting || addressesLoading}
          onClick={handleOpenModifyAddress}
        >
          {addressesLoading ? "加载地址..." : "修改地址"}
        </button>
        <button
          className="portal-ghost danger"
          type="button"
          disabled={!canCancel || acting}
          onClick={handleCancel}
        >
          {acting && canCancel ? "取消中..." : "取消订单"}
        </button>
        {canPay ? (
          <button className="portal-cta" type="button" disabled={acting} onClick={handlePay}>
            {acting ? "支付中..." : `立即支付 ${formatAmount(order.amount_total, order.currency)}`}
          </button>
        ) : null}
      </div>

      {showAddressModal ? (
        <AddressModal
          addresses={addresses}
          onClose={() => setShowAddressModal(false)}
          onSelect={handleSelectAddress}
          selecting={acting}
        />
      ) : null}
    </div>
  );
}

function AddressModal({
  addresses,
  onClose,
  onSelect,
  selecting
}: {
  addresses: PortalAddress[];
  onClose: () => void;
  onSelect: (address: PortalAddress) => void;
  selecting: boolean;
}) {
  return (
    <div className="portal-modal">
      <div className="portal-modal-card">
        <div className="portal-modal-header">
          <h3>选择收货地址</h3>
          <button className="portal-ghost" type="button" onClick={onClose}>
            关闭
          </button>
        </div>

        <div className="portal-modal-list">
          {addresses.length === 0 ? <div className="empty-card">暂无地址，请先在账户中心添加地址。</div> : null}
          {addresses.map((address) => (
            <div key={address.id} className="portal-card address-select">
              <div>
                <div className="address-name">
                  {address.contact_name} {address.contact_phone} {address.is_default ? "(默认)" : ""}
                </div>
                <div className="address-detail">{address.address_full}</div>
                {address.door_note ? <div className="address-detail">{address.door_note}</div> : null}
              </div>
              <button
                className="portal-secondary"
                type="button"
                disabled={selecting}
                onClick={() => onSelect(address)}
              >
                {selecting ? "提交中..." : "使用该地址"}
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
