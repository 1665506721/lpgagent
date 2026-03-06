import { useEffect, useMemo, useState } from "react";

import {
  PortalApiError,
  checkoutPortalCart,
  clearPortalCart,
  listPortalAddresses,
  listPortalCart,
  removePortalCartItem,
  upsertPortalCartItem,
  type PortalAddress,
  type PortalCartSummary,
} from "../../lib/portalApi";

type AccessoryProduct = {
  sku: string;
  name: string;
  category: "管件" | "阀门" | "安防" | "灶具" | "配件";
  price: number;
  tag: string;
  desc: string;
};

type CheckoutForm = {
  address_id: number;
  eta_date: string;
  eta_slot: string;
  is_urgent: boolean;
  notes: string;
  need_invoice: boolean;
  invoice_title: string;
  invoice_tax_no: string;
};

type CheckoutSuccess = {
  id: number;
  orderNo: string;
  amount: string;
  etaStart: string;
  etaEnd: string;
  address: string;
  contact: string;
  invoice: string;
};

const PRODUCTS: AccessoryProduct[] = [
  { sku: "HOSE", name: "耐高温燃气软管（2m）", category: "管件", price: 35, tag: "常备", desc: "多层防爆结构，适配常见家商用接口" },
  { sku: "REGULATOR", name: "安全减压阀", category: "阀门", price: 80, tag: "热卖", desc: "稳定调压，适用于瓶装液化气场景" },
  { sku: "ALARM", name: "燃气报警器", category: "安防", price: 120, tag: "推荐", desc: "燃气异常浓度自动声光报警" },
  { sku: "VALVE", name: "自闭阀", category: "阀门", price: 68, tag: "安全", desc: "异常断气自闭保护，提升用气安全" },
  { sku: "STOVE_1B", name: "单眼燃气灶", category: "灶具", price: 259, tag: "新品", desc: "小型厨房/后厨适用，火力稳定" },
  { sku: "STOVE_2B", name: "双眼燃气灶", category: "灶具", price: 499, tag: "经典", desc: "家用主流规格，兼顾效率与稳定" },
  { sku: "IGNITER", name: "点火器", category: "配件", price: 45, tag: "易耗", desc: "燃气灶点火更灵敏，兼容主流型号" },
  { sku: "SEAL_TAPE", name: "密封生料带", category: "管件", price: 15, tag: "辅材", desc: "接口密封防渗漏，安装维修常用" },
  { sku: "CLAMP_SET", name: "卡箍套装（4只）", category: "管件", price: 22, tag: "辅材", desc: "软管紧固固定，提升连接可靠性" },
];

const CATEGORIES = ["全部", "管件", "阀门", "安防", "灶具", "配件"] as const;
const SLOT_OPTIONS = ["09:00-11:00", "11:00-13:00", "13:00-15:00", "15:00-17:00", "17:00-19:00", "19:00-21:00"] as const;

