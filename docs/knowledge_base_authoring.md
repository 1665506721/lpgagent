# Portal 知识库编写规范（V2）

## 目标
- 让 RAG 对中文口语问题稳定命中。
- 避免模板噪声文档污染召回结果。

## 文件位置
- 业务知识：`backend/knowledge_base/biz_docs/*.md`
- 安全知识：`backend/knowledge_base/safety_docs/*.md`

## 必填字段
每个文档必须包含以下字段，否则不会入库：

```md
title: 标题
tags: 标签1, 标签2
topic: price|invoice|inspection|safety_leak|...
policy_type: COMPLIANCE|OPERATIONS|...
policy_level: REGULATORY|INTERNAL
source: 来源
updated_at: YYYY-MM-DD
content:
- 要点1
- 要点2
aliases:
- 用户口语问法1
- 用户口语问法2
intent_tags:
- 对应意图标签1
```

## 编写要求
1. `content` 只写可执行、可验证的事实。
2. `aliases` 覆盖口语、省略、错别字近似问法。
3. 每条要点尽量 20-80 字，避免超长段落。
4. 安全类文档必须标注 `risk_level`（HIGH/MEDIUM/LOW）。
5. 文档语种统一中文，英文模板文档不入索引。

## 重建命令
```bash
python manage.py rebuild_kb --domain all --force
```

## 环境配置（Embedding）
```bash
KB_EMBED_PROVIDER=LOCAL_BGE_M3
KB_EMBED_MODEL=BAAI/bge-m3
KB_EMBED_DEVICE=cpu
```

