"""秒杀入口 Redis Lua 原子逻辑。"""

from typing import Dict

from redis import Redis

LUA_SCRIPT = """
-- KEYS: none
-- ARGV: sku_id, user_id, request_id, rate_limit_max

local sku_id = ARGV[1]
local user_id = ARGV[2]
local request_id = ARGV[3]
local rate_limit_max = tonumber(ARGV[4])

local stock_key = "stock:" .. sku_id
local order_once_key = "order_once:" .. sku_id .. ":" .. user_id
local req_status_key = "req_status:" .. request_id
local rl_key = "rl:" .. user_id

-- 幂等校验
if redis.call("EXISTS", order_once_key) == 1 then
    return 2
end

-- 简单限流：1 秒最多 rate_limit_max 次
local rl_count = redis.call("INCR", rl_key)
if rl_count == 1 then
    redis.call("EXPIRE", rl_key, 1)
end
if rl_count > rate_limit_max then
    return 3
end

-- 库存校验与扣减
local stock = tonumber(redis.call("GET", stock_key) or "0")
if stock <= 0 then
    return 1
end

redis.call("DECR", stock_key)

-- 记录幂等与请求状态
redis.call("SET", order_once_key, request_id, "EX", 86400)
redis.call("SET", req_status_key, "PENDING", "EX", 3600)

return 0
"""

CODE_MESSAGE = {
    0: "成功",
    1: "库存不足",
    2: "重复下单",
    3: "请求过于频繁",
}


def execute_seckill(
    redis_client: Redis,
    *,
    sku_id: str,
    user_id: str,
    request_id: str,
    rate_limit_max: int = 5,
) -> Dict[str, str | int]:
    """执行秒杀入口 Lua 脚本并返回统一结果。"""

    script = redis_client.register_script(LUA_SCRIPT)
    code = int(
        script(
            keys=[],
            args=[sku_id, user_id, request_id, rate_limit_max],
        )
    )

    return {
        "code": code,
        "message": CODE_MESSAGE.get(code, "未知错误"),
        "request_id": request_id,
        "sku_id": sku_id,
        "user_id": user_id,
    }