function formatDate(date: Date) {
  const y = date.getFullYear();
  const m = `${date.getMonth() + 1}`.padStart(2, "0");
  const d = `${date.getDate()}`.padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function parseSlotStart(slot: string) {
  const [start] = slot.split("-");
  const [hour, minute] = start.split(":").map((value) => Number(value));
  return { hour, minute };
}

function slotStartDateTime(dateText: string, slot: string) {
  const [year, month, day] = dateText.split("-").map((value) => Number(value));
  const { hour, minute } = parseSlotStart(slot);
  return new Date(year, month - 1, day, hour, minute, 0, 0);
}

function isSlotSelectable(dateText: string, slot: string, now = new Date()) {
  return slotStartDateTime(dateText, slot).getTime() > now.getTime();
}

function generateDateOptions() {
  const today = new Date();
  return new Array(5).fill(null).map((_, index) => {
    const d = new Date(today);
    d.setDate(today.getDate() + index);
    return { label: index === 0 ? "今天" : index === 1 ? "明天" : `${d.getMonth() + 1}月${d.getDate()}日`, value: formatDate(d) };
  });
}

function firstSlotForDate(dateValue: string) {
  return SLOT_OPTIONS.find((slot) => isSlotSelectable(dateValue, slot)) || null;
}

function firstSchedule(dateValues: string[]) {
  for (const dateValue of dateValues) {
    const slot = firstSlotForDate(dateValue);
    if (slot) return { eta_date: dateValue, eta_slot: slot };
  }
  return { eta_date: dateValues[0], eta_slot: SLOT_OPTIONS[0] };
}

function getDefaultAddress(addresses: PortalAddress[]) {
  return addresses.find((item) => item.is_default) || addresses[0] || null;
}

function getErrorMessage(err: unknown) {
  if (err instanceof PortalApiError) {
    if (err.code === "VALIDATION_ERROR") {
      const detail = (err.details as { detail?: unknown } | undefined)?.detail;
      if (detail === "eta_slot_in_past") return "所选时段已过，请更换时间";
    }
    return err.message;
  }
  return err instanceof Error ? err.message : "操作失败，请稍后重试";
}

function emptyCartSummary(): PortalCartSummary {
  return { items: [], selected_count: 0, total_amount: "0.00", currency: "CNY" };
}

export default function AccessoriesStorePage() {
  const dateOptions = useMemo(() => generateDateOptions(), []);
  const dateValues = useMemo(() => dateOptions.map((item) => item.value), [dateOptions]);

  const [activeCategory, setActiveCategory] = useState<(typeof CATEGORIES)[number]>("全部");
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(false);
  const [itemLoadingSku, setItemLoadingSku] = useState<string>("");
  const [error, setError] = useState("");
  const [hint, setHint] = useState("");
  const [cartOpen, setCartOpen] = useState(false);

  const [showCheckout, setShowCheckout] = useState(false);
  const [addresses, setAddresses] = useState<PortalAddress[]>([]);
  const [checkoutForm, setCheckoutForm] = useState<CheckoutForm | null>(null);
  const [success, setSuccess] = useState<CheckoutSuccess | null>(null);
  const [cart, setCart] = useState<PortalCartSummary>(emptyCartSummary());

  const filteredProducts = useMemo(() => {
    return PRODUCTS.filter((product) => {
      const matchCategory = activeCategory === "全部" || product.category === activeCategory;
      const search = keyword.trim().toLowerCase();
      const matchKeyword = !search || product.name.toLowerCase().includes(search) || product.desc.toLowerCase().includes(search) || product.sku.toLowerCase().includes(search);
      return matchCategory && matchKeyword;
    });
  }, [activeCategory, keyword]);

  const cartQtyMap = useMemo(() => {
    const map: Record<string, number> = {};
    (cart.items || []).forEach((item) => {
      map[item.sku] = item.quantity;
    });
    return map;
  }, [cart.items]);

  const selectedCount = cart.selected_count || 0;
  const totalAmountText = cart.total_amount || "0.00";
  const previewNames = (cart.items || []).slice(0, 3).map((item) => `${item.name}×${item.quantity}`);
  const hasMorePreview = (cart.items || []).length > 3;

  const patchCheckout = (patch: Partial<CheckoutForm>) => setCheckoutForm((prev) => (prev ? { ...prev, ...patch } : prev));

  const reloadCart = async () => {
    try {
      const data = await listPortalCart();
      setCart(data);
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  useEffect(() => {
    void reloadCart();
  }, []);

  useEffect(() => {
    const refreshFromEvent = (event: Event) => {
      const detail = (event as CustomEvent<{ domains?: string[] }>).detail;
      const domains = Array.isArray(detail?.domains) ? detail?.domains : [];
      if (!domains.length || domains.includes("cart") || domains.includes("orders")) {
        void reloadCart();
      }
      if ((domains.includes("addresses") || !domains.length) && showCheckout) {
        void listPortalAddresses()
          .then((result) => {
            setAddresses(result);
            const nextDefault = getDefaultAddress(result);
            if (nextDefault) {
              patchCheckout({ address_id: nextDefault.id });
            }
          })
          .catch(() => {
            // ignore refresh failure
          });
      }
    };
    window.addEventListener("portal:data-updated", refreshFromEvent as EventListener);
    const timer = window.setInterval(() => {
      void reloadCart();
    }, 25000);
    return () => {
      window.removeEventListener("portal:data-updated", refreshFromEvent as EventListener);
      window.clearInterval(timer);
    };
  }, [showCheckout]);

  const updateCartQuantity = async (sku: string, nextQty: number) => {
    setError("");
    setHint("");
    setItemLoadingSku(sku);
    try {
      if (nextQty <= 0) {
        const data = await removePortalCartItem(sku);
        setCart(data);
      } else {
        const data = await upsertPortalCartItem({ sku, quantity: nextQty });
        setCart(data);
      }
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setItemLoadingSku("");
    }
  };

  const changeQty = async (sku: string, delta: number) => {
    const current = cartQtyMap[sku] || 0;
    const next = Math.max(0, current + delta);
    await updateCartQuantity(sku, next);
  };

  const clearCart = async () => {
    if (selectedCount === 0) return;
    if (!window.confirm("确认清空购物车吗？")) return;
    setLoading(true);
    setError("");
    try {
      const data = await clearPortalCart();
      setCart(data);
      setHint("购物车已清空");
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const openCheckout = async () => {
    setError("");
    setHint("");
    const token = localStorage.getItem("portal_token");
    if (!token) {
      setError("请先登录后再结算");
      window.location.hash = "#/portal/login";
      return;
    }
    if (selectedCount < 1) {
      setError("请先加入配件到购物车");
      return;
    }

    setLoading(true);
    try {
      const result = await listPortalAddresses();
      const defaultAddress = getDefaultAddress(result);
      if (!defaultAddress) {
        setError("请先在个人中心新增地址");
        return;
      }
      const schedule = firstSchedule(dateValues);
      setAddresses(result);
      setCheckoutForm({
        address_id: defaultAddress.id,
        eta_date: schedule.eta_date,
        eta_slot: schedule.eta_slot,
        is_urgent: false,
        notes: "配件商城购物车下单",
        need_invoice: false,
        invoice_title: "",
        invoice_tax_no: ""
      });
      setShowCheckout(true);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const submitCheckout = async () => {
    if (!checkoutForm) return;
    if (!isSlotSelectable(checkoutForm.eta_date, checkoutForm.eta_slot)) {
      setError("所选时段已不可用，请重新选择");
      return;
    }
    if (checkoutForm.need_invoice && !checkoutForm.invoice_title.trim()) {
      setError("需要开票时请填写发票抬头");
      return;
    }

    setLoading(true);
    setError("");
    try {
      const paid = await checkoutPortalCart({
        address_id: checkoutForm.address_id,
        eta_date: checkoutForm.eta_date,
        eta_slot: checkoutForm.eta_slot,
        is_urgent: checkoutForm.is_urgent,
        notes: checkoutForm.notes,
        need_invoice: checkoutForm.need_invoice,
        invoice_title: checkoutForm.need_invoice ? checkoutForm.invoice_title.trim() : "",
        invoice_tax_no: checkoutForm.need_invoice ? checkoutForm.invoice_tax_no.trim() : "",
        auto_pay: true,
      });
      await reloadCart();
      setShowCheckout(false);
      setCartOpen(false);
      setSuccess({
        id: paid.id,
        orderNo: paid.order_no,
        amount: paid.amount_total,
        etaStart: paid.eta_start,
        etaEnd: paid.eta_end,
        address: `${paid.address_snapshot.address_full}${paid.address_snapshot.door_note ? ` ${paid.address_snapshot.door_note}` : ""}`,
        contact: `${paid.contact_snapshot.contact_name} ${paid.contact_snapshot.contact_phone}`,
        invoice: checkoutForm.need_invoice ? checkoutForm.invoice_title.trim() : "不开票"
      });
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="portal-page">
      <div className="portal-page-header">
        <div><div className="portal-title">配件商城</div><div className="portal-subtitle">展示、加购、统一结算，服务单与配件单共用订单流程。</div></div>
        <div className="portal-search small"><span className="portal-search-icon">🔎</span><input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索配件名称 / SKU" /></div>
      </div>

      <div className="portal-pill-group">{CATEGORIES.map((label) => (<button key={label} type="button" className={activeCategory === label ? "portal-pill active" : "portal-pill"} onClick={() => setActiveCategory(label)}>{label}</button>))}</div>
      {hint ? <div className="auth-hint">{hint}</div> : null}
      {error ? <div className="auth-error">{error}</div> : null}

      <div className="portal-grid four">
        {filteredProducts.map((item) => {
          const qty = cartQtyMap[item.sku] || 0;
          return (
            <div key={item.sku} className="portal-card product-card">
              <div className="product-cover">{item.category}</div>
              <span className="product-tag">{item.tag}</span>
              <div className="product-name">{item.name}</div>
              <div className="product-desc">{item.desc}</div>
              <div className="product-footer">
                <span className="product-price">¥{item.price.toFixed(2)}</span>
                <div className="product-actions">
                  <button className="portal-icon-btn" type="button" onClick={() => void changeQty(item.sku, -1)} disabled={itemLoadingSku === item.sku || loading}>-</button>
                  <span className="product-qty">{qty}</span>
                  <button className="portal-icon-btn" type="button" onClick={() => void changeQty(item.sku, 1)} disabled={itemLoadingSku === item.sku || loading}>+</button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="portal-cart-bar enhanced">
        <div className="cart-main">
          <div className="cart-total">¥{totalAmountText}</div>
          <div className="cart-meta">已选 {selectedCount} 件配件</div>
          {previewNames.length ? <div className="cart-preview">{previewNames.join("、")}{hasMorePreview ? "..." : ""}</div> : <div className="cart-preview muted">购物车为空，先挑几件配件吧</div>}
        </div>
        <div className="cart-actions">
          <button className="portal-secondary" type="button" onClick={() => setCartOpen(true)} disabled={selectedCount < 1}>购物车明细</button>
          <button className="portal-ghost danger" type="button" onClick={() => void clearCart()} disabled={loading || selectedCount < 1}>清空购物车</button>
          <button className="portal-cta" type="button" onClick={() => void openCheckout()} disabled={loading || selectedCount < 1}>{loading ? "处理中..." : "去结算"}</button>
        </div>
      </div>

      {cartOpen ? <CartDrawer items={cart.items || []} onClose={() => setCartOpen(false)} onChangeQty={(sku, delta) => void changeQty(sku, delta)} onRemove={(sku) => void updateCartQuantity(sku, 0)} busySku={itemLoadingSku} /> : null}
      {showCheckout && checkoutForm ? <CheckoutModal form={checkoutForm} addresses={addresses} dateOptions={dateOptions} onClose={() => setShowCheckout(false)} onChange={patchCheckout} onSubmit={submitCheckout} loading={loading} /> : null}
      {success ? <OrderSuccessModal info={success} onClose={() => setSuccess(null)} onViewOrder={() => { setSuccess(null); window.location.hash = `#/portal/orders/${success.id}`; }} onContinue={() => setSuccess(null)} /> : null}
    </div>
  );
}

function CartDrawer({ items, onClose, onChangeQty, onRemove, busySku }: { items: Array<{ sku: string; name: string; price: string; quantity: number; amount: string }>; onClose: () => void; onChangeQty: (sku: string, delta: number) => void; onRemove: (sku: string) => void; busySku: string; }) {
  return (
    <div className="portal-modal" onClick={onClose}>
      <div className="portal-modal-card wide cart-drawer" onClick={(event) => event.stopPropagation()}>
        <div className="portal-modal-header"><h3>购物车明细</h3><button className="portal-ghost" type="button" onClick={onClose}>关闭</button></div>
        <div className="portal-modal-list">
          {!items.length ? <div className="portal-subtitle">购物车为空</div> : null}
          {items.map((item) => (
            <div key={item.sku} className="cart-line">
              <div className="cart-line-main">
                <strong>{item.name}</strong>
                <small>单价 ¥{item.price}</small>
              </div>
              <div className="cart-line-actions">
                <button className="portal-icon-btn" type="button" onClick={() => onChangeQty(item.sku, -1)} disabled={busySku === item.sku}>-</button>
                <span>{item.quantity}</span>
                <button className="portal-icon-btn" type="button" onClick={() => onChangeQty(item.sku, 1)} disabled={busySku === item.sku}>+</button>
                <strong>¥{item.amount}</strong>
                <button className="portal-ghost danger" type="button" onClick={() => onRemove(item.sku)} disabled={busySku === item.sku}>删除</button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function CheckoutModal({ form, addresses, dateOptions, onClose, onChange, onSubmit, loading }: { form: CheckoutForm; addresses: PortalAddress[]; dateOptions: Array<{label: string; value: string}>; onClose: () => void; onChange: (patch: Partial<CheckoutForm>) => void; onSubmit: () => void; loading: boolean; }) {
  return (
    <div className="portal-modal">
      <div className="portal-modal-card wide">
        <div className="portal-modal-header"><h3>配件结算</h3><button className="portal-ghost" type="button" onClick={onClose}>关闭</button></div>
        <div className="portal-form-grid">
          <div className="portal-form-full"><label>地址</label><select value={form.address_id} onChange={(event) => onChange({ address_id: Number(event.target.value) })}>{addresses.map((address) => (<option key={address.id} value={address.id}>{address.contact_name} {address.contact_phone} / {address.address_full}</option>))}</select></div>
          <div><label>日期</label><select value={form.eta_date} onChange={(event) => onChange({ eta_date: event.target.value })}>{dateOptions.map((item) => (<option key={item.value} value={item.value}>{item.label}</option>))}</select></div>
          <div><label>时段</label><select value={form.eta_slot} onChange={(event) => onChange({ eta_slot: event.target.value })}>{SLOT_OPTIONS.map((slot) => (<option key={slot} value={slot}>{slot}</option>))}</select></div>
          <div className="portal-form-full auth-checkbox"><input type="checkbox" checked={form.is_urgent} onChange={(event) => onChange({ is_urgent: event.target.checked })} /><span>加急处理</span></div>
          <div className="portal-form-full auth-checkbox"><input type="checkbox" checked={form.need_invoice} onChange={(event) => onChange({ need_invoice: event.target.checked })} /><span>需要发票</span></div>
          {form.need_invoice ? (
            <>
              <div><label>发票抬头</label><input value={form.invoice_title} onChange={(event) => onChange({ invoice_title: event.target.value })} /></div>
              <div><label>税号</label><input value={form.invoice_tax_no} onChange={(event) => onChange({ invoice_tax_no: event.target.value.toUpperCase() })} /></div>
            </>
          ) : null}
          <div className="portal-form-full"><label>备注</label><textarea value={form.notes} rows={2} onChange={(event) => onChange({ notes: event.target.value })} /></div>
        </div>
        <div className="portal-actions"><button className="portal-secondary" type="button" onClick={onClose}>取消</button><button className="portal-cta" type="button" onClick={onSubmit} disabled={loading}>{loading ? "提交中..." : "提交并支付"}</button></div>
      </div>
    </div>
  );
}

function OrderSuccessModal({ info, onClose, onViewOrder, onContinue }: { info: CheckoutSuccess; onClose: () => void; onViewOrder: () => void; onContinue: () => void; }) {
  return (
    <div className="portal-modal">
      <div className="portal-modal-card wide">
        <div className="portal-modal-header"><h3>配件下单成功</h3><button className="portal-ghost" type="button" onClick={onClose}>关闭</button></div>
        <div className="payment-info">
          <div><span>订单号</span><strong>{info.orderNo}</strong></div>
          <div><span>配送时间</span><strong>{info.etaStart.slice(0, 16).replace("T", " ")} - {info.etaEnd.slice(11, 16)}</strong></div>
          <div><span>地址</span><strong>{info.address}</strong></div>
          <div><span>联系人</span><strong>{info.contact}</strong></div>
          <div><span>发票</span><strong>{info.invoice}</strong></div>
          <div><span>金额</span><strong>¥{info.amount}</strong></div>
        </div>
        <div className="portal-actions center"><button className="portal-secondary" type="button" onClick={onViewOrder}>查看订单</button><button className="portal-cta" type="button" onClick={onContinue}>继续购物</button></div>
      </div>
    </div>
  );
}
