"""Kafka Producer 初始化与发送封装。"""

import json
import logging
from datetime import datetime, timezone

from confluent_kafka import Producer

from app.core.config import settings

_producer: Producer | None = None
_logger = logging.getLogger(__name__)


def get_producer() -> Producer:
    """获取 Kafka Producer 单例。"""

    global _producer
    if _producer is None:
        _producer = Producer({"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS})
        _logger.info(
            "Kafka Producer 初始化，bootstrap=%s，topic=%s",
            settings.KAFKA_BOOTSTRAP_SERVERS,
            settings.KAFKA_TOPIC_ORDER_CREATE,
        )
    return _producer


def send_order_create(*, request_id: str, user_id: str, sku_id: str) -> bool:
    """发送下单消息到 Kafka。"""

    payload = {
        "request_id": request_id,
        "user_id": user_id,
        "sku_id": sku_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    delivery_error = {"value": None}

    def _on_delivery(err, _msg) -> None:
        if err is not None:
            delivery_error["value"] = err

    try:
        producer = get_producer()
        producer.produce(
            settings.KAFKA_TOPIC_ORDER_CREATE,
            key=request_id,
            value=json.dumps(payload, ensure_ascii=False),
            on_delivery=_on_delivery,
        )
        producer.poll(0)
        remaining = producer.flush(2.0)
        if remaining != 0 or delivery_error["value"] is not None:
            raise RuntimeError(
                f"Kafka 发送失败，bootstrap={settings.KAFKA_BOOTSTRAP_SERVERS}，"
                f"topic={settings.KAFKA_TOPIC_ORDER_CREATE}，error={delivery_error['value']}"
            )
        return True
    except Exception:
        _logger.exception(
            "Kafka 发送失败，bootstrap=%s，topic=%s",
            settings.KAFKA_BOOTSTRAP_SERVERS,
            settings.KAFKA_TOPIC_ORDER_CREATE,
        )
        return False
