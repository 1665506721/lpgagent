# Customer Portal API (MVP)

This document describes how to run and verify the customer portal backend APIs.

## 1. Run locally
```bash
cd backend
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

If you have old local DB, ensure latest portal migrations are applied:
```bash
cd backend
python manage.py makemigrations customer_portal
python manage.py migrate
```

Frontend dev server (recommended with proxy):
```bash
cd frontend
npm install
npm run dev
```

Notes:
- Frontend runs on `http://127.0.0.1:9100` by default.
- Vite proxy forwards `/api/*` to `http://127.0.0.1:8000`, so portal APIs work without browser CORS issues.
- If you need direct cross-origin calls, set `CORS_ALLOWED_ORIGINS` in backend env, e.g.:
  `CORS_ALLOWED_ORIGINS=http://127.0.0.1:9100,http://localhost:9100`
- After changing backend CORS settings, restart backend server.
- After changing Vite proxy (`vite.config.ts`), restart frontend dev server.
- Portal payment is mock payment in MVP: `/api/portal/orders/{id}/pay` returns success immediately.
- LLM profile encryption key:
  - Production: must set `PORTAL_PROVIDER_SECRET` (Fernet key).
  - Generate once with:
    `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

## 2. Auth token
All protected endpoints require `Authorization: Token <token>` header. The token is returned by register/login.

## 2.2 Chat routing metadata (V2)
Portal chat now returns optional `routing` metadata in `/api/chat` response:

```json
{
  "routing": {
    "mode": "v2",
    "lane": "action|rag|smalltalk|safety|policy_guard|fallback_readonly",
    "model_source": "cloud|local|none",
    "write_allowed": true,
    "degraded_reason": null,
    "kb_topic": "price|invoice|inspection|safety_leak|policy|none",
    "retrieval_quality": {
      "accepted_count": 2,
      "best_score": 0.71,
      "avg_score": 0.56
    }
  }
}
```

Notes:
- `mode=v2` is the default portal route.
- When cloud model is unavailable, system may enter `fallback_readonly`.
- In `fallback_readonly`, write operations are blocked; read-only queries and safety guidance remain available.

## 2.3 Notification Center APIs

Portal now provides persisted system notifications (order/payment/address/feedback/profile events):

- `GET /api/portal/notifications?page=1&page_size=20&only_unread=false`
- `POST /api/portal/notifications/{id}/read`
- `POST /api/portal/notifications/read-all`

All endpoints require `Authorization: Token <token>`.

Quick verification:

```bash
# list notifications
curl -X GET "http://localhost:8000/api/portal/notifications?page=1&page_size=20" \
  -H "Authorization: Token TOKEN"

# read one notification
curl -X POST "http://localhost:8000/api/portal/notifications/1/read" \
  -H "Authorization: Token TOKEN"

# read all notifications
curl -X POST "http://localhost:8000/api/portal/notifications/read-all" \
  -H "Authorization: Token TOKEN"
