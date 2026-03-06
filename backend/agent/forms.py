from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class FormDefinition:
    form_id: str
    title: str
    description: str
    schema: Dict[str, Any]
    submit_intent: str
    confirm_required: bool
    cta_label: str


def _clean_prefill(prefill: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    # 中文注释：仅保留非空预填字段，避免前端渲染脏数据
    if not prefill:
        return {}
    return {key: value for key, value in prefill.items() if value not in (None, "")}


def _build_order_create_schema():
    return {
        "type": "object",
        "properties": {
            "cylinder_type": {
                "type": "string",
                "enum": [
                    "15kg",
                    "5kg",
                    "45kg",
                    "钢瓶回收",
                    "更换软管",
                    "更换减压阀",
                    "报警器服务",
                    "上门安检",
                    "其他",
                ],
            },
            "quantity": {"type": "integer", "minimum": 1, "maximum": 10},
            "address": {"type": "string", "minLength": 2},
            "contact_phone_last4": {"type": "string", "pattern": "^(\\d{11}|\\d{4})$"},
            "preferred_time": {"type": "string", "enum": ["尽快", "今天", "明天", "指定时间"]},
            "notes": {"type": "string"},
        },
        "required": ["cylinder_type", "quantity", "address"],
        "additionalProperties": False,
    }


def _build_ticket_complaint_schema():
    return {
        "type": "object",
        "properties": {
            "related_order_id": {"type": "string"},
            "issue_type": {
                "type": "string",
                "enum": ["态度问题", "配送延误", "费用争议", "安全隐患", "其他"],
            },
            "description": {"type": "string", "minLength": 3},
            "contact_phone_last4": {"type": "string", "pattern": "^(\\d{11}|\\d{4})$"},
            "need_callback": {"type": "boolean", "default": True},
        },
        "required": ["issue_type", "description"],
        "additionalProperties": False,
    }


def _build_modify_address_schema():
    return {
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "minLength": 6},
            "new_address": {"type": "string", "minLength": 2},
            "contact_phone_last4": {"type": "string", "pattern": "^(\\d{11}|\\d{4})$"},
        },
        "required": ["order_id", "new_address"],
        "additionalProperties": False,
    }


def _build_urge_confirm_schema():
    return {
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "minLength": 6},
            "urge_reason": {"type": "string", "enum": ["已超时", "临时改时间", "家里没人", "其他"]},
            "need_callback": {"type": "boolean", "default": False},
        },
        "required": ["order_id", "urge_reason"],
        "additionalProperties": False,
    }


def _build_order_query_schema():
    return {
        "type": "object",
        "properties": {
            "query_type": {"type": "string", "enum": ["订单号", "手机号"]},
            "order_id": {"type": "string"},
            "phone_last4": {"type": "string", "pattern": "^(\\d{11}|\\d{4})$"},
        },
        "required": ["query_type"],
        "additionalProperties": False,
    }


def _build_safety_service_schema():
    return {
        "type": "object",
        "properties": {
            "service_type": {
                "type": "string",
                "enum": ["上门安检", "报修", "更换软管咨询", "报警器咨询"],
            },
            "address": {"type": "string", "minLength": 2},
            "preferred_time": {"type": "string", "enum": ["尽快", "今天", "明天", "指定时间"]},
            "contact_phone_last4": {"type": "string", "pattern": "^(\\d{11}|\\d{4})$"},
            "issue_description": {"type": "string", "minLength": 3},
        },
        "required": ["service_type", "address", "issue_description"],
        "additionalProperties": False,
    }


FORM_DEFINITIONS = {
    "order_create_v1": FormDefinition(
        form_id="order_create_v1",
        title="在线下单",
        description="请补充下单或服务信息，方便我们尽快安排配送或上门。",
        schema=_build_order_create_schema(),
        submit_intent="ORDER_CREATE",
        confirm_required=False,
        cta_label="提交订单",
    ),
    "ticket_complaint_v1": FormDefinition(
        form_id="ticket_complaint_v1",
        title="投诉工单",
        description="请补充投诉信息，我们会尽快跟进。",
        schema=_build_ticket_complaint_schema(),
        submit_intent="CREATE_TICKET",
        confirm_required=False,
        cta_label="提交投诉",
    ),
    "order_modify_address_v1": FormDefinition(
        form_id="order_modify_address_v1",
        title="修改配送地址",
        description="请填写订单号与新地址。",
        schema=_build_modify_address_schema(),
        submit_intent="MODIFY_ORDER",
        confirm_required=True,
        cta_label="提交修改",
    ),
    "order_urge_confirm_v1": FormDefinition(
        form_id="order_urge_confirm_v1",
        title="催单确认",
        description="确认催单后，我们将为您创建催单工单。",
        schema=_build_urge_confirm_schema(),
        submit_intent="QUERY_ORDER",
        confirm_required=True,
        cta_label="确认催单",
    ),
    "order_query_v1": FormDefinition(
        form_id="order_query_v1",
        title="订单查询",
        description="请选择查询方式并补充信息。",
        schema=_build_order_query_schema(),
        submit_intent="QUERY_ORDER",
        confirm_required=False,
        cta_label="查询订单",
    ),
    "safety_service_request_v1": FormDefinition(
        form_id="safety_service_request_v1",
        title="安全服务预约",
        description="请补充预约信息，我们会尽快安排上门。",
        schema=_build_safety_service_schema(),
        submit_intent="SAFETY_GUIDE",
        confirm_required=False,
        cta_label="提交预约",
    ),
}


def build_form(form_id: str, prefill: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    # 中文注释：根据 form_id 构建表单协议对象
    definition = FORM_DEFINITIONS.get(form_id)
    if not definition:
        return None
    return {
        "form_id": definition.form_id,
        "title": definition.title,
        "description": definition.description,
        "schema": definition.schema,
        "prefill": _clean_prefill(prefill),
        "submit_intent": definition.submit_intent,
        "confirm_required": definition.confirm_required,
        "cta_label": definition.cta_label,
    }
