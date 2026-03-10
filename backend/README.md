# Backend README

`backend/` 是 Django + DRF 服务端，负责：
- `/api/chat` Agent 编排与工具调用
- Portal 账号/地址/订单/通知/反馈业务接口
- 知识库检索（RAG）与事件审计回放
- 非结构化/多模态文档入库与重建索引

## 1. 启动
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

## 2. 常用命令
```bash
python manage.py test
python manage.py rebuild_kb --domain safety --force
python manage.py rebuild_kb --domain biz --force
python manage.py ingest_documents --file C:\docs\manual.pdf --domain biz
python manage.py ingest_documents --dir C:\docs\kb --domain safety --versioning-strategy keep_history
python manage.py reindex_document --doc-id doc_xxx
```

## 3. 配置建议（使用 `.env`）
请在本地创建 `backend/.env`，不要提交到 Git。

示例：
```env
MODEL_PROVIDER=OLLAMA
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5:7b-instruct
OPENAI_API_KEY=your_api_key_here
DATABASE_URL=sqlite:///db.sqlite3
KB_EMBED_PROVIDER=LOCAL_BGE_M3
KB_EMBED_MODEL=BAAI/bge-m3
KB_EMBED_DEVICE=cpu
```

## 4. 文档入库 API
### 4.1 单文件入库
```bash
curl -X POST http://localhost:8000/api/ingest \
  -F "file=@C:/docs/manual.pdf" \
  -F "domain=biz" \
  -F "source=manual.pdf" \
  -F "versioning_strategy=keep_history"
```

### 4.2 批量入库
```bash
curl -X POST http://localhost:8000/api/ingest/batch \
  -F "files=@C:/docs/a.pdf" \
  -F "files=@C:/docs/b.docx" \
  -F "domain=safety"
```

也支持 JSON 方式传本地路径：
```json
{
  "domain": "biz",
  "versioning_strategy": "replace",
  "file_paths": ["C:/docs/a.md", "C:/docs/b.txt"]
}
```

### 4.3 重建索引
```bash
curl -X POST http://localhost:8000/api/reindex \
  -H "Content-Type: application/json" \
  -d '{"doc_id":"doc_xxx","versioning_strategy":"keep_history"}'
```

### 4.4 查看与删除文档
```bash
curl http://localhost:8000/api/documents
curl http://localhost:8000/api/documents?domain=biz&include_history=true
curl -X DELETE "http://localhost:8000/api/documents/doc_xxx?domain=biz"
```

## 5. 支持格式与策略
- 支持文件：PDF、DOCX、Markdown、TXT、XLSX、PNG/JPG/JPEG
- PDF：优先原生文本，文本过少时自动 OCR 兜底
- 图片：统一 OCR
- Markdown / DOCX：保留标题层级
- XLSX：按 sheet + row 展开为可检索文本
- chunk：支持 FAQ/QA、标题章节、普通段落 + overlap 三类策略
- metadata：保留 `source/file_name/doc_type/version/chunk_id/page_num/section/title`

当前实现边界：
- 文档入库按 `domain=biz|safety` 显式指定，不做自动域判断
- `replace` 会替换旧版本；`keep_history` 保留历史注册记录，但默认只保留最新版本参与在线检索
- 删除文档会删除向量并标记注册表状态，不会自动清理原始文件目录
- parser 依赖按文件类型懒加载，缺依赖时只影响对应文件类型，不影响服务启动

## 6. OCR 依赖说明
当前默认 OCR 方案是 `rapidocr-onnxruntime`，无需额外安装 Tesseract。
如果环境缺少 OCR 依赖，图片和扫描 PDF 会退化为空文本或低召回，请优先安装：
```bash
pip install rapidocr-onnxruntime Pillow
```

## 7. 验证
推荐最少执行：
```bash
python manage.py check
python manage.py test knowledge_base.tests core.tests.test_tools_api --verbosity 1
```

## 8. 关键目录
- `agent/`: 编排器、路由、工具、对话规则与测试
- `core/`: 通用模型与 API 视图
- `customer_portal/`: 门户业务域（地址/订单/通知等）
- `knowledge_base/`: 文档、legacy 索引、非结构化入库、检索
- `config/`: Django settings / urls

## 9. 相关文档
- 非结构化入库更新：`../docs/rag_unstructured_ingestion_update_20260310.md`
- 面试版 RAG 路径：`../面试/13-RAG构建路径.md`
- 面试版 Agent 路径：`../面试/14-Agent构建路径.md`
