import type { JsonSchema, SchemaProperty } from "./api";

export type SchemaField = {
  name: string;
  label: string;
  type: string;
  required: boolean;
  options?: string[];
  minimum?: number;
  maximum?: number;
  pattern?: string;
};

const FIELD_LABELS: Record<string, string> = {
  cylinder_type: "钢瓶规格",
  quantity: "数量",
  address: "地址",
  contact_phone_last4: "手机号",
  preferred_time: "期望时间",
  notes: "备注",
  related_order_id: "关联订单号",
  issue_type: "问题类型",
  description: "问题描述",
  need_callback: "是否需要回访",
  order_id: "订单号",
  new_address: "新地址",
  urge_reason: "催单原因",
  query_type: "查询方式",
  phone_last4: "手机号",
  service_type: "服务类型",
  issue_description: "问题说明",
  contact_name: "联系人姓名",
  contact_phone: "联系电话",
  address_full: "服务地址",
  door_note: "门牌备注",
  eta_date: "预约日期",
  eta_slot: "预约时段",
  eta_window: "期望时段",
  is_urgent: "是否加急",
  install_item: "安装项目",
  check_scope: "安检范围",
  issue_desc: "故障描述",
  return_empty: "是否回收空瓶",
  items: "配件清单"
};

const FIELD_PLACEHOLDERS: Record<string, string> = {
  address: "例如：xx路88号",
  new_address: "例如：xx路88号",
  description: "请简要描述问题",
  issue_description: "请说明需要处理的问题",
  related_order_id: "可选填写订单号",
  order_id: "请输入订单号",
  phone_last4: "请输入11位手机号",
  contact_phone_last4: "请输入11位手机号",
  contact_phone: "请输入11位手机号",
  address_full: "例如：xx路88号",
  door_note: "例如：门牌号或楼层信息",
  eta_date: "例如：2026-02-10",
  eta_slot: "例如：09:00-11:00"
};

function resolveLabel(name: string) {
  return FIELD_LABELS[name] || name;
}

export function resolvePlaceholder(name: string) {
  return FIELD_PLACEHOLDERS[name] || "";
}

function resolveType(property?: SchemaProperty) {
  if (!property) {
    return "string";
  }
  if (property.enum) {
    return "enum";
  }
  return property.type || "string";
}

export function buildFields(schema?: JsonSchema): SchemaField[] {
  if (!schema?.properties) {
    return [];
  }
  const requiredSet = new Set(schema.required || []);
  return Object.entries(schema.properties).map(([name, property]) => ({
    name,
    label: resolveLabel(name),
    type: resolveType(property),
    required: requiredSet.has(name),
    options: property.enum,
    minimum: property.minimum,
    maximum: property.maximum,
    pattern: property.pattern
  }));
}

export function normalizePayload(fields: SchemaField[], values: Record<string, unknown>) {
  const output: Record<string, unknown> = {};
  fields.forEach((field) => {
    const value = values[field.name];
    if (value === undefined || value === null || value === "") {
      return;
    }
    if (field.type === "integer" || field.type === "number") {
      const parsed = Number(value);
      output[field.name] = Number.isNaN(parsed) ? value : parsed;
      return;
    }
    if (field.type === "boolean") {
      output[field.name] = Boolean(value);
      return;
    }
    output[field.name] = value;
  });
  return output;
}
