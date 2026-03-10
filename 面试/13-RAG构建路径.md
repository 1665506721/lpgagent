# 13-RAG构建路径.md

# 该项目的 RAG 构建路径

## 1. 一句话概括
这个项目的 RAG 不是一个“通用大而全”的检索系统，而是一个面向 LPG 客服场景的领域化 RAG。

它的核心思路是：
- 知识按 `biz` 和 `safety` 两个 domain 分库
- 先做轻量 query rewrite 和路由判断
- 再做向量召回
- 再做一层基于主题和词项的轻量重排
- 最后根据命中质量决定走“证据型回答”还是“LLM 兜底”

从工程上看，当前项目已经形成了完整的两条链路：
- 旧链路：仓库内 Markdown 规则文档 -> 切分 -> Chroma
- 新链路：PDF/DOCX/Markdown/TXT/XLSX/图片 -> 解析/OCR -> 清洗 -> 差异化 chunk -> Chroma

## 2. 代码入口与主路径
### 2.1 在线问答入口
在线问答入口是：
- `backend/core/views.py` 的 `/api/chat`
- 之后进入 `agent.orchestrator.run_orchestrator()`
- Portal 主链路实际主要在 `backend/agent/portal_orchestrator.py`

### 2.2 检索调用入口
真正触发知识检索时，主要走：
- `backend/agent/portal_orchestrator.py`
  - `_rewrite_kb_query(...)`
  - `_collect_kb_hits(...)`
  - `_llm_compose_kb_reply(...)`
- `backend/agent/tools.py`
  - `kb_search`
  - `safety_search`
- `backend/knowledge_base/retriever.py`
- `backend/knowledge_base/vector_store.py`

### 2.3 离线建库与入库入口
离线/入库链路在：
- 旧知识库构建：`backend/knowledge_base/loader.py` + `chunking.py` + `vector_store.py`
- 新增非结构化入库：`backend/knowledge_base/ingest_service.py`
- 统一解析器：`backend/knowledge_base/parsers/`
- OCR：`backend/knowledge_base/ocr.py`
- 差异化 chunk：`backend/knowledge_base/ingest_chunking.py`

## 3. 用的是什么向量数据库
当前项目使用的是：
- `Chroma`

具体封装位置：
- `backend/knowledge_base/vector_store.py`

实现方式：
- 通过 `chromadb.PersistentClient(path=...)` 使用本地持久化 Chroma
- 每个 domain 一个 collection：
  - `safety -> safety_kb`
  - `biz -> biz_kb`

这样设计的好处是：
- 结构简单，适合本地开发和小中规模项目
- 无需额外部署 PGVector / Milvus / Elasticsearch
- 方便快速迭代和测试

它的 tradeoff 是：
- 更适合单机、轻量级场景
- 不适合大规模高并发、多租户和复杂过滤检索场景

## 4. Embedding 模型怎么做的
### 4.1 当前 embedding 工厂
embedding 封装也在：
- `backend/knowledge_base/vector_store.py`

当前支持多种 embedding provider：
- `LOCAL_BGE_M3`
- `OLLAMA`
- `sentence-transformers fallback`
- `SimpleEmbeddingFunction fallback`

### 4.2 默认策略
默认优先级是：
1. 如果配置了 `KB_EMBED_PROVIDER=LOCAL_BGE_M3`，优先走 `BAAI/bge-m3`
2. 如果本地 FlagEmbedding 不可用，则退到 `sentence-transformers`
3. 如果本地模型再不可用，就退到一个简单 hash embedding，主要用于测试和兜底

### 4.3 面试里怎么讲
可以这样讲：
- 向量层我做成了可插拔工厂，不把 embedding provider 写死
- 默认优先本地 `bge-m3`，因为中文场景和多语场景表现更稳
- 同时保留 `Ollama` 和 `sentence-transformers` fallback，保证环境切换和测试稳定性

## 5. 知识是怎么组织的
### 5.1 Domain 拆分
知识按业务语义拆成两个域：
- `biz`：价格、发票、年检、配送规则、订单规则等业务知识
- `safety`：燃气安全、漏气判断、应急步骤等高风险知识

这不是纯工程拆分，而是业务语义拆分。好处是：
- 能降低业务知识和安全知识的相互干扰
- 能让 query routing 更稳定
- 能为高风险场景留出更严格的控制空间

### 5.2 旧知识格式
原始项目的知识库主要是结构化 Markdown 文档，放在：
- `backend/knowledge_base/biz_docs/`
- `backend/knowledge_base/safety_docs/`

旧文档要求包含：
- `title`
- `tags`
- `topic`
- `policy_type / risk_level / policy_level`
- `source`
- `updated_at`
- `content`
- `aliases`
- `intent_tags`

