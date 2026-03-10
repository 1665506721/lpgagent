# RAG 非结构化与多模态文档入库能力更新（2026-03-10）

## 1. 结论
当前项目已经达到“最小可用版本”的目标，可以完成非结构化和多模态文档入库，并与现有 Django RAG + Agent 主链路共存。

这次改造是增量扩展，不是重做：
- 没有替换现有 `/api/chat`、Agent 路由、工具调用和问答主链路
- 新能力全部收敛在 `backend/knowledge_base/` 子系统
- 现有 `biz/safety` 双知识域和 Chroma 向量库继续保留

结论可以概括为：
- 对“文档解析 -> 清洗 -> chunk -> embedding -> 向量入库 -> 重建/删除 -> 版本管理”这一条链路，已经具备可运行实现
- 对“非结构化和多模态文档入库”这一目标，当前版本可视为已达成 MVP
- 对“生产级大规模入库、异步任务、精细化增量更新、复杂版面理解”这些更高阶目标，当前版本仍有后续优化空间

## 2. 已实现能力
### 2.1 支持的文件类型
当前已支持：
- PDF
- DOCX
- Markdown
- TXT
- XLSX
- PNG / JPG / JPEG

### 2.2 解析能力
当前统一入口为：
- `load_document(file_path) -> DocumentParseResult`

已实现行为：
- PDF：优先提取原生文本；当文本过少时自动走 OCR 兜底
- DOCX：按标题样式保留章节层级
- Markdown：按 `# / ## / ###` 等标题保留章节结构
- TXT：直接读取并清洗
- XLSX：按 `sheet + row` 展开为可检索文本片段
- 图片：通过 OCR 提取文本

### 2.3 清洗与结构化
已实现统一清洗：
- 去除异常空白和脏字符
- 保留段落边界
- 表格行转为可检索文本
- 输出统一结构，含 `text/source/file_name/doc_type/title/section/page_num/extra_metadata`

### 2.4 差异化 chunk
已实现三类 chunk 策略：
- FAQ / Q&A：按问答对切分
- 有明显标题层级的文档：按章节切分
- 普通长文本：按段落 + overlap 切分

chunk metadata 已保留：
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

### 2.5 OCR 与多模态
当前 OCR 方案：
- 默认使用 `rapidocr-onnxruntime`
- 图片 OCR 可用
- 扫描版 PDF OCR fallback 可用
- OCR 模块做了独立封装，后续可替换为其他后端

### 2.6 向量化与入库
已实现：
- 复用现有 embedding 工厂
- 写入现有 Chroma collection
- legacy markdown 知识和新上传文档可共存
- 支持 `doc_id` 级删除
- 支持单文档重建索引
- 支持批量入库

### 2.7 版本管理
已实现两种策略：
- `replace`
- `keep_history`

当前语义：
- `replace`：删除旧版本向量，并删除旧版本注册记录，只保留新版本
- `keep_history`：保留旧版本注册记录，但在线检索默认只保留最新版本的向量，避免旧版本污染召回

### 2.8 API 与命令
已新增 API：
- `POST /api/ingest`
- `POST /api/ingest/batch`
- `POST /api/reindex`
- `GET /api/documents`
- `DELETE /api/documents/{doc_id}`

已新增管理命令：
- `python manage.py ingest_documents --file ... --domain biz|safety`
- `python manage.py ingest_documents --dir ... --domain biz|safety`
- `python manage.py reindex_document --doc-id ...`
- `python manage.py reindex_document --file ... --domain ...`

## 3. 与原项目的兼容性
本次改造遵守了“最小侵入式”原则。

保持不变的部分：
- `/api/chat` 主入口
- `agent.orchestrator` / `portal_orchestrator`
- 现有 `kb_search / safety_search` 的调用方式
- 现有 embedding 工厂
- 现有 Chroma 持久化目录

只新增或扩展的部分：
- `knowledge_base` 的解析、入库、文档注册表、API、管理命令

这意味着：
- 原有问答链路不会因为这次改造被重构
- 新入库能力可以被独立使用和演进
- 后续如果需要替换 OCR、parser 或版本策略，影响面主要仍在 `knowledge_base` 子系统内

## 4. 当前实现的验收结果
从能力角度看，目标已达成 MVP：
- 可以上传或扫描目录中的多种非结构化/多模态文件
- 可以为文档生成标准化 metadata 和 chunk
- 可以写入现有向量库并被现有检索链路消费
- 可以查看文档注册记录、删除文档、重建索引
- 可以对重复上传文档进行版本管理

已完成的本地验证：
- `python backend/manage.py test knowledge_base.tests core.tests.test_tools_api --verbosity 1`
- `python backend/manage.py check`

说明：
- 目前测试重点覆盖了解析、chunk、版本管理、API 接口和现有 tool API 回归
- 还没有覆盖大文件、并发批量入库、真实扫描 PDF 大样本等更重的场景压测

## 5. 当前已知限制
当前版本仍有这些边界：
- `keep_history` 会保留历史版本数据库记录，但不会让旧版本继续参与在线检索
- 删除文档时，当前会删除向量并把数据库记录标记为删除；不会自动清理磁盘上的原始文件目录
- 批量入库 API 当前以“单次请求单 domain”为主，不做自动 domain 推断
- 对复杂表格、复杂版面 PDF、图片中非标准排版文字的理解能力仍然有限
- 如果某个 parser 依赖未安装，会在该类文件入库时报错，而不是自动降级为其它解析器

## 6. 建议如何判断“是否达标”
如果你的目标是：
- 让现有 RAG 项目具备一个可维护、可扩展的文档入库能力
- 支持 PDF / DOCX / MD / TXT / XLSX / 图片
- 支持 OCR fallback、chunk 策略差异化、版本管理、删除与重建
- 且不改坏现有问答与 Agent 主链路

那么当前版本已经达标。

如果你的目标进一步提高到：
- 大规模批量异步导入
- 复杂扫描件和复杂表格高保真解析
- 多租户权限隔离
- chunk 级增量更新
- 数据治理后台和任务监控

那么当前版本还属于第一阶段完成，还需要继续演进。

## 7. 后续建议
下一阶段优先建议：
1. 为入库增加异步任务和进度状态
2. 增加文件物理删除和存储清理策略
3. 为 `/api/documents` 增加更多过滤和按 `source` 删除能力
4. 引入更强的表格和版面解析策略
5. 做真实业务文档样本的召回质量评估

## 8. 相关文件
核心实现位置：
- `backend/knowledge_base/ingest_service.py`
- `backend/knowledge_base/ingest_chunking.py`
- `backend/knowledge_base/vector_store.py`
- `backend/knowledge_base/views.py`
- `backend/knowledge_base/models.py`
- `backend/knowledge_base/parsers/`
- `backend/knowledge_base/ocr.py`

配套说明：
- `backend/README.md`
- `backend/requirements.txt`
