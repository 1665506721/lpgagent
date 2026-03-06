import { useEffect, useMemo, useState } from "react";

import {
  PortalApiError,
  createPortalOrder,
  listPortalAddresses,
  payPortalOrder,
  type PortalAddress
} from "../../lib/portalApi";
import { ADDRESSES } from "./portalData";

type ServiceCode =
  | "LPG_CYLINDER_DELIVERY"
  | "CYLINDER_EXCHANGE"
  | "INSTALLATION"
  | "SAFETY_CHECK"
  | "REPAIR";

type OrderFlowPageProps = {
  initialServiceCode?: string;
};

type DraftPayload = {
  companyName: string;
  contactName: string;
  contactPhone: string;
  addressFull: string;
  doorNote: string;
  notes: string;
  isUrgent: boolean;
  selectedDate: string;
  selectedSlot: string;
  needInvoice: boolean;
  invoiceTitle: string;
  invoiceTaxNo: string;
  cylinderType: string;
  quantity: number;
  returnEmpty: boolean;
  installServiceItem: string;
  installItem: string;
  safetyServiceItem: string;
  checkScope: string;
  repairServiceItem: string;
  issueDesc: string;
};

type DraftRecord = {
  id: string;
  serviceCode: ServiceCode;
  updatedAt: string;
  payload: DraftPayload;
};

type SuccessInfo = {
  id: number;
  orderNo: string;
  amount: string;
  etaStart: string;
  etaEnd: string;
  address: string;
  contact: string;
  invoice: string;
};

type ScheduleSeed = { date: string; slot: string };

const DRAFT_BOX_KEY = "portal_order_draft_box_v1";
const SLOT_OPTIONS = ["09:00-11:00", "11:00-13:00", "13:00-15:00", "15:00-17:00", "17:00-19:00", "19:00-21:00"] as const;
const INSTALL_SERVICE_ITEMS = ["热水器安装", "灶具安装", "阀门更换", "管道改造"] as const;
const SAFETY_SERVICE_ITEMS = ["入户安检", "年度安检", "开业前安检", "隐患复检"] as const;
const REPAIR_SERVICE_ITEMS = ["漏气排查", "点火故障", "阀门故障", "管道维修", "其他"] as const;

const SERVICES: { code: ServiceCode; label: string; desc: string }[] = [
  { code: "LPG_CYLINDER_DELIVERY", label: "瓶装配送", desc: "选择瓶型与数量，快速下单" },
  { code: "CYLINDER_EXCHANGE", label: "换瓶", desc: "支持空瓶回收与新瓶更换" },
  { code: "INSTALLATION", label: "安装", desc: "填写安装服务项目，预约上门" },
  { code: "SAFETY_CHECK", label: "安检", desc: "选择安检项目并填写范围" },
  { code: "REPAIR", label: "报修", desc: "选择报修项目并描述故障" }
];

const SERVICE_ICON_MAP: Record<ServiceCode, string> = {
  LPG_CYLINDER_DELIVERY: "📦",
  CYLINDER_EXCHANGE: "🔁",
  INSTALLATION: "🛠",
  SAFETY_CHECK: "🛡",
  REPAIR: "⚠",
};

const SERVICE_LABEL_MAP: Record<ServiceCode, string> = {
  LPG_CYLINDER_DELIVERY: "瓶装配送",
  CYLINDER_EXCHANGE: "换瓶",
  INSTALLATION: "安装",
  SAFETY_CHECK: "安检",
  REPAIR: "报修"
};

const PRICE_MAP = {
  delivery: { "5kg": 60, "15kg": 120, "45kg": 280 },
  installation: 199,
  safety: 99,
  repair: 99
} as const;

function computeEstimate(payload: DraftPayload, serviceCode: ServiceCode) {
  let subtotal = 0;
  if (serviceCode === "LPG_CYLINDER_DELIVERY" || serviceCode === "CYLINDER_EXCHANGE") {
    const unit = PRICE_MAP.delivery[payload.cylinderType as keyof typeof PRICE_MAP.delivery] || PRICE_MAP.delivery["15kg"];
    subtotal = unit * Math.max(1, Number(payload.quantity) || 1);
  } else if (serviceCode === "INSTALLATION") {
    subtotal = PRICE_MAP.installation;
  } else if (serviceCode === "SAFETY_CHECK") {
    subtotal = PRICE_MAP.safety;
  } else {
    subtotal = PRICE_MAP.repair;
  }
  const urgentFee = payload.isUrgent ? Math.min(50, Math.max(10, Math.round(subtotal * 0.1))) : 0;
  return {
    subtotal,
    urgentFee,
    total: subtotal + urgentFee
  };
}

