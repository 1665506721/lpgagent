"""开发环境库存加载脚本。"""

import argparse
import os
import sys

import redis


def main() -> None:
    parser = argparse.ArgumentParser(description="写入 Redis 初始库存")
    parser.add_argument("--sku", required=True, help="商品 SKU")
    parser.add_argument("--stock", required=True, type=int, help="库存数量，必须为非负整数")
    args = parser.parse_args()

    if args.stock < 0:
        print("错误：stock 不能为负数")
        raise SystemExit(1)

    host = os.getenv("REDIS_HOST", "localhost")
    port = int(os.getenv("REDIS_PORT", "6379"))
    db = int(os.getenv("REDIS_DB", "0"))

    try:
        client = redis.Redis(host=host, port=port, db=db, decode_responses=True)
        key = f"stock:{args.sku}"
        client.set(key, args.stock)
        print(f"写入成功：sku={args.sku}，stock={args.stock}")
    except Exception as exc:
        print(f"错误：写入 Redis 失败，{exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
