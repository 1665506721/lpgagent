"""订单消费者入口。"""

import logging
import os
import sys
import time
from pathlib import Path

from confluent_kafka import KafkaError

# 兼容直接运行：python app/main.py
if __name__ == "__main__" and __package__ is None:
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))

from app.consumer.handler import handle_message
from app.infra.db import init_db
from app.infra.kafka_consumer import get_consumer


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    init_db()

    topic = os.getenv("KAFKA_TOPIC_ORDER_CREATE", "order_create")
    consumer = get_consumer()
    consumer.subscribe([topic])
    logging.info("开始消费主题：%s", topic)

    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                logging.error("Kafka 消费错误：%s", msg.error())
                time.sleep(1)
                continue
            if msg.value() is None:
                continue
            should_commit = handle_message(msg.value())
            if should_commit:
                try:
                    consumer.commit(message=msg)
                except Exception:
                    logging.exception("提交 offset 失败")
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