function formatDate(date: Date) {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
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
    return {
      label: index === 0 ? "今天" : index === 1 ? "明天" : `${d.getMonth() + 1}月${d.getDate()}日`,
      value: formatDate(d)
    };
  });
}

function findFirstSlotForDate(dateValue: string, now = new Date()) {
  return SLOT_OPTIONS.find((slot) => isSlotSelectable(dateValue, slot, now)) || null;
}

function findFirstAvailableSchedule(dateValues: string[], now = new Date()): ScheduleSeed {
  for (const dateValue of dateValues) {
    const first = findFirstSlotForDate(dateValue, now);
    if (first) return { date: dateValue, slot: first };
  }
  return { date: dateValues[0], slot: SLOT_OPTIONS[0] };
}

function findNextAvailableFromDate(dateValues: string[], fromDate: string, now = new Date()) {
  const startIndex = Math.max(0, dateValues.indexOf(fromDate));
  for (let index = startIndex; index < dateValues.length; index += 1) {
    const first = findFirstSlotForDate(dateValues[index], now);
    if (first) return { date: dateValues[index], slot: first };
  }
  return null;
}

function mapFallbackAddress() {
  const fallbackPhones = ["13800138000", "13900139000", "18900189000"];
  return ADDRESSES.map((item) => ({
    id: Number(String(item.id).replace(/\D/g, "")) || Math.floor(Math.random() * 100000),
    contact_name: item.name,
    contact_phone: fallbackPhones[Number(String(item.id).replace(/\D/g, "")) % fallbackPhones.length] || fallbackPhones[0],
    address_full: item.address,
    door_note: "",
    is_default: item.tag === "默认",
    created_at: new Date().toISOString()
  } as PortalAddress));
}

function readDraftRecords() {
  try {
    const raw = localStorage.getItem(DRAFT_BOX_KEY);
    if (!raw) return [] as DraftRecord[];
    const parsed = JSON.parse(raw) as DraftRecord[];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item) => item && item.id)
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  } catch {
    return [] as DraftRecord[];
  }
}

function writeDraftRecords(records: DraftRecord[]) {
  const sorted = [...records].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)).slice(0, 50);
  localStorage.setItem(DRAFT_BOX_KEY, JSON.stringify(sorted));
  return sorted;
}

function buildDefaultPayload(scheduleSeed: ScheduleSeed): DraftPayload {
  return {
    companyName: "",
    contactName: "",
    contactPhone: "",
    addressFull: "",
    doorNote: "",
    notes: "",
    isUrgent: false,
    selectedDate: scheduleSeed.date,
    selectedSlot: scheduleSeed.slot,
    needInvoice: false,
    invoiceTitle: "",
    invoiceTaxNo: "",
    cylinderType: "15kg",
    quantity: 1,
    returnEmpty: true,
    installServiceItem: INSTALL_SERVICE_ITEMS[0],
    installItem: "",
    safetyServiceItem: SAFETY_SERVICE_ITEMS[0],
    checkScope: "厨房",
    repairServiceItem: REPAIR_SERVICE_ITEMS[0],
    issueDesc: ""
  };
}

function formatOrderError(err: unknown) {
  if (err instanceof PortalApiError) {
    if (err.code === "VALIDATION_ERROR") {
      const detail = (err.details as { detail?: unknown } | undefined)?.detail;
      if (detail === "eta_slot_in_past") return "所选时间段已过，请重新选择";
    }
    return err.message;
  }
  return err instanceof Error ? err.message : "下单失败，请稍后重试";
}

