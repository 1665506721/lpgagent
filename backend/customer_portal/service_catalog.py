from datetime import datetime, timedelta

from .constants import (
    ACCESSORY_SKUS,
    DELIVERY_PRICES,
    SERVICE_TYPE_ACCESSORIES,
    SERVICE_TYPE_CYLINDER_EXCHANGE,
    SERVICE_TYPE_INSTALLATION,
    SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
    SERVICE_TYPE_REPAIR,
    SERVICE_TYPE_SAFETY_CHECK,
    SERVICE_TYPE_LABELS,
    SERVICE_WINDOW_END,
    SERVICE_WINDOW_START,
    WINDOW_GRANULARITY_MINUTES,
)


def list_services():
    return [{"code": code, "name": SERVICE_TYPE_LABELS.get(code, code)} for code in SERVICE_TYPE_LABELS]


def _build_slot_options():
    start = datetime.combine(datetime.today(), SERVICE_WINDOW_START)
    end = datetime.combine(datetime.today(), SERVICE_WINDOW_END)
    slots = []
    while start < end:
        next_time = start + timedelta(minutes=WINDOW_GRANULARITY_MINUTES)
        slots.append(f"{start:%H:%M}-{next_time:%H:%M}")
        start = next_time
    return slots


def _common_fields():
    return {
        "contact_name": {"type": "string", "minLength": 1},
        "contact_phone": {"type": "string", "pattern": "^(\\d{11}|\\d{4})$"},
        "address_full": {"type": "string", "minLength": 2},
        "door_note": {"type": "string"},
        "eta_date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
        "eta_slot": {"type": "string", "enum": _build_slot_options()},
        "is_urgent": {"type": "boolean", "default": False},
        "notes": {"type": "string"},
    }


def get_service_form(service_type):
    if service_type == SERVICE_TYPE_LPG_CYLINDER_DELIVERY:
        properties = {
            **_common_fields(),
            "cylinder_type": {"type": "string", "enum": list(DELIVERY_PRICES.keys())},
            "quantity": {"type": "integer", "minimum": 1, "maximum": 10},
        }
        required = ["contact_name", "contact_phone", "address_full", "cylinder_type", "quantity"]
    elif service_type == SERVICE_TYPE_CYLINDER_EXCHANGE:
        properties = {
            **_common_fields(),
            "cylinder_type": {"type": "string", "enum": list(DELIVERY_PRICES.keys())},
            "quantity": {"type": "integer", "minimum": 1, "maximum": 10},
            "return_empty": {"type": "boolean"},
        }
        required = [
            "contact_name",
            "contact_phone",
            "address_full",
            "cylinder_type",
            "quantity",
            "return_empty",
        ]
    elif service_type == SERVICE_TYPE_INSTALLATION:
        properties = {
            **_common_fields(),
            "install_item": {"type": "string", "minLength": 1},
        }
        required = ["contact_name", "contact_phone", "address_full", "install_item"]
    elif service_type == SERVICE_TYPE_SAFETY_CHECK:
        properties = {
            **_common_fields(),
            "check_scope": {"type": "string", "minLength": 1},
        }
        required = ["contact_name", "contact_phone", "address_full", "check_scope"]
    elif service_type == SERVICE_TYPE_REPAIR:
        properties = {
            **_common_fields(),
            "issue_desc": {"type": "string", "minLength": 1},
        }
        required = ["contact_name", "contact_phone", "address_full", "issue_desc"]
    elif service_type == SERVICE_TYPE_ACCESSORIES:
        properties = {
            **_common_fields(),
            "items": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "sku": {"type": "string", "enum": list(ACCESSORY_SKUS.keys())},
                        "quantity": {"type": "integer", "minimum": 1, "maximum": 20},
                    },
                    "required": ["sku", "quantity"],
                    "additionalProperties": False,
                },
            },
        }
        required = ["contact_name", "contact_phone", "address_full", "items"]
    else:
        return None

    return {
        "form_id": f"{service_type.lower()}_v1",
        "title": SERVICE_TYPE_LABELS.get(service_type, service_type),
        "description": "请填写服务与联系信息。",
        "schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        "cta_label": "确认提交",
    }