也就是说，这个项目最初不是把 Markdown 当“原始长文档”直接切，而是把它当“半结构化知识条目”来处理。

## 6. 文档是如何切分的
这个项目现在有两套切分策略。

### 6.1 旧知识库切分
旧知识库切分在：
- `backend/knowledge_base/chunking.py`

特点：
- 先把 `content_bullets / extra_bullets / aliases` 收集成语义单元
- 每个单元按字符窗再切一次
- chunk 之间做短 overlap
- 如果某个 chunk 太短，会和前一个 chunk 合并

本质上这是一个：
- 面向条目型知识的轻量切分
- 不是按 token 粗暴等长切
- 更接近“语义 bullet 聚合切分”

### 6.2 新非结构化文档切分
新链路切分在：
- `backend/knowledge_base/ingest_chunking.py`

当前实现了三类策略：
1. FAQ / Q&A 文档
   - 识别 `Q:/A:`、`问/答` 结构
   - 按问答对直接切块
2. 有标题层级的文档
   - 按 section 切
   - 如果 section 太长，再在 section 内做段落切分
3. 普通长文本
   - 按段落切
   - 带 overlap

当前默认参数：
- `chunk_size = 800`
- `overlap = 120`

### 6.3 面试里的重点表达
你可以强调：
- 我没有只做固定长度切分，而是按文档结构自适应切分
- FAQ 文档按问答对切，说明文档按标题章节切，普通长文按段落切
- 这样做是为了提升 chunk 的语义完整性，减少召回后上下文碎片化

## 7. 多模态和 OCR 怎么做的
### 7.1 支持的格式
当前新增入库支持：
- PDF
- DOCX
- Markdown
- TXT
- XLSX
- PNG / JPG / JPEG

### 7.2 OCR 方案
OCR 封装在：
- `backend/knowledge_base/ocr.py`

默认方案：
- `rapidocr-onnxruntime`

作用：
- 图片 OCR
- 扫描版 PDF OCR fallback

### 7.3 PDF 处理策略
PDF parser 在：
- `backend/knowledge_base/parsers/pdf.py`

逻辑是：
1. 先用 `PyMuPDF` 提取原生文本
2. 如果文本过少，说明可能是扫描版 PDF
3. 这时把 page 渲染成图像，再走 OCR

这是比较典型的“native text first, OCR fallback”策略。

## 8. Metadata 是怎么设计的
### 8.1 旧链路 metadata
旧链路 metadata 里保留了：
- `doc_id`
- `title`
- `tags`
- `aliases`
- `intent_tags`
- `domain`
- `topic`
- `risk_level / policy_type / policy_level`
- `source`
- `updated_at`
- `chunk_index`

### 8.2 新链路 metadata
新链路 chunk metadata 里重点保留：
- `parent_doc_id`
- `chunk_id`
- `chunk_index`
- `source`
- `file_name`
- `doc_type`
- `title`
- `section`
- `page_num`
- `version`

这意味着：
- 召回后不仅能拿到文本，还能拿到来源、版本和文档位置
- 这对可追溯性、重建索引和后续展示都很重要

## 9. 召回是怎么做的
### 9.1 初召回
初召回走的是标准向量召回：
- `collection.query(query_texts=[query], n_results=top_k)`

位置：
- `backend/knowledge_base/vector_store.py -> retrieve_knowledge(...)`

### 9.2 召回分域
检索时不是一个总库一起搜，而是先定域：
- 安全问题 -> `safety_kb`
- 业务问题 -> `biz_kb`

这样做可以减少跨域噪声。

## 10. 有没有重排
有，但不是独立 cross-encoder，而是轻量规则式 rerank。

重排逻辑在：
- `backend/knowledge_base/retriever.py -> _rerank_hits(...)`

当前做法：
1. 先拿向量相似度结果
2. 再根据 query term 和文档内容做 lexical bonus
3. 如果命中了 topic hint，再加 topic bonus
4. 如果命中了 intent_tags，再加一层 bonus
5. 最终重新排序

具体来说：
- lexical match 最多加 0.2
- topic 精准命中可再加 0.25
- intent tag 命中可再加 0.15

### 10.1 为什么这么做
因为客服类事实问答里，经常会出现：
- 向量相似度不错，但 topic 不准
- 词项直接命中其实更可靠

所以这里用了一个“向量初召回 + 轻量词法/主题重排”的方案。

### 10.2 面试里怎么说
可以这样说：
- 当前项目没有上 cross-encoder reranker，而是先做向量召回，再结合 topic、关键词和 intent tag 做轻量重排
- 这样做的原因是工程复杂度低、延迟小，而且对当前领域场景已经能提升命中稳定性
- 如果后续规模继续增大，可以替换成真正的 reranker 模型