```

## 2.1 Test account
- Built-in test account (auto-created):  
  `phone=123` / `password=123`
- Phone validation rule:
  - `123` is reserved for testing.
  - Other phones must match China mainland mobile format: `^1[3-9]\d{9}$`.

## 3. Curl examples
Replace `TOKEN` with the token from login/register. The SMS endpoint returns the code for local testing.

### 3.1 Request SMS code
```bash
curl -X POST http://localhost:8000/api/portal/auth/sms -H "Content-Type: application/json" -d "{\"phone\":\"13800138000\",\"purpose\":\"REGISTER\"}"
```

### 3.2 Register
```bash
curl -X POST http://localhost:8000/api/portal/auth/register -H "Content-Type: application/json" -d "{\"phone\":\"13800138000\",\"password\":\"Passw0rd!\",\"sms_code\":\"123456\",\"display_name\":\"Alice\"}"
```

### 3.3 Login
```bash
curl -X POST http://localhost:8000/api/portal/auth/login -H "Content-Type: application/json" -d "{\"phone\":\"13800138000\",\"password\":\"Passw0rd!\"}"
```

### 3.4 Create address
```bash
curl -X POST http://localhost:8000/api/portal/addresses -H "Content-Type: application/json" -H "Authorization: Token TOKEN" -d "{\"contact_name\":\"Alice\",\"contact_phone\":\"13800138000\",\"address_full\":\"No.1 Road\",\"door_note\":\"Room 502\",\"is_default\":true}"
```

### 3.5 Create order (cylinder delivery)
```bash
curl -X POST http://localhost:8000/api/portal/orders -H "Content-Type: application/json" -H "Authorization: Token TOKEN" -d "{\"service_type\":\"LPG_CYLINDER_DELIVERY\",\"service_payload\":{\"cylinder_type\":\"15kg\",\"quantity\":1},\"address_id\":1,\"eta_date\":\"2026-02-10\",\"eta_slot\":\"09:00-11:00\",\"is_urgent\":false,\"notes\":\"Call before arrive\"}"
```

### 3.6 Pay (mock)
```bash
curl -X POST http://localhost:8000/api/portal/orders/1/pay -H "Authorization: Token TOKEN"
```

### 3.7 Query orders
```bash
curl -X GET "http://localhost:8000/api/portal/orders?status=PAID&keyword=LPG2026&page=1&page_size=10" -H "Authorization: Token TOKEN"
```

Response `data` includes:
- `items`: order list
- `page` / `page_size` / `total` / `total_pages`
- `keyword` / `status` (echoed effective filters)

### 3.8 Query order detail
```bash
curl -X GET "http://localhost:8000/api/portal/orders/1" -H "Authorization: Token TOKEN"
```
`data.events` returns audit event chain for timeline rendering.

### 3.9 Cancel (success)
```bash
curl -X POST http://localhost:8000/api/portal/orders/1/cancel -H "Authorization: Token TOKEN"
```

### 3.10 Cancel (failure example)
```bash
curl -X POST http://localhost:8000/api/portal/orders/9999/cancel -H "Authorization: Token TOKEN"
```

### 3.11 Submit complaint / suggestion
```bash
curl -X POST http://localhost:8000/api/portal/feedbacks \
  -H "Content-Type: application/json" \
  -H "Authorization: Token TOKEN" \
  -d "{\"feedback_type\":\"COMPLAINT\",\"target_type\":\"ORDER_SERVICE\",\"order_id\":1,\"title\":\"配送迟到\",\"content\":\"预约时段延迟超过2小时\",\"contact_phone\":\"13800138000\"}"
```

### 3.12 List my complaints / suggestions
```bash
curl -X GET "http://localhost:8000/api/portal/feedbacks?feedback_type=COMPLAINT" -H "Authorization: Token TOKEN"
```

### 3.13 Cart APIs (配件购物车)
```bash
# 查询购物车
curl -X GET "http://localhost:8000/api/portal/cart/items" -H "Authorization: Token TOKEN"

# 设置某个 SKU 数量（quantity=0 表示移除）
curl -X POST "http://localhost:8000/api/portal/cart/items" \
  -H "Content-Type: application/json" \
  -H "Authorization: Token TOKEN" \
  -d "{\"sku\":\"ALARM\",\"quantity\":2}"

# 删除单个 SKU
curl -X DELETE "http://localhost:8000/api/portal/cart/items/ALARM" -H "Authorization: Token TOKEN"

# 清空购物车
curl -X POST "http://localhost:8000/api/portal/cart/clear" -H "Authorization: Token TOKEN"

# 购物车统一下单并 mock 支付
curl -X POST "http://localhost:8000/api/portal/cart/checkout" \
  -H "Content-Type: application/json" \
  -H "Authorization: Token TOKEN" \
  -d "{\"address_id\":1,\"eta_date\":\"2026-02-26\",\"eta_slot\":\"11:00-13:00\",\"is_urgent\":false,\"notes\":\"配件统一下单\",\"need_invoice\":true,\"invoice_title\":\"上海某某公司\",\"invoice_tax_no\":\"91310000XXXXXX\"}"
```

### 3.13 LLM 配置（账号级）

注意：生产环境必须配置 `PORTAL_PROVIDER_SECRET`（Fernet key）。
说明：同账号下新增 OPENAI_COMPAT 配置时，若 `api_key` 留空，后端会自动复用该账号已有配置的密钥（优先同 `api_base_url`）。

```bash
# 列出配置
curl -X GET "http://localhost:8000/api/portal/llm-profiles" -H "Authorization: Token TOKEN"

# 新建配置（魔搭 OpenAI 兼容）
curl -X POST "http://localhost:8000/api/portal/llm-profiles" \
  -H "Content-Type: application/json" \
  -H "Authorization: Token TOKEN" \
  -d "{\"name\":\"我的魔搭\",\"provider_type\":\"OPENAI_COMPAT\",\"api_base_url\":\"https://dashscope.aliyuncs.com/compatible-mode/v1\",\"api_key\":\"sk-xxx\",\"model_name\":\"qwen-plus\",\"is_active\":true}"

# 拉取模型列表
curl -X GET "http://localhost:8000/api/portal/llm-profiles/1/models" -H "Authorization: Token TOKEN"

# 测试连接
curl -X POST "http://localhost:8000/api/portal/llm-profiles/1/validate" -H "Authorization: Token TOKEN"

