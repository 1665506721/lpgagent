#!/usr/bin/env bash
set -euo pipefail

# 一键启动压测脚本（可通过环境变量覆盖参数）
BASE_URL="${BASE_URL:-http://localhost:8000}"
SKU_ID="${SKU_ID:-sku123}"
PRELOAD_STOCK="${PRELOAD_STOCK:-200000}"
USERS="${USERS:-100}"
SPAWN_RATE="${SPAWN_RATE:-20}"
RUN_TIME="${RUN_TIME:-1m}"

if [[ -z "${ADMIN_TOKEN:-}" ]]; then
  echo "错误：请设置 ADMIN_TOKEN 以调用管理接口"
  exit 1
fi

export BASE_URL SKU_ID PRELOAD_STOCK ADMIN_TOKEN

locust -f scripts/locustfile.py \
  --headless \
  -u "${USERS}" \
  -r "${SPAWN_RATE}" \
  -t "${RUN_TIME}" \
  --host "${BASE_URL}"
