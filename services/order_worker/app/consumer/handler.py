"""消息处理逻辑。"""

import json
import logging
import time
from datetime import datetime

from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from app.domain.repository import create_order_idempotent
from app.infra.db import get_sessionmaker
from app.infra.redis_client import get_redis


def _parse_created_at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def handle_message(raw_value: bytes) -> bool:
    """处理单条 Kafka 消息，返回是否应提交 offset。"""

    try:
        payload = json.loads(raw_value.decode("utf-8"))
    except Exception:
        logging.exception("消息解析失败，已跳过")
        return True

    request_id = payload.get("request_id")
    user_id = payload.get("user_id")
    sku_id = payload.get("sku_id")
    created_at = payload.get("created_at")

    if not request_id or not user_id or not sku_id or not created_at:
        logging.error("消息字段缺失，已跳过")
        return True

    logging.info("收到消息，request_id=%s", request_id)

    try:
        created_at_dt = _parse_created_at(created_at)
    except Exception:
        logging.error("created_at 解析失败，已跳过，request_id=%s", request_id)
        return True

    session_maker = get_sessionmaker()
    for attempt in range(2):
        try:
            with session_maker() as session:
                inserted = create_order_idempotent(
                    session,
                    request_id=request_id,
                    user_id=user_id,
                    sku_id=sku_id,
                    created_at=created_at_dt,
                )
            if inserted:
                logging.info("落库成功，request_id=%s", request_id)
            else:
                logging.info("订单已存在，request_id=%s", request_id)
            _update_status(request_id, "SUCCESS")
            logging.info("更新状态 SUCCESS，request_id=%s", request_id)
            return True
        except SQLAlchemyError:
            logging.exception("数据库写入失败，request_id=%s", request_id)
            if attempt == 0:
                time.sleep(1)
                continue
            _update_status(request_id, "FAILED")
            logging.info("更新状态 FAILED，request_id=%s", request_id)
            return True

    return True


def _update_status(request_id: str, status: str) -> None:
    try:
        redis_client = get_redis()
        redis_client.set(f"req_status:{request_id}", status, ex=3600)
    except RedisError:
        logging.exception("Redis 更新状态失败，request_id=%s", request_id)
