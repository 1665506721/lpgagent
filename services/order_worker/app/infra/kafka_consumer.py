"""Kafka Consumer 初始化。"""

import os

from confluent_kafka import Consumer


def get_consumer() -> Consumer:
    """创建并返回 Kafka Consumer。"""

    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    group_id = os.getenv("KAFKA_CONSUMER_GROUP", "order_worker")

    return Consumer(
        {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "latest",
            "enable.auto.commit": False,
        }
    )
