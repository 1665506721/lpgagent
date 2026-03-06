import { useCallback, useEffect, useState } from "react";

import {
  changePortalPassword,
  createPortalAddress,
  createPortalFeedback,
  deletePortalAddress,
  getPortalMe,
  listPortalAddresses,
  listPortalFeedbacks,
  listPortalOrders,
  setPortalDefaultAddress,
  updatePortalAddress,
  updatePortalMe,
  type PortalAddress,
  type PortalAuthProfile,
  type PortalFeedbackItem,
  type PortalOrderListItem,
} from "../../lib/portalApi";

function handleLogout() {
  localStorage.removeItem("portal_token");
  localStorage.removeItem("portal_profile_phone");
  localStorage.removeItem("portal_profile_id");
  window.location.hash = "#/portal/login";
}

function maskPhone(phone: string) {
  const cleaned = (phone || "").replace(/\D/g, "");
  if (cleaned.length !== 11) return phone;
  return `${cleaned.slice(0, 3)}****${cleaned.slice(7)}`;
}

function isValidCnPhone(phone: string) {
  const normalized = (phone || "").trim();
  if (normalized === "123") return true;
  return /^1[3-9]\d{9}$/.test(normalized);
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatAmount(amount: string, currency: string) {
  const number = Number(amount);
  if (Number.isNaN(number)) return `${currency} ${amount}`;
  return currency === "CNY" ? `¥${number.toFixed(2)}` : `${currency} ${number.toFixed(2)}`;
}

function feedbackStatusLabel(status: string) {
  if (status === "NEW") return "待处理";
  if (status === "PROCESSING") return "处理中";
  if (status === "CLOSED") return "已关闭";
  return status;
}

function orderStatusClass(status: string) {
  if (status === "COMPLETED") return "success";
  if (status === "CANCELED" || status === "EXPIRED") return "danger";
  if (status === "PENDING_PAYMENT") return "warn";
  return "info";
}

type AddressFormState = {
  id?: number;
  contact_name: string;
  contact_phone: string;
  address_full: string;
  door_note: string;
  is_default: boolean;
};

type FeedbackFormState = {
  feedback_type: "COMPLAINT" | "SUGGESTION";
  target_type: "ONLINE_SERVICE" | "ORDER_SERVICE";
  order_id: string;
  title: string;
  content: string;
  contact_phone: string;
};

const EMPTY_ADDRESS_FORM: AddressFormState = {
  contact_name: "",
  contact_phone: "",
  address_full: "",
  door_note: "",
  is_default: false,
};

const EMPTY_FEEDBACK_FORM: FeedbackFormState = {
  feedback_type: "COMPLAINT",
  target_type: "ONLINE_SERVICE",
  order_id: "",
  title: "",
  content: "",
  contact_phone: "",
};

export default function ProfileCenterPage() {
  const [profile, setProfile] = useState<PortalAuthProfile | null>(null);
  const [addresses, setAddresses] = useState<PortalAddress[]>([]);
  const [recentOrders, setRecentOrders] = useState<PortalOrderListItem[]>([]);
  const [orderOptions, setOrderOptions] = useState<PortalOrderListItem[]>([]);
  const [feedbackRecords, setFeedbackRecords] = useState<PortalFeedbackItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [actionHint, setActionHint] = useState("");

  const [displayName, setDisplayName] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);

  const [passwordModalOpen, setPasswordModalOpen] = useState(false);
  const [pwdOld, setPwdOld] = useState("");
  const [pwdNew, setPwdNew] = useState("");
  const [pwdConfirm, setPwdConfirm] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);

  const [addressFormOpen, setAddressFormOpen] = useState(false);
  const [addressForm, setAddressForm] = useState<AddressFormState>(EMPTY_ADDRESS_FORM);
  const [savingAddress, setSavingAddress] = useState(false);
  const [settingDefaultId, setSettingDefaultId] = useState<number | null>(null);
  const [deletingAddressId, setDeletingAddressId] = useState<number | null>(null);

  const [feedbackModalOpen, setFeedbackModalOpen] = useState(false);
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false);
  const [feedbackForm, setFeedbackForm] = useState<FeedbackFormState>(EMPTY_FEEDBACK_FORM);

  const [lastDirtyAt, setLastDirtyAt] = useState(() => localStorage.getItem("portal_data_dirty_at") || "");

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [meData, addressData, orderData, orderOptionsData, feedbackData] = await Promise.all([
        getPortalMe(),
        listPortalAddresses(),
        listPortalOrders({ page: 1, page_size: 2 }),
        listPortalOrders({ page: 1, page_size: 50 }),
        listPortalFeedbacks(),
      ]);
      setProfile(meData);
      setDisplayName(meData.display_name || "");
      localStorage.setItem("portal_profile_phone", meData.phone || "");
      localStorage.setItem("portal_profile_id", String(meData.id || ""));
      setAddresses(addressData);
      setRecentOrders(orderData.items || []);
      setOrderOptions(orderOptionsData.items || []);
      setFeedbackRecords(feedbackData || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "个人中心加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  useEffect(() => {
    const refreshIfProfile = () => {
      if (window.location.hash.startsWith("#/portal/profile")) {
        void loadData();
      }
    };
    const refreshFromDataUpdate = (event: Event) => {
      const detail = (event as CustomEvent<{ domains?: string[] }>).detail;
      const domains = Array.isArray(detail?.domains) ? detail?.domains : [];
      if (
        !domains.length
        || domains.includes("profile")
        || domains.includes("addresses")
        || domains.includes("orders")
        || domains.includes("notifications")
      ) {
        refreshIfProfile();
      }
    };
    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        refreshIfProfile();
      }
    };
    window.addEventListener("focus", refreshIfProfile);
    window.addEventListener("hashchange", refreshIfProfile);
    window.addEventListener("portal:data-updated", refreshFromDataUpdate as EventListener);
    window.addEventListener("storage", refreshIfProfile);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      window.removeEventListener("focus", refreshIfProfile);
      window.removeEventListener("hashchange", refreshIfProfile);
      window.removeEventListener("portal:data-updated", refreshFromDataUpdate as EventListener);
      window.removeEventListener("storage", refreshIfProfile);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [loadData]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const stamp = localStorage.getItem("portal_data_dirty_at") || "";
      if (stamp && stamp !== lastDirtyAt) {
        setLastDirtyAt(stamp);
        if (window.location.hash.startsWith("#/portal/profile")) {
          void loadData();
        }
      }
    }, 25000);
    return () => window.clearInterval(timer);
  }, [lastDirtyAt, loadData]);

  const openCreateAddress = () => {
    setAddressForm(EMPTY_ADDRESS_FORM);
    setAddressFormOpen(true);
  };

  const openEditAddress = (address: PortalAddress) => {
    setAddressForm({
      id: address.id,
      contact_name: address.contact_name,
      contact_phone: address.contact_phone,
      address_full: address.address_full,
      door_note: address.door_note,
      is_default: address.is_default,
    });
    setAddressFormOpen(true);
  };

  const handleSaveProfile = async () => {
    setError("");
    setFeedback("");
    if (!displayName.trim()) {
      setError("昵称不能为空");
      return;
    }
    setSavingProfile(true);
    try {
      const updated = await updatePortalMe({ display_name: displayName.trim() });
      setProfile(updated);
      setDisplayName(updated.display_name || "");
      setFeedback("个人资料已更新");
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新昵称失败");
    } finally {
      setSavingProfile(false);
    }
  };

  const handleChangePassword = async () => {
    setError("");
    setFeedback("");
    if (!pwdOld.trim() || !pwdNew.trim() || !pwdConfirm.trim()) {
      setError("请完整填写密码信息");
      return;
    }
    if (pwdNew.length < 8) {
      setError("新密码至少 8 位");
      return;
    }
    if (pwdNew !== pwdConfirm) {
      setError("两次输入的新密码不一致");
      return;
    }
    setSavingPassword(true);
    try {
      const result = await changePortalPassword({
        old_password: pwdOld,
        new_password: pwdNew,
        confirm_password: pwdConfirm,
      });
      localStorage.setItem("portal_token", result.token);
      setPwdOld("");
      setPwdNew("");
      setPwdConfirm("");
      setPasswordModalOpen(false);
      setFeedback("密码修改成功");
    } catch (err) {
      setError(err instanceof Error ? err.message : "修改密码失败");
    } finally {
      setSavingPassword(false);
    }
  };

  const handleSaveAddress = async () => {
    setError("");
    setFeedback("");
    if (!addressForm.contact_name.trim() || !addressForm.contact_phone.trim() || !addressForm.address_full.trim()) {
      setError("请完整填写地址信息");
      return;
    }
    if (!isValidCnPhone(addressForm.contact_phone)) {
      setError("地址联系电话需为中国大陆手机号（测试号可用 123）");
      return;
    }

    setSavingAddress(true);
    try {
      const payload = {
        contact_name: addressForm.contact_name.trim(),
        contact_phone: addressForm.contact_phone.trim(),
        address_full: addressForm.address_full.trim(),
        door_note: addressForm.door_note.trim(),
        is_default: addressForm.is_default,
      };
      if (addressForm.id) {
        await updatePortalAddress(addressForm.id, payload);
        setFeedback("地址已更新");
      } else {
        await createPortalAddress(payload);
        setFeedback("地址已新增");
      }
      setAddressFormOpen(false);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存地址失败");
    } finally {
      setSavingAddress(false);
    }
  };

  const handleSetDefaultAddress = async (address: PortalAddress) => {
    setError("");
    setFeedback("");
    setSettingDefaultId(address.id);
    try {
      await setPortalDefaultAddress(address.id);
      setFeedback("默认地址已更新");
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "设置默认地址失败");
    } finally {
      setSettingDefaultId(null);
    }
  };

  const handleDeleteAddress = async (address: PortalAddress) => {
    const confirmed = window.confirm(`确认删除地址：${address.address_full} 吗？`);
    if (!confirmed) return;

    setError("");
    setFeedback("");
    setDeletingAddressId(address.id);
    try {
      await deletePortalAddress(address.id);
      setFeedback("地址已删除");
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除地址失败");
    } finally {
      setDeletingAddressId(null);
    }
  };

  const openFeedbackModal = (feedbackType: "COMPLAINT" | "SUGGESTION") => {
    setFeedbackForm({
      ...EMPTY_FEEDBACK_FORM,
      feedback_type: feedbackType,
      contact_phone: profile?.phone || "",
    });
    setFeedbackModalOpen(true);
  };

  const handleSubmitFeedback = async () => {
    setError("");
    setFeedback("");

    if (!feedbackForm.title.trim() || !feedbackForm.content.trim()) {
      setError("请填写反馈标题与详细内容");
      return;
    }
    if (feedbackForm.target_type === "ORDER_SERVICE" && !feedbackForm.order_id) {
      setError("请选择要投诉/建议的订单");
      return;
    }
    if (feedbackForm.contact_phone && !isValidCnPhone(feedbackForm.contact_phone)) {
      setError("联系电话格式不正确");
      return;
    }

    setFeedbackSubmitting(true);
    try {
      await createPortalFeedback({
        feedback_type: feedbackForm.feedback_type,
        target_type: feedbackForm.target_type,
        order_id: feedbackForm.target_type === "ORDER_SERVICE" ? Number(feedbackForm.order_id) : undefined,
        title: feedbackForm.title.trim(),
        content: feedbackForm.content.trim(),
        contact_phone: feedbackForm.contact_phone.trim() || undefined,
      });
      setFeedbackModalOpen(false);
      setFeedback("提交成功，我们会尽快处理您的反馈");
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交反馈失败");
    } finally {
      setFeedbackSubmitting(false);
    }
  };

  const defaultAddress = addresses.find((item) => item.is_default) || null;
  const pendingOrderCount = recentOrders.filter((item) => item.status === "PENDING_PAYMENT").length;
  const activeOrderCount = recentOrders.filter((item) => ["PAID", "SCHEDULED", "IN_SERVICE"].includes(item.status)).length;
  const feedbackOpenCount = feedbackRecords.filter((item) => item.status !== "CLOSED").length;
  const profileCompletion = [Boolean(profile?.display_name), Boolean(profile?.phone), Boolean(defaultAddress), recentOrders.length > 0].filter(Boolean).length;
  const profileCompletionPercent = Math.round((profileCompletion / 4) * 100);

  return (
    <div className="portal-page profile-page profile-v2">
      <div className="portal-card profile-v2-hero">
        <div className="profile-v2-hero-main">
          <div className="profile-avatar">👤</div>
          <div className="profile-v2-identity">
            <div className="profile-name">{profile?.display_name || "未命名用户"}</div>
            <div className="profile-meta">ID: {profile?.id || "-"} · 账号: {profile?.phone || "-"}</div>
            <div className="profile-chip-row">
              <span className="portal-pill active">资料完整度 {profileCompletionPercent}%</span>
              <span className="portal-pill">{defaultAddress ? "默认地址已设置" : "尚未设置默认地址"}</span>
            </div>
          </div>
        </div>
        <div className="profile-actions">
          <button className="portal-secondary" type="button" onClick={() => (window.location.hash = "#/portal/orders")}>我的订单</button>
          <button className="portal-secondary" type="button" onClick={() => (window.location.hash = "#/portal/chat")}>联系客服</button>
          <button className="portal-secondary" type="button" onClick={() => openFeedbackModal("COMPLAINT")}>提交投诉</button>
          <button
            className="portal-ghost"
            type="button"
            onClick={() => {
              if (!profile?.phone) return;
              navigator.clipboard.writeText(profile.phone).then(() => setActionHint("已复制账号手机号")).catch(() => setActionHint("复制失败，请手动复制"));
            }}
          >
            复制手机号
          </button>
          <button className="portal-ghost danger" type="button" onClick={handleLogout}>退出登录</button>
        </div>
      </div>

      <div className="profile-v2-stats">
        <div className="portal-card profile-v2-stat"><div className="metric-title">待支付订单</div><div className="metric-value">{pendingOrderCount}</div><div className="metric-sub">可在订单页快速支付或取消</div></div>
        <div className="portal-card profile-v2-stat"><div className="metric-title">待服务订单</div><div className="metric-value">{activeOrderCount}</div><div className="metric-sub">包含已支付 / 已预约 / 服务中</div></div>
        <div className="portal-card profile-v2-stat"><div className="metric-title">地址数量</div><div className="metric-value">{addresses.length}</div><div className="metric-sub">默认联系人：{defaultAddress?.contact_name || "-"}</div></div>
        <div className="portal-card profile-v2-stat"><div className="metric-title">资料完成度</div><div className="metric-value">{profileCompletionPercent}%</div><div className="metric-sub">建议保持默认地址与联系方式最新</div></div>
      </div>

      {loading ? <div className="portal-card empty-card">个人信息加载中...</div> : null}
      {actionHint ? <div className="auth-hint">{actionHint}</div> : null}
      {feedback ? <div className="auth-hint">{feedback}</div> : null}
      {error ? <div className="auth-error">{error}</div> : null}

      <div className="profile-v2-main">
        <div className="profile-v2-left">
          <div className="portal-card section-card">
            <div className="portal-section-header compact">
              <div>
                <div className="portal-card-title">基础资料</div>
                <div className="portal-subtitle">昵称将用于客服称呼和下单默认联系人建议</div>
              </div>
              <button className="portal-secondary" type="button" onClick={() => setPasswordModalOpen(true)}>修改密码</button>
            </div>
            <div className="portal-form-grid">
              <div><label>昵称</label><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="请输入昵称" /></div>
              <div><label>手机号（登录账号）</label><input value={profile?.phone || ""} disabled /></div>
            </div>
            <div className="portal-actions">
              <button className="portal-secondary" type="button" onClick={() => void loadData()}>刷新资料</button>
              <button className="portal-cta" type="button" disabled={savingProfile} onClick={handleSaveProfile}>{savingProfile ? "保存中..." : "保存更改"}</button>
            </div>
          </div>

          <div className="portal-card section-card">
            <div className="portal-section-header"><h2>地址管理</h2><button className="portal-cta" type="button" onClick={openCreateAddress}>+ 新增地址</button></div>
            <div className="portal-subtitle">地址手机号仅允许中国大陆手机号（测试账号可用 123）</div>
            <div className="profile-v2-address-list">
              {addresses.length === 0 ? <div className="empty-card">暂无地址，请新增一个收货地址。</div> : null}
              {addresses.map((address) => (
                <div key={address.id} className={`profile-v2-address-item ${address.is_default ? "default" : ""}`}>
                  <div className="profile-v2-address-main">
                    <div className="address-name">{address.contact_name}{address.is_default ? <span className="portal-pill active">默认</span> : null}</div>
                    <div className="address-phone">{maskPhone(address.contact_phone)}</div>
                    <div className="address-detail">{address.address_full}</div>
                    {address.door_note ? <div className="address-detail">{address.door_note}</div> : null}
                  </div>
                  <div className="address-tools">
                    {!address.is_default ? (
                      <button className="portal-ghost" type="button" disabled={settingDefaultId === address.id} onClick={() => void handleSetDefaultAddress(address)}>{settingDefaultId === address.id ? "设置中..." : "设为默认"}</button>
                    ) : null}
                    <button className="portal-ghost" type="button" onClick={() => openEditAddress(address)}>编辑</button>
                    <button className="portal-ghost danger" type="button" disabled={deletingAddressId === address.id} onClick={() => void handleDeleteAddress(address)}>{deletingAddressId === address.id ? "删除中..." : "删除"}</button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="profile-v2-right">
          <div className="portal-card section-card profile-v2-side-card">
            <div className="portal-section-header"><h2>最近订单</h2><button className="portal-secondary" type="button" onClick={() => (window.location.hash = "#/portal/orders")}>查看全部订单</button></div>
            <div className="profile-v2-order-list">
              {recentOrders.length === 0 ? <div className="empty-card">暂无订单记录</div> : null}
              {recentOrders.map((order) => (
                <div key={order.id} className="profile-v2-order-item">
                  <div className="order-card-header">
                    <div><div className="address-name">{order.service_type_label}</div><div className="address-phone">{order.order_no}</div></div>
                    <span className={`portal-status ${orderStatusClass(order.status)}`}>{order.status_label}</span>
                  </div>
                  <div className="address-detail">下单：{formatDateTime(order.created_at)}</div>
                  <div className="address-detail">服务：{formatDateTime(order.eta_start)}</div>
                  <div className="profile-v2-order-foot">
                    <strong>{formatAmount(order.amount_total, order.currency)}</strong>
                    <button className="portal-ghost" type="button" onClick={() => (window.location.hash = `#/portal/orders/${order.id}`)}>详情</button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="portal-card section-card profile-v2-side-card">
            <div className="portal-section-header">
              <h2>反馈建议</h2>
              <div className="portal-actions">
                <button className="portal-secondary" type="button" onClick={() => openFeedbackModal("COMPLAINT")}>投诉</button>
                <button className="portal-secondary" type="button" onClick={() => openFeedbackModal("SUGGESTION")}>建议</button>
              </div>
            </div>
            <div className="profile-v2-feedback-list">
              {feedbackRecords.length === 0 ? <div className="empty-card">暂无反馈记录</div> : null}
              {feedbackRecords.slice(0, 3).map((item) => (
                <div key={item.id} className="profile-v2-feedback-item">
                  <div className="address-head"><div className="address-name">{item.feedback_type === "COMPLAINT" ? "投诉" : "建议"} · {item.title}</div><span className="portal-pill">{feedbackStatusLabel(item.status)}</span></div>
                  <div className="address-detail">{item.target_type === "ORDER_SERVICE" ? `订单：${item.order_no || "-"}` : "线上服务"}</div>
                  <div className="address-detail">{item.content}</div>
                  <div className="address-detail">提交时间：{formatDateTime(item.created_at)}</div>
                </div>
              ))}
              {feedbackOpenCount > 0 ? <div className="portal-subtitle">当前待处理反馈：{feedbackOpenCount}</div> : null}
            </div>
          </div>
        </div>
      </div>

      {passwordModalOpen ? (
        <div className="portal-modal" onClick={() => setPasswordModalOpen(false)}>
          <div className="portal-modal-card profile-password-modal" onClick={(event) => event.stopPropagation()}>
            <div className="portal-modal-header"><h3>修改密码</h3><button className="portal-ghost" type="button" onClick={() => setPasswordModalOpen(false)}>关闭</button></div>
            <div className="portal-form-grid">
              <div className="portal-form-full"><label>旧密码</label><input type="password" value={pwdOld} onChange={(event) => setPwdOld(event.target.value)} placeholder="请输入旧密码" /></div>
              <div><label>新密码</label><input type="password" value={pwdNew} onChange={(event) => setPwdNew(event.target.value)} placeholder="至少8位" /></div>
              <div><label>确认新密码</label><input type="password" value={pwdConfirm} onChange={(event) => setPwdConfirm(event.target.value)} placeholder="再次输入新密码" /></div>
            </div>
            <div className="portal-actions">
              <button className="portal-secondary" type="button" onClick={() => setPasswordModalOpen(false)}>取消</button>
              <button className="portal-cta" type="button" disabled={savingPassword} onClick={() => void handleChangePassword()}>{savingPassword ? "提交中..." : "确认修改"}</button>
            </div>
          </div>
        </div>
      ) : null}

      {addressFormOpen ? (
        <div className="portal-modal">
          <div className="portal-modal-card">
            <div className="portal-modal-header"><h3>{addressForm.id ? "编辑地址" : "新增地址"}</h3><button className="portal-ghost" type="button" onClick={() => setAddressFormOpen(false)}>关闭</button></div>
            <div className="portal-form-grid">
              <div><label>联系人</label><input value={addressForm.contact_name} onChange={(event) => setAddressForm((prev) => ({ ...prev, contact_name: event.target.value }))} placeholder="请输入联系人姓名" /></div>
              <div><label>联系电话（中国大陆手机号）</label><input value={addressForm.contact_phone} onChange={(event) => setAddressForm((prev) => ({ ...prev, contact_phone: event.target.value.replace(/\D/g, "") }))} placeholder="11位手机号，如 13800138000" /></div>
              <div className="portal-form-full"><label>详细地址</label><input value={addressForm.address_full} onChange={(event) => setAddressForm((prev) => ({ ...prev, address_full: event.target.value }))} placeholder="请输入详细地址" /></div>
              <div className="portal-form-full"><label>门牌备注</label><input value={addressForm.door_note} onChange={(event) => setAddressForm((prev) => ({ ...prev, door_note: event.target.value }))} placeholder="如：3号楼2单元302" /></div>
              <div className="portal-form-full auth-checkbox"><input type="checkbox" checked={addressForm.is_default} onChange={(event) => setAddressForm((prev) => ({ ...prev, is_default: event.target.checked }))} /><span>设为默认地址</span></div>
            </div>
            <div className="portal-actions">
              <button className="portal-secondary" type="button" onClick={() => setAddressFormOpen(false)}>取消</button>
              <button className="portal-cta" type="button" disabled={savingAddress} onClick={() => void handleSaveAddress()}>{savingAddress ? "保存中..." : "保存地址"}</button>
            </div>
          </div>
        </div>
      ) : null}

      {feedbackModalOpen ? (
        <div className="portal-modal">
          <div className="portal-modal-card wide">
            <div className="portal-modal-header"><h3>{feedbackForm.feedback_type === "COMPLAINT" ? "提交投诉" : "提交建议"}</h3><button className="portal-ghost" type="button" onClick={() => setFeedbackModalOpen(false)}>关闭</button></div>
            <div className="portal-form-grid">
              <div>
                <label>反馈类型</label>
                <select value={feedbackForm.feedback_type} onChange={(event) => setFeedbackForm((prev) => ({ ...prev, feedback_type: event.target.value as "COMPLAINT" | "SUGGESTION" }))}>
                  <option value="COMPLAINT">投诉</option><option value="SUGGESTION">建议</option>
                </select>
              </div>
              <div>
                <label>反馈对象</label>
                <select value={feedbackForm.target_type} onChange={(event) => setFeedbackForm((prev) => ({ ...prev, target_type: event.target.value as "ONLINE_SERVICE" | "ORDER_SERVICE", order_id: event.target.value === "ONLINE_SERVICE" ? "" : prev.order_id }))}>
                  <option value="ONLINE_SERVICE">线上服务/平台体验</option><option value="ORDER_SERVICE">订单服务</option>
                </select>
              </div>

              {feedbackForm.target_type === "ORDER_SERVICE" ? (
                <div className="portal-form-full">
                  <label>选择订单</label>
                  <select value={feedbackForm.order_id} onChange={(event) => setFeedbackForm((prev) => ({ ...prev, order_id: event.target.value }))}>
                    <option value="">请选择订单</option>
                    {orderOptions.map((order) => (<option key={order.id} value={order.id}>{order.order_no} / {order.service_type_label} / {order.status_label}</option>))}
                  </select>
                </div>
              ) : null}

              <div className="portal-form-full"><label>标题</label><input value={feedbackForm.title} onChange={(event) => setFeedbackForm((prev) => ({ ...prev, title: event.target.value }))} placeholder="请简要描述问题或建议" /></div>
              <div className="portal-form-full"><label>详细内容</label><textarea rows={4} value={feedbackForm.content} onChange={(event) => setFeedbackForm((prev) => ({ ...prev, content: event.target.value }))} placeholder="请提供尽可能详细的信息，便于我们排查与改进" /></div>
              <div><label>联系电话（可选）</label><input value={feedbackForm.contact_phone} onChange={(event) => setFeedbackForm((prev) => ({ ...prev, contact_phone: event.target.value.replace(/\D/g, "") }))} placeholder="手机号" /></div>
            </div>
            <div className="portal-actions">
              <button className="portal-secondary" type="button" onClick={() => setFeedbackModalOpen(false)}>取消</button>
              <button className="portal-cta" type="button" disabled={feedbackSubmitting} onClick={() => void handleSubmitFeedback()}>{feedbackSubmitting ? "提交中..." : "提交反馈"}</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
