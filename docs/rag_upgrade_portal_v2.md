# Portal RAG 升级说明（V2）

## 本次升级内容
1. 去规则化：非动作问答改为 LLM-first，规则仅保留安全/合规硬边界。
2. 中文语料重建：新增核心中文知识文档，并过滤旧英文模板噪声文档。
3. 切片策略升级：中文字符窗 + overlap，提升长问句召回稳定性。
4. Embedding 升级：默认 `LOCAL_BGE_M3`，失败自动降级到本地简单向量（仅应急）。
5. 路由可观测增强：`routing` 增加 `kb_topic` 与 `retrieval_quality`。

## 环境变量
```bash
KB_EMBED_PROVIDER=LOCAL_BGE_M3
KB_EMBED_MODEL=BAAI/bge-m3
KB_EMBED_DEVICE=cpu
```

## 重建知识库
```bash
python manage.py rebuild_kb --domain all --force
```

重建输出会包含：
- `provider`（配置期望）
- `actual_provider`（实际生效）
- `model`
- `device`

## 线上验收建议
1. 提问“今日液化气价格”应命中价格主题，不应召回隐私类文档。
2. 提问“企业开票流程”应返回结构化流程答案。
3. 提问“煤气有些漏了怎么判断”应给判断步骤和应急提醒。
4. 在 `AgentEvent` 中检查 `portal_non_actionable_retrieval` 的 `accepted_count/best_score`。

