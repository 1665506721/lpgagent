from customer_portal.constants import INSPECTION_POLICY_SOURCE_REF, INSPECTION_POLICY_VERSION, INSPECTION_RULES


def normalize_cylinder_type(value):
    raw = str(value or "").strip().lower().replace(" ", "")
    if not raw:
        return ""
    if raw in {"50kg", "50公斤"}:
        return "45kg"
    if raw in {"45kg", "45公斤"}:
        return "45kg"
    if raw in {"15kg", "15公斤"}:
        return "15kg"
    if raw in {"5kg", "5公斤"}:
        return "5kg"
    return raw


def get_inspection_rule(cylinder_type):
    normalized = normalize_cylinder_type(cylinder_type)
    rule = INSPECTION_RULES.get(normalized) or INSPECTION_RULES.get("15kg")
    return {
        "cylinder_type": normalized or "15kg",
        "cycle_months": int(rule.get("cycle_months") or 48),
        "design_service_life_months": int(rule.get("design_service_life_months") or 96),
        "max_service_life_months": int(rule.get("max_service_life_months") or 144),
        "policy_version": INSPECTION_POLICY_VERSION,
        "source_ref": INSPECTION_POLICY_SOURCE_REF,
    }