## 11. 有没有 query rewrite
有。

位置：
- `backend/agent/portal_orchestrator.py -> _rewrite_kb_query(...)`

逻辑：
- 用最近对话上下文 + 当前用户问题
- 让 LLM 把原问题改写成更适合检索的 query
- 只取首行，避免模型输出大段解释污染检索词

这一步主要解决：
- 用户口语化表达过强
- 上下文省略
- 检索 query 不够聚焦

## 12. 在线 RAG 的完整路径
Portal 侧的一条典型 RAG 路径可以概括为：

1. 用户问题进入 `/api/chat`
2. `portal_orchestrator` 先判断是不是非动作型问题，是否需要 KB
3. 根据问题和 topic 做 domain 路由
4. 进入 `_rewrite_kb_query(...)` 做轻量 query rewrite
5. 进入 `_collect_kb_hits(...)`，实际调 `kb_search` 或 `safety_search`
6. 由 `retriever.py` 完成向量召回 + 轻量重排
7. 如果命中质量足够：
   - 进入 `_llm_compose_kb_reply(...)`
   - 让 LLM 基于 bullets 组织回答
8. 如果命中不足：
   - 对强事实问题返回澄清或保守答复
   - 对一般问题允许走 LLM fallback

也就是说，这个项目不是“只要检索了就强行回答”，而是：
- 先判断命中质量
- 再决定是证据型回答、澄清，还是回退到 LLM

## 13. 新增非结构化入库的离线路径
新文档入库路径可以概括为：

1. 接收文件
   - API：`/api/ingest` / `/api/ingest/batch`
   - CLI：`ingest_documents`
2. 落原始文件到本地持久化目录
3. `load_document(...)` 根据后缀自动分发 parser
4. 做文本清洗和结构化
5. `split_document(...)` 做差异化 chunk
6. 生成 embedding
7. 写入对应 domain 的 Chroma collection
8. 在 `KnowledgeDocument` 表里记录：
   - `doc_id`
   - `domain`
   - `source`
   - `version`
   - `checksum`
   - `storage_path`
9. 支持：
   - `replace`
   - `keep_history`
   - `delete`
   - `reindex`

## 14. 这个 RAG 系统的特点
### 优点
- 领域拆分清晰，业务知识和安全知识分域管理
- embedding 层可插拔
- 旧结构化知识与新非结构化文档可共存
- chunk 不是简单定长切分，而是结构感知切分
- 有 query rewrite
- 有轻量重排
- 有 metadata 和版本管理
- 和现有 Agent 主链路解耦，侵入小

### 限制
- 向量库用的是 Chroma，更偏轻量，不是大规模生产级方案
- rerank 目前还是规则型，不是独立 reranker 模型
- 复杂 PDF 版面和复杂表格解析能力还有限
- 当前是同步入库，不是异步任务化

## 15. 面试时可直接复述的版本
可以直接这样讲：

> 这个项目的 RAG 我做成了一个领域化检索系统，而不是通用搜索。知识先按业务和安全两个 domain 分库，向量库用的是 Chroma，本地持久化。embedding 层做成可插拔工厂，默认优先 `bge-m3`，也支持 Ollama 和 sentence-transformers fallback。在线检索时会先做 query rewrite，再做向量召回，然后结合 topic、关键词和 intent tag 做一层轻量重排。命中质量够高时，我再把检索到的 bullets 喂给 LLM 生成证据型回答；如果命中不够，会选择澄清或者 LLM fallback，而不是强答。离线侧我又扩了一套非结构化和多模态入库链路，支持 PDF、DOCX、Markdown、TXT、XLSX 和图片，PDF 采用 native text first + OCR fallback，chunk 也不是固定长度，而是按 FAQ、标题章节和普通段落三类策略切分，同时保留完整 metadata 和版本管理。整体上，它更强调工程可维护性和领域问答稳定性。 

## 16. 相关代码位置
- 向量库与 embedding：`backend/knowledge_base/vector_store.py`
- 初召回与轻量重排：`backend/knowledge_base/retriever.py`
- 旧 Markdown 知识加载：`backend/knowledge_base/loader.py`
- 旧条目型 chunk：`backend/knowledge_base/chunking.py`
- 新文档差异化 chunk：`backend/knowledge_base/ingest_chunking.py`
- 新文档解析：`backend/knowledge_base/parsers/`
- OCR：`backend/knowledge_base/ocr.py`
- 入库服务：`backend/knowledge_base/ingest_service.py`
- 在线 RAG 调度：`backend/agent/portal_orchestrator.py`
