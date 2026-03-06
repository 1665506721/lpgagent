export type PortalErrorPayload = {
  code: string;
  message: string;
  details?: Record<string, unknown>;
};

type PortalResponse<T> = {
  ok: boolean;
  data: T | null;
  error: PortalErrorPayload | null;
};

export class PortalApiError extends Error {
  code: string;
  details?: Record<string, unknown>;

  constructor(payload: PortalErrorPayload) {
    super(payload.message || "请求失败，请稍后重试");
    this.name = "PortalApiError";
    this.code = payload.code || "UNKNOWN_ERROR";
    this.details = payload.details;
  }
}

export type PortalOrderEvent = {
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type PortalOrderListItem = {
  id: number;
  order_no: string;
  service_type: string;
  service_type_label: string;
  status: string;
  status_label: string;
  eta_start: string;
  eta_end: string;
  amount_total: string;
  currency: string;
  assigned_worker?: {
    name: string;
    phone: string;
  };
  created_at: string;
};

export type PortalOrderDetail = {
  id: number;
  order_no: string;
  service_type: string;
  service_type_label: string;
  status: string;
  status_label: string;
  eta_start: string;
  eta_end: string;
  cancel_deadline: string;
  address_edit_deadline: string;
  is_urgent: boolean;
  notes: string;
  amount_subtotal: string;
  amount_urgent_fee: string;
  amount_total: string;
  currency: string;
  address_snapshot: {
    address_full: string;
    door_note?: string;
  };
  contact_snapshot: {
    contact_name: string;
    contact_phone: string;
  };
  service_payload: Record<string, unknown>;
  assigned_worker?: {
    name: string;
    phone: string;
  };
  expires_at: string;
  created_at: string;
  updated_at: string;
  events: PortalOrderEvent[];
};

export type PortalOrderListData = {
  items: PortalOrderListItem[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  keyword: string;
  status: string;
};

export type PortalAddress = {
  id: number;
  contact_name: string;
  contact_phone: string;
  address_full: string;
  door_note: string;
  is_default: boolean;
  created_at: string;
};

export type PortalCartItem = {
  sku: string;
  name: string;
  category: string;
  quantity: number;
  price: string;
  amount: string;
  updated_at: string;
};

export type PortalCartSummary = {
  items: PortalCartItem[];
  selected_count: number;
  total_amount: string;
  currency: string;
  deleted_count?: number;
};

export type PortalAuthProfile = {
  id: number;
  phone: string;
  display_name: string;
};

export type PortalAuthResponse = {
  token: string;
  profile: PortalAuthProfile;
};

export type PortalFeedbackItem = {
  id: number;
  feedback_type: "COMPLAINT" | "SUGGESTION";
  target_type: "ONLINE_SERVICE" | "ORDER_SERVICE";
  title: string;
  content: string;
  contact_phone: string;
  status: "NEW" | "PROCESSING" | "CLOSED";
  order_no: string;
  created_at: string;
  updated_at: string;
};

export type PortalChatHistoryItem = {
  id: number;
  role: "user" | "assistant";
  content: string;
  run_id?: string | null;
  created_at: string;
};

export type PortalNotificationItem = {
  id: number;
  category: "ORDER" | "PAYMENT" | "ADDRESS" | "FEEDBACK" | "PROFILE";
  event_code: string;
  title: string;
  content: string;
  level: "INFO" | "SUCCESS" | "WARNING" | "ERROR";
  is_read: boolean;
  target_type: "ORDER" | "FEEDBACK" | "PROFILE" | "ADDRESS" | "CHAT" | "NONE";
  target_id?: number | null;
  target_route: string;
  meta_json?: Record<string, unknown>;
  created_at: string;
  read_at?: string | null;
};

export type PortalNotificationListData = {
  items: PortalNotificationItem[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  unread_count: number;
  only_unread: boolean;
};

export type PortalLlmProviderType = "OPENAI_COMPAT";

export type PortalLlmProfile = {
  id: number;
  name: string;
  provider_type: PortalLlmProviderType;
  api_base_url: string;
  model_name: string;
  api_key_masked: string;
  is_active: boolean;
  extra_json?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type PortalLlmProfileListData = {
  items: PortalLlmProfile[];
  active_profile_id: number | null;
};

export type PortalLlmModelOption = {
  id: string;
  label: string;
};

export type PortalDataUpdateDetail = {
  domains: string[];
  at: string;
};

const API_BASE = import.meta.env?.VITE_API_BASE || "http://127.0.0.1:8000";

export function emitPortalNotificationRefresh() {
  window.dispatchEvent(new CustomEvent("portal:notification-refresh"));
}

export function emitPortalDataUpdated(domains: string[]) {
  const normalized = Array.from(new Set((domains || []).map((item) => String(item || "").trim()).filter(Boolean)));
  if (!normalized.length) return;
  const at = new Date().toISOString();
  localStorage.setItem("portal_data_dirty_at", at);
  const detail: PortalDataUpdateDetail = { domains: normalized, at };
  window.dispatchEvent(new CustomEvent("portal:data-updated", { detail }));
}

function getToken() {
  return localStorage.getItem("portal_token") || "";
}

type RequestOptions = {
  method?: string;
  auth?: boolean;
  body?: unknown;
};

function toFriendlyMessage(error: PortalErrorPayload | null | undefined): string {
  const code = error?.code || "";
  if (code === "AUTH_REQUIRED") return "请先登录后再操作";
  if (code === "ORDER_NOT_FOUND") return "订单不存在或无权限访问";
  if (code === "ORDER_EXPIRED") return "订单已过期，请重新下单";
  if (code === "ORDER_NOT_CANCELABLE") return "当前订单不满足取消条件";
  if (code === "ORDER_NOT_EDITABLE") return "当前订单暂不可编辑";
  if (code === "VALIDATION_ERROR") return "提交信息不完整或格式不正确";
  if (code === "PROVIDER_PROFILE_NOT_FOUND") return "模型配置不存在";
  if (code === "PROVIDER_PROFILE_FORBIDDEN") return "无权限访问该模型配置";
  if (code === "PROVIDER_CONFIG_INVALID") return "模型配置参数无效";
  if (code === "PROVIDER_MODELS_UNAVAILABLE") return "模型列表拉取失败，请检查 API 地址或密钥";
  if (code === "PROVIDER_VALIDATE_FAILED") return "模型连通性校验失败";
  if (code === "ENCRYPTION_CONFIG_ERROR") return "后端加密配置异常，请联系管理员";
  if (code === "NOTIFICATION_NOT_FOUND") return "通知不存在";
  if (code === "CART_EMPTY") return "购物车为空，请先添加商品";
  if (code === "ADDRESS_REQUIRED") return "缺少地址，请先补充默认地址";
  if (code === "NETWORK_ERROR") return "无法连接后端服务，请确认后端已启动";
  return error?.message || "请求失败，请稍后重试";
}

async function portalRequest<T>(path: string, options?: RequestOptions): Promise<T> {
  const method = options?.method || "GET";
  const auth = options?.auth ?? true;
  const token = getToken();

  const headers: Record<string, string> = {
    Accept: "application/json"
  };
  if (auth && token) {
    headers.Authorization = `Token ${token}`;
  }

  let body: string | undefined;
  if (options?.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body
    });
  } catch {
    throw new PortalApiError({
      code: "NETWORK_ERROR",
      message: "无法连接后端服务，请确认后端已启动并重启前端"
    });
  }

  const payload = (await response.json().catch(() => null)) as PortalResponse<T> | null;
  if (!payload || !response.ok || !payload.ok || payload.data === null) {
    if (payload?.error?.code === "AUTH_REQUIRED" || response.status === 401) {
      localStorage.removeItem("portal_token");
      localStorage.removeItem("portal_profile_phone");
      localStorage.removeItem("portal_profile_id");
      if (!window.location.hash.startsWith("#/portal/login")) {
        window.location.hash = "#/portal/login";
      }
    }
    const fallback: PortalErrorPayload = {
      code: "REQUEST_FAILED",
      message: "请求失败，请稍后重试"
    };
    const normalized = payload?.error || fallback;
    throw new PortalApiError({
      ...normalized,
      message: toFriendlyMessage(normalized)
    });
  }
  return payload.data;
}

export async function loginPortal(phone: string, password: string): Promise<PortalAuthResponse> {
  return portalRequest<PortalAuthResponse>("/api/portal/auth/login", {
    method: "POST",
    auth: false,
    body: { phone, password }
  });
}

export async function registerPortal(payload: {
  phone: string;
  password: string;
  sms_code: string;
  display_name?: string;
}): Promise<PortalAuthResponse> {
  return portalRequest<PortalAuthResponse>("/api/portal/auth/register", {
    method: "POST",
    auth: false,
    body: payload
  });
}

export async function requestSmsCode(phone: string, purpose = "REGISTER") {
  return portalRequest<{ phone: string; code: string; purpose: string }>("/api/portal/auth/sms", {
    method: "POST",
    auth: false,
    body: { phone, purpose }
  });
}

export async function listPortalAddresses(): Promise<PortalAddress[]> {
  return portalRequest<PortalAddress[]>("/api/portal/addresses");
}

export async function createPortalAddress(payload: {
  contact_name: string;
  contact_phone: string;
  address_full: string;
  door_note?: string;
  is_default?: boolean;
}) {
  const result = await portalRequest<PortalAddress>("/api/portal/addresses", {
    method: "POST",
    body: payload
  });
  emitPortalDataUpdated(["addresses", "profile", "notifications"]);
  emitPortalNotificationRefresh();
  return result;
}

export async function listPortalCart() {
  return portalRequest<PortalCartSummary>("/api/portal/cart/items");
}

export async function upsertPortalCartItem(payload: { sku: string; quantity: number }) {
  const result = await portalRequest<PortalCartSummary>("/api/portal/cart/items", {
    method: "POST",
    body: payload,
  });
  emitPortalDataUpdated(["cart"]);
  return result;
}

export async function removePortalCartItem(sku: string) {
  const result = await portalRequest<PortalCartSummary>(`/api/portal/cart/items/${encodeURIComponent(sku)}`, {
    method: "DELETE",
  });
  emitPortalDataUpdated(["cart"]);
  return result;
}

export async function clearPortalCart() {
  const result = await portalRequest<PortalCartSummary>("/api/portal/cart/clear", {
    method: "POST",
  });
  emitPortalDataUpdated(["cart"]);
  return result;
}

export async function checkoutPortalCart(payload: {
  address_id?: number;
  eta_date?: string;
  eta_slot?: string;
  is_urgent?: boolean;
  notes?: string;
  need_invoice?: boolean;
  invoice_title?: string;
  invoice_tax_no?: string;
  auto_pay?: boolean;
}) {
  const result = await portalRequest<PortalOrderDetail>("/api/portal/cart/checkout", {
    method: "POST",
    body: payload,
  });
  emitPortalDataUpdated(["cart", "orders", "notifications"]);
  emitPortalNotificationRefresh();
  return result;
}

export async function updatePortalAddress(
  addressId: number,
  payload: {
    contact_name?: string;
    contact_phone?: string;
    address_full?: string;
    door_note?: string;
    is_default?: boolean;
  }
) {
  const result = await portalRequest<PortalAddress>(`/api/portal/addresses/${addressId}`, {
    method: "PUT",
    body: payload
  });
  emitPortalDataUpdated(["addresses", "profile", "notifications"]);
  emitPortalNotificationRefresh();
  return result;
}

export async function deletePortalAddress(addressId: number) {
  const result = await portalRequest<{ deleted_id: number }>(`/api/portal/addresses/${addressId}`, {
    method: "DELETE"
  });
  emitPortalDataUpdated(["addresses", "profile", "notifications"]);
  emitPortalNotificationRefresh();
  return result;
}

export async function setPortalDefaultAddress(addressId: number) {
  const result = await portalRequest<PortalAddress>(`/api/portal/addresses/${addressId}/default`, {
    method: "POST"
  });
  emitPortalDataUpdated(["addresses", "profile", "orders", "notifications"]);
  emitPortalNotificationRefresh();
  return result;
}

export async function getPortalMe() {
  return portalRequest<PortalAuthProfile>("/api/portal/me");
}

export async function updatePortalMe(payload: { display_name: string }) {
  const result = await portalRequest<PortalAuthProfile>("/api/portal/me", {
    method: "PUT",
    body: payload
  });
  emitPortalDataUpdated(["profile", "notifications"]);
  emitPortalNotificationRefresh();
  return result;
}

export async function changePortalPassword(payload: {
  old_password: string;
  new_password: string;
  confirm_password: string;
}) {
  const result = await portalRequest<{ token: string }>("/api/portal/me/password", {
    method: "POST",
    body: payload
  });
  emitPortalDataUpdated(["profile", "notifications"]);
  emitPortalNotificationRefresh();
  return result;
}

export async function createPortalOrder(payload: Record<string, unknown>) {
  const result = await portalRequest<PortalOrderDetail>("/api/portal/orders", {
    method: "POST",
    body: payload
  });
  emitPortalDataUpdated(["orders", "notifications"]);
  emitPortalNotificationRefresh();
  return result;
}

export async function payPortalOrder(orderId: number) {
  const result = await portalRequest<PortalOrderDetail>(`/api/portal/orders/${orderId}/pay`, {
    method: "POST"
  });
  emitPortalDataUpdated(["orders", "notifications"]);
  emitPortalNotificationRefresh();
  return result;
}

export async function cancelPortalOrder(orderId: number) {
  const result = await portalRequest<PortalOrderDetail>(`/api/portal/orders/${orderId}/cancel`, {
    method: "POST"
  });
  emitPortalDataUpdated(["orders", "notifications"]);
  emitPortalNotificationRefresh();
  return result;
}

export async function modifyPortalOrderAddress(
  orderId: number,
  payload: {
    address_id?: number;
    contact_name?: string;
    contact_phone?: string;
    address_full?: string;
    door_note?: string;
  }
) {
  const result = await portalRequest<PortalOrderDetail>(`/api/portal/orders/${orderId}/modify-address`, {
    method: "POST",
    body: payload
  });
  emitPortalDataUpdated(["orders", "addresses", "notifications"]);
  emitPortalNotificationRefresh();
  return result;
}

export async function getPortalOrder(orderId: number) {
  return portalRequest<PortalOrderDetail>(`/api/portal/orders/${orderId}`);
}

export async function listPortalOrders(params?: {
  status?: string;
  page?: number;
  page_size?: number;
  keyword?: string;
}) {
  const search = new URLSearchParams();
  if (params?.status) search.set("status", params.status);
  if (params?.page) search.set("page", String(params.page));
  if (params?.page_size) search.set("page_size", String(params.page_size));
  if (params?.keyword) search.set("keyword", params.keyword);

  const suffix = search.toString();
  return portalRequest<PortalOrderListData>(`/api/portal/orders${suffix ? `?${suffix}` : ""}`);
}

export async function listPortalFeedbacks(params?: {
  feedback_type?: "COMPLAINT" | "SUGGESTION";
  target_type?: "ONLINE_SERVICE" | "ORDER_SERVICE";
}) {
  const search = new URLSearchParams();
  if (params?.feedback_type) search.set("feedback_type", params.feedback_type);
  if (params?.target_type) search.set("target_type", params.target_type);
  const suffix = search.toString();
  return portalRequest<PortalFeedbackItem[]>(`/api/portal/feedbacks${suffix ? `?${suffix}` : ""}`);
}

export async function listPortalChatHistory(limit = 200) {
  const query = new URLSearchParams();
  query.set("limit", String(limit));
  const suffix = query.toString();
  return portalRequest<{ items: PortalChatHistoryItem[]; count: number }>(
    `/api/portal/chat/history${suffix ? `?${suffix}` : ""}`
  );
}

export async function clearPortalChatHistory() {
  return portalRequest<{ deleted_count: number }>("/api/portal/chat/history/clear", {
    method: "POST",
  });
}

export async function createPortalFeedback(payload: {
  feedback_type: "COMPLAINT" | "SUGGESTION";
  target_type: "ONLINE_SERVICE" | "ORDER_SERVICE";
  title: string;
  content: string;
  contact_phone?: string;
  order_id?: number;
}) {
  const result = await portalRequest<PortalFeedbackItem>("/api/portal/feedbacks", {
    method: "POST",
    body: payload
  });
  emitPortalDataUpdated(["profile", "notifications"]);
  emitPortalNotificationRefresh();
  return result;
}

export async function listPortalNotifications(params?: {
  page?: number;
  page_size?: number;
  only_unread?: boolean;
}) {
  const search = new URLSearchParams();
  if (params?.page) search.set("page", String(params.page));
  if (params?.page_size) search.set("page_size", String(params.page_size));
  if (typeof params?.only_unread === "boolean") search.set("only_unread", String(params.only_unread));
  const suffix = search.toString();
  return portalRequest<PortalNotificationListData>(`/api/portal/notifications${suffix ? `?${suffix}` : ""}`);
}

export async function readPortalNotification(notificationId: number) {
  const result = await portalRequest<PortalNotificationItem>(`/api/portal/notifications/${notificationId}/read`, {
    method: "POST",
  });
  emitPortalDataUpdated(["notifications"]);
  emitPortalNotificationRefresh();
  return result;
}

export async function readAllPortalNotifications() {
  const result = await portalRequest<{ updated_count: number }>("/api/portal/notifications/read-all", {
    method: "POST",
  });
  emitPortalDataUpdated(["notifications"]);
  emitPortalNotificationRefresh();
  return result;
}

export async function listPortalLlmProfiles() {
  return portalRequest<PortalLlmProfileListData>("/api/portal/llm-profiles");
}

export async function createPortalLlmProfile(payload: {
  name: string;
  provider_type: PortalLlmProviderType;
  api_base_url: string;
  api_key?: string;
  model_name: string;
  is_active?: boolean;
  extra_json?: Record<string, unknown>;
}) {
  return portalRequest<PortalLlmProfile>("/api/portal/llm-profiles", {
    method: "POST",
    body: payload,
  });
}

export async function updatePortalLlmProfile(
  profileId: number,
  payload: {
    name?: string;
    provider_type?: PortalLlmProviderType;
    api_base_url?: string;
    api_key?: string;
    model_name?: string;
    is_active?: boolean;
    extra_json?: Record<string, unknown>;
  }
) {
  return portalRequest<PortalLlmProfile>(`/api/portal/llm-profiles/${profileId}`, {
    method: "PUT",
    body: payload,
  });
}

export async function deletePortalLlmProfile(profileId: number) {
  return portalRequest<{ deleted_id: number }>(`/api/portal/llm-profiles/${profileId}`, {
    method: "DELETE",
  });
}

export async function activatePortalLlmProfile(profileId: number) {
  return portalRequest<PortalLlmProfile>(`/api/portal/llm-profiles/${profileId}/activate`, {
    method: "POST",
  });
}

export async function fetchPortalLlmModels(profileId: number) {
  return portalRequest<{ items: PortalLlmModelOption[]; count: number }>(
    `/api/portal/llm-profiles/${profileId}/models`
  );
}

export async function validatePortalLlmProfile(profileId: number) {
  return portalRequest<{ reachable: boolean; model_count: number; sample_models: string[] }>(
    `/api/portal/llm-profiles/${profileId}/validate`,
    { method: "POST" }
  );
}