# 激活配置
curl -X POST "http://localhost:8000/api/portal/llm-profiles/1/activate" -H "Authorization: Token TOKEN"
```

## Chat History (Account-level)

- `GET /api/portal/chat/history?limit=200`
  - Returns persisted chat messages for current authenticated account.
  - Ordered by `created_at` ascending (old -> new), survives page refresh and backend restart.
- `POST /api/portal/chat/history/clear`
  - Clears chat history for current authenticated account.

Example:

```bash
curl -X GET "http://localhost:8000/api/portal/chat/history?limit=50" -H "Authorization: Token TOKEN"
```

## 4. User-side AI chat (tool execution with confirmation)

- Endpoint: `POST /api/chat`
- Must include portal auth token in header:
  - `Authorization: Token <portal_token>`
- Recommended request body fields:
  - `message`: user message
  - `model_provider`: e.g. `OLLAMA`
  - `provider_profile_id` (optional): portal账号级 LLM 配置 ID；传入后后端会自动注入
    - `provider_type=OPENAI_COMPAT`
    - `provider_base_url=profile.api_base_url`
    - `provider_model=profile.model_name`
    - `provider_api_key=decrypt(profile.api_key_ciphertext)`
  - 未传 `provider_profile_id` 时：若有 active profile 自动使用；无配置则回退本地 OLLAMA
  - `provider_type`: keep `OLLAMA` for local model switching
  - `provider_model`: selected local model name, e.g. `qwen3:4b`
  - `portal_mode`: `true` to force user-side dialog workflow (ask details -> confirm -> execute)
  - `portal_rag_config` (optional): override RAG runtime params for current session
    - `top_k` (1~8)
    - `min_score` (0~1)
    - `min_hits` (1~5)
    - `max_bullets` (1~8)
    - `enable_rewrite` (boolean)
  - `run_id` (optional): continue the same conversation context

Response additions for confirmation workflow:
- `confirm_required: true` means a mutating tool is waiting for user confirmation
- `pending_action` includes current pending operation metadata
- User replies `确认` to execute, or `取消` to abort
- Model strategy:
  - model available -> prefer LLM style response + LLM-assisted KB routing
  - model unavailable -> degrade to deterministic flow (order tools still available), no hard block

Example:
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Token TOKEN" \
  -d "{\"message\":\"我要下单 15kg 2瓶\",\"model_provider\":\"OLLAMA\",\"provider_type\":\"OLLAMA\",\"provider_model\":\"qwen3:4b\",\"portal_mode\":true,\"portal_rag_config\":{\"top_k\":4,\"min_score\":0.32,\"min_hits\":1,\"max_bullets\":4,\"enable_rewrite\":true}}"
```

### 4.1 Local Ollama model list

Frontend model selector can read local model list from:

```bash
curl -X GET "http://localhost:8000/api/ollama/models"
```

Response example:

```json
{
  "provider": "OLLAMA",
  "base_url": "http://localhost:11434",
  "models": ["qwen3:4b", "deepseek-r1:8b"],
  "reachable": true,
  "error": null
}
```

### 4.2 Warmup / start local model

```bash
curl -X POST "http://localhost:8000/api/ollama/warmup" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"qwen3:4b\"}"
```

If warmup fails, portal chat degrades to non-LLM deterministic flow.

### 4.3 Conversation memory (current)

- Short-term memory is persisted in `AgentEvent` under the same `run_id`.
- Includes user messages, collected slots, pending action status, and confirm/cancel records.
- User tone preference is stored in `CustomerChatPreference.tone_style`.
- Default profile/address is loaded via `portal_get_context` for auto-fill behavior.

### 4.4 LLM + RAG routing flow (portal chat)

1. Recognize actionable intent first (order/payment/cancel/modify/feedback/profile/refund).
2. For actionable intents: collect missing fields -> ask confirmation -> execute tool.
3. For non-actionable questions:
   - fixed small talk -> direct response (no tool).
   - otherwise LLM decides whether KB is needed (`safety` / `biz`).
   - if KB needed: call `safety_search` or `kb_search`, then LLM composes final response.
   - if KB not needed: LLM composes direct conversational response.
   - if model unavailable: fallback to heuristic rule response.

### 4.5 Additional tool-backed actions in chat

- Update profile display name (requires confirmation).
- Request refund (submitted as order complaint ticket, requires confirmation).
- Password change is currently guided to `个人中心-修改密码` for safety (avoid plaintext password in chat history).

## 5. RAG Architecture

Portal chat 的 RAG 结构、单一路由流程、检索质量门槛与 query 改写策略见：

- `docs/rag_architecture.md`
