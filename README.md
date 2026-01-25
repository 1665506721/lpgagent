# 高并发请求受理系统demo（Redis Lua 原子校验 + Kafka 削峰）

面试级高并发请求受理与配额分配系统示例工程，重点展示高并发入口、Redis Lua 原子操作、消息队列削峰与工程化结构。

## 背景与目标

在高并发场景下（如限量资源分配、预约名额、活动资格发放），
直接将请求同步写入数据库容易造成数据库过载与严重的并发一致性问题。

本项目的目标是：
- 在高并发入口快速判定请求是否具备“受理资格”
- 使用 Redis Lua 实现原子化校验与配额扣减
- 通过 Kafka 对受理成功的请求进行削峰异步处理
- 提供可查询的请求状态，形成完整工程闭环

## 当前阶段说明

本阶段为开发/单机环境验证版本，聚焦流程闭环与工程化结构。生产化仍需进一步压测、多实例部署、容量评估与故障演练。

## 核心设计

### Redis Lua 原子校验
- 所有配额校验与扣减在 Lua 中完成
- 避免“先查后改”导致的并发竞态
- 防止超发/超卖

### 异步削峰
- 受理成功的请求写入 Kafka
- 下游通过 Worker 平滑消费并落库
- 数据库只承受稳定写入压力

### 幂等与一致性
- request_id 作为全链路幂等键
- 数据库对 request_id 建立唯一约束
- 重复消费不会产生重复数据

### 请求状态管理
- Redis 维护 req_status:{request_id}
- 客户端可通过接口查询处理进度

## 快速开始（本地运行）

### 前置条件
- Docker & Docker Compose
- Python 3.11 + Poetry
- curl（jq 可选）

### 启动基础设施
```bash
cd /home/host-13/projects/hcrs

docker compose -f deploy/docker-compose.yml up -d

docker ps
```

### 启动 API 服务
```bash
cd /home/host-13/projects/hcrs/services/admission_api

KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \
ADMIN_TOKEN=dev-token-123 \
REDIS_HOST=localhost \
REDIS_PORT=6379 \
REDIS_DB=0 \
KAFKA_TOPIC_ORDER_CREATE=order_create \
poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 启动 Worker
```bash
cd /home/host-13/projects/hcrs/services/order_worker

export KAFKA_BOOTSTRAP_SERVERS=localhost:9092
export KAFKA_TOPIC_ORDER_CREATE=order_create
export KAFKA_CONSUMER_GROUP=order_worker
export DATABASE_URL=postgresql+psycopg://seckill:seckill@localhost:5432/seckill
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_DB=0

poetry run python app/main.py
```

### 冒烟验证

重置配额（需要 X-Admin-Token）：
```bash
curl -X POST http://localhost:8000/admin/quota/reset \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: dev-token-123" \
  -d '{"resource_id":"sku123","stock":1000}'
```

发起受理请求：
```bash
curl -X POST http://localhost:8000/admission/requests \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","sku_id":"sku123"}'
```

查询状态（替换为上一步返回的 request_id）：
```bash
curl http://localhost:8000/admission/requests/{request_id}
```

## 返回码说明

| code | 含义 |
|----|----|
| 0 | 受理成功，已进入异步处理 |
| 1 | 配额不足 |
| 2 | 重复请求（幂等拦截） |
| 3 | 触发限流 |
| 4 | Kafka 入队失败 |

## 常见问题

### Kafka 连接失败 / code=4
- 确认 KAFKA_BOOTSTRAP_SERVERS 在启动 uvicorn 的终端中设置
- 若日志出现 kafka:9092 无法解析，需检查 Kafka advertised.listeners 配置

### Worker 启动后回放历史消息
- Kafka 按 consumer group 维护 offset
- 可通过更换 KAFKA_CONSUMER_GROUP 或使用 latest 策略避免回放

### jq 未安装
- 可直接去掉 `| jq`
- 或使用 `python -m json.tool` 查看 JSON

## 接口

### 请求受理

- POST /admission/requests
- GET  /admission/requests/{request_id}

### 管理侧配额

- POST /admin/quota/load
- GET  /admin/quota/{resource_id}
- POST /admin/quota/reset

## 压测

使用 Locust 对请求受理入口进行压测，覆盖：
- POST /admission/requests
- GET /admission/requests/{request_id}（轻量轮询）

压测前会自动调用管理接口重置配额（默认 stock=200000）。

### 一键运行（推荐）

```bash
export ADMIN_TOKEN=dev-token-123
export BASE_URL=http://localhost:8000
export SKU_ID=sku123
export PRELOAD_STOCK=200000
export USERS=200
export SPAWN_RATE=50
export RUN_TIME=2m

./scripts/run_locust.sh
```

### 直接运行 Locust

```bash
export ADMIN_TOKEN=dev-token-123
export BASE_URL=http://localhost:8000
export SKU_ID=sku123
export PRELOAD_STOCK=200000

locust -f scripts/locustfile.py --headless -u 200 -r 50 -t 2m --host http://localhost:8000
```

压测结束后会在控制台输出按 code 统计的汇总信息，并可在 Locust 输出中看到 /admission/requests 的 RPS 与失败率。
