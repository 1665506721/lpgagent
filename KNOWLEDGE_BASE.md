# 知识库总览（Safety + Biz）

## 1. 结论：知识库不是单一文件
当前知识库由**多个 Markdown 文档组成**，分别放在：
- `backend/knowledge_base/safety_docs/`
- `backend/knowledge_base/biz_docs/`

这种拆分方式更便于维护：你可以**按主题单独修改某一个文件**，不必改动整库。

---

## 2. 知识库结构与索引方式
- 文档格式：Markdown，包含结构化字段（标题/标签/风险级别/条款）
- 读取入口：`backend/knowledge_base/loader.py`
- 切分策略：`backend/knowledge_base/chunking.py`
- 向量库：Chroma（本地持久化目录 `backend/data/chroma/`）
- 索引管理：`python manage.py rebuild_kb --domain safety|biz --force`

> 系统会把每个文档拆成多个 chunk，并携带 metadata（如 `doc_id`、`risk_level`、`source`）。

---

## 3. Safety 知识库目录（燃气安全）
位置：`backend/knowledge_base/safety_docs/`

覆盖主题（示例）：
- 报警器响/误报/夜间警报
- 异味/疑似泄漏/应急处置
- 禁止行为（开关电器/明火）
- 关阀/通风/撤离
- 一氧化碳中毒/头晕/昏迷
- 软管老化/减压阀异常
- 点火失败/热水器异常
- 日常检查/更换周期

重点文档示例：
- `safety_manual_v1.md`
- `emergency_v1.md`
- `gas_smell_leak.md`
- `alarm_true_alarm.md`

---

## 4. Biz 知识库目录（业务规则）
位置：`backend/knowledge_base/biz_docs/`

覆盖主题（示例）：
- 配送流程与服务承诺
- 修改/取消规则
- 退款规则
- 工单分类与处理流程
- 隐私与脱敏
- 安全提醒触发条件

重点文档示例：
- `delivery_policy_v1.md`
- `ticket_policy_v1.md`
- `privacy_notice_v1.md`
- `refund_rules_time_limits.md`

---

## 5. 文档内容规范（简化版）
每篇文档建议包含：
- title: 标题
- tags: 标签
- risk_level 或 policy_type
- content: 条款要点（bullet）
- do_not / exceptions / source 等

这能让检索结果更容易被模型引用（比如“根据安全手册第 X 条…”）。

---

## 6. 如何增删改（推荐流程）
1) 新增/修改单个文档（只改对应 md 文件）
2) 运行索引重建：
   ```bash
   cd backend
   python manage.py rebuild_kb --domain safety --force
   python manage.py rebuild_kb --domain biz --force
   ```
3) 调试检索：
   ```bash
   curl -X POST http://localhost:8000/api/tools/kb_search -H "Content-Type: application/json" -d '{"domain":"safety","query":"报警器响了怎么办","top_k":3}'
   ```

---

## 7. 是否需要“单一文件版本”？
目前不建议合并为单一大文件，因为：
- 大文件修改易冲突，难以定位与审阅
- 条款更新通常是局部修订，更适合按主题独立维护

如果你确实需要“单文件镜像”，可以后续添加一个**只读汇总脚本**自动生成（不替代原始文档）。