export default function OrderFlowPage({ initialServiceCode }: OrderFlowPageProps) {
  const dateOptions = useMemo(() => generateDateOptions(), []);
  const dateValues = useMemo(() => dateOptions.map((item) => item.value), [dateOptions]);
  const scheduleSeed = useMemo(() => findFirstAvailableSchedule(dateValues), [dateValues]);

  const [selectedService, setSelectedService] = useState<ServiceCode>(
    initialServiceCode && SERVICES.some((item) => item.code === initialServiceCode)
      ? (initialServiceCode as ServiceCode)
      : "LPG_CYLINDER_DELIVERY"
  );
  const [form, setForm] = useState<DraftPayload>(() => buildDefaultPayload(scheduleSeed));
  const [showAddress, setShowAddress] = useState(false);
  const [addressOptions, setAddressOptions] = useState<PortalAddress[]>([]);
  const [addressLoading, setAddressLoading] = useState(false);
  const [showDraftBox, setShowDraftBox] = useState(false);
  const [draftRecords, setDraftRecords] = useState<DraftRecord[]>(() => readDraftRecords());
  const [currentDraftId, setCurrentDraftId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [hint, setHint] = useState("");
  const [orderInfo, setOrderInfo] = useState<SuccessInfo | null>(null);
  const estimate = useMemo(() => computeEstimate(form, selectedService), [form, selectedService]);

  if (initialServiceCode === "ACCESSORIES") {
    window.location.hash = "#/portal/store";
    return null;
  }

  const patchForm = (patch: Partial<DraftPayload>) => setForm((prev) => ({ ...prev, ...patch }));

  const selectDate = (dateValue: string) => {
    const firstSlot = findFirstSlotForDate(dateValue);
    if (!firstSlot) {
      const fallback = findNextAvailableFromDate(dateValues, dateValue);
      if (!fallback) {
        setHint("当前日期无可用时间段");
        return;
      }
      patchForm({ selectedDate: fallback.date, selectedSlot: fallback.slot });
      setHint(`已自动切换到可用时间：${fallback.date} ${fallback.slot}`);
      return;
    }
    patchForm({ selectedDate: dateValue, selectedSlot: firstSlot });
    setHint("");
  };

  const selectSlot = (slot: string) => {
    if (!isSlotSelectable(form.selectedDate, slot)) {
      setHint("该时间段不可用");
      return;
    }
    patchForm({ selectedSlot: slot });
    setHint("");
  };
  const buildServicePayload = (serviceCode: ServiceCode, payload: DraftPayload) => {
    const invoiceFields = {
      invoice_required: payload.needInvoice,
      invoice_title: payload.needInvoice ? payload.invoiceTitle.trim() : "",
      invoice_tax_no: payload.needInvoice ? payload.invoiceTaxNo.trim() : ""
    };

    if (serviceCode === "LPG_CYLINDER_DELIVERY") {
      return { cylinder_type: payload.cylinderType, quantity: payload.quantity, ...invoiceFields };
    }
    if (serviceCode === "CYLINDER_EXCHANGE") {
      return {
        cylinder_type: payload.cylinderType,
        quantity: payload.quantity,
        return_empty: payload.returnEmpty,
        ...invoiceFields
      };
    }
    if (serviceCode === "INSTALLATION") {
      return {
        install_item: payload.installItem.trim()
          ? `${payload.installServiceItem} - ${payload.installItem.trim()}`
          : payload.installServiceItem,
        ...invoiceFields
      };
    }
    if (serviceCode === "SAFETY_CHECK") {
      return {
        check_scope: payload.checkScope.trim()
          ? `${payload.safetyServiceItem} / ${payload.checkScope.trim()}`
          : payload.safetyServiceItem,
        ...invoiceFields
      };
    }
    return {
      issue_desc: payload.issueDesc.trim()
        ? `${payload.repairServiceItem}: ${payload.issueDesc.trim()}`
        : payload.repairServiceItem,
      ...invoiceFields
    };
  };

  const validateForm = (serviceCode: ServiceCode, payload: DraftPayload) => {
    if (!payload.contactName.trim() || !payload.contactPhone.trim() || !payload.addressFull.trim()) {
      return "请填写联系人、联系电话和服务地址";
    }
    if (!/^(123|1[3-9]\d{9})$/.test(payload.contactPhone.trim())) {
      return "联系电话格式不正确";
    }
    if (!isSlotSelectable(payload.selectedDate, payload.selectedSlot)) {
      return "所选时间段已不可用，请重新选择";
    }
    if (payload.needInvoice && !payload.invoiceTitle.trim()) {
      return "开票时请填写发票抬头";
    }
    if (serviceCode === "REPAIR" && !payload.issueDesc.trim()) {
      return "报修服务需要填写故障描述";
    }
    return "";
  };

  const submitOrder = async (serviceCode: ServiceCode, payload: DraftPayload) => {
    setError("");
    setHint("");

    const token = localStorage.getItem("portal_token");
    if (!token) {
      setError("请先登录再下单");
      window.location.hash = "#/portal/login";
      return;
    }

    const validationError = validateForm(serviceCode, payload);
    if (validationError) {
      setError(validationError);
      return;
    }

    setSubmitting(true);
    try {
      const notesParts = [payload.notes.trim()];
      if (payload.companyName.trim()) notesParts.push(`企业：${payload.companyName.trim()}`);
      if (payload.needInvoice) notesParts.push(`开票：${payload.invoiceTitle.trim()} ${payload.invoiceTaxNo.trim()}`.trim());

      const order = await createPortalOrder({
        service_type: serviceCode,
        service_payload: buildServicePayload(serviceCode, payload),
        contact_name: payload.contactName,
        contact_phone: payload.contactPhone,
        address_full: payload.addressFull,
        door_note: payload.doorNote,
        eta_date: payload.selectedDate,
        eta_slot: payload.selectedSlot,
        is_urgent: payload.isUrgent,
        notes: notesParts.filter(Boolean).join("\n")
      });
      const paid = await payPortalOrder(order.id);

      setOrderInfo({
        id: paid.id,
        orderNo: paid.order_no,
        amount: paid.amount_total,
        etaStart: paid.eta_start,
        etaEnd: paid.eta_end,
        address: `${paid.address_snapshot.address_full}${paid.address_snapshot.door_note ? ` ${paid.address_snapshot.door_note}` : ""}`,
        contact: `${paid.contact_snapshot.contact_name} ${paid.contact_snapshot.contact_phone}`,
        invoice: payload.needInvoice ? payload.invoiceTitle.trim() : "不开票"
      });
    } catch (err) {
      setError(formatOrderError(err));
    } finally {
      setSubmitting(false);
    }
  };

  const saveDraft = () => {
    const now = new Date().toISOString();
    const draftId = currentDraftId || `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const record: DraftRecord = { id: draftId, serviceCode: selectedService, payload: form, updatedAt: now };
    const withoutCurrent = draftRecords.filter((item) => item.id !== draftId);
    setDraftRecords(writeDraftRecords([record, ...withoutCurrent]));
    setCurrentDraftId(draftId);
    setShowDraftBox(true);
    setHint("草稿已保存");
  };

  const loadDraft = (record: DraftRecord) => {
    const next = { ...buildDefaultPayload(scheduleSeed), ...record.payload };
    if (!isSlotSelectable(next.selectedDate, next.selectedSlot)) {
      const fallback = findNextAvailableFromDate(dateValues, next.selectedDate) || scheduleSeed;
      next.selectedDate = fallback.date;
      next.selectedSlot = fallback.slot;
      setHint("草稿中的时间段已过期，已自动调整");
    }
    setSelectedService(record.serviceCode);
    setForm(next);
    setCurrentDraftId(record.id);
    setShowDraftBox(false);
  };

  const removeDraft = (draftId: string) => {
    if (!window.confirm("确认删除该草稿吗？")) return;
    setDraftRecords(writeDraftRecords(draftRecords.filter((item) => item.id !== draftId)));
    if (currentDraftId === draftId) setCurrentDraftId(null);
  };

  const resetForm = () => {
    setForm(buildDefaultPayload(scheduleSeed));
    setCurrentDraftId(null);
    setHint("表单已重置");
    setError("");
  };

  const openAddressModal = async () => {
    setAddressLoading(true);
    try {
      const result = await listPortalAddresses();
      setAddressOptions(result.length > 0 ? result : mapFallbackAddress());
    } catch {
      setAddressOptions(mapFallbackAddress());
      setHint("地址接口暂不可用，已加载本地示例地址");
    } finally {
      setAddressLoading(false);
      setShowAddress(true);
    }
  };

  useEffect(() => {
    const syncDefaultAddress = async () => {
      try {
        const result = await listPortalAddresses();
        if (!Array.isArray(result) || !result.length) return;
        const defaultAddress = result.find((item) => item.is_default) || result[0];
        if (!defaultAddress) return;
        patchForm({
          addressFull: defaultAddress.address_full || "",
          contactName: defaultAddress.contact_name || "",
          contactPhone: defaultAddress.contact_phone || "",
          doorNote: defaultAddress.door_note || "",
        });
      } catch {
        // keep current form
      }
    };
    void syncDefaultAddress();
    const onDataUpdated = (event: Event) => {
      const detail = (event as CustomEvent<{ domains?: string[] }>).detail;
      const domains = Array.isArray(detail?.domains) ? detail?.domains : [];
      if (!domains.length || domains.includes("addresses")) {
        void syncDefaultAddress();
      }
    };
    window.addEventListener("portal:data-updated", onDataUpdated as EventListener);
    return () => {
      window.removeEventListener("portal:data-updated", onDataUpdated as EventListener);
    };
  }, []);

  return (
    <div className="portal-page">
      <div className="portal-page-header">
        <div>
          <div className="portal-title">下单服务</div>
          <div className="portal-subtitle">服务类型与服务信息整合在同一表单中，支持草稿与快速下单。</div>
        </div>
      </div>

      <div className="portal-card order-flow-block">
        <div className="order-flow-section-head">
          <span className="order-flow-step">1</span>
          <h3>选择服务类型</h3>
        </div>
        <div className="order-service-grid">
          {SERVICES.map((service) => (
            <button
              key={service.code}
              type="button"
              className={`order-service-card ${selectedService === service.code ? "active" : ""}`}
              onClick={() => {
                setSelectedService(service.code);
                setCurrentDraftId(null);
              }}
            >
              <div className="order-service-card-head">
                <span className="order-service-icon">{SERVICE_ICON_MAP[service.code]}</span>
                <span className={`order-service-radio ${selectedService === service.code ? "active" : ""}`} />
              </div>
              <span className="order-service-title">{service.label}</span>
              <small>{service.desc}</small>
            </button>
          ))}
          <button className="order-service-card accessory" type="button" onClick={() => (window.location.hash = "#/portal/store")}>
            <div className="order-service-card-head">
              <span className="order-service-icon">🛒</span>
              <span className="order-service-radio" />
            </div>
            <span className="order-service-title">配件商城</span>
            <small>配件请进入商城购物车统一下单</small>
          </button>
        </div>
      </div>
      <div className="portal-card order-flow-block">
        <div className="order-flow-section-head">
          <span className="order-flow-step">2</span>
          <h3>填写服务信息</h3>
        </div>
        <div className="order-flow-form-grid">
          <label>
            企业/单位名称（可选）
            <input
              placeholder="请输入企业名称"
              value={form.companyName}
              onChange={(event) => patchForm({ companyName: event.target.value })}
            />
          </label>
          <label>
            服务地址
            <div className="portal-inline">
              <input
                placeholder="请选择或输入地址"
                value={form.addressFull}
                onChange={(event) => patchForm({ addressFull: event.target.value })}
              />
              <button className="portal-ghost" type="button" onClick={openAddressModal} disabled={addressLoading}>
                {addressLoading ? "加载中..." : "地址簿"}
              </button>
            </div>
          </label>
          <label>
            联系人姓名
            <input
              placeholder="请输入姓名"
              value={form.contactName}
              onChange={(event) => patchForm({ contactName: event.target.value })}
            />
          </label>
          <label>
            联系电话
            <input
              placeholder="请输入电话"
              value={form.contactPhone}
              onChange={(event) => patchForm({ contactPhone: event.target.value.replace(/\D/g, "") })}
            />
          </label>

          <label className="portal-form-full">
            门牌备注
            <input
              placeholder="例如：1号楼203室"
              value={form.doorNote}
              onChange={(event) => patchForm({ doorNote: event.target.value })}
            />
          </label>

          <label className="portal-form-full">
            服务项目字段
            <div className="order-flow-service-fields">
              {(selectedService === "LPG_CYLINDER_DELIVERY" || selectedService === "CYLINDER_EXCHANGE") ? (
                <>
                  <select value={form.cylinderType} onChange={(event) => patchForm({ cylinderType: event.target.value })}>
                    <option value="5kg">5kg</option>
                    <option value="15kg">15kg</option>
                    <option value="45kg">45kg</option>
                  </select>
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={form.quantity}
                    onChange={(event) => patchForm({ quantity: Math.max(1, Number(event.target.value) || 1) })}
                  />
                  {selectedService === "CYLINDER_EXCHANGE" ? (
                    <label className="auth-checkbox">
                      <input type="checkbox" checked={form.returnEmpty} onChange={(event) => patchForm({ returnEmpty: event.target.checked })} />
                      <span>回收空瓶</span>
                    </label>
                  ) : null}
                </>
              ) : null}
              {selectedService === "INSTALLATION" ? (
                <>
                  <select value={form.installServiceItem} onChange={(event) => patchForm({ installServiceItem: event.target.value })}>
                    {INSTALL_SERVICE_ITEMS.map((item) => (<option key={item} value={item}>{item}</option>))}
                  </select>
                  <input value={form.installItem} onChange={(event) => patchForm({ installItem: event.target.value })} placeholder="设备型号/品牌（可选）" />
                </>
              ) : null}
              {selectedService === "SAFETY_CHECK" ? (
                <>
                  <select value={form.safetyServiceItem} onChange={(event) => patchForm({ safetyServiceItem: event.target.value })}>
                    {SAFETY_SERVICE_ITEMS.map((item) => (<option key={item} value={item}>{item}</option>))}
                  </select>
                  <input value={form.checkScope} onChange={(event) => patchForm({ checkScope: event.target.value })} placeholder="安检范围（如厨房、后厨）" />
                </>
              ) : null}
              {selectedService === "REPAIR" ? (
                <>
                  <select value={form.repairServiceItem} onChange={(event) => patchForm({ repairServiceItem: event.target.value })}>
                    {REPAIR_SERVICE_ITEMS.map((item) => (<option key={item} value={item}>{item}</option>))}
                  </select>
                  <input value={form.issueDesc} onChange={(event) => patchForm({ issueDesc: event.target.value })} placeholder="请描述故障情况" />
                </>
              ) : null}
            </div>
          </label>

          <label className="portal-form-full">
            预约时间
            <div className="schedule-panel order-flow-schedule">
              <div className="schedule-days">
                {dateOptions.map((item) => (
                  <button key={item.value} type="button" className={form.selectedDate === item.value ? "portal-pill active" : "portal-pill"} onClick={() => selectDate(item.value)}>{item.label}</button>
                ))}
              </div>
              <div className="schedule-slots">
                {SLOT_OPTIONS.map((slot) => (
                  <button key={slot} type="button" disabled={!isSlotSelectable(form.selectedDate, slot)} className={form.selectedSlot === slot ? "slot active" : "slot"} onClick={() => selectSlot(slot)}>{slot}</button>
                ))}
              </div>
            </div>
          </label>

          <div className="portal-form-full order-flow-switches">
            <label className="auth-checkbox">
              <input type="checkbox" checked={form.isUrgent} onChange={(event) => patchForm({ isUrgent: event.target.checked })} />
              <span>加急处理（加收费用）</span>
            </label>
            <label className="auth-checkbox">
              <input type="checkbox" checked={form.needInvoice} onChange={(event) => patchForm({ needInvoice: event.target.checked })} />
              <span>需要开票</span>
            </label>
          </div>

          {form.needInvoice ? (
            <div className="portal-form-full order-flow-service-fields invoice-fields">
              <input value={form.invoiceTitle} onChange={(event) => patchForm({ invoiceTitle: event.target.value })} placeholder="发票抬头（必填）" />
              <input value={form.invoiceTaxNo} onChange={(event) => patchForm({ invoiceTaxNo: event.target.value.toUpperCase() })} placeholder="税号（可选）" />
            </div>
          ) : null}

          <label className="portal-form-full">
            备注信息
            <textarea placeholder="如有其他特殊要求，请在此填写" value={form.notes} onChange={(event) => patchForm({ notes: event.target.value })} rows={4} />
          </label>
        </div>

        {hint ? <div className="auth-hint">{hint}</div> : null}
        {error ? <div className="auth-error">{error}</div> : null}

        <div className="order-flow-summary">
          <div className="order-flow-amount">
            <span>预计总金额</span>
            <strong>¥{estimate.total.toFixed(2)}</strong>
            <small>小计 ¥{estimate.subtotal.toFixed(2)} {estimate.urgentFee > 0 ? `+ 加急 ¥${estimate.urgentFee.toFixed(2)}` : ""}</small>
          </div>
          <div className="order-flow-summary-actions">
            <button className="portal-ghost danger" type="button" onClick={resetForm}>重置</button>
            <button className="portal-secondary" type="button" onClick={saveDraft}>保存草稿</button>
            <button className={showDraftBox ? "portal-secondary active" : "portal-secondary"} type="button" onClick={() => setShowDraftBox((prev) => !prev)}>
              草稿箱（{draftRecords.length}）
            </button>
            <button className="portal-cta" type="button" onClick={() => void submitOrder(selectedService, form)} disabled={submitting}>
              {submitting ? "提交中..." : "提交订单"}
            </button>
          </div>
        </div>

        {showDraftBox ? (
          <div className="draft-box">
            <div className="draft-box-list">
              {draftRecords.length === 0 ? <div className="empty-card">暂无草稿</div> : null}
              {draftRecords.map((record) => (
                <div key={record.id} className="portal-card draft-item">
                  <div className="draft-item-main">
                    <div className="draft-item-title">{SERVICE_LABEL_MAP[record.serviceCode]}</div>
                    <div className="draft-item-meta">{new Date(record.updatedAt).toLocaleString()}</div>
                  </div>
                  <div className="draft-item-actions">
                    <button className="portal-secondary" type="button" onClick={() => loadDraft(record)}>载入</button>
                    <button className="portal-cta" type="button" onClick={() => void submitOrder(record.serviceCode, record.payload)}>直接下单</button>
                    <button className="portal-ghost danger" type="button" onClick={() => removeDraft(record.id)}>删除</button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      {showAddress ? (
        <AddressModal
          addresses={addressOptions}
          onClose={() => setShowAddress(false)}
          onSelect={(address) => {
            patchForm({ addressFull: address.address_full, contactName: address.contact_name, contactPhone: address.contact_phone, doorNote: address.door_note || "" });
            setShowAddress(false);
          }}
        />
      ) : null}

      {orderInfo ? (
        <OrderSuccessModal
          info={orderInfo}
          onClose={() => setOrderInfo(null)}
          onViewOrder={() => { setOrderInfo(null); window.location.hash = `#/portal/orders/${orderInfo.id}`; }}
          onContinue={() => { setOrderInfo(null); resetForm(); }}
        />
      ) : null}
    </div>
  );
}

