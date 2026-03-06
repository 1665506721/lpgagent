from abc import ABC, abstractmethod

from external.mock_data import generate_mock_orders, reset_mock_orders


class OrderProvider(ABC):
    # 中文注释：提供统一抽象接口，便于未来替换为真实外部系统
    @abstractmethod
    def get_order(self, order_id):
        raise NotImplementedError

    @abstractmethod
    def list_orders_by_phone(self, phone, limit=10):
        raise NotImplementedError

    @abstractmethod
    def reseed(self):
        raise NotImplementedError


class MockOrderProvider(OrderProvider):
    # 中文注释：Mock 实现用于演示与联调，不依赖外部 API
    def __init__(self):
        self._orders = generate_mock_orders()

    def _refresh(self):
        self._orders = generate_mock_orders()

    def get_order(self, order_id):
        self._refresh()
        for item in self._orders:
            if int(item["order_id"]) == int(order_id):
                return item
        return None

    def list_orders_by_phone(self, phone, limit=10):
        self._refresh()
        normalized = _normalize_phone(phone)
        # 中文注释：支持完整手机号与后四位匹配，避免仅靠后四位带来冲突
        if normalized.isdigit() and len(normalized) == 11:
            matches = [
                item
                for item in self._orders
                if item.get("customer", {}).get("phone_full") == normalized
            ]
        elif normalized.isdigit() and len(normalized) == 4:
            matches = [
                item
                for item in self._orders
                if item["customer"]["phone_masked"].endswith(normalized)
            ]
        else:
            matches = [
                item for item in self._orders if item["customer"]["phone_masked"] == normalized
            ]
        return matches[:limit]

    def reseed(self):
        return reset_mock_orders()


def _normalize_phone(phone):
    if not phone:
        return ""
    phone = str(phone).strip()
    if "****" in phone:
        return phone
    digits = "".join([ch for ch in phone if ch.isdigit()])
    if len(digits) == 4:
        return digits
    if len(digits) >= 11:
        return digits[:11]
    return phone


_PROVIDER = MockOrderProvider()


def get_order_provider():
    # 中文注释：集中管理 provider，后续可切换为 HttpOrderProvider（TODO）
    return _PROVIDER
