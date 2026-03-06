# Portal RAG 结构与流程

本文档描述当前企业用户端（`portal_mode`）在聊天中的 RAG 结构、单一路由流程与质量控制策略。

## 1. 总体结构

- 业务编排入口：`backend/agent/portal_orchestrator.py`
- 工具执行入口：`backend/agent/tools.py`
- 知识库检索层：`backend/knowledge_base/retriever.py`
- 向量库实现：`backend/knowledge_base/vector_store.py`
- 知识文档加载与切分：
  - `backend/knowledge_base/loader.py`
  - `backend/knowledge_base/chunking.py`

## 2. 知识域拆分

- `safety`：燃气安全、应急处置、风险相关知识
- `biz`：价格、发票、服务规则、流程说明等业务知识

对应向量集合：

- `safety_kb`
- `biz_kb`

## 3. 单一路由（非动作问答）

当前非动作问答统一走 `_answer_non_actionable_query`，不再并行走多套 RAG 兜底路由。

流程如下：

1. 小问候/感谢/结束语：直接固定回复（不检索）
2. 路由判定：
   - 优先 LLM 路由：`_llm_decide_kb_route`
   - LLM 不可用时使用启发式路由：`_heuristic_kb_route`
3. Query 改写：`_rewrite_kb_query`
4. 按域检索：`_collect_kb_hits`
5. 质量门槛判断（见第 4 节）
6. 命中质量足够：
   - 优先 LLM 基于证据生成：`_llm_compose_kb_reply`
   - 否则返回 bullets 摘要
7. 命中质量不足：
   - 走 `_llm_general_reply`（自然回复）
   - 若 LLM 不可用则走固定兜底回复

## 4. 检索质量门槛

当前配置（`backend/agent/portal_orchestrator.py`）：

- `KB_TOP_K = 4`
- `KB_MIN_SCORE = 0.32`
- `KB_MIN_ACCEPTED_HITS = 1`
- `KB_MAX_BULLETS = 4`

前端可调参数（通过 `portal_rag_config` 透传）：

- `top_k`
- `min_score`
- `min_hits`
- `max_bullets`
- `enable_rewrite`

实现要点：

- 从向量检索结果中过滤 `score >= KB_MIN_SCORE` 的命中
- 仅使用通过门槛的命中生成证据 bullets
- 若通过门槛数量不足，不进入“基于 KB 的回答”，改走一般回复链路

## 5. Query 改写策略

改写函数：`_rewrite_kb_query`

- 输入：原用户问题 + 路由阶段给出的候选 query + 最近对话上下文
- 输出：单行短 query（8~36 字）
- 约束：不新增事实，不输出 JSON，不输出解释
- 目标：提高向量召回的可命中性，减少口语表达导致的空检索

## 6. 观测与审计

在 `AgentEvent` 中记录了非动作问答的关键规划事件：

- `portal_non_actionable_direct`
- `portal_non_actionable_route`（含 `kb_plan`）
- `portal_non_actionable_retrieval`（含 `domain/query/accepted_count/best_score/avg_score`）

这保证了检索是否发生、命中质量是否达标可追踪。

## 7. 后续可优化项（不引入 reranker 前提）

- 为不同 domain 设置不同分数门槛（如 `safety` 更严格）
- 对低质量命中场景增加“澄清提问”分支，而不是直接泛化回复
- 对 query 改写增加可配置开关（便于 A/B 比较）
- 对检索结果增加时间/版本信息权重（如果文档频繁更新）
