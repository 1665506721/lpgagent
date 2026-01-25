"""秒杀入口 Lua 脚本单测。"""

import time
import uuid

import pytest

from app.infra.redis_client import get_redis
from app.infra.seckill_lua import execute_seckill


def _reset_keys(redis_client, *, sku_id: str, user_id: str, request_id: str) -> None:
    keys = [
        f"stock:{sku_id}",
        f"order_once:{sku_id}:{user_id}",
        f"req_status:{request_id}",
        f"rl:{user_id}",
    ]
    redis_client.delete(*keys)


@pytest.fixture()
def redis_client():
    client = get_redis()
    client.ping()
    return client


def test_seckill_success_and_repeat(redis_client):
    sku_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    request_id = str(uuid.uuid4())

    _reset_keys(redis_client, sku_id=sku_id, user_id=user_id, request_id=request_id)
    redis_client.set(f"stock:{sku_id}", 1)

    result = execute_seckill(
        redis_client,
        sku_id=sku_id,
        user_id=user_id,
        request_id=request_id,
    )
    assert result["code"] == 0
    assert redis_client.get(f"req_status:{request_id}") == "PENDING"

    repeat_result = execute_seckill(
        redis_client,
        sku_id=sku_id,
        user_id=user_id,
        request_id=str(uuid.uuid4()),
    )
    assert repeat_result["code"] == 2


def test_seckill_out_of_stock(redis_client):
    sku_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    request_id = str(uuid.uuid4())

    _reset_keys(redis_client, sku_id=sku_id, user_id=user_id, request_id=request_id)
    redis_client.set(f"stock:{sku_id}", 0)

    result = execute_seckill(
        redis_client,
        sku_id=sku_id,
        user_id=user_id,
        request_id=request_id,
    )
    assert result["code"] == 1


def test_seckill_rate_limit(redis_client):
    sku_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    redis_client.set(f"stock:{sku_id}", 100)
    redis_client.delete(f"rl:{user_id}")

    codes = []
    for _ in range(7):
        request_id = str(uuid.uuid4())
        redis_client.delete(f"req_status:{request_id}")
        redis_client.delete(f"order_once:{sku_id}:{user_id}")
        result = execute_seckill(
            redis_client,
            sku_id=sku_id,
            user_id=user_id,
            request_id=request_id,
        )
        codes.append(result["code"])

    assert 3 in codes
    time.sleep(1.1)