function AddressModal({ addresses, onClose, onSelect }: { addresses: PortalAddress[]; onClose: () => void; onSelect: (address: PortalAddress) => void; }) {
  return (
    <div className="portal-modal">
      <div className="portal-modal-card">
        <div className="portal-modal-header">
          <h3>选择地址</h3>
          <button className="portal-ghost" type="button" onClick={onClose}>关闭</button>
        </div>
        <div className="portal-modal-list">
          {addresses.length === 0 ? <div className="empty-card">暂无地址，请先到个人中心新增地址</div> : null}
          {addresses.map((address) => (
            <div key={address.id} className="portal-card address-select">
              <div>
                <div className="address-name">{address.contact_name} {address.contact_phone} {address.is_default ? "(默认)" : ""}</div>
                <div className="address-detail">{address.address_full}</div>
              </div>
              <button className="portal-secondary" type="button" onClick={() => onSelect(address)}>使用</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function OrderSuccessModal({ info, onClose, onViewOrder, onContinue }: { info: SuccessInfo; onClose: () => void; onViewOrder: () => void; onContinue: () => void; }) {
  return (
    <div className="portal-modal">
      <div className="portal-modal-card wide">
        <div className="portal-modal-header">
          <h3>下单并支付成功</h3>
          <button className="portal-ghost" type="button" onClick={onClose}>关闭</button>
        </div>
        <div className="payment-info">
          <div><span>订单号</span><strong>{info.orderNo}</strong></div>
          <div><span>服务时间</span><strong>{info.etaStart.slice(0, 16).replace("T", " ")} - {info.etaEnd.slice(11, 16)}</strong></div>
          <div><span>联系人</span><strong>{info.contact}</strong></div>
          <div><span>地址</span><strong>{info.address}</strong></div>
          <div><span>发票</span><strong>{info.invoice}</strong></div>
          <div><span>金额</span><strong>¥{info.amount}</strong></div>
        </div>
        <div className="portal-actions center">
          <button className="portal-secondary" type="button" onClick={onViewOrder}>查看订单</button>
          <button className="portal-cta" type="button" onClick={onContinue}>继续下单</button>
        </div>
      </div>
    </div>
  );
}

