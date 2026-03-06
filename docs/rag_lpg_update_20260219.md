# RAG 与个性化对话更新（2026-02-19）

## 本次新增

- 新增业务知识文档：
  - `backend/knowledge_base/biz_docs/price_lpg_monthly_reference.md`
  - `backend/knowledge_base/biz_docs/cylinder_inspection_cycle_rules.md`
- 聊天意图路由新增：
  - `PRICE_QUERY`（价格/涨价类问答）
  - `CYLINDER_INSPECTION_QUERY`（气瓶年检到期查询）
- 个人数据优先策略：
  - 年检问题先查用户订单 `service_payload.next_inspection_date`；
  - 无个人记录再走 RAG 通用规则。
- 新增会话记忆模型：
  - `CustomerConversationMemory`（`memory_json`）
  - 每轮聊天自动更新 `last_intent`、`last_user_message`、`order_pref` 等信息。

## 路由规则（关键点）

- 价格/年检提问不再直接进入下单收集流程。
- 只有明确下单动作（如“下单/预约/安排上门”等）才进入 `CREATE_ORDER`。
- 下单草稿会优先复用记忆中的联系人/地址/常用瓶型。

## 索引构建

1. 迁移数据库：
```bash
cd backend
python manage.py migrate
```

2. 重建业务知识库：
```bash
cd backend
python manage.py rebuild_kb --domain biz --force
```

## 备注

- `vector_store` 已调整为默认使用本地兜底 embedding；只有显式配置 `OLLAMA_EMBED_MODEL` 才启用 Ollama embedding，避免非 embedding 模型导致重建失败。
