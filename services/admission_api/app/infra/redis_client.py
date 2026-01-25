"""Redis 客户端初始化与获取。"""

import os

import redis


def get_redis() -> redis.Redis:
    """从环境变量读取配置并返回 Redis 实例。"""

    host = os.getenv("REDIS_HOST", "localhost")
    port = int(os.getenv("REDIS_PORT", "6379"))
    db = int(os.getenv("REDIS_DB", "0"))

    return redis.Redis(host=host, port=port, db=db, decode_responses=True)
